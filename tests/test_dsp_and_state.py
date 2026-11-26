"""Tests for anti-feedback audio DSP and Sleep/Wake/Panic state manager."""

from __future__ import annotations

import numpy as np

from art_director.audio.dsp import AudioDSPProcessor, HighPassFilter
from art_director.config import SleepWakeSettings
from art_director.core.event_bus import EventBus
from art_director.core.state import ListeningMode, StateManager


def test_highpass_attenuates_low_monitor_bleed():
    sr = 16000
    t = np.arange(sr // 2) / float(sr)
    low_rumble = (0.5 * np.sin(2 * np.pi * 35.0 * t)).astype(np.float32)
    speech_tone = (0.5 * np.sin(2 * np.pi * 1000.0 * t)).astype(np.float32)

    hpf = HighPassFilter(cutoff_hz=120.0, sample_rate=sr)
    out_low = hpf.process(low_rumble)
    hpf.reset()
    out_high = hpf.process(speech_tone)

    rms_low_in = float(np.sqrt(np.mean(low_rumble ** 2)))
    rms_low_out = float(np.sqrt(np.mean(out_low[200:] ** 2)))
    rms_high_out = float(np.sqrt(np.mean(out_high[200:] ** 2)))

    assert rms_low_out < rms_low_in * 0.4
    assert rms_high_out > rms_low_out * 2.5


def test_noise_gate_blocks_quiet_noise_and_segments_speech():
    dsp = AudioDSPProcessor(
        sample_rate=16000,
        highpass_enabled=False,
        noise_gate_db=-35.0,
        hangover_ms=64,
        max_utterance_sec=2.0,
    )
    quiet = np.full(1024, 0.001, dtype=np.float32)  # ~ -60 dBFS
    res_q = dsp.process_block(quiet)
    assert res_q.gate_open is False
    assert res_q.pcm16_bytes == b"\x00\x00" * 1024

    loud = np.full(1024, 0.25, dtype=np.float32)  # ~ -12 dBFS
    res_l = dsp.process_block(loud)
    assert res_l.gate_open is True
    assert res_l.completed_utterance is None

    # Silence after speech triggers hangover and then completes utterance
    completed = None
    for _ in range(4):
        step = dsp.process_block(quiet)
        if step.completed_utterance is not None:
            completed = step.completed_utterance
            break
    assert completed is not None
    assert completed.size >= 1024


def test_state_manager_emojis_and_cancellation():
    bus = EventBus()
    sw = SleepWakeSettings(start_in_sleep_mode=False, wake_emoji="👍", sleep_emoji="👋")
    sm = StateManager(sw, bus)

    assert sm.mode == ListeningMode.WAKE
    assert sm.emoji == "👍"

    sm.set_sleep("test")
    assert sm.mode == ListeningMode.SLEEP
    assert sm.emoji == "👋"

    token = sm.trigger_panic("test")
    assert token.is_cancelled is True
    assert sm.mode == ListeningMode.PANIC
    assert sm.emoji == "🚨"

    sm.finish_panic(enter_sleep=True)
    assert sm.mode == ListeningMode.SLEEP
    assert sm.emoji == "👋"
    assert sm.panic_token.is_cancelled is False


def test_midi_program_change_roundtrip_and_execution(monkeypatch):
    import sys
    import types

    from art_director.config.schema import (
        ActionStep,
        AppConfig,
        ProgramFunction,
        ProgramProfile,
        compute_function_signature,
    )
    from art_director.core.executor import ProgramExecutor
    from art_director.core.state import CancellationToken
    from art_director.os_layer import create_os_bridge

    step = ActionStep(
        kind="midi_pc",
        midi_port="Synth Out",
        midi_channel=2,
        midi_value=45,
        midi_bank_msb=1,
        midi_bank_lsb=4,
    )
    assert "ProgChg" in step.describe()
    assert "MSB=1" in step.describe()
    assert "LSB=4" in step.describe()
    assert compute_function_signature([step]) == "midipc:2:1:4:45"

    cfg = AppConfig()
    cfg.sleep_wake.ptt_hotkey = "pause"
    cfg.sleep_wake.auto_sleep_after_sec = 12.5
    cfg.programs.append(
        ProgramProfile(
            id="synth",
            name="Tastiera",
            functions=[
                ProgramFunction(
                    id="fn_pc",
                    commands=["suono piano"],
                    steps=[step],
                    focus_before_run=False,
                    launch_if_closed=False,
                )
            ],
        )
    )
    restored = AppConfig.from_dict(cfg.to_dict())
    assert restored.sleep_wake.ptt_hotkey == "pause"
    assert restored.sleep_wake.auto_sleep_after_sec == 12.5
    restored_step = restored.programs[-1].functions[0].steps[0]
    assert restored_step.kind == "midi_pc"
    assert restored_step.midi_bank_msb == 1
    assert restored_step.midi_bank_lsb == 4
    assert restored_step.midi_value == 45

    sent_messages: list[object] = []

    class _FakePort:
        def send(self, msg):
            sent_messages.append(msg)

        def close(self):
            pass

    fake_mido = types.SimpleNamespace(
        Message=lambda msg_type, **kwargs: types.SimpleNamespace(
            type=msg_type, **kwargs
        )
    )
    monkeypatch.setitem(sys.modules, "mido", fake_mido)

    ex = ProgramExecutor(os_bridge=create_os_bridge())
    monkeypatch.setattr(ex._midi, "_ensure_port", lambda _name: _FakePort())
    prog = restored.programs[-1]
    res = ex.execute_function(prog, prog.functions[0], {}, CancellationToken())
    assert res.handled is True
    assert len(sent_messages) == 3
    assert (sent_messages[0].type, sent_messages[0].channel, sent_messages[0].control, sent_messages[0].value) == (
        "control_change",
        1,
        0,
        1,
    )
    assert (sent_messages[1].type, sent_messages[1].channel, sent_messages[1].control, sent_messages[1].value) == (
        "control_change",
        1,
        32,
        4,
    )
    assert (sent_messages[2].type, sent_messages[2].channel, sent_messages[2].program) == (
        "program_change",
        1,
        45,
    )
    ex.close()


def test_dsp_flush_pending_and_capture_service_ptt_release():
    from art_director.audio.input_stream import AudioCaptureService
    from art_director.config.schema import AudioSettings

    captured = []
    svc = AudioCaptureService(
        settings=AudioSettings(sample_rate=16000, highpass_enabled=False, noise_gate_db=-35.0),
        bus=EventBus(),
        on_chunk=captured.append,
    )
    loud = np.full(1024, 0.3, dtype=np.float32)
    for _ in range(3):
        res = svc.dsp.process_block(loud)
        assert res.completed_utterance is None

    # PTT release flushes buffered active speech without needing silence hangover
    svc.set_muted(True, flush_pending=True)
    assert len(captured) == 1
    assert captured[0].completed_utterance is not None
    assert captured[0].completed_utterance.size >= 1600
    assert svc.dsp.flush_pending() is None


def test_hotkey_manager_ptt_dedup_and_aliases():
    import types

    from art_director.os_layer.hotkeys import (
        GlobalHotkeyManager,
        _hotkey_tokens,
        normalize_pynput_hotkey,
    )

    assert normalize_pynput_hotkey("pause") == "<pause>"
    assert normalize_pynput_hotkey("scroll_lock") == "<scroll_lock>"
    assert normalize_pynput_hotkey("<alt>+-") == "<alt>+-"
    assert _hotkey_tokens("<ctrl>+<space>") == {"ctrl", "space"}

    press_count = 0
    release_count = 0

    def _on_press():
        nonlocal press_count
        press_count += 1

    def _on_release():
        nonlocal release_count
        release_count += 1

    mgr = GlobalHotkeyManager()
    mgr._ptt_tokens = _hotkey_tokens("pause")
    mgr._on_ptt_press = _on_press
    mgr._on_ptt_release = _on_release

    pause_key = types.SimpleNamespace(name="pause")
    # OS key-repeat presses must fire on_ptt_press once
    mgr._handle_ptt_press(pause_key)
    mgr._handle_ptt_press(pause_key)
    assert press_count == 1
    assert mgr.is_ptt_held is True

    mgr._handle_ptt_release(pause_key)
    assert release_count == 1
    assert mgr.is_ptt_held is False

    # Combo <ctrl>+<space> requires both keys held
    mgr._ptt_tokens = _hotkey_tokens("<ctrl>+<space>")
    ctrl_key = types.SimpleNamespace(name="ctrl_l")
    space_key = types.SimpleNamespace(name="space")
    mgr._handle_ptt_press(ctrl_key)
    assert press_count == 1
    mgr._handle_ptt_press(space_key)
    assert press_count == 2
    mgr._handle_ptt_release(space_key)
    assert release_count == 2


def test_controller_ptt_and_auto_sleep(tmp_path):
    import time

    from art_director.config import ConfigManager
    from art_director.core.controller import ArtDirectorController

    cfg_mgr = ConfigManager(tmp_path / "cfg1.json")
    cfg = cfg_mgr.config
    cfg.stt.engine = "samples_only"
    cfg.stt.samples_dir = str(tmp_path)
    cfg.sleep_wake.start_in_sleep_mode = True
    cfg.sleep_wake.mute_mic_in_sleep = True
    cfg.sleep_wake.ptt_hotkey = "pause"

    ctrl = ArtDirectorController(cfg_mgr, enable_audio=False, enable_hotkeys=False)
    ctrl.start(launched_at_boot=False)
    try:
        assert ctrl.state.mode == ListeningMode.SLEEP
        assert ctrl.audio._muted is True

        ctrl._on_ptt_press()
        assert ctrl.state.mode == ListeningMode.WAKE
        assert ctrl.audio._muted is False

        ctrl._on_ptt_release()
        assert ctrl.state.mode == ListeningMode.SLEEP
        assert ctrl.audio._muted is True
        assert ctrl._ptt_grace_until > time.monotonic()
    finally:
        ctrl.stop()

    cfg_mgr2 = ConfigManager(tmp_path / "cfg2.json")
    cfg2 = cfg_mgr2.config
    cfg2.stt.engine = "samples_only"
    cfg2.stt.samples_dir = str(tmp_path)
    cfg2.sleep_wake.start_in_sleep_mode = False
    cfg2.sleep_wake.mute_mic_in_sleep = False
    cfg2.sleep_wake.ptt_hotkey = ""
    cfg2.sleep_wake.auto_sleep_after_sec = 0.12

    ctrl2 = ArtDirectorController(cfg_mgr2, enable_audio=False, enable_hotkeys=False)
    ctrl2.start(launched_at_boot=False)
    try:
        assert ctrl2.state.mode == ListeningMode.WAKE
        deadline = time.monotonic() + 1.5
        while ctrl2.state.mode != ListeningMode.SLEEP and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ctrl2.state.mode == ListeningMode.SLEEP
    finally:
        ctrl2.stop()


def test_hotkey_display_plus_and_qt_conversion():
    from PySide6.QtCore import Qt
    from pynput import keyboard

    from art_director.os_layer.hotkeys import (
        _parse_single_hotkey_for_pynput,
        format_hotkey_display,
        normalize_pynput_hotkey,
    )
    from art_director.ui import qt_key_to_pynput_hotkey

    assert normalize_pynput_hotkey("<alt>++") == "<alt>+<plus>"
    assert format_hotkey_display("<ctrl>+<esc>") == "Ctrl+Esc"
    assert format_hotkey_display("<alt>+-") == "Alt+-"
    assert format_hotkey_display("<alt>+<plus>") == "Alt++"
    assert format_hotkey_display("<pause>") == "Pausa"
    assert format_hotkey_display("") == ""

    parsed_plus = _parse_single_hotkey_for_pynput(keyboard, "<alt>+<plus>")
    assert parsed_plus == [keyboard.Key.alt, keyboard.KeyCode.from_char("+")]

    # Pure enum conversion checks (no QApplication needed)
    assert qt_key_to_pynput_hotkey(Qt.Key.Key_Control, Qt.KeyboardModifier.ControlModifier) == ""
    assert (
        qt_key_to_pynput_hotkey(
            Qt.Key.Key_Escape,
            Qt.KeyboardModifier.ControlModifier,
        )
        == "<ctrl>+<esc>"
    )
    assert (
        qt_key_to_pynput_hotkey(
            Qt.Key.Key_Minus,
            Qt.KeyboardModifier.AltModifier,
            "-",
        )
        == "<alt>+-"
    )
    assert qt_key_to_pynput_hotkey(Qt.Key.Key_F12, Qt.KeyboardModifier.NoModifier) == "<f12>"
    assert (
        qt_key_to_pynput_hotkey(
            Qt.Key.Key_S,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier,
            "s",
        )
        == "<ctrl>+<alt>+s"
    )
