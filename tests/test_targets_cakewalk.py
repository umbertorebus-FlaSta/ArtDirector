"""Tests for Sonar Cakewalk / DAW target (transport, unique project switching, named tracks)."""

from __future__ import annotations

from art_director.config import AppConfig
from art_director.core.event_bus import EventBus
from art_director.core.state import CancellationToken
from art_director.os_layer.base import OSBridge, WindowInfo
from art_director.targets import CakewalkDAWTarget, TargetContext, find_project_by_unique_name


class FakeOSBridge(OSBridge):
    def __init__(self) -> None:
        self.focused: list[list[str]] = []
        self.hotkeys: list[str] = []
        self.opened_files: list[str] = []

    @property
    def platform_name(self) -> str:
        return "test"

    def list_windows(self) -> list[WindowInfo]:
        return [WindowInfo(handle=1, title="Cakewalk - Live", is_active=True)]

    def get_foreground_window(self) -> WindowInfo | None:
        return self.list_windows()[0]

    def focus_window(self, patterns: list[str]) -> bool:
        self.focused.append(patterns)
        return True

    def close_window_handle(self, handle) -> bool:  # noqa: ANN001
        return True

    def send_hotkey(self, hotkey: str) -> bool:
        self.hotkeys.append(hotkey)
        return True

    def open_document_or_file(self, file_path) -> tuple[bool, str]:  # noqa: ANN001
        self.opened_files.append(str(file_path))
        return True, f"Opened {file_path}"

    def set_autostart(self, enabled, script_or_exe, background=True):  # noqa: ANN001
        return True, "ok"

    def is_autostart_enabled(self) -> bool:
        return False


class FakeMidi:
    def __init__(self) -> None:
        self.cc_calls: list[tuple[str, int, int, int]] = []
        self.note_calls: list[tuple[str, int, int, int]] = []

    def send_cc(self, port_name: str, channel: int, control: int, value: int) -> bool:
        self.cc_calls.append((port_name, channel, control, value))
        return True

    def send_note(self, port_name: str, channel: int, note: int, velocity: int = 127) -> bool:
        self.note_calls.append((port_name, channel, note, velocity))
        return True

    def close(self) -> None:
        pass


def test_find_project_by_unique_name_and_ambiguity(tmp_path):
    (tmp_path / "Intro_Concerto.cwp").write_text("dummy", encoding="utf-8")
    (tmp_path / "Rock_Medley_2026.cwp").write_text("dummy", encoding="utf-8")
    (tmp_path / "Ballad_Uno.cwp").write_text("dummy", encoding="utf-8")
    (tmp_path / "Ballad_Due.cwp").write_text("dummy", encoding="utf-8")

    match, _, _ = find_project_by_unique_name("rock medley", [str(tmp_path)], [".cwp"])
    assert match is not None and match.name == "Rock_Medley_2026.cwp"

    ambig, cands, msg = find_project_by_unique_name("ballad", [str(tmp_path)], [".cwp"])
    assert ambig is None
    assert len(cands) == 2
    assert "non univoco" in msg.lower()


def test_cakewalk_transport_project_switch_and_named_tracks(tmp_path):
    proj = tmp_path / "Finale_Show.cwp"
    proj.write_text("data", encoding="utf-8")

    cfg = AppConfig()
    cfg.cakewalk.workspace_folders = [str(tmp_path)]
    cfg.cakewalk.close_wait_ms = 50
    cfg.cakewalk.midi_port_name = "loopMIDI Port"

    os_b = FakeOSBridge()
    midi = FakeMidi()
    target = CakewalkDAWTarget(midi=midi)  # type: ignore[arg-type]
    ctx = TargetContext(cfg, os_b, CancellationToken(), EventBus())

    assert target.handle("play", ctx).handled
    assert target.handle("registra", ctx).handled
    assert target.handle("inserisci marker", ctx).handled
    assert target.handle("prossimo marker", ctx).handled
    assert "space" in os_b.hotkeys
    assert "r" in os_b.hotkeys
    assert "m" in os_b.hotkeys

    # Clean close + unique project open
    res = target.handle("apri progetto finale show", ctx)
    assert res.handled
    assert "<ctrl>+s" in os_b.hotkeys
    assert "<ctrl>+w" in os_b.hotkeys
    assert str(proj) in os_b.opened_files

    # Track volume & edit FX by unique name ("voce")
    res_vol = target.handle("volume traccia voce 50", ctx)
    assert res_vol.handled
    assert midi.cc_calls[-1] == ("loopMIDI Port", 1, 7, 64)

    res_fx = target.handle("edit effetti voce", ctx)
    assert res_fx.handled
    assert midi.cc_calls[-1] == ("loopMIDI Port", 1, 20, 127)


def test_find_project_ignores_sonar_autosave_copies_when_primary_exists(tmp_path):
    (tmp_path / "Money  48KHz  6'.cwp").write_text("main", encoding="utf-8")
    (tmp_path / "Salva automaticamente copia di Money  48KHz  6'.cwp").write_text("bak", encoding="utf-8")
    (tmp_path / "L'ultima Luna 48KHz  5' 30.cwp").write_text("main2", encoding="utf-8")
    (tmp_path / "Salva automaticamente copia di L'ultima Luna 48KHz  5' 30.cwp").write_text("bak2", encoding="utf-8")

    m1, _, _ = find_project_by_unique_name("money", [str(tmp_path)], [".cwp"])
    assert m1 is not None and m1.name == "Money  48KHz  6'.cwp"

    m2, _, _ = find_project_by_unique_name("ultima luna", [str(tmp_path)], [".cwp"])
    assert m2 is not None and m2.name == "L'ultima Luna 48KHz  5' 30.cwp"
