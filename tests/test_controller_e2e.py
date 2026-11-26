"""End-to-end orchestration and PySide6 GUI/Tray tests for Art Director."""

from __future__ import annotations

import os
import time

from art_director.config import ConfigManager
from art_director.core import ArtDirectorController, ListeningMode
from art_director.targets import BehringerXR18Target, QLCPlusTarget
from test_os_and_launcher import MockPopupLauncherOS


def test_controller_e2e_sleep_wake_routing_and_panic(tmp_path):
    cfg_mgr = ConfigManager(tmp_path / "cfg.json")
    cfg = cfg_mgr.config
    cfg.prefix_routes["xr18"].prefixes = ["mixerone"]
    cfg.stage_launcher.apps[0].executable = "/apps/xair"
    cfg.stage_launcher.apps[0].skip_if_running = False
    cfg_mgr.save(cfg)

    osc_calls: list[tuple[str, int, str, object]] = []
    xr18 = BehringerXR18Target(osc_sender=lambda h, p, a, v: osc_calls.append((h, p, a, v)))
    qlc = QLCPlusTarget(
        osc_sender=lambda h, p, a, v: osc_calls.append((h, p, a, v)),
        artnet_sender=lambda h, p, pkt: None,
    )
    os_b = MockPopupLauncherOS()
    ctrl = ArtDirectorController(
        config_manager=cfg_mgr,
        os_bridge=os_b,
        targets_override={"xr18": xr18, "qlc": qlc},
        enable_audio=False,
        enable_hotkeys=False,
    )
    events = []
    ctrl.bus.subscribe("command_executed", lambda ev: events.append(ev.payload))

    ctrl.start(launched_at_boot=False)
    try:
        assert ctrl.state.mode == ListeningMode.WAKE
        assert ctrl.state.emoji == "👍"

        # 1. Dynamic prefix routing works
        ctrl.process_text_command("mixerone canale 1 fader 75")
        time.sleep(0.1)
        assert any(c[2] == "/ch/01/mix/fader" for c in osc_calls)

        # 2. Sleep mode blocks commands and updates emoji to 👋
        ctrl.process_text_command("dormi")
        assert ctrl.state.mode == ListeningMode.SLEEP
        assert ctrl.state.emoji == "👋"

        before_len = len(osc_calls)
        ctrl.process_text_command("mixerone canale 2 muta")
        time.sleep(0.1)
        assert len(osc_calls) == before_len

        # 3. Wake mode restores 👍 and command execution
        ctrl.process_text_command("sveglia")
        assert ctrl.state.mode == ListeningMode.WAKE
        assert ctrl.state.emoji == "👍"

        # 4. Popup dismiss & stage app launch via voice (bare prefix, '<prefix> apri', 'apri <prefix>')
        ctrl.process_text_command("chiudi avviso")
        ctrl.process_text_command("mixerone")
        ctrl.process_text_command("mixerone apri")
        ctrl.process_text_command("apri mixerone")
        deadline = time.monotonic() + 2.0
        while len(events) < 5 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert os_b.launched.count(("/apps/xair", "", "")) == 3

        # 5. Global Panic mutes XR18 LR, blackouts QLC+, and enters Sleep Mode
        actions = ctrl.trigger_panic(source="test")
        assert any("Master LR" in a for a in actions)
        assert any("Blackout" in a for a in actions)
        assert ctrl.state.mode == ListeningMode.SLEEP
    finally:
        ctrl.stop()


def test_gui_main_window_tray_and_close_to_background(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from art_director.ui import MainWindow, SettingsDialog

    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)

    cfg_mgr = ConfigManager(tmp_path / "gui_cfg.json")
    ctrl = ArtDirectorController(
        config_manager=cfg_mgr,
        os_bridge=MockPopupLauncherOS(),
        enable_audio=False,
        enable_hotkeys=False,
    )
    ctrl.start()
    win = MainWindow(controller=ctrl, start_hidden=False)
    try:
        assert "👍" in win.toggle_mode_btn.text()
        ctrl.set_sleep_mode("test")
        app.processEvents()
        assert "👋" in win.toggle_mode_btn.text()

        # Closing via 'X' hides window instead of quitting daemon
        win.close()
        app.processEvents()
        assert not win.isVisible()
        assert ctrl._running is True  # Daemon still alive in background

        # Main window has both input gain and noise gate sliders plus 4 system tabs
        assert hasattr(win, "gain_slider")
        assert hasattr(win, "gate_slider")
        assert win.system_tabs.count() == 4
        win.gain_slider.setValue(25)
        app.processEvents()
        assert ctrl.config.audio.input_gain == 2.5

        # App / Settings dialog holds managed apps only (0 when empty)
        dlg = SettingsDialog(ctrl, parent=win)
        assert dlg.tabs.count() == 0
        dlg._on_save()
        dlg.close()
    finally:
        win.quit_completely()
        app.processEvents()


def test_vosk_empty_dir_validation_and_app_discovery(tmp_path):
    from art_director.core.app_discovery import discover_stage_app_executables
    from art_director.stt.vosk_engine import VoskSTTEngine, is_valid_vosk_model_dir

    empty_dir = tmp_path / "Richiami comandi"
    empty_dir.mkdir()
    assert is_valid_vosk_model_dir(empty_dir) is False
    ok, msg = VoskSTTEngine(str(empty_dir)).load()
    assert ok is False
    assert "NON contiene un modello Vosk valido" in msg

    discovered = discover_stage_app_executables()
    assert isinstance(discovered, dict)


def test_app_discovery_prioritization_and_wizard_search_offscreen(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from art_director.core.app_discovery import (
        InstalledProgram,
        _compute_category_tier,
        _is_junk_app,
        _name_quality_score,
    )
    from art_director.ui.program_wizard import AddProgramWizardDialog

    assert _is_junk_app("obs-midi", r"C:\Program Files\obs-studio\unins001.exe") is True
    assert _is_junk_app("Character Map", r"C:\WINDOWS\system32\charmap.exe") is True
    assert _is_junk_app("REAPER", r"C:\Program Files\REAPER (x64)\reaper.exe") is False

    assert _name_quality_score("REAPER (x64)", r"C:\Program Files\REAPER (x64)\reaper.exe") > (
        _name_quality_score(
            "REAPER (x64) (create new project)",
            r"C:\Program Files\REAPER (x64)\reaper.exe",
        )
    )
    assert _name_quality_score("DaVinci Resolve", r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe") > (
        _name_quality_score(
            "Blackmagic Proxy Generator Lite",
            r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe",
        )
    )
    assert _compute_category_tier("REAPER", r"C:\Program Files\REAPER (x64)\reaper.exe") == 0
    assert _compute_category_tier("Google Chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe") == 2

    mock_apps = [
        InstalledProgram("X-AIR Edit", r"C:\apps\X-AIR-Edit.exe", "X-AIR-Edit", category_tier=-1),
        InstalledProgram("REAPER", r"C:\Program Files\REAPER (x64)\reaper.exe", "REAPER", category_tier=-1),
        InstalledProgram("Google Chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe", "Google Chrome", category_tier=2),
    ]
    monkeypatch.setattr("art_director.ui.program_wizard.discover_all_installed_programs", lambda: mock_apps)

    app = QApplication.instance() or QApplication([])
    cfg_mgr = ConfigManager(tmp_path / "wiz_cfg.json")
    ctrl = ArtDirectorController(
        config_manager=cfg_mgr,
        os_bridge=MockPopupLauncherOS(),
        enable_audio=False,
        enable_hotkeys=False,
    )
    wiz = AddProgramWizardDialog(ctrl)
    try:
        assert wiz.prog_combo.count() == 3
        assert wiz.name_edit.text() == "X-AIR Edit"

        wiz.prog_filter_edit.setText("reap")
        app.processEvents()
        assert wiz.prog_combo.count() == 1
        assert wiz.name_edit.text() == "REAPER"
        assert wiz.exe_edit.text() == r"C:\Program Files\REAPER (x64)\reaper.exe"
    finally:
        wiz.close()
        app.processEvents()
