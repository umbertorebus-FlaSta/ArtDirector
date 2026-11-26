"""macOS OS bridge using AppleScript/System Events and LaunchAgents."""

from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path
from typing import Any

from .base import OSBridge, WindowInfo

_PLIST_LABEL = "com.artdirector.daemon"


class MacOSBridge(OSBridge):
    """macOS implementation for window focus, popup dismissal, and LaunchAgents."""

    @property
    def platform_name(self) -> str:
        return "macos"

    def _plist_path(self) -> Path:
        return Path.home() / "Library" / "LaunchAgents" / f"{_PLIST_LABEL}.plist"

    def _run_osascript(self, script: str) -> str:
        try:
            proc = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            return proc.stdout.strip()
        except Exception:
            return ""

    def list_windows(self) -> list[WindowInfo]:
        script = (
            'tell application "System Events"\n'
            "set out to {}\n"
            "set frontProc to name of first application process whose frontmost is true\n"
            "repeat with p in (every application process whose background only is false)\n"
            "set pname to name of p\n"
            "try\n"
            "repeat with w in (every window of p)\n"
            "set wtitle to name of w\n"
            "set wsub to subrole of w\n"
            'set end of out to pname & "|" & wtitle & "|" & wsub & "|" & (pname is equal to frontProc)\n'
            "end repeat\n"
            "end try\n"
            "end repeat\n"
            "return out\n"
            "end tell"
        )
        raw = self._run_osascript(script)
        if not raw:
            return []
        windows: list[WindowInfo] = []
        for entry in raw.split(", "):
            parts = entry.split("|")
            if len(parts) < 4:
                continue
            proc_name, title, subrole, is_front = parts[0], parts[1], parts[2], parts[3]
            display = f"{proc_name} - {title}" if title else proc_name
            windows.append(
                WindowInfo(
                    handle=(proc_name, title),
                    title=display,
                    class_name=subrole,
                    is_dialog=("dialog" in subrole.lower() or "sheet" in subrole.lower()),
                    is_active=(is_front.lower() == "true"),
                )
            )
        return windows

    def get_foreground_window(self) -> WindowInfo | None:
        script = (
            'tell application "System Events"\n'
            "set p to first application process whose frontmost is true\n"
            "set pname to name of p\n"
            'set wtitle to ""\n'
            'set wsub to ""\n'
            "try\n"
            "set w to front window of p\n"
            "set wtitle to name of w\n"
            "set wsub to subrole of w\n"
            "end try\n"
            'return pname & "|" & wtitle & "|" & wsub\n'
            "end tell"
        )
        raw = self._run_osascript(script)
        if not raw:
            return None
        parts = raw.split("|")
        proc_name = parts[0] if parts else ""
        title = parts[1] if len(parts) > 1 else ""
        subrole = parts[2] if len(parts) > 2 else ""
        display = f"{proc_name} - {title}" if title else proc_name
        return WindowInfo(
            handle=(proc_name, title),
            title=display,
            class_name=subrole,
            is_dialog=("dialog" in subrole.lower() or "sheet" in subrole.lower()),
            is_active=True,
        )

    def focus_window(self, patterns: list[str]) -> bool:
        norm_patterns = [p.strip().lower() for p in patterns if p.strip()]
        if not norm_patterns:
            return False
        for win in self.list_windows():
            if any(pat in win.title.lower() for pat in norm_patterns):
                proc_name = win.handle[0] if isinstance(win.handle, tuple) else win.title
                escaped = proc_name.replace('"', '\\"')
                self._run_osascript(f'tell application "{escaped}" to activate')
                return True
        return False

    def close_window_handle(self, handle: Any) -> bool:
        if isinstance(handle, tuple) and handle[0]:
            proc_name = str(handle[0]).replace('"', '\\"')
            self._run_osascript(
                f'tell application "System Events" to tell process "{proc_name}" '
                "to click (first button of front window whose subrole is \"AXCloseButton\")"
            )
            return True
        return self.send_hotkey("<cmd>+w")

    def get_window_rect(self, handle: Any) -> tuple[int, int, int, int] | None:
        if not (isinstance(handle, tuple) and handle[0]):
            return None
        proc_name = str(handle[0]).replace('"', '\\"')
        raw = self._run_osascript(
            f'tell application "System Events" to tell process "{proc_name}"\n'
            "set p to position of front window\n"
            "set s to size of front window\n"
            'return (item 1 of p) & "," & (item 2 of p) & "," & (item 1 of s) & "," & (item 2 of s)\n'
            "end tell"
        )
        parts = [x.strip() for x in raw.split(",")]
        if len(parts) == 4 and all(p.lstrip("-").isdigit() for p in parts):
            return int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
        return None

    def set_autostart(
        self, enabled: bool, script_or_exe: list[str], background: bool = True
    ) -> tuple[bool, str]:
        plist_path = self._plist_path()
        try:
            if not enabled:
                if plist_path.exists():
                    plist_path.unlink()
                return True, "Avvio automatico macOS disattivato"

            args = list(script_or_exe)
            if background and "--background" not in args:
                args.append("--background")

            plist_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "Label": _PLIST_LABEL,
                "ProgramArguments": args,
                "RunAtLoad": True,
                "KeepAlive": False,
            }
            with plist_path.open("wb") as fp:
                plistlib.dump(data, fp)
            return True, f"LaunchAgent creato: {plist_path}"
        except Exception as exc:
            return False, f"Errore configurazione LaunchAgent macOS: {exc}"

    def is_autostart_enabled(self) -> bool:
        return self._plist_path().exists()
