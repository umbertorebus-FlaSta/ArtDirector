"""Unit, hybrid routing, and offscreen UI tests for acoustic voice sample matching."""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np

from art_director.audio.dsp import VADChunkResult
from art_director.config import (
    ActionStep,
    ConfigManager,
    ProgramFunction,
    ProgramProfile,
)
from art_director.core import ArtDirectorController, ListeningMode, ProgramExecutor
from art_director.stt.base import BaseSTTEngine, STTResult
from art_director.stt.sample_matcher import (
    AcousticSampleLibrary,
    SampleEntry,
    dtw_similarity,
    extract_mfcc_features,
    load_wav_float32,
    save_wav_pcm16,
    trim_silence,
)
from test_dynamic_programs_and_macros import PickerTestOSBridge


class HybridMockOSBridge(PickerTestOSBridge):
    def __init__(self) -> None:
        super().__init__()
        self.opened_docs: list[Path] = []

    def launch_executable(
        self, executable: str, arguments: str = "", working_dir: str = ""
    ) -> tuple[bool, str]:
        self.launched.append((executable, arguments, working_dir))
        return True, "mock launched"

    def open_document_or_file(self, path: Path) -> tuple[bool, str]:
        self.opened_docs.append(Path(path))
        return True, "mock opened"


class FakeFallbackSTTEngine(BaseSTTEngine):
    def __init__(self, reply_text: str) -> None:
        self.reply_text = reply_text
        self._loaded = True
        self.calls = 0

    @property
    def name(self) -> str:
        return "vosk"

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def load(self) -> tuple[bool, str]:
        self._loaded = True
        return True, "mock loaded"

    def unload(self) -> None:
        self._loaded = False

    def reset(self) -> None:
        return

    def process_chunk(self, chunk: VADChunkResult) -> list[STTResult]:
        if chunk.completed_utterance is None:
            return []
        self.calls += 1
        return [STTResult(text=self.reply_text, is_final=True, confidence=1.0, latency_ms=5.0, engine="vosk")]


def _synth_phrase(
    syllables: list[tuple[float, float, float, float]],
    sr: int = 16000,
    speed_scale: float = 1.0,
) -> np.ndarray:
    """Synthesize multi-syllable vowel/formant contours with distinct MFCC trajectories."""
    segments: list[np.ndarray] = []
    for f1, f2, f3, dur_sec in syllables:
        n = max(160, int(round(dur_sec * speed_scale * sr)))
        t = np.arange(n, dtype=np.float32) / float(sr)
        env = np.hanning(n).astype(np.float32)
        sig = (
            0.55 * np.sin(2.0 * np.pi * f1 * t)
            + 0.35 * np.sin(2.0 * np.pi * f2 * t)
            + 0.20 * np.sin(2.0 * np.pi * f3 * t)
        ).astype(np.float32)
        segments.append(sig * env * 0.45)
    return np.concatenate(segments)


def test_mfcc_extraction_trim_and_wav_roundtrip(tmp_path):
    sr = 16000
    core = _synth_phrase(
        [
            (300.0, 900.0, 2300.0, 0.16),
            (650.0, 1750.0, 2700.0, 0.18),
            (420.0, 2200.0, 3100.0, 0.16),
        ],
        sr=sr,
    )
    padded = np.concatenate(
        [np.zeros(int(0.25 * sr), dtype=np.float32), core, np.zeros(int(0.25 * sr), dtype=np.float32)]
    )

    trimmed = trim_silence(padded, sample_rate=sr)
    assert trimmed.size < padded.size
    assert trimmed.size >= int(0.35 * sr)

    assert extract_mfcc_features(np.zeros(4000, dtype=np.float32), sample_rate=sr) is None
    feats = extract_mfcc_features(padded, sample_rate=sr, trim=True)
    assert feats is not None
    assert feats.ndim == 2
    assert feats.shape[1] == 26  # 13 CMVN MFCC + 13 Delta

    wav_path = tmp_path / "uehberi.wav"
    save_wav_pcm16(wav_path, padded, sample_rate=sr)
    reloaded, loaded_sr = load_wav_float32(wav_path)
    assert loaded_sr == sr
    assert reloaded.dtype == np.float32
    assert np.max(np.abs(reloaded)) > 0.5


def test_dtw_similarity_handles_speed_variation_and_rejects_different_phrases():
    word_a = _synth_phrase(
        [
            (280.0, 820.0, 2100.0, 0.16),
            (450.0, 1300.0, 2500.0, 0.16),
            (720.0, 2350.0, 3200.0, 0.18),
        ]
    )
    # Same phrase spoken ~18% slower (typical live variation)
    word_a_slow = _synth_phrase(
        [
            (285.0, 840.0, 2130.0, 0.16),
            (460.0, 1320.0, 2520.0, 0.16),
            (710.0, 2310.0, 3170.0, 0.18),
        ],
        speed_scale=1.18,
    )
    # Different spectral progression (high-to-low vs low-to-high formants)
    word_b = _synth_phrase(
        [
            (760.0, 2450.0, 3400.0, 0.18),
            (520.0, 1550.0, 2600.0, 0.16),
            (260.0, 720.0, 1850.0, 0.16),
        ]
    )

    fa = extract_mfcc_features(word_a)
    fa_slow = extract_mfcc_features(word_a_slow)
    fb = extract_mfcc_features(word_b)
    assert fa is not None and fa_slow is not None and fb is not None

    same_score = dtw_similarity(fa, fa_slow)
    diff_score = dtw_similarity(fa, fb)
    assert same_score >= 0.72
    assert diff_score < same_score - 0.12


def test_sample_library_sleep_gating_and_program_context_bias(tmp_path):
    samples_dir = tmp_path / "campioni"
    wake_audio = _synth_phrase(
        [(280.0, 850.0, 2100.0, 0.18), (680.0, 2250.0, 3100.0, 0.18)]
    )
    func_audio = _synth_phrase(
        [(700.0, 2300.0, 3150.0, 0.18), (300.0, 850.0, 2000.0, 0.18)]
    )
    save_wav_pcm16(samples_dir / "scetat.wav", wake_audio)
    save_wav_pcm16(samples_dir / "rec_xr18.wav", func_audio)
    save_wav_pcm16(samples_dir / "rec_sonar.wav", func_audio)

    lib = AcousticSampleLibrary(samples_dir, sample_rate=16000)
    count = lib.rebuild(
        [
            SampleEntry(sample_file="scetat.wav", kind="wake", label="scetat"),
            SampleEntry(
                sample_file="rec_xr18.wav",
                kind="program_func",
                label="XR18 Rec",
                program_id="xr18",
                function_id="f1",
            ),
            SampleEntry(
                sample_file="rec_sonar.wav",
                kind="program_func",
                label="Sonar Rec",
                program_id="sonar",
                function_id="f2",
            ),
        ]
    )
    assert count == 3

    # Sleep mode restricts matches strictly to wake/panic
    blocked = lib.match(func_audio, threshold=0.68, allowed_kinds={"wake", "panic"})
    assert blocked is None
    allowed_wake = lib.match(wake_audio, threshold=0.68, allowed_kinds={"wake", "panic"})
    assert allowed_wake is not None
    assert allowed_wake.entry.kind == "wake"

    # Ambiguous template prefers active program context
    biased = lib.match(func_audio, threshold=0.68, preferred_program_id="sonar")
    assert biased is not None
    assert biased.entry.program_id == "sonar"


def test_hybrid_controller_executes_sampled_command_and_falls_back_for_variable_macro(tmp_path):
    cfg_mgr = ConfigManager(tmp_path / "cfg_hybrid.json")
    samples_dir = tmp_path / "campioni"
    proj_dir = tmp_path / "ProgettiSonar"
    proj_dir.mkdir(parents=True)
    money_file = proj_dir / "Money.cwp"
    money_file.write_text("dummy project", encoding="utf-8")

    # Distinct synthetic waveforms for: wake, sampled function, and an un-sampled utterance
    sampled_muta_audio = _synth_phrase(
        [(290.0, 840.0, 2050.0, 0.16), (690.0, 2200.0, 3100.0, 0.18)]
    )
    unsampled_variable_audio = _synth_phrase(
        [(740.0, 2400.0, 3300.0, 0.18), (270.0, 760.0, 1900.0, 0.18)]
    )
    save_wav_pcm16(samples_dir / "muta_voce.wav", sampled_muta_audio)

    cfg = cfg_mgr.config
    cfg.stt.engine = "samples_hybrid"
    cfg.stt.samples_dir = str(samples_dir)
    cfg.stt.sample_match_threshold = 0.68
    cfg.stt.hybrid_fallback_engine = "vosk"

    sonar = ProgramProfile(
        id="cakewalk",
        name="Sonar",
        executable="C:/Program Files/Cakewalk/Sonar.exe",
        open_commands=["Ueh Sona"],
        window_title_patterns=["Cakewalk Sonar"],
        functions=[
            ProgramFunction(
                id="fn_muta",
                commands=["togli voce"],
                sample_files=["muta_voce.wav"],
                steps=[ActionStep(kind="click", rel_x=0.5, rel_y=0.5)],
            ),
            ProgramFunction(
                id="fn_apri_prog",
                commands=["chiudi progetto e apri {nome}"],
                steps=[
                    ActionStep(kind="hotkey", hotkey="<ctrl>+w"),
                    ActionStep(kind="wait", delay_ms=20),
                    ActionStep(
                        kind="open_project",
                        project_folders=[str(proj_dir)],
                        project_extensions=[".cwp"],
                        use_spoken_param=True,
                    ),
                ],
            ),
        ],
    )
    cfg.programs.append(sonar)
    cfg_mgr.save(cfg)

    os_b = HybridMockOSBridge()
    ctrl = ArtDirectorController(
        config_manager=cfg_mgr,
        os_bridge=os_b,
        enable_audio=False,
        enable_hotkeys=False,
    )
    fake_fallback = FakeFallbackSTTEngine("ueh sona chiudi progetto e apri money")
    events: list[dict] = []
    ctrl.bus.subscribe("command_executed", lambda ev: events.append(ev.payload))

    ctrl.start(launched_at_boot=False)
    ctrl.stt.start(load_models=False)
    ctrl.stt._engine = fake_fallback  # Inject offline mock fallback without touching hardware
    try:
        assert ctrl.state.mode == ListeningMode.WAKE
        assert ctrl.stt.sample_library.count == 1

        # 1. Sampled phrase hits acoustic MFCC+DTW matcher immediately (< fallback not called)
        ctrl.stt.submit_chunk(
            VADChunkResult(
                processed_float32=sampled_muta_audio,
                pcm16_bytes=b"",
                rms_db=-12.0,
                peak_db=-6.0,
                gate_open=True,
                completed_utterance=sampled_muta_audio,
            )
        )
        deadline = time.monotonic() + 2.0
        while len(events) < 1 and time.monotonic() < deadline:
            time.sleep(0.02)

        assert len(events) >= 1
        assert fake_fallback.calls == 0
        assert os_b.clicks[-1] == (0 + 960, 0 + 540, "left", 1)

        # 2. Unsampled spoken phrase ("... apri money") falls through to hybrid STT fallback
        ctrl.stt.submit_chunk(
            VADChunkResult(
                processed_float32=unsampled_variable_audio,
                pcm16_bytes=b"",
                rms_db=-12.0,
                peak_db=-6.0,
                gate_open=True,
                completed_utterance=unsampled_variable_audio,
            )
        )
        deadline = time.monotonic() + 2.5
        while len(os_b.launched) < 1 and time.monotonic() < deadline:
            time.sleep(0.02)

        assert fake_fallback.calls == 1
        assert os_b.hotkeys[-1] == "<ctrl>+w"
        assert os_b.launched[-1][0] == "C:/Program Files/Cakewalk/Sonar.exe"
        assert "Money.cwp" in os_b.launched[-1][1]
    finally:
        ctrl.stop()


def test_settings_dialog_and_main_window_hybrid_sample_controls_offscreen(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from art_director.ui import MainWindow, SettingsDialog

    app = QApplication.instance() or QApplication([])
    cfg_mgr = ConfigManager(tmp_path / "ui_samples.json")
    ctrl = ArtDirectorController(
        config_manager=cfg_mgr,
        os_bridge=HybridMockOSBridge(),
        enable_audio=False,
        enable_hotkeys=False,
    )
    ctrl.start()
    win = MainWindow(controller=ctrl, start_hidden=False)
    try:
        assert "Campioni audio indicizzati" in win.prefix_summary_label.text()
        assert win.system_tabs.tabText(3) == "Riconoscimento & Campioni"
        assert win.system_panel.stt_engine_combo.currentText() == "samples_hybrid"
        win.system_panel.stt_engine_combo.setCurrentText("samples_only")
        win.system_panel.sample_thresh_spin.setValue(74)
        win.system_panel.fallback_combo.setCurrentText("none")
        win.system_panel._on_save_clicked()

        assert ctrl.config.stt.engine == "samples_only"
        assert ctrl.config.stt.sample_match_threshold == 0.74
        assert ctrl.config.stt.hybrid_fallback_engine == "none"

        dlg = SettingsDialog(ctrl, parent=win)
        try:
            assert dlg.tabs.count() == 0
            dlg._on_save()
        finally:
            dlg.close()

        # Warning appears if user has recorded samples while stt.engine is still 'vosk'
        cfg = ctrl.config
        cfg.stt.engine = "vosk"
        cfg.programs.append(
            ProgramProfile(
                id="p1",
                name="TestApp",
                open_commands=["Apri"],
                open_samples=["dummy.wav"],
            )
        )
        ctrl.stt.sample_library.rebuild([])
        ctrl.stt.sample_library._entries.append(
            SampleEntry(sample_file="dummy.wav", kind="program_open", label="Apri", program_id="p1")
        )
        win._sync_ui_from_config()
        assert "samples_hybrid" in win.prefix_summary_label.text()
    finally:
        win.quit_completely()
        app.processEvents()


def test_mfcc_48khz_and_cross_rate_matching(tmp_path):
    samples_dir = tmp_path / "campioni48"
    a_48 = _synth_phrase(
        [(280.0, 820.0, 2100.0, 0.16), (480.0, 1450.0, 2550.0, 0.16), (720.0, 2350.0, 3200.0, 0.18)],
        sr=48000,
    )
    a_16_slow = _synth_phrase(
        [(285.0, 840.0, 2120.0, 0.16), (490.0, 1470.0, 2560.0, 0.16), (710.0, 2320.0, 3180.0, 0.18)],
        sr=16000,
        speed_scale=1.15,
    )
    b_48 = _synth_phrase(
        [(760.0, 2450.0, 3400.0, 0.18), (520.0, 1550.0, 2600.0, 0.16), (260.0, 720.0, 1850.0, 0.16)],
        sr=48000,
    )
    save_wav_pcm16(samples_dir / "uehberi_48k.wav", a_48, sample_rate=48000)

    lib = AcousticSampleLibrary(samples_dir, sample_rate=16000)
    assert lib.rebuild([SampleEntry(sample_file="uehberi_48k.wav", kind="program_open", label="UehBerì", program_id="xr18")]) == 1

    match_same = lib.match(a_16_slow, threshold=0.68)
    assert match_same is not None
    assert match_same.entry.program_id == "xr18"

    fa = extract_mfcc_features(a_48, sample_rate=48000)
    fb = extract_mfcc_features(b_48, sample_rate=48000)
    assert fa is not None and fb is not None
    assert dtw_similarity(fa, fb) < match_same.score - 0.10


def test_picker_ignores_non_target_foreground_window_and_hud():
    from art_director.os_layer.base import WindowInfo
    from art_director.os_layer.picker import WindowPickerSession

    os_b = HybridMockOSBridge()
    sonar_win = WindowInfo(handle=202, title="Cakewalk Sonar - Live", pid=2000, is_active=False)
    sonar_plugin_popup = WindowInfo(handle=203, title="ProChannel EQ", pid=2000, is_active=False)
    antigravity_win = WindowInfo(handle=301, title="Antigravity Workspace", pid=3000, is_active=True)
    hud_win = WindowInfo(handle=401, title="Picking su Sonar / Cakewalk", pid=4000, is_active=True)
    os_b.windows = [sonar_win, sonar_plugin_popup, antigravity_win, hud_win]
    os_b.rects[203] = (200, 150, 800, 500)
    os_b.rects[301] = (0, 0, 1920, 1080)

    active_fg = {"w": antigravity_win}
    os_b.get_foreground_window = lambda: active_fg["w"]  # type: ignore[method-assign]

    sess = WindowPickerSession(
        os_bridge=os_b,
        window_patterns=["Cakewalk"],
        ignore_rects_provider=lambda: [(40, 24, 500, 50)],
    )
    sess._active = True

    # Clicking while Antigravity or Picking HUD is foreground must NOT record into Sonar
    sess._handle_click(960, 540, object(), True)
    active_fg["w"] = hud_win
    sess._handle_click(500, 35, object(), True)
    assert sess.steps == []

    # Clicking inside HUD ignore rect even when Sonar is active must NOT record
    active_fg["w"] = sonar_win
    sess._handle_click(450, 40, object(), True)
    assert sess.steps == []

    # Clicking inside Sonar itself or a same-PID plugin dialog DOES record
    sess._handle_click(960, 540, object(), True)
    active_fg["w"] = sonar_plugin_popup
    sess._handle_click(500, 300, object(), True)
    assert len(sess.steps) >= 2


def test_picking_hud_stop_unblocked_and_restores_nested_dialogs_offscreen(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog

    from art_director.ui import SettingsDialog
    from art_director.ui.program_wizard import FunctionRecorderDialog

    monkeypatch.setattr(
        "art_director.os_layer.picker.WindowPickerSession.start",
        lambda self: (True, "mock started"),
    )
    monkeypatch.setattr(
        "art_director.os_layer.picker.WindowPickerSession.stop",
        lambda self: [ActionStep(kind="click", rel_x=0.25, rel_y=0.5)],
    )

    app = QApplication.instance() or QApplication([])
    cfg_mgr = ConfigManager(tmp_path / "hud_modal.json")
    ctrl = ArtDirectorController(
        config_manager=cfg_mgr,
        os_bridge=HybridMockOSBridge(),
        enable_audio=False,
        enable_hotkeys=False,
    )
    prog = ProgramProfile(
        id="sonar",
        name="Sonar / Cakewalk",
        window_title_patterns=["Cakewalk"],
        open_commands=["Uesonà"],
    )
    settings = SettingsDialog(ctrl)
    settings.setWindowModality(Qt.WindowModality.ApplicationModal)
    wizard = QDialog(settings)
    wizard.setWindowModality(Qt.WindowModality.ApplicationModal)
    fn_dlg = FunctionRecorderDialog(ctrl, prog, parent=wizard)
    fn_dlg.setWindowModality(Qt.WindowModality.ApplicationModal)
    try:
        settings.show()
        wizard.show()
        fn_dlg.show()
        app.processEvents()

        fn_dlg._start_picking()
        app.processEvents()

        assert fn_dlg._hud is not None
        assert fn_dlg._hud.isVisible()
        assert not fn_dlg.isVisible()
        assert not wizard.isVisible()
        assert not settings.isVisible()

        # Fine Picking button must be unblocked and close HUD cleanly via QueuedConnection
        hud_ref = fn_dlg._hud
        assert isinstance(hud_ref.screen_rect_tuple(), tuple)
        assert len(hud_ref.screen_rect_tuple()) == 4
        assert fn_dlg.sample_recorder.sample_list.minimumHeight() >= 96

        QTest.mouseClick(hud_ref.stop_btn, Qt.MouseButton.LeftButton)
        app.processEvents()
        app.processEvents()

        assert fn_dlg._hud is None
        assert len(fn_dlg._steps) == 1
        assert fn_dlg.isVisible()
        assert wizard.isVisible()
        assert settings.isVisible()
    finally:
        fn_dlg.close()
        wizard.close()
        settings.close()
        app.processEvents()


def test_comma_separated_open_commands_and_sample_list_scroll_size(tmp_path):
    from art_director.core import CommandRouter

    cfg_mgr = ConfigManager(tmp_path / "comma_cfg.json")
    cfg = cfg_mgr.config
    sonar = ProgramProfile(
        id="sonar",
        name="Sonar / Cakewalk",
        open_commands=["uesona, sonar, daw"],
    )
    cfg.programs.append(sonar)
    router = CommandRouter(cfg)
    assert router.route("sonar").kind == "program_open"
    assert router.route("daw").kind == "program_open"
    assert router.route("uesona").kind == "program_open"


def test_picking_hud_keeps_nested_exec_dialogs_alive_offscreen(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from art_director.ui import SettingsDialog
    from art_director.ui.program_wizard import FunctionRecorderDialog

    monkeypatch.setattr(
        "art_director.os_layer.picker.WindowPickerSession.start",
        lambda self: (True, "mock started"),
    )
    monkeypatch.setattr(
        "art_director.os_layer.picker.WindowPickerSession.stop",
        lambda self: [ActionStep(kind="click", rel_x=0.3, rel_y=0.6)],
    )

    app = QApplication.instance() or QApplication([])
    cfg_mgr = ConfigManager(tmp_path / "exec_hud.json")
    ctrl = ArtDirectorController(
        config_manager=cfg_mgr,
        os_bridge=HybridMockOSBridge(),
        enable_audio=False,
        enable_hotkeys=False,
    )
    prog = ProgramProfile(
        id="xair",
        name="X-AIR Edit",
        window_title_patterns=["X-AIR-Edit"],
        open_commands=["UehBerì"],
    )
    settings = SettingsDialog(ctrl)
    fn_dlg = FunctionRecorderDialog(ctrl, prog, parent=settings)
    fn_dlg.cmd_edit.setText("Muta Chitarra")

    results: dict[str, object] = {}

    def _open_fn_exec() -> None:
        results["fn_exec"] = fn_dlg.exec()

    def _start_pick() -> None:
        fn_dlg._start_picking()
        results["hud_visible"] = bool(fn_dlg._hud and fn_dlg._hud.isVisible())
        results["fn_hidden"] = not fn_dlg.isVisible()
        results["settings_hidden"] = not settings.isVisible()
        results["modal_while_picking"] = app.activeModalWidget()

    def _click_stop() -> None:
        assert fn_dlg._hud is not None
        QTest.mouseClick(fn_dlg._hud.stop_btn, Qt.MouseButton.LeftButton)

    def _verify_and_accept() -> None:
        results["hud_after_stop"] = fn_dlg._hud
        results["steps_after_stop"] = len(fn_dlg._steps)
        results["fn_restored"] = fn_dlg.isVisible()
        results["settings_restored"] = settings.isVisible()
        fn_dlg.accept()
        QTimer.singleShot(20, settings.accept)

    QTimer.singleShot(20, _open_fn_exec)
    QTimer.singleShot(60, _start_pick)
    QTimer.singleShot(110, _click_stop)
    QTimer.singleShot(160, _verify_and_accept)
    QTimer.singleShot(1500, settings.reject)

    settings_res = settings.exec()
    assert settings_res == 1
    assert results.get("fn_exec") == 1
    assert results.get("hud_visible") is True
    assert results.get("fn_hidden") is True
    assert results.get("settings_hidden") is True
    assert results.get("modal_while_picking") is None
    assert results.get("hud_after_stop") is None
    assert results.get("steps_after_stop") == 1
    assert results.get("fn_restored") is True
    assert results.get("settings_restored") is True


def test_picker_matches_target_process_even_when_window_title_differs(monkeypatch):
    from art_director.os_layer.base import WindowInfo
    from art_director.os_layer.picker import WindowPickerSession

    os_b = HybridMockOSBridge()
    xair_win = WindowInfo(handle=305, title="XR18 Studio Mixer", pid=os.getpid(), is_active=True)
    other_win = WindowInfo(handle=306, title="Other App", pid=999999, is_active=False)
    os_b.windows = [xair_win, other_win]
    os_b.rects[305] = (100, 100, 1000, 600)
    os_b.rects[306] = (0, 0, 1920, 1080)

    active_fg = {"w": xair_win}
    os_b.get_foreground_window = lambda: active_fg["w"]  # type: ignore[method-assign]

    sess = WindowPickerSession(
        os_bridge=os_b,
        window_patterns=["X-AIR-Edit"],
        process_name="python",
    )
    sess._active = True
    monkeypatch.setattr(
        sess,
        "_matches_target_process",
        lambda pid: pid == os.getpid(),
    )

    sess._handle_click(600, 400, object(), True)
    assert len(sess.steps) == 1
    assert abs(sess.steps[0].rel_x - 0.5) < 0.01
    assert abs(sess.steps[0].rel_y - 0.5) < 0.01

    active_fg["w"] = other_win
    sess._handle_click(600, 400, object(), True)
    assert len(sess.steps) == 1


def test_hotkey_if_dialog_only_fires_when_popup_appears(tmp_path):
    from art_director.core.executor import ProgramExecutor
    from art_director.core.state import CancellationToken
    from art_director.os_layer.base import WindowInfo

    os_b = HybridMockOSBridge()
    sonar_main = WindowInfo(handle=202, title="Cakewalk Sonar - Song", pid=2000, is_active=True)
    save_popup = WindowInfo(
        handle=209,
        title="Cakewalk",
        class_name="#32770",
        pid=2000,
        is_dialog=True,
        is_active=True,
    )
    os_b.windows = [sonar_main]
    fg_holder = {"w": sonar_main}
    os_b.get_foreground_window = lambda: fg_holder["w"]  # type: ignore[method-assign]

    proj = tmp_path / "Money  48KHz  6'.cwp"
    proj.write_text("x", encoding="utf-8")

    prog = ProgramProfile(
        id="sonar",
        name="Sonar / Cakewalk",
        executable="C:/Program Files/Cakewalk/Sonar/Sonar.exe",
        window_title_patterns=["Cakewalk"],
        functions=[
            ProgramFunction(
                id="fn_switch",
                commands=["chiudi il progetto e apri {nome}"],
                allow_without_prefix=True,
                steps=[
                    ActionStep(kind="hotkey", hotkey="c"),
                    ActionStep(kind="hotkey_if_dialog", hotkey="n", delay_ms=120),
                    ActionStep(
                        kind="open_project",
                        project_folders=[str(tmp_path)],
                        project_extensions=[".cwp"],
                        use_spoken_param=True,
                    ),
                ],
            )
        ],
    )
    ex = ProgramExecutor(os_b)

    # Case 1: popup opens -> 'n' IS sent
    fg_holder["w"] = save_popup
    res1 = ex.execute_function(prog, prog.functions[0], {"nome": "money"}, CancellationToken())
    assert res1.handled
    assert os_b.hotkeys == ["c", "n"]
    assert len(os_b.launched) == 1

    # Case 2: NO popup opens -> 'n' is NOT sent
    os_b.hotkeys.clear()
    os_b.launched.clear()
    fg_holder["w"] = sonar_main
    res2 = ex.execute_function(prog, prog.functions[0], {"nome": "money"}, CancellationToken())
    assert res2.handled
    assert os_b.hotkeys == ["c"]
    assert len(os_b.launched) == 1


def test_build_sample_entries_skips_parameterized_functions(tmp_path):
    from art_director.stt.manager import build_sample_entries_from_config

    cfg = ConfigManager(tmp_path / "param_skip.json").config
    sonar = ProgramProfile(
        id="sonar",
        name="Sonar / Cakewalk",
        open_commands=["Uesonà"],
        open_samples=["open.wav"],
        functions=[
            ProgramFunction(
                id="fn_param",
                commands=["chiudi il progetto e apri {nome}"],
                allow_without_prefix=True,
                sample_files=["should_be_skipped.wav"],
                steps=[ActionStep(kind="open_project", use_spoken_param=True)],
            ),
            ProgramFunction(
                id="fn_fixed",
                commands=["play"],
                sample_files=["play.wav"],
                steps=[ActionStep(kind="hotkey", hotkey="space")],
            ),
        ],
    )
    cfg.programs.append(sonar)
    entries = build_sample_entries_from_config(cfg)
    files = {e.sample_file for e in entries}
    assert "open.wav" in files
    assert "play.wav" in files
    assert "should_be_skipped.wav" not in files


def test_open_project_uses_open_hotkey_when_app_already_running(tmp_path):
    from art_director.core.executor import ProgramExecutor
    from art_director.core.state import CancellationToken
    from art_director.os_layer.base import WindowInfo

    proj = tmp_path / "Money  48KHz  6'.cwp"
    proj.write_text("x", encoding="utf-8")

    os_b = HybridMockOSBridge()
    sonar_main = WindowInfo(handle=202, title="Cakewalk Sonar", pid=2000, is_active=True)
    open_dlg = WindowInfo(
        handle=210,
        title="Apri",
        class_name="#32770",
        pid=2000,
        is_dialog=True,
        is_active=True,
    )
    fg_holder = {"w": sonar_main}
    clipboard: list[str] = []

    def _send_hk(hk: str) -> bool:
        os_b.hotkeys.append(hk)
        if hk == "o":
            fg_holder["w"] = open_dlg
        return True

    os_b.windows = [sonar_main]
    os_b.get_foreground_window = lambda: fg_holder["w"]  # type: ignore[method-assign]
    os_b.send_hotkey = _send_hk  # type: ignore[method-assign]
    os_b.set_clipboard_text = lambda txt: (clipboard.append(txt), True)[1]  # type: ignore[method-assign]

    prog = ProgramProfile(
        id="sonar",
        name="Sonar / Cakewalk",
        executable="C:/Program Files/Cakewalk/Sonar/Sonar.exe",
        window_title_patterns=["Cakewalk"],
        functions=[
            ProgramFunction(
                id="fn_open",
                commands=["chiudi il progetto e apri {nome}"],
                allow_without_prefix=True,
                steps=[
                    ActionStep(
                        kind="open_project",
                        project_folders=[str(tmp_path)],
                        project_extensions=[".cwp"],
                        use_spoken_param=True,
                        open_hotkey="o",
                    )
                ],
            )
        ],
    )
    ex = ProgramExecutor(os_b)

    # Case 1: Sonar is running -> sends 'o', pastes full path, hits 'enter', does NOT spawn a 2nd process!
    res1 = ex.execute_function(prog, prog.functions[0], {"nome": "money"}, CancellationToken())
    assert res1.handled
    assert os_b.hotkeys == ["o", "<ctrl>+a", "<ctrl>+v", "enter"]
    assert clipboard == [str(proj)]
    assert os_b.launched == []

    # Case 2: Sonar is closed -> falls back to direct launch with file argument
    os_b.hotkeys.clear()
    os_b.windows = []
    res2 = ex.execute_function(prog, prog.functions[0], {"nome": "money"}, CancellationToken())
    assert res2.handled
    assert len(os_b.launched) == 1
    assert "Money  48KHz  6'.cwp" in os_b.launched[0][1]


def test_whisper_model_validation_discovery_resampling_and_prompt(tmp_path, monkeypatch):
    import os
    from types import SimpleNamespace

    from art_director.audio.dsp import VADChunkResult
    from art_director.core.event_bus import EventBus
    from art_director.stt.manager import STTManager, build_whisper_initial_prompt
    from art_director.stt.whisper_engine import FasterWhisperSTTEngine, is_valid_whisper_model_dir

    # 1. Validation distinguishes real CTranslate2 folder from campioni/
    bad_dir = tmp_path / "campioni"
    bad_dir.mkdir()
    (bad_dir / "test.wav").write_bytes(b"RIFF")
    assert not is_valid_whisper_model_dir(bad_dir)

    good_dir = tmp_path / "models" / "faster-whisper-base"
    good_dir.mkdir(parents=True)
    (good_dir / "model.bin").write_bytes(b"bin")
    (good_dir / "config.json").write_text("{}", encoding="utf-8")
    assert is_valid_whisper_model_dir(good_dir)

    # 2. Song title cleaner & compact initial_prompt prioritization
    songs_dir = tmp_path / "FLOW 8"
    songs_dir.mkdir()
    (songs_dir / "Salva automaticamente copia di Money  48KHz  6'.cwp").write_text("x", encoding="utf-8")
    (songs_dir / "Money  48KHz  6'.cwp").write_text("x", encoding="utf-8")
    (songs_dir / "Hotel California 48KHz   6 '30.cwp").write_text("x", encoding="utf-8")
    (songs_dir / "ACQUA AZZURRA (48KHz).cwp").write_text("x", encoding="utf-8")

    cfg = ConfigManager(tmp_path / "whisper_cfg.json").config
    cfg.stt.engine = "samples_hybrid"
    cfg.stt.hybrid_fallback_engine = "faster_whisper"
    cfg.stt.whisper_model_path_or_size = str(bad_dir)
    cfg.audio.sample_rate = 48000
    cfg.programs.append(
        ProgramProfile(
            id="sonar",
            name="Sonar / Cakewalk",
            functions=[
                ProgramFunction(
                    id="fn_open",
                    commands=["chiudi il progetto e apri {nome}"],
                    allow_without_prefix=True,
                    steps=[
                        ActionStep(
                            kind="open_project",
                            project_folders=[str(songs_dir)],
                            project_extensions=[".cwp"],
                            use_spoken_param=True,
                        )
                    ],
                )
            ],
        )
    )

    prompt = build_whisper_initial_prompt(cfg)
    assert len(prompt) <= 165
    assert "chiudi il progetto e apri" in prompt.lower()
    assert "Money" in prompt
    assert "48KHz" not in prompt
    assert "Salva automaticamente" not in prompt

    # 3. Auto-discovery recovers from invalid path (like campioni/) and sets 48kHz + prompt
    monkeypatch.setattr(
        "art_director.stt.manager.discover_local_models",
        lambda: {"vosk": [], "faster_whisper": [good_dir]},
    )
    mgr = STTManager(cfg, EventBus(), on_result=lambda _r: None)
    engine = mgr._create_stt_engine("faster_whisper")
    assert isinstance(engine, FasterWhisperSTTEngine)
    assert engine.model_path_or_size == str(good_dir)
    assert engine.sample_rate == 48000
    assert "Money" in engine.initial_prompt

    # Invalid path cannot sneak into WhisperModel(..., local_files_only=True)
    os.environ.pop("HF_HUB_OFFLINE", None)
    bad_eng = FasterWhisperSTTEngine(model_path_or_size=str(bad_dir))
    ok_bad, msg_bad = bad_eng.load()
    assert not ok_bad
    assert "model.bin" in msg_bad
    assert "HF_HUB_OFFLINE" not in os.environ

    # 4. 48 kHz -> 16 kHz resampling inside process_chunk + clean transcription args
    captured: dict[str, object] = {}

    class _FakeModel:
        def transcribe(self, audio, **kwargs):
            captured["audio_len"] = len(audio)
            captured["kwargs"] = kwargs
            return [SimpleNamespace(text="Chiudi il progetto e apri Money.")], SimpleNamespace()

    engine._model = _FakeModel()
    utt_48k = np.zeros(48000, dtype=np.float32)  # 1.0 sec @ 48 kHz
    res = engine.process_chunk(
        VADChunkResult(
            processed_float32=utt_48k[:1024],
            pcm16_bytes=b"",
            rms_db=-20.0,
            peak_db=-10.0,
            gate_open=True,
            completed_utterance=utt_48k,
        )
    )
    assert len(res) == 1
    assert res[0].text == "Chiudi il progetto e apri Money."
    assert captured["audio_len"] == 16000
    kw = captured["kwargs"]
    assert isinstance(kw, dict)
    assert kw["temperature"] == 0.0
    assert kw["without_timestamps"] is True
    assert "Money" in str(kw["initial_prompt"])


def test_paste_text_search_clear_and_roundtrip(tmp_path):
    import os
    from PySide6.QtWidgets import QApplication
    from art_director.core.executor import ProgramExecutor
    from art_director.core.state import CancellationToken
    from art_director.os_layer.base import WindowInfo
    from art_director.ui.program_wizard import AdvancedStepDialog

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _app = QApplication.instance() or QApplication([])

    os_b = HybridMockOSBridge()
    os_b.windows = [WindowInfo(handle=301, title="VirtualDJ", pid=3000, is_active=True)]
    clipboard: list[str] = []
    os_b.set_clipboard_text = lambda txt: (clipboard.append(txt), True)[1]  # type: ignore[method-assign]

    prog = ProgramProfile(
        id="vdj",
        name="VirtualDJ",
        window_title_patterns=["VirtualDJ"],
        functions=[
            ProgramFunction(
                id="fn_search_clear",
                commands=["cerca brano"],
                allow_without_prefix=True,
                steps=[
                    ActionStep(
                        kind="paste_text",
                        paste_text="",
                        paste_clear_first=True,
                        paste_before_hotkey="f3",
                    )
                ],
            ),
            ProgramFunction(
                id="fn_song",
                commands=["fastcars"],
                allow_without_prefix=True,
                steps=[
                    ActionStep(
                        kind="paste_text",
                        paste_text="FASTCARS",
                        paste_clear_first=True,
                        paste_before_hotkey="f3",
                        paste_after_hotkey="",
                    ),
                    ActionStep(kind="hotkey", hotkey="down"),
                    ActionStep(kind="hotkey", hotkey="enter"),
                ],
            ),
            ProgramFunction(
                id="fn_dyn",
                commands=["cerca {nome}"],
                steps=[ActionStep(kind="paste_text", paste_text="{nome}")],
            ),
        ],
    )
    ex = ProgramExecutor(os_b)

    # 1. "Cerca brano" opens search & clears previous text without pasting
    res1 = ex.execute_function(prog, prog.functions[0], {}, CancellationToken())
    assert res1.handled
    assert os_b.focused
    assert os_b.hotkeys == ["f3", "<ctrl>+a", "backspace"]
    assert clipboard == []

    # 2. Fixed song search -> pastes song name -> down -> enter (VDJ load)
    os_b.hotkeys.clear()
    res2 = ex.execute_function(prog, prog.functions[1], {}, CancellationToken())
    assert res2.handled
    assert os_b.hotkeys == ["f3", "<ctrl>+a", "<ctrl>+v", "down", "enter"]
    assert clipboard == ["FASTCARS"]

    # 3. Parameterized {nome} substitution
    os_b.hotkeys.clear()
    clipboard.clear()
    res3 = ex.execute_function(
        prog, prog.functions[2], {"nome": "Hotel California"}, CancellationToken()
    )
    assert res3.handled
    assert os_b.hotkeys == ["<ctrl>+a", "<ctrl>+v"]
    assert clipboard == ["Hotel California"]

    # 4. Config serialization round-trip preserves paste_text fields
    cm = ConfigManager(tmp_path / "vdj_cfg.json")
    cm.config.programs.append(prog)
    cm.save()
    loaded = ConfigManager(tmp_path / "vdj_cfg.json").config
    st_loaded = loaded.programs[0].functions[1].steps[0]
    assert st_loaded.kind == "paste_text"
    assert st_loaded.paste_text == "FASTCARS"
    assert st_loaded.paste_before_hotkey == "f3"
    assert st_loaded.paste_clear_first is True

    # 5. AdvancedStepDialog UI offscreen round-trip for paste_text
    dlg = AdvancedStepDialog(initial_step=st_loaded)
    assert dlg.kind_combo.currentData() == "paste_text"
    assert dlg.paste_text_edit.text() == "FASTCARS"
    assert dlg.paste_before_edit.text() == "f3"
    dlg.paste_after_edit.setText("enter")
    dlg._on_ok()
    assert dlg.step is not None
    assert dlg.step.paste_after_hotkey == "enter"


def test_parse_and_send_hotkey_aliases_for_spacebar_and_italian_keys(monkeypatch):
    from pynput.keyboard import Key
    from art_director.os_layer import base as os_base

    assert os_base.parse_hotkey_tokens("spacebar") == ["spacebar"]
    assert os_base.parse_hotkey_tokens(" ") == ["space"]
    assert os_base.parse_hotkey_tokens("tasto enter") == ["enter"]
    assert os_base.parse_hotkey_tokens("<ctrl>+spazio") == ["ctrl", "spazio"]
    # Accented single-char shortcut key must stay intact
    assert os_base.parse_hotkey_tokens("ò") == ["ò"]

    sent: list[tuple[str, object]] = []

    class _FakeController:
        def press(self, k):
            sent.append(("press", k))

        def release(self, k):
            sent.append(("release", k))

    monkeypatch.setattr("pynput.keyboard.Controller", _FakeController)
    for raw, expected in (
        ("spacebar", Key.space),
        ("spazio", Key.space),
        (" ", Key.space),
        ("tasto enter", Key.enter),
        ("invio", Key.enter),
        ("ò", "ò"),
    ):
        sent.clear()
        assert os_base.send_keys_pynput(raw) is True
        assert ("press", expected) in sent
        assert ("release", expected) in sent


def test_numpad_and_literal_plus_hotkey_picking_and_sending(monkeypatch):
    from pynput.keyboard import KeyCode
    from art_director.os_layer import base as os_base
    from art_director.os_layer.picker import _format_pynput_key

    # Picking distinguishes Windows Numpad VK_ADD/VK_SUBTRACT from standard '+'
    assert _format_pynput_key(KeyCode(vk=107, char="+")) == ("<num_add>", False)
    assert _format_pynput_key(KeyCode(vk=109, char="-")) == ("<num_sub>", False)
    assert _format_pynput_key(KeyCode(vk=187, char="+")) == ("+", False)

    assert os_base.parse_hotkey_tokens("+") == ["+"]
    assert os_base.parse_hotkey_tokens("<ctrl>++") == ["ctrl", "+"]
    assert os_base.parse_hotkey_tokens("<num_add>") == ["num_add"]
    assert os_base.parse_hotkey_tokens("numpad+") == ["num_add"]
    assert os_base.parse_hotkey_tokens("numpad-") == ["num_sub"]

    sent: list[tuple[str, object]] = []

    class _FakeController:
        def press(self, k):
            sent.append(("press", k))

        def release(self, k):
            sent.append(("release", k))

    monkeypatch.setattr("pynput.keyboard.Controller", _FakeController)
    assert os_base.send_keys_pynput("+") is True
    assert ("press", "+") in sent

    for tok, expected_vk in (("<num_add>", 0x6B), ("numpad+", 0x6B), ("<num_sub>", 0x6D)):
        sent.clear()
        assert os_base.send_keys_pynput(tok) is True
        pressed = [k for kind, k in sent if kind == "press"]
        assert len(pressed) == 1
        assert getattr(pressed[0], "vk", None) == expected_vk


def test_picker_ignores_other_windows_alt_tab_and_key_autorepeat(monkeypatch):
    import os
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from pynput.keyboard import Key, KeyCode
    from art_director.os_layer.base import WindowInfo
    from art_director.os_layer.picker import WindowPickerSession
    from art_director.ui.program_wizard import PickingHudBar

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _app = QApplication.instance() or QApplication([])

    os_b = HybridMockOSBridge()
    vdj_win = WindowInfo(handle=10, title="VirtualDJ", pid=500, is_active=True)
    antigravity_win = WindowInfo(handle=20, title="Antigravity", pid=600, is_active=True)
    os_b.windows = [vdj_win, antigravity_win]

    stopped = []
    sess = WindowPickerSession(
        os_bridge=os_b,
        window_patterns=["VirtualDJ"],
        on_stop_requested=lambda: stopped.append(True),
        process_name="virtualdj",
    )
    sess._active = True

    # 1. Keys typed in another app (e.g. Antigravity) must NOT be recorded
    os_b.get_foreground_window = lambda: antigravity_win  # type: ignore[method-assign]
    sess._handle_key_press(KeyCode.from_char("h"))
    assert sess.steps == []

    # 2. Switch to VirtualDJ -> Alt+Tab window switch is ignored; auto-repeat is collapsed to 1 step
    os_b.get_foreground_window = lambda: vdj_win  # type: ignore[method-assign]
    sess._handle_key_press(Key.alt_l)
    sess._handle_key_press(Key.tab)
    sess._handle_key_release(Key.tab)
    sess._handle_key_release(Key.alt_l)
    assert sess.steps == []

    for _ in range(50):
        sess._handle_key_press(KeyCode.from_char("5"))
    sess._handle_key_release(KeyCode.from_char("5"))
    assert len(sess.steps) == 1
    assert sess.steps[0].hotkey == "5"

    # 3. F9 still stops picking regardless of which window is in foreground
    os_b.get_foreground_window = lambda: antigravity_win  # type: ignore[method-assign]
    sess._handle_key_press(Key.f9)
    assert stopped == [True]

    # 4. PickingHudBar allows focus/click cleanly on Windows
    hud = PickingHudBar("VirtualDJ")
    assert not bool(hud.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus)
    hud_stops = []
    hud.stop_clicked.connect(lambda: hud_stops.append(True))
    hud.stop_btn.click()
    assert hud_stops == [True]
    hud.close()


def test_universal_osc_relative_toggle_query_and_xr18_cmd_dialog(tmp_path):
    import os
    import socket
    import threading
    import pytest
    from PySide6.QtWidgets import QApplication
    from pythonosc.osc_message import OscMessage
    from pythonosc.osc_message_builder import OscMessageBuilder

    from art_director.core.executor import ProgramExecutor
    from art_director.core.state import CancellationToken
    from art_director.targets.base import query_osc_value
    from art_director.ui.program_wizard import AdvancedStepDialog

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _app = QApplication.instance() or QApplication([])

    # 1. Live UDP query_osc_value round-trip on loopback
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.bind(("127.0.0.1", 0))
    srv_port = srv.getsockname()[1]

    def _reply_once() -> None:
        data, client_addr = srv.recvfrom(1024)
        req = OscMessage(data)
        b = OscMessageBuilder(address=req.address)
        b.add_arg(0.625)
        srv.sendto(b.build().dgram, client_addr)
        srv.close()

    t = threading.Thread(target=_reply_once, daemon=True)
    t.start()
    assert query_osc_value("127.0.0.1", srv_port, "/ch/07/mix/fader", timeout_sec=0.5) == pytest.approx(
        0.625
    )

    # 2. Universal OSC relative + toggle + XR18 Smart execution in samples_only workflow
    sent: list[tuple[str, int, str, object]] = []
    live_osc: dict[str, float] = {"/ch/07/mix/fader": 0.50}
    os_b = HybridMockOSBridge()
    ex = ProgramExecutor(
        os_b,
        osc_sender=lambda h, p, a, v: (sent.append((h, p, a, v)), live_osc.__setitem__(a, float(v))),
        osc_querier=lambda _h, _p, a: live_osc.get(a),
    )

    prog_qlc = ProgramProfile(
        id="qlc",
        name="QLC+",
        functions=[
            ProgramFunction(
                id="fn_dim_up",
                commands=["alza dimmer"],
                steps=[
                    ActionStep(
                        kind="osc",
                        osc_host="127.0.0.1",
                        osc_port=7700,
                        osc_address="/1/dimmer",
                        osc_mode="relative",
                        osc_value=15.0,
                        osc_min=0.0,
                        osc_max=255.0,
                        osc_type="int",
                        osc_query_before_update=False,
                    )
                ],
            ),
            ProgramFunction(
                id="fn_strobo_tog",
                commands=["strobo"],
                steps=[
                    ActionStep(
                        kind="osc",
                        osc_host="127.0.0.1",
                        osc_port=7700,
                        osc_address="/vc/strobo",
                        osc_mode="toggle",
                        osc_min=0.0,
                        osc_max=1.0,
                        osc_type="int",
                        osc_query_before_update=False,
                    )
                ],
            ),
            ProgramFunction(
                id="fn_xr_smart",
                commands=["alza chitarra"],
                steps=[
                    ActionStep(
                        kind="xr18_cmd",
                        osc_host="192.168.1.55",
                        osc_port=10024,
                        xr18_command="alza canale 7 di 2 db",
                        xr18_step_db=2.0,
                    )
                ],
            ),
        ],
    )

    # QLC+ one-way relative starts from midpoint (127.5) + 15 -> 142
    r_up1 = ex.execute_function(prog_qlc, prog_qlc.functions[0], {}, CancellationToken())
    assert r_up1.handled
    assert sent[-1] == ("127.0.0.1", 7700, "/1/dimmer", 142)
    r_up2 = ex.execute_function(prog_qlc, prog_qlc.functions[0], {}, CancellationToken())
    assert r_up2.handled
    assert sent[-1] == ("127.0.0.1", 7700, "/1/dimmer", 157)

    # QLC+ toggle alternates 1 -> 0 -> 1
    assert ex.execute_function(prog_qlc, prog_qlc.functions[1], {}, CancellationToken()).handled
    assert sent[-1] == ("127.0.0.1", 7700, "/vc/strobo", 1)
    assert ex.execute_function(prog_qlc, prog_qlc.functions[1], {}, CancellationToken()).handled
    assert sent[-1] == ("127.0.0.1", 7700, "/vc/strobo", 0)

    # XR18 Smart step uses custom IP and live queried fader (0.50 = -10 dB -> -8 dB = 0.55)
    r_xr = ex.execute_function(prog_qlc, prog_qlc.functions[2], {}, CancellationToken())
    assert r_xr.handled
    assert sent[-1][0] == "192.168.1.55"
    assert sent[-1][2] == "/ch/07/mix/fader"
    assert sent[-1][3] == pytest.approx(0.55, abs=1e-4)

    # Config round-trip & UI dialog preserve custom port 7700 and xr18_cmd
    cm = ConfigManager(tmp_path / "osc_cfg.json")
    cm.config.programs.append(prog_qlc)
    cm.save()
    loaded = ConfigManager(tmp_path / "osc_cfg.json").config
    st_osc = loaded.programs[0].functions[0].steps[0]
    dlg1 = AdvancedStepDialog(initial_step=st_osc)
    assert dlg1.kind_combo.currentData() == "osc"
    assert dlg1.port_spin.value() == 7700
    assert dlg1.osc_mode_combo.currentData() == "relative"
    dlg1._on_ok()
    assert dlg1.step is not None and dlg1.step.osc_max == 255.0

    st_xr = loaded.programs[0].functions[2].steps[0]
    dlg2 = AdvancedStepDialog(initial_step=st_xr)
    assert dlg2.kind_combo.currentData() == "xr18_cmd"
    assert dlg2.xr18_cmd_edit.text() == "alza canale 7 di 2 db"
    dlg2._on_ok()
    assert dlg2.step is not None and dlg2.step.osc_host == "192.168.1.55"


def test_function_recorder_delete_step_shortcut_context_and_default_host(tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeySequence, QShortcut
    from PySide6.QtWidgets import QAbstractItemView, QApplication, QMenu
    from art_director.ui.program_wizard import FunctionRecorderDialog, ProgramTabWidget

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _app = QApplication.instance() or QApplication([])

    prog = ProgramProfile(
        id="xair_ui",
        name="X-AIR Edit",
        window_title_patterns=["X-AIR-Edit"],
        functions=[
            ProgramFunction(
                id="alza_7",
                commands=["alza sette"],
                steps=[
                    ActionStep(
                        kind="xr18_cmd",
                        xr18_command="alza canale 7",
                        osc_host="192.168.10.21",
                        osc_port=10024,
                        xr18_step_db=2.0,
                    ),
                    ActionStep(kind="wait", delay_ms=200),
                    ActionStep(kind="hotkey", hotkey="<ctrl>+s"),
                ],
            ),
            ProgramFunction(
                id="abbassa_7",
                commands=["abbassa sette"],
                steps=[ActionStep(kind="wait", delay_ms=100)],
            ),
        ],
    )
    cm = ConfigManager(tmp_path / "ui_del_cfg.json")
    cm.config.programs.append(prog)
    ctrl = ArtDirectorController(
        config_manager=cm,
        os_bridge=HybridMockOSBridge(),
        enable_audio=False,
        enable_hotkeys=False,
    )

    dlg = FunctionRecorderDialog(ctrl, prog, existing_function=prog.functions[0])
    assert dlg._default_osc_host_port() == ("192.168.10.21", 10024)
    assert dlg.steps_list.count() == 3
    assert dlg.steps_list.selectionMode() == QAbstractItemView.SelectionMode.ExtendedSelection
    assert dlg.steps_list.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu

    # Canc/Delete QShortcut removes the currently selected step
    del_shortcuts = [
        sc
        for sc in dlg.steps_list.findChildren(QShortcut)
        if sc.key() == QKeySequence(Qt.Key.Key_Delete)
    ]
    assert len(del_shortcuts) == 1
    dlg.steps_list.setCurrentRow(1)  # wait 200ms
    del_shortcuts[0].activated.emit()
    assert [s.kind for s in dlg._steps] == ["xr18_cmd", "hotkey"]

    # Duplicate & move step work cleanly
    dlg.steps_list.setCurrentRow(1)  # hotkey
    dlg._duplicate_selected_step()
    assert len(dlg._steps) == 3
    dlg._move_selected_step(-1)
    assert [s.kind for s in dlg._steps] == ["xr18_cmd", "hotkey", "hotkey"]

    # Right-click context menu on steps_list exposes Delete and removes step when chosen
    captured_labels: list[str] = []

    def fake_menu_exec(self_menu, _global_pos):
        nonlocal captured_labels
        captured_labels = [act.text() for act in self_menu.actions() if not act.isSeparator()]
        for act in self_menu.actions():
            if "Elimina passo" in act.text():
                return act
        return None

    monkeypatch.setattr(QMenu, "exec", fake_menu_exec)
    item_rect = dlg.steps_list.visualItemRect(dlg.steps_list.item(1))
    dlg._on_steps_context_menu(item_rect.center())
    assert any("Modifica passo" in lbl for lbl in captured_labels)
    assert any("Duplica passo" in lbl for lbl in captured_labels)
    assert any("Elimina passo" in lbl for lbl in captured_labels)
    assert len(dlg._steps) == 2

    # Multi-selection deletion removes all selected rows safely
    dlg.steps_list.clearSelection()
    dlg.steps_list.item(0).setSelected(True)
    dlg.steps_list.item(1).setSelected(True)
    dlg._remove_selected_step()
    assert dlg._steps == []
    # Even when current dialog steps are empty, program-level OSC IP still defaults to 192.168.10.21
    assert dlg._default_osc_host_port() == ("192.168.10.21", 10024)

    # ProgramTabWidget fn_table also supports Delete shortcut and right-click context menu
    tab = ProgramTabWidget(ctrl, prog)
    assert tab.fn_table.selectionBehavior() == QAbstractItemView.SelectionBehavior.SelectRows
    assert tab.fn_table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
    assert tab.fn_table.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu

    fn_shortcuts = [
        sc
        for sc in tab.fn_table.findChildren(QShortcut)
        if sc.key() == QKeySequence(Qt.Key.Key_Delete)
    ]
    assert len(fn_shortcuts) == 1
    assert tab.fn_table.rowCount() == 2

    captured_fn_labels: list[str] = []

    def fake_fn_menu_exec(self_menu, _global_pos):
        nonlocal captured_fn_labels
        captured_fn_labels = [act.text() for act in self_menu.actions() if not act.isSeparator()]
        for act in self_menu.actions():
            if "Elimina funzione" in act.text():
                return act
        return None

    monkeypatch.setattr(QMenu, "exec", fake_fn_menu_exec)
    fn_rect = tab.fn_table.visualItemRect(tab.fn_table.item(1, 0))
    tab._on_fn_table_context_menu(fn_rect.center())
    assert any("Elimina funzione" in lbl for lbl in captured_fn_labels)
    assert len(prog.functions) == 1

    # Pressing Delete (Canc) deletes the remaining row
    tab.fn_table.setCurrentCell(0, 0)
    fn_shortcuts[0].activated.emit()
    assert len(prog.functions) == 0
    assert tab.fn_table.rowCount() == 0

