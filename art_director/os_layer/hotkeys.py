"""Cross-platform global hotkey manager."""

from __future__ import annotations

import sys
import threading
from typing import Callable


def _split_hotkey_parts(hotkey: str) -> list[str]:
    """Split a hotkey string on '+' while preserving a literal trailing '+' or '++'."""
    raw = hotkey.strip()
    if not raw:
        return []
    parts: list[str] = []
    # Preserve literal '+' if expression ends with '+' (e.g. '<alt>++' or '+')
    trailing_plus = raw.endswith("+")
    for tok in raw.split("+"):
        t = tok.strip().lower()
        if t:
            parts.append(t)
    if trailing_plus:
        parts.append("plus")
    return parts


def normalize_pynput_hotkey(hotkey: str) -> str:
    """Ensure hotkey string conforms to pynput GlobalHotKeys syntax."""
    tokens = _split_hotkey_parts(hotkey)
    out: list[str] = []
    special_names = {
        "ctrl",
        "control",
        "alt",
        "shift",
        "cmd",
        "super",
        "win",
        "esc",
        "escape",
        "enter",
        "return",
        "space",
        "tab",
        "backspace",
        "delete",
        "up",
        "down",
        "left",
        "right",
        "home",
        "end",
        "page_up",
        "page_down",
        "insert",
        "pause",
        "scroll_lock",
        "caps_lock",
        "num_lock",
        "print_screen",
        "plus",
        "num_add",
        "num_sub",
        "f1",
        "f2",
        "f3",
        "f4",
        "f5",
        "f6",
        "f7",
        "f8",
        "f9",
        "f10",
        "f11",
        "f12",
    }
    aliases = {
        "control": "ctrl",
        "escape": "esc",
        "return": "enter",
        "invio": "enter",
        "spazio": "space",
        "spacebar": "space",
        "ins": "insert",
        "canc": "delete",
        "del": "delete",
        "win": "cmd",
        "super": "cmd",
        "pausa": "pause",
        "+": "plus",
    }
    for tok in tokens:
        bare = tok[1:-1] if tok.startswith("<") and tok.endswith(">") else tok
        bare = aliases.get(bare, bare)
        if bare in special_names:
            out.append(f"<{bare}>")
        else:
            out.append(bare)
    return "+".join(out)


def format_hotkey_display(hotkey: str) -> str:
    """Format a hotkey string into a clean human-readable label (e.g. 'Ctrl+Esc', 'Alt+-')."""
    norm = normalize_pynput_hotkey(hotkey)
    if not norm:
        return ""
    win_cmd = "Win" if sys.platform == "win32" else ("Cmd" if sys.platform == "darwin" else "Super")
    labels = {
        "ctrl": "Ctrl",
        "alt": "Alt",
        "shift": "Shift",
        "cmd": win_cmd,
        "esc": "Esc",
        "enter": "Invio",
        "space": "Spazio",
        "tab": "Tab",
        "backspace": "Backspace",
        "delete": "Canc",
        "insert": "Ins",
        "up": "Su",
        "down": "Giù",
        "left": "Sinistra",
        "right": "Destra",
        "home": "Home",
        "end": "Fine",
        "page_up": "PagSu",
        "page_down": "PagGiù",
        "pause": "Pausa",
        "scroll_lock": "BlocScorr",
        "caps_lock": "BlocMaiusc",
        "num_lock": "BlocNum",
        "print_screen": "Stamp",
        "plus": "+",
        "num_add": "Num+",
        "num_sub": "Num-",
    }
    pretty: list[str] = []
    for part in norm.split("+"):
        bare = part[1:-1] if part.startswith("<") and part.endswith(">") else part
        if bare in labels:
            pretty.append(labels[bare])
        elif len(bare) >= 2 and bare.startswith("f") and bare[1:].isdigit():
            pretty.append(bare.upper())
        elif len(bare) == 1:
            pretty.append(bare.upper())
        else:
            pretty.append(bare.capitalize())
    return "+".join(pretty)


def _hotkey_tokens(hotkey: str) -> set[str]:
    norm = normalize_pynput_hotkey(hotkey)
    tokens: set[str] = set()
    for part in norm.split("+"):
        p = part.strip()
        if p.startswith("<") and p.endswith(">"):
            p = p[1:-1]
        if p == "plus":
            p = "+"
        elif p == "num_sub":
            p = "-"
        if p:
            tokens.add(p)
    return tokens


def _canonical_event_key(key: object) -> str | None:
    name = getattr(key, "name", None)
    if isinstance(name, str) and name:
        low = name.lower()
        for mod in ("ctrl", "alt", "shift", "cmd"):
            if low == mod or low.startswith(f"{mod}_"):
                return mod
        return low
    vk = getattr(key, "vk", None)
    if vk == 0x6B:
        return "num_add"
    if vk == 0x6D:
        return "num_sub"
    if isinstance(vk, int) and 65 <= vk <= 90:
        return chr(vk).lower()
    if isinstance(vk, int) and 48 <= vk <= 57:
        return chr(vk)
    ch = getattr(key, "char", None)
    if isinstance(ch, str) and ch:
        if 1 <= ord(ch) <= 26:
            return chr(ord("a") + ord(ch) - 1)
        return ch.lower()
    return None


def _parse_single_hotkey_for_pynput(keyboard_mod, combo: str):
    """Parse normalized hotkey into pynput keys, supporting '+' and numpad tokens safely."""
    keys = []
    for part in combo.split("+"):
        p = part.strip()
        if not p:
            continue
        if p in ("<plus>", "<num_add>"):
            keys.append(keyboard_mod.KeyCode.from_char("+"))
        elif p == "<num_sub>":
            keys.append(keyboard_mod.KeyCode.from_char("-"))
        else:
            keys.extend(keyboard_mod.HotKey.parse(p))
    return keys


class GlobalHotkeyManager:
    """Registers toggle hotkeys and optional Push-to-Talk (hold/release) key listener."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._listener = None
        self._ptt_listener = None
        self._bindings: dict[str, Callable[[], None]] = {}
        self._ptt_tokens: set[str] = set()
        self._pressed_keys: set[str] = set()
        self._ptt_held = False
        self._on_ptt_press: Callable[[], None] | None = None
        self._on_ptt_release: Callable[[], None] | None = None

    @property
    def is_ptt_held(self) -> bool:
        return self._ptt_held

    def start(
        self,
        bindings: dict[str, Callable[[], None]],
        ptt_hotkey: str = "",
        on_ptt_press: Callable[[], None] | None = None,
        on_ptt_release: Callable[[], None] | None = None,
    ) -> tuple[bool, str]:
        with self._lock:
            self.stop()
            clean_bindings: dict[str, Callable[[], None]] = {}
            for combo, cb in bindings.items():
                norm = normalize_pynput_hotkey(combo)
                if norm:
                    clean_bindings[norm] = cb
            self._bindings = clean_bindings
            self._ptt_tokens = _hotkey_tokens(ptt_hotkey) if ptt_hotkey.strip() else set()
            self._pressed_keys.clear()
            self._ptt_held = False
            self._on_ptt_press = on_ptt_press
            self._on_ptt_release = on_ptt_release

            if not clean_bindings and not self._ptt_tokens:
                return True, "Nessun hotkey globale configurato"

            try:
                from pynput import keyboard

                parts_msg: list[str] = []
                if clean_bindings:
                    hotkey_objs = [
                        keyboard.HotKey(_parse_single_hotkey_for_pynput(keyboard, combo), cb)
                        for combo, cb in clean_bindings.items()
                    ]

                    class _SafeGlobalHotKeys(keyboard.GlobalHotKeys):
                        def __init__(self, objs):
                            self._hotkeys = objs
                            keyboard.Listener.__init__(
                                self,
                                on_press=self._on_press,
                                on_release=self._on_release,
                            )

                    self._listener = _SafeGlobalHotKeys(hotkey_objs)
                    self._listener.daemon = True
                    self._listener.start()
                    parts_msg.append(f"Hotkey: {', '.join(clean_bindings)}")
                if self._ptt_tokens:
                    self._ptt_listener = keyboard.Listener(
                        on_press=self._handle_ptt_press,
                        on_release=self._handle_ptt_release,
                    )
                    self._ptt_listener.daemon = True
                    self._ptt_listener.start()
                    parts_msg.append(f"PTT: {normalize_pynput_hotkey(ptt_hotkey)}")
                return True, " | ".join(parts_msg)
            except Exception as exc:
                self.stop()
                return False, f"Impossibile avviare hotkey globali: {exc}"

    def _handle_ptt_press(self, key: object) -> None:
        tok = _canonical_event_key(key)
        if not tok:
            return
        fire = False
        with self._lock:
            self._pressed_keys.add(tok)
            if self._ptt_tokens and not self._ptt_held and self._ptt_tokens.issubset(self._pressed_keys):
                self._ptt_held = True
                fire = True
        if fire and self._on_ptt_press is not None:
            self._on_ptt_press()

    def _handle_ptt_release(self, key: object) -> None:
        tok = _canonical_event_key(key)
        if not tok:
            return
        fire = False
        with self._lock:
            self._pressed_keys.discard(tok)
            if self._ptt_held and tok in self._ptt_tokens:
                self._ptt_held = False
                fire = True
        if fire and self._on_ptt_release is not None:
            self._on_ptt_release()

    def stop(self) -> None:
        with self._lock:
            for attr in ("_listener", "_ptt_listener"):
                lst = getattr(self, attr, None)
                if lst is not None:
                    try:
                        lst.stop()
                    except Exception:
                        pass
                    setattr(self, attr, None)
            self._pressed_keys.clear()
            self._ptt_held = False
