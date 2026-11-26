"""Linux OS bridge using wmctrl/xdotool (X11/XWayland) and XDG autostart."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .base import OSBridge, WindowInfo


class LinuxOSBridge(OSBridge):
    """Linux implementation for window focus, popup dismissal, and .desktop autostart."""

    @property
    def platform_name(self) -> str:
        return "linux"

    def _desktop_path(self) -> Path:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg) if xdg else Path.home() / ".config"
        return base / "autostart" / "art-director.desktop"

    def list_windows(self) -> list[WindowInfo]:
        windows: list[WindowInfo] = []
        active_id = ""
        if shutil.which("xdotool"):
            try:
                res = subprocess.run(
                    ["xdotool", "getactivewindow"],
                    capture_output=True,
                    text=True,
                    timeout=1.5,
                )
                if res.returncode == 0:
                    active_id = res.stdout.strip()
            except Exception:
                pass

        if shutil.which("wmctrl"):
            try:
                res = subprocess.run(
                    ["wmctrl", "-lp"],
                    capture_output=True,
                    text=True,
                    timeout=1.5,
                )
                for line in res.stdout.splitlines():
                    parts = line.split(None, 4)
                    if len(parts) < 5:
                        continue
                    wid_hex, _desk, pid_s, _host, title = parts
                    wid_int = int(wid_hex, 16)
                    is_active = active_id == str(wid_int)
                    windows.append(
                        WindowInfo(
                            handle=wid_hex,
                            title=title.strip(),
                            pid=int(pid_s) if pid_s.isdigit() else 0,
                            is_active=is_active,
                        )
                    )
                return windows
            except Exception:
                pass

        if shutil.which("xdotool") and active_id:
            try:
                name_res = subprocess.run(
                    ["xdotool", "getwindowname", active_id],
                    capture_output=True,
                    text=True,
                    timeout=1.0,
                )
                if name_res.returncode == 0:
                    windows.append(
                        WindowInfo(
                            handle=active_id,
                            title=name_res.stdout.strip(),
                            is_active=True,
                        )
                    )
            except Exception:
                pass
        return windows

    def get_foreground_window(self) -> WindowInfo | None:
        for win in self.list_windows():
            if win.is_active:
                return win
        return None

    def focus_window(self, patterns: list[str]) -> bool:
        norm_patterns = [p.strip().lower() for p in patterns if p.strip()]
        if not norm_patterns:
            return False

        for win in self.list_windows():
            if any(pat in win.title.lower() for pat in norm_patterns):
                if shutil.which("wmctrl"):
                    res = subprocess.run(
                        ["wmctrl", "-ia", str(win.handle)],
                        capture_output=True,
                        timeout=1.5,
                    )
                    if res.returncode == 0:
                        return True
                if shutil.which("xdotool"):
                    res = subprocess.run(
                        ["xdotool", "windowactivate", str(win.handle)],
                        capture_output=True,
                        timeout=1.5,
                    )
                    return res.returncode == 0
        return False

    def close_window_handle(self, handle: Any) -> bool:
        if handle and shutil.which("wmctrl"):
            res = subprocess.run(
                ["wmctrl", "-ic", str(handle)], capture_output=True, timeout=1.5
            )
            if res.returncode == 0:
                return True
        if handle and shutil.which("xdotool"):
            res = subprocess.run(
                ["xdotool", "windowclose", str(handle)], capture_output=True, timeout=1.5
            )
            if res.returncode == 0:
                return True
        return self.send_hotkey("<alt>+<f4>")

    def get_window_rect(self, handle: Any) -> tuple[int, int, int, int] | None:
        if not handle or not shutil.which("xdotool"):
            return None
        try:
            res = subprocess.run(
                ["xdotool", "getwindowgeometry", "--shell", str(handle)],
                capture_output=True,
                text=True,
                timeout=1.5,
            )
            vals: dict[str, int] = {}
            for line in res.stdout.splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    if v.strip().lstrip("-").isdigit():
                        vals[k.strip()] = int(v.strip())
            if all(k in vals for k in ("X", "Y", "WIDTH", "HEIGHT")):
                return vals["X"], vals["Y"], vals["WIDTH"], vals["HEIGHT"]
        except Exception:
            pass
        return None

    def set_autostart(
        self, enabled: bool, script_or_exe: list[str], background: bool = True
    ) -> tuple[bool, str]:
        desktop_file = self._desktop_path()
        try:
            if not enabled:
                if desktop_file.exists():
                    desktop_file.unlink()
                return True, "Avvio automatico Linux disattivato"

            args = list(script_or_exe)
            if background and "--background" not in args:
                args.append("--background")

            exec_cmd = " ".join(shlex.quote(a) for a in args)
            desktop_file.parent.mkdir(parents=True, exist_ok=True)
            content = (
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=Art Director\n"
                "Comment=Offline Voice Stage Controller\n"
                f"Exec={exec_cmd}\n"
                "Terminal=false\n"
                "X-GNOME-Autostart-enabled=true\n"
            )
            desktop_file.write_text(content, encoding="utf-8")
            return True, f"Desktop entry creata: {desktop_file}"
        except Exception as exc:
            return False, f"Errore configurazione autostart Linux: {exc}"

    def is_autostart_enabled(self) -> bool:
        return self._desktop_path().exists()
