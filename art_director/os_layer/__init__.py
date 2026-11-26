"""OS abstraction factory and exports."""

from __future__ import annotations

import sys
from pathlib import Path

from .base import OSBridge, WindowInfo, send_keys_pynput
from .hotkeys import GlobalHotkeyManager, format_hotkey_display, normalize_pynput_hotkey
from .installer import (
    enable_portable_mode,
    get_install_dir,
    install_on_system,
    is_installed_on_system,
    uninstall_from_system,
)
from .linux import LinuxOSBridge
from .macos import MacOSBridge
from .picker import WindowPickerSession
from .windows import WindowsOSBridge


def create_os_bridge() -> OSBridge:
    if sys.platform == "win32":
        return WindowsOSBridge()
    if sys.platform == "darwin":
        return MacOSBridge()
    return LinuxOSBridge()


def get_launch_command_parts() -> list[str]:
    """Return the exact executable + script arguments for OS autostart registration."""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    entry = Path(__file__).resolve().parents[2] / "run_art_director.py"
    return [sys.executable, str(entry)]


__all__ = [
    "GlobalHotkeyManager",
    "LinuxOSBridge",
    "MacOSBridge",
    "OSBridge",
    "WindowInfo",
    "WindowPickerSession",
    "WindowsOSBridge",
    "create_os_bridge",
    "enable_portable_mode",
    "format_hotkey_display",
    "get_install_dir",
    "get_launch_command_parts",
    "install_on_system",
    "is_installed_on_system",
    "normalize_pynput_hotkey",
    "send_keys_pynput",
    "uninstall_from_system",
]
