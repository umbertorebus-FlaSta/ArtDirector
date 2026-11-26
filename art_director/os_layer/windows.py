"""Windows OS bridge using ctypes Win32 APIs and winreg."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import subprocess
import sys
from pathlib import Path
from typing import Any

from .base import OSBridge, WindowInfo

if sys.platform == "win32":
    import winreg

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.restype = wintypes.BOOL
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextLengthW.restype = ctypes.c_int
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowTextW.restype = ctypes.c_int
    _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetClassNameW.restype = ctypes.c_int
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetWindowLongW.restype = ctypes.c_long
    _user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    _user32.GetWindow.restype = wintypes.HWND
    _user32.IsIconic.argtypes = [wintypes.HWND]
    _user32.IsIconic.restype = wintypes.BOOL
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.ShowWindow.restype = wintypes.BOOL
    _user32.BringWindowToTop.argtypes = [wintypes.HWND]
    _user32.BringWindowToTop.restype = wintypes.BOOL
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.SetForegroundWindow.restype = wintypes.BOOL
    _user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    _user32.AttachThreadInput.restype = wintypes.BOOL
    _user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.PostMessageW.restype = wintypes.BOOL
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.GetWindowRect.restype = wintypes.BOOL
    _user32.OpenClipboard.argtypes = [wintypes.HWND]
    _user32.OpenClipboard.restype = wintypes.BOOL
    _user32.CloseClipboard.argtypes = []
    _user32.CloseClipboard.restype = wintypes.BOOL
    _user32.EmptyClipboard.argtypes = []
    _user32.EmptyClipboard.restype = wintypes.BOOL
    _user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    _user32.SetClipboardData.restype = wintypes.HANDLE
    _kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    _kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    _kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalLock.restype = ctypes.c_void_p
    _kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalUnlock.restype = wintypes.BOOL
    _kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalFree.restype = wintypes.HGLOBAL
    _CF_UNICODETEXT = 13
    _GMEM_MOVEABLE = 0x0002
    _WM_CLOSE = 0x0010
    _SW_RESTORE = 9
    _GWL_STYLE = -16
    _WS_POPUP = 0x80000000
    _GW_OWNER = 4
    _RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    _RUN_NAME = "ArtDirector"
else:
    _user32 = None
    _kernel32 = None


def _build_window_info(hwnd: int, fg_hwnd: int, allow_empty_title: bool = False) -> WindowInfo | None:
    if _user32 is None or not hwnd:
        return None
    length = _user32.GetWindowTextLengthW(hwnd)
    if length <= 0 and not allow_empty_title:
        return None
    buf = ctypes.create_unicode_buffer(max(1, length + 1))
    if length > 0:
        _user32.GetWindowTextW(hwnd, buf, length + 1)
    title = buf.value.strip()
    if not title and not allow_empty_title:
        return None

    cls_buf = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, cls_buf, 256)
    cls_name = cls_buf.value

    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    style = _user32.GetWindowLongW(hwnd, _GWL_STYLE)
    owner = _user32.GetWindow(hwnd, _GW_OWNER)
    is_dialog = cls_name == "#32770" or (bool(owner) and bool(style & _WS_POPUP))
    return WindowInfo(
        handle=hwnd,
        title=title,
        class_name=cls_name,
        pid=int(pid.value),
        is_dialog=is_dialog,
        is_active=(hwnd == fg_hwnd),
    )


class WindowsOSBridge(OSBridge):
    """Windows implementation for window focus, popup dismissal, and HKCU Run autostart."""

    @property
    def platform_name(self) -> str:
        return "windows"

    def list_windows(self) -> list[WindowInfo]:
        if _user32 is None:
            return []
        windows: list[WindowInfo] = []
        fg_hwnd = _user32.GetForegroundWindow() or 0
        enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _callback(hwnd: int, _lparam: int) -> bool:
            if not _user32.IsWindowVisible(hwnd):
                return True
            info = _build_window_info(hwnd, fg_hwnd, allow_empty_title=False)
            if info is not None:
                windows.append(info)
            return True

        _user32.EnumWindows(enum_proc_type(_callback), 0)
        return windows

    def get_foreground_window(self) -> WindowInfo | None:
        if _user32 is None:
            return None
        hwnd = _user32.GetForegroundWindow()
        if not hwnd:
            return None
        return _build_window_info(hwnd, hwnd, allow_empty_title=True)

    def focus_window(self, patterns: list[str]) -> bool:
        if _user32 is None or not patterns:
            return False
        match = self.find_window(patterns)
        if match is None:
            return False

        hwnd = int(match.handle)
        if _user32.IsIconic(hwnd):
            _user32.ShowWindow(hwnd, _SW_RESTORE)

        fg = _user32.GetForegroundWindow()
        if fg == hwnd:
            return True

        fg_thread = _user32.GetWindowThreadProcessId(fg, None) if fg else 0
        cur_thread = _kernel32.GetCurrentThreadId()
        attached = False
        try:
            if fg_thread and fg_thread != cur_thread:
                attached = bool(_user32.AttachThreadInput(cur_thread, fg_thread, True))
            _user32.BringWindowToTop(hwnd)
            ok = bool(_user32.SetForegroundWindow(hwnd))
            return ok
        finally:
            if attached:
                _user32.AttachThreadInput(cur_thread, fg_thread, False)

    def close_window_handle(self, handle: Any) -> bool:
        if _user32 is None or not handle:
            return False
        return bool(_user32.PostMessageW(int(handle), _WM_CLOSE, 0, 0))

    def get_window_rect(self, handle: Any) -> tuple[int, int, int, int] | None:
        if _user32 is None or not handle:
            return None
        rect = wintypes.RECT()
        if not _user32.GetWindowRect(int(handle), ctypes.byref(rect)):
            return None
        w = int(rect.right - rect.left)
        h = int(rect.bottom - rect.top)
        if w <= 0 or h <= 0:
            return None
        return (int(rect.left), int(rect.top), w, h)

    def set_clipboard_text(self, text: str) -> bool:
        if _user32 is None or _kernel32 is None:
            return False
        data = (text + "\x00").encode("utf-16-le")
        hmem = _kernel32.GlobalAlloc(_GMEM_MOVEABLE, len(data))
        if not hmem:
            return False
        ptr = _kernel32.GlobalLock(hmem)
        if not ptr:
            _kernel32.GlobalFree(hmem)
            return False
        ctypes.memmove(ptr, data, len(data))
        _kernel32.GlobalUnlock(hmem)
        if not _user32.OpenClipboard(None):
            _kernel32.GlobalFree(hmem)
            return False
        try:
            _user32.EmptyClipboard()
            if not _user32.SetClipboardData(_CF_UNICODETEXT, hmem):
                _kernel32.GlobalFree(hmem)
                return False
            return True
        finally:
            _user32.CloseClipboard()

    def set_autostart(
        self, enabled: bool, script_or_exe: list[str], background: bool = True
    ) -> tuple[bool, str]:
        if sys.platform != "win32":
            return False, "Non siamo su Windows"
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_ALL_ACCESS
            ) as key:
                if not enabled:
                    try:
                        winreg.DeleteValue(key, _RUN_NAME)
                    except FileNotFoundError:
                        pass
                    return True, "Avvio automatico Windows disattivato"

                cmd_parts = list(script_or_exe)
                if cmd_parts:
                    exe_path = Path(cmd_parts[0])
                    if exe_path.name.lower() == "python.exe":
                        pythonw = exe_path.with_name("pythonw.exe")
                        if pythonw.exists():
                            cmd_parts[0] = str(pythonw)
                if background and "--background" not in cmd_parts:
                    cmd_parts.append("--background")

                cmdline = subprocess.list2cmdline(cmd_parts)
                winreg.SetValueEx(key, _RUN_NAME, 0, winreg.REG_SZ, cmdline)
                return True, f"Avvio automatico Windows attivato: {cmdline}"
        except Exception as exc:
            return False, f"Errore configurazione avvio automatico Windows: {exc}"

    def is_autostart_enabled(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ
            ) as key:
                val, _ = winreg.QueryValueEx(key, _RUN_NAME)
                return bool(val)
        except FileNotFoundError:
            return False
        except Exception:
            return False
