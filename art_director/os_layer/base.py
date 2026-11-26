"""Cross-platform OS abstraction layer interface."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class WindowInfo:
    handle: Any
    title: str
    class_name: str = ""
    pid: int = 0
    is_dialog: bool = False
    is_active: bool = False


def parse_hotkey_tokens(hotkey: str) -> list[str]:
    """Parse '<ctrl>+<shift>+s', '+', '<num_add>', 'numpad+', 'spacebar', or ' ' into tokens."""
    if hotkey == " ":
        return ["space"]
    raw_low = hotkey.strip().lower()
    if raw_low == "+":
        return ["+"]
    direct_numpad_aliases = {
        "numpad+": "num_add",
        "numpad +": "num_add",
        "num+": "num_add",
        "num +": "num_add",
        "tastierino+": "num_add",
        "tastierino +": "num_add",
        "numpad-": "num_sub",
        "numpad -": "num_sub",
        "num-": "num_sub",
        "num -": "num_sub",
        "tastierino-": "num_sub",
        "tastierino -": "num_sub",
    }
    if raw_low in direct_numpad_aliases:
        return [direct_numpad_aliases[raw_low]]

    trailing_plus = raw_low.endswith("++")
    split_src = raw_low[:-1] if trailing_plus else raw_low
    parts = [p.strip() for p in split_src.split("+") if p.strip()]
    if trailing_plus:
        parts.append("+")

    cleaned: list[str] = []
    for part in parts:
        if part.startswith("<") and part.endswith(">"):
            part = part[1:-1].strip()
        for prefix in ("tasto ", "key "):
            if part.startswith(prefix) and len(part) > len(prefix):
                part = part[len(prefix) :].strip()
                break
        if part in direct_numpad_aliases:
            part = direct_numpad_aliases[part]
        if part:
            cleaned.append(part)
    return cleaned


def send_keys_pynput(hotkey: str) -> bool:
    """Send a single key or key combination cross-platform via pynput."""
    tokens = parse_hotkey_tokens(hotkey)
    if not tokens:
        return False
    try:
        from pynput.keyboard import Controller, Key, KeyCode
    except Exception:
        return False

    key_map = {
        "ctrl": Key.ctrl,
        "control": Key.ctrl,
        "ctrl_l": Key.ctrl_l,
        "ctrl_r": Key.ctrl_r,
        "alt": Key.alt,
        "alt_l": Key.alt_l,
        "alt_gr": Key.alt_gr,
        "shift": Key.shift,
        "cmd": Key.cmd,
        "super": Key.cmd,
        "win": Key.cmd,
        "space": Key.space,
        "spacebar": Key.space,
        "spazio": Key.space,
        "barra": Key.space,
        "barraspaziatrice": Key.space,
        "barra spaziatrice": Key.space,
        "spc": Key.space,
        "enter": Key.enter,
        "return": Key.enter,
        "invio": Key.enter,
        "a capo": Key.enter,
        "esc": Key.esc,
        "escape": Key.esc,
        "tab": Key.tab,
        "tabulazione": Key.tab,
        "backspace": Key.backspace,
        "back": Key.backspace,
        "indietro": Key.backspace,
        "delete": Key.delete,
        "del": Key.delete,
        "canc": Key.delete,
        "up": Key.up,
        "su": Key.up,
        "freccia su": Key.up,
        "down": Key.down,
        "giu": Key.down,
        "giù": Key.down,
        "freccia giu": Key.down,
        "freccia giù": Key.down,
        "left": Key.left,
        "sinistra": Key.left,
        "freccia sinistra": Key.left,
        "right": Key.right,
        "destra": Key.right,
        "freccia destra": Key.right,
        "home": Key.home,
        "end": Key.end,
        "page_up": Key.page_up,
        "pageup": Key.page_up,
        "pgup": Key.page_up,
        "pag su": Key.page_up,
        "page_down": Key.page_down,
        "pagedown": Key.page_down,
        "pgdn": Key.page_down,
        "pag giu": Key.page_down,
        "pag giù": Key.page_down,
        "insert": Key.insert,
        "ins": Key.insert,
        "num_add": KeyCode.from_vk(0x6B),
        "numpad_add": KeyCode.from_vk(0x6B),
        "add": KeyCode.from_vk(0x6B),
        "num_sub": KeyCode.from_vk(0x6D),
        "numpad_sub": KeyCode.from_vk(0x6D),
        "subtract": KeyCode.from_vk(0x6D),
        "num_mul": KeyCode.from_vk(0x6A),
        "numpad_mul": KeyCode.from_vk(0x6A),
        "num*": KeyCode.from_vk(0x6A),
        "numpad*": KeyCode.from_vk(0x6A),
        "multiply": KeyCode.from_vk(0x6A),
        "num_div": KeyCode.from_vk(0x6F),
        "numpad_div": KeyCode.from_vk(0x6F),
        "num/": KeyCode.from_vk(0x6F),
        "numpad/": KeyCode.from_vk(0x6F),
        "divide": KeyCode.from_vk(0x6F),
        "num_dec": KeyCode.from_vk(0x6E),
        "numpad_dec": KeyCode.from_vk(0x6E),
        "decimal": KeyCode.from_vk(0x6E),
        **{f"num_{i}": KeyCode.from_vk(0x60 + i) for i in range(10)},
        **{f"numpad{i}": KeyCode.from_vk(0x60 + i) for i in range(10)},
        **{f"num{i}": KeyCode.from_vk(0x60 + i) for i in range(10)},
        "f1": Key.f1,
        "f2": Key.f2,
        "f3": Key.f3,
        "f4": Key.f4,
        "f5": Key.f5,
        "f6": Key.f6,
        "f7": Key.f7,
        "f8": Key.f8,
        "f9": Key.f9,
        "f10": Key.f10,
        "f11": Key.f11,
        "f12": Key.f12,
    }

    resolved: list[Any] = []
    for tok in tokens:
        if tok in key_map:
            resolved.append(key_map[tok])
        elif len(tok) == 1:
            resolved.append(tok)
        else:
            return False

    kb = Controller()
    modifiers = resolved[:-1]
    main_key = resolved[-1]
    pressed: list[Any] = []
    try:
        for mod in modifiers:
            kb.press(mod)
            pressed.append(mod)
        if modifiers:
            time.sleep(0.02)
        kb.press(main_key)
        time.sleep(0.03)
        kb.release(main_key)
        return True
    finally:
        for mod in reversed(pressed):
            try:
                kb.release(mod)
            except Exception:
                pass


class OSBridge(ABC):
    """Abstract platform bridge for windows, popups, launching, and autostart."""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        ...

    @abstractmethod
    def list_windows(self) -> list[WindowInfo]:
        ...

    @abstractmethod
    def get_foreground_window(self) -> WindowInfo | None:
        ...

    @abstractmethod
    def focus_window(self, patterns: list[str]) -> bool:
        ...

    def find_window(self, patterns: list[str]) -> WindowInfo | None:
        norm = [p.strip().lower() for p in patterns if p.strip()]
        if not norm:
            return None
        allow_own = any("art director" in p for p in norm)
        for win in self.list_windows():
            tl = win.title.lower()
            if not allow_own and (
                "art director" in tl
                or "picking su " in tl
                or "nuova funzione / macro" in tl
            ):
                continue
            if any(pat in tl for pat in norm):
                return win
        return None

    def get_window_rect(self, handle: Any) -> tuple[int, int, int, int] | None:  # noqa: ARG002
        """Return (left, top, width, height) in screen coordinates."""
        return None

    @abstractmethod
    def close_window_handle(self, handle: Any) -> bool:
        ...

    def send_hotkey(self, hotkey: str) -> bool:
        return send_keys_pynput(hotkey)

    def set_clipboard_text(self, text: str) -> bool:  # noqa: ARG002
        """Copy UTF-8 text to the OS clipboard when supported."""
        return False

    def mouse_click_at(
        self, x: int, y: int, button: str = "left", clicks: int = 1
    ) -> bool:
        try:
            from pynput.mouse import Button, Controller

            mouse = Controller()
            mouse.position = (int(x), int(y))
            time.sleep(0.02)
            btn = Button.right if button == "right" else Button.left
            mouse.click(btn, max(1, int(clicks)))
            return True
        except Exception:
            return False

    def mouse_scroll_at(self, x: int, y: int, dy: int = 3) -> bool:
        try:
            from pynput.mouse import Controller

            mouse = Controller()
            mouse.position = (int(x), int(y))
            time.sleep(0.02)
            mouse.scroll(0, int(dy))
            return True
        except Exception:
            return False

    def open_document_or_file(self, file_path: str | Path) -> tuple[bool, str]:
        path = str(file_path)
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
                return True, f"Opened {path}"
            if sys.platform == "darwin":
                subprocess.Popen(["open", path])
                return True, f"Opened {path}"
            subprocess.Popen(["xdg-open", path])
            return True, f"Opened {path}"
        except Exception as exc:
            return False, f"Failed to open {path}: {exc}"

    def launch_executable(
        self, executable: str, arguments: str = "", working_dir: str = ""
    ) -> tuple[bool, str]:
        exe = executable.strip()
        if not exe:
            return False, "Percorso eseguibile vuoto"
        cwd = working_dir.strip() or None
        if cwd and not Path(cwd).exists():
            cwd = None

        try:
            if sys.platform == "win32" and exe.lower().endswith((".lnk", ".url")) and not arguments.strip():
                os.startfile(exe)  # type: ignore[attr-defined]
                return True, f"Avviato collegamento Windows: {exe}"

            if sys.platform == "darwin" and exe.endswith(".app"):
                cmd = ["open", "-a", exe]
                if arguments.strip():
                    cmd.extend(["--args", *shlex.split(arguments)])
                subprocess.Popen(cmd, cwd=cwd)
                return True, f"Avviata app macOS: {exe}"

            args_list = shlex.split(arguments, posix=(sys.platform != "win32")) if arguments.strip() else []
            cmd = [exe, *args_list]
            kwargs: dict[str, Any] = {"cwd": cwd}
            if sys.platform == "win32":
                kwargs["creationflags"] = (
                    getattr(subprocess, "DETACHED_PROCESS", 0)
                    | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                )
            else:
                kwargs["start_new_session"] = True
            subprocess.Popen(cmd, **kwargs)
            return True, f"Avviato: {exe}"
        except Exception as exc:
            return False, f"Errore avvio {exe}: {exc}"

    def dismiss_popup(
        self,
        strategy: str,
        dialog_keywords: list[str],
        protect_main_windows: bool,
        protected_patterns: list[str],
    ) -> tuple[bool, str]:
        """Attempt to dismiss an active error dialog, popup, or splash banner."""
        fg = self.get_foreground_window()
        windows = self.list_windows()
        target_win: WindowInfo | None = None

        if fg and self._is_likely_popup(fg, dialog_keywords):
            target_win = fg
        else:
            for win in windows:
                if self._is_likely_popup(win, dialog_keywords):
                    target_win = win
                    break

        if target_win is None:
            target_win = fg

        if target_win is None:
            ok = self.send_hotkey("esc")
            return ok, "Inviato ESC globale (nessuna finestra attiva rilevata)"

        title_l = target_win.title.lower()
        is_protected = protect_main_windows and (
            "art director" in title_l
            or any(p.lower() in title_l for p in protected_patterns if p.strip())
        ) and not target_win.is_dialog

        if strategy == "esc":
            ok = self.send_hotkey("esc")
            return ok, f"Inviato ESC a '{target_win.title}'"
        if strategy == "enter":
            ok = self.send_hotkey("enter")
            return ok, f"Inviato Invio a '{target_win.title}'"
        if strategy == "wm_close":
            if is_protected:
                ok = self.send_hotkey("esc")
                return ok, f"Finestra principale protetta '{target_win.title}': inviato ESC"
            ok = self.close_window_handle(target_win.handle)
            return ok, f"Inviata chiusura finestra a '{target_win.title}'"

        # "smart" or "esc_then_close"
        if target_win.is_dialog or self._matches_keywords(title_l, dialog_keywords):
            self.send_hotkey("esc")
            time.sleep(0.08)
            still_there = self._window_still_exists(target_win.handle)
            if still_there and not is_protected:
                self.close_window_handle(target_win.handle)
                time.sleep(0.05)
                if self._window_still_exists(target_win.handle):
                    self.send_hotkey("enter")
                return True, f"Popup chiuso ('{target_win.title}')"
            return True, f"Popup chiuso con ESC ('{target_win.title}')"

        if is_protected:
            ok = self.send_hotkey("esc")
            return ok, f"Inviato ESC sicuro a '{target_win.title}'"

        ok = self.send_hotkey("esc")
        if strategy == "esc_then_close" and self._window_still_exists(target_win.handle):
            self.close_window_handle(target_win.handle)
        return ok, f"Inviato comando chiusura rapida a '{target_win.title}'"

    def _window_still_exists(self, handle: Any) -> bool:
        return any(w.handle == handle for w in self.list_windows())

    def _matches_keywords(self, title_l: str, keywords: list[str]) -> bool:
        return any(k.lower() in title_l for k in keywords if k.strip())

    def _is_likely_popup(self, win: WindowInfo, keywords: list[str]) -> bool:
        if win.is_dialog:
            return True
        return self._matches_keywords(win.title.lower(), keywords)

    @abstractmethod
    def set_autostart(
        self, enabled: bool, script_or_exe: list[str], background: bool = True
    ) -> tuple[bool, str]:
        ...

    @abstractmethod
    def is_autostart_enabled(self) -> bool:
        ...
