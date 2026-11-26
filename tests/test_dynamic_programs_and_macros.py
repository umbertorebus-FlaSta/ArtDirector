"""Tests for Schema 1-2-3 dynamic programs, alias deduplication, picking, and parameterized macros."""

from __future__ import annotations

import os
import time

from art_director.config import (
    ActionStep,
    AppConfig,
    ConfigManager,
    ProgramProfile,
    register_or_merge_function,
)
from art_director.core import ArtDirectorController, CancellationToken, CommandRouter, ProgramExecutor
from art_director.os_layer.base import OSBridge, WindowInfo


class PickerTestOSBridge(OSBridge):
    def __init__(self) -> None:
        self.windows = [
            WindowInfo(handle=101, title="X-AIR-Edit v1.8", is_active=True),
            WindowInfo(handle=202, title="Cakewalk Sonar - Live", is_active=False),
        ]
        self.rects = {
            101: (100, 50, 1000, 600),
            202: (0, 0, 1920, 1080),
        }
        self.clicks: list[tuple[int, int, str, int]] = []
        self.scrolls: list[tuple[int, int, int]] = []
        self.hotkeys: list[str] = []
        self.launched: list[tuple[str, str, str]] = []
        self.focused: list[list[str]] = []

    @property
    def platform_name(self) -> str:
        return "mock"

    def list_windows(self) -> list[WindowInfo]:
        return list(self.windows)

    def get_foreground_window(self) -> WindowInfo | None:
        return self.windows[0]

    def focus_window(self, patterns: list[str]) -> bool:
        self.focused.append(patterns)
        return True

    def close_window_handle(self, handle) -> bool:  # noqa: ANN001
        return True

    def get_window_rect(self, handle):  # noqa: ANN001
        return self.rects.get(handle)

    def mouse_click_at(self, x: int, y: int, button: str = "left", clicks: int = 1) -> bool:
        self.clicks.append((x, y, button, clicks))
        return True

    def mouse_scroll_at(self, x: int, y: int, dy: int = 3) -> bool:
        self.scrolls.append((x, y, dy))
        return True

    def send_hotkey(self, hotkey: str) -> bool:
        self.hotkeys.append(hotkey)
        return True

    def launch_executable(self, executable: str, arguments: str = "", working_dir: str = ""):
        self.launched.append((executable, arguments, working_dir))
        return True, f"Launched {executable}"

    def set_autostart(self, enabled, script_or_exe, background=True):  # noqa: ANN001
        return True, "ok"

    def is_autostart_enabled(self) -> bool:
        return False


def test_repeat_picking_merges_as_alias_and_persists(tmp_path):
    prof = ProgramProfile(
        id="xair",
        name="X-AIR Edit",
        executable="C:/apps/X-AIR-Edit.exe",
        window_title_patterns=["X-AIR-Edit"],
        open_commands=["UehBerì", "Mixer", "Control", "Berì"],
    )

    fn1, merged1 = register_or_merge_function(
        prof,
        ["Muta voce"],
        [ActionStep(kind="click", rel_x=0.25, rel_y=0.50)],
    )
    assert merged1 is False
    assert len(prof.functions) == 1

    # Pick near the exact same button -> automatically merges as alias!
    fn2, merged2 = register_or_merge_function(
        prof,
        ["Togli voce"],
        [ActionStep(kind="click", rel_x=0.254, rel_y=0.496)],
    )
    assert merged2 is True
    assert fn2 is fn1
    assert len(prof.functions) == 1
    assert fn1.primary_command == "Muta voce"
    assert fn1.aliases == ["Togli voce"]

    # Round-trip save/load in ConfigManager
    mgr = ConfigManager(tmp_path / "prog_cfg.json")
    cfg = mgr.config
    cfg.programs.append(prof)
    mgr.save(cfg)

    reloaded = ConfigManager(tmp_path / "prog_cfg.json").config
    assert len(reloaded.programs) == 1
    assert reloaded.programs[0].open_commands == ["UehBerì", "Mixer", "Control", "Berì"]
    assert reloaded.programs[0].functions[0].commands == ["Muta voce", "Togli voce"]


def test_parameterized_macro_closes_and_opens_unique_project_with_safety(tmp_path):
    (tmp_path / "Money.cwp").write_text("cwp", encoding="utf-8")
    (tmp_path / "Shine on You 25.cwp").write_text("cwp", encoding="utf-8")

    sonar = ProgramProfile(
        id="sonar",
        name="Sonar",
        executable="C:/Program Files/Cakewalk/Sonar/Sonar.exe",
        window_title_patterns=["Cakewalk Sonar"],
        open_commands=["ueh sonà", "sonar"],
    )
    fn, _ = register_or_merge_function(
        sonar,
        ["chiudi il progetto appena finito ed apri {nome}"],
        [
            ActionStep(kind="hotkey", hotkey="<ctrl>+w"),
            ActionStep(kind="wait", delay_ms=50),
            ActionStep(
                kind="open_project",
                project_folders=[str(tmp_path)],
                project_extensions=[".cwp"],
                use_spoken_param=True,
            ),
        ],
    )

    cfg = AppConfig(programs=[sonar])
    router = CommandRouter(cfg)

    # Note minor article variation ("i progetto" vs "il progetto") matching real user prompt!
    m = router.route("ueh Sonà, chiudi i progetto appena finito ed apri money")
    assert m.kind == "program_func"
    assert m.program_id == "sonar"
    assert m.function_id == fn.id
    assert m.params == {"nome": "money"}

    os_b = PickerTestOSBridge()
    executor = ProgramExecutor(os_b)

    # Safety check: if song doesn't exist, abort BEFORE closing current project!
    res_fail = executor.execute_function(
        sonar, fn, {"nome": "brano inesistente xyz"}, CancellationToken()
    )
    assert res_fail.handled is False
    assert os_b.hotkeys == []
    assert os_b.launched == []

    # Valid song: closes current project (<ctrl>+w) and launches Money.cwp!
    res_ok = executor.execute_function(sonar, fn, m.params, CancellationToken())
    assert res_ok.handled is True
    assert "<ctrl>+w" in os_b.hotkeys
    assert os_b.launched[-1][0] == "C:/Program Files/Cakewalk/Sonar/Sonar.exe"
    assert "Money.cwp" in os_b.launched[-1][1]


def test_window_relative_click_scroll_and_background_osc(tmp_path):
    xair = ProgramProfile(
        id="xair",
        name="X-AIR Edit",
        executable="C:/apps/X-AIR-Edit.exe",
        window_title_patterns=["X-AIR-Edit"],
        open_commands=["UehBerì", "Mixer", "Control", "Berì"],
    )
    register_or_merge_function(
        xair,
        ["muta voce", "togli voce"],
        [ActionStep(kind="click", rel_x=0.5, rel_y=0.5)],
    )
    osc_calls: list[tuple[str, int, str, object]] = []
    register_or_merge_function(
        xair,
        ["scena rock"],
        [
            ActionStep(
                kind="osc",
                osc_host="192.168.1.100",
                osc_port=10024,
                osc_address="/-snap/load",
                osc_value=3,
                osc_type="int",
            )
        ],
    )

    cfg_mgr = ConfigManager(tmp_path / "e2e_prog.json")
    cfg = cfg_mgr.config
    cfg.programs.append(xair)
    cfg_mgr.save(cfg)

    os_b = PickerTestOSBridge()
    ctrl = ArtDirectorController(
        config_manager=cfg_mgr,
        os_bridge=os_b,
        enable_audio=False,
        enable_hotkeys=False,
    )
    ctrl.program_executor = ProgramExecutor(
        os_b, osc_sender=lambda h, p, a, v: osc_calls.append((h, p, a, v))
    )
    events = []
    ctrl.bus.subscribe("command_executed", lambda ev: events.append(ev.payload))
    ctrl.start()
    try:
        # Alias opening command ("Control") -> launches/focuses X-AIR Edit
        ctrl.process_text_command("Control")
        # Picked click using window rect (100, 50, 1000, 600) -> abs (600, 350)
        ctrl.process_text_command("UehBerì togli voce")
        # Background OSC without stealing focus
        ctrl.process_text_command("Berì scena rock")

        deadline = time.monotonic() + 2.0
        while len(events) < 3 and time.monotonic() < deadline:
            time.sleep(0.02)

        assert len(events) == 3
        assert os_b.clicks[-1] == (600, 350, "left", 1)
        assert osc_calls[-1] == ("192.168.1.100", 10024, "/-snap/load", 3)
    finally:
        ctrl.stop()


def test_dynamic_program_tab_appears_in_settings_offscreen(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from art_director.ui import SettingsDialog

    app = QApplication.instance() or QApplication([])
    cfg_mgr = ConfigManager(tmp_path / "ui_prog.json")
    cfg = cfg_mgr.config
    cfg.programs.append(
        ProgramProfile(
            id="inkscape",
            name="Inkscape",
            executable="/usr/bin/inkscape",
            open_commands=["Inkscape"],
        )
    )
    cfg_mgr.save(cfg)

    ctrl = ArtDirectorController(
        config_manager=cfg_mgr,
        os_bridge=PickerTestOSBridge(),
        enable_audio=False,
        enable_hotkeys=False,
    )
    dlg = SettingsDialog(ctrl)
    try:
        # App / Settings layer shows only dynamic app tabs ("Inkscape")
        assert dlg.tabs.count() == 1
        assert dlg.tabs.tabText(0) == "Inkscape"
        dlg._on_save()
    finally:
        dlg.close()
        app.processEvents()
