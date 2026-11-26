"""Tests for popup interception/protection and stage application startup launcher."""

from __future__ import annotations

from art_director.config import StageAppEntry, StageLauncherSettings
from art_director.core.app_launcher import StageAppLauncher
from art_director.core.event_bus import EventBus
from art_director.core.state import CancellationToken
from art_director.os_layer.base import OSBridge, WindowInfo


class MockPopupLauncherOS(OSBridge):
    def __init__(self) -> None:
        self.windows = [
            WindowInfo(handle=10, title="Cakewalk", is_dialog=False, is_active=False),
            WindowInfo(
                handle=20,
                title="Audio Device Not Detected - Error",
                class_name="#32770",
                is_dialog=True,
                is_active=True,
            ),
        ]
        self.closed_handles: list[int] = []
        self.sent_keys: list[str] = []
        self.launched: list[tuple[str, str, str]] = []

    @property
    def platform_name(self) -> str:
        return "mock"

    def list_windows(self) -> list[WindowInfo]:
        return list(self.windows)

    def get_foreground_window(self) -> WindowInfo | None:
        for w in self.windows:
            if w.is_active:
                return w
        return None

    def focus_window(self, patterns: list[str]) -> bool:
        return True

    def close_window_handle(self, handle) -> bool:  # noqa: ANN001
        self.closed_handles.append(handle)
        self.windows = [w for w in self.windows if w.handle != handle]
        return True

    def send_hotkey(self, hotkey: str) -> bool:
        self.sent_keys.append(hotkey)
        return True

    def launch_executable(self, executable: str, arguments: str = "", working_dir: str = ""):
        self.launched.append((executable, arguments, working_dir))
        return True, f"Launched {executable}"

    def set_autostart(self, enabled, script_or_exe, background=True):  # noqa: ANN001
        return True, "ok"

    def is_autostart_enabled(self) -> bool:
        return False


def test_popup_dismiss_closes_dialog_but_protects_main_window():
    os_b = MockPopupLauncherOS()
    ok, msg = os_b.dismiss_popup(
        strategy="smart",
        dialog_keywords=["error", "audio", "device"],
        protect_main_windows=True,
        protected_patterns=["Cakewalk"],
    )
    assert ok is True
    assert "esc" in os_b.sent_keys
    assert 20 in os_b.closed_handles
    assert 10 not in os_b.closed_handles
    assert "Audio Device Not Detected" in msg


def test_stage_launcher_startup_sequence_and_panic_abort():
    os_b = MockPopupLauncherOS()
    settings = StageLauncherSettings(
        launch_apps_on_art_director_start=True,
        initial_startup_delay_sec=0.0,
        apps=[
            StageAppEntry(
                id="mixer",
                name="X-AIR Edit",
                aliases=["mixer"],
                executable="/apps/xair",
                delay_after_sec=0.01,
                launch_on_startup=True,
                skip_if_running=False,
            ),
            StageAppEntry(
                id="lights",
                name="QLC+",
                aliases=["luci"],
                executable="/apps/qlcplus",
                arguments="-w",
                delay_after_sec=0.01,
                launch_on_startup=True,
                skip_if_running=False,
            ),
            StageAppEntry(
                id="dj",
                name="VirtualDJ",
                aliases=["vdj"],
                executable="/apps/vdj",
                launch_on_startup=False,
                skip_if_running=False,
            ),
        ],
    )
    launcher = StageAppLauncher(settings, os_b, EventBus())
    logs = launcher.launch_all_startup_apps(
        cancel_token=CancellationToken(), only_flagged=True, initial_delay=False
    )
    assert len(logs) == 2
    assert os_b.launched == [("/apps/xair", "", ""), ("/apps/qlcplus", "-w", "")]

    # Voice launch single app (even if not flagged for boot)
    ok_single, _ = launcher.handle_voice_command("apri vdj")
    assert ok_single is True
    assert os_b.launched[-1] == ("/apps/vdj", "", "")

    # Pre-cancelled token aborts startup sequence immediately
    os_b.launched.clear()
    cancelled = CancellationToken()
    cancelled.cancel()
    abort_logs = launcher.launch_all_startup_apps(
        cancel_token=cancelled, only_flagged=True, initial_delay=False
    )
    assert os_b.launched == []
    assert "PANIC" in abort_logs[0]
