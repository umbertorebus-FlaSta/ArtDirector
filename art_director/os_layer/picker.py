"""Interactive cross-platform window picking and macro sequence recorder."""

from __future__ import annotations

from pathlib import Path
import re
import threading
import time
from typing import Callable

from ..config.schema import ActionStep
from .base import OSBridge


def _format_pynput_key(key) -> tuple[str, bool]:
    """Return (token_name, is_modifier) from a pynput key object."""
    try:
        from pynput.keyboard import Key
    except Exception:
        return "", False

    modifiers = {
        Key.ctrl: "ctrl",
        Key.ctrl_l: "ctrl",
        Key.ctrl_r: "ctrl",
        Key.alt: "alt",
        Key.alt_l: "alt",
        Key.alt_r: "alt",
        Key.alt_gr: "alt",
        Key.shift: "shift",
        Key.shift_l: "shift",
        Key.shift_r: "shift",
        Key.cmd: "cmd",
        Key.cmd_l: "cmd",
        Key.cmd_r: "cmd",
    }
    if key in modifiers:
        return modifiers[key], True

    specials = {
        Key.space: "space",
        Key.enter: "enter",
        Key.esc: "esc",
        Key.tab: "tab",
        Key.backspace: "backspace",
        Key.delete: "delete",
        Key.up: "up",
        Key.down: "down",
        Key.left: "left",
        Key.right: "right",
        Key.home: "home",
        Key.end: "end",
        Key.page_up: "page_up",
        Key.page_down: "page_down",
        Key.insert: "insert",
        Key.f1: "f1",
        Key.f2: "f2",
        Key.f3: "f3",
        Key.f4: "f4",
        Key.f5: "f5",
        Key.f6: "f6",
        Key.f7: "f7",
        Key.f8: "f8",
        Key.f9: "f9",
        Key.f10: "f10",
        Key.f11: "f11",
        Key.f12: "f12",
    }
    if key in specials:
        return f"<{specials[key]}>" if specials[key] not in ("space", "enter", "esc", "tab") else specials[key], False

    vk = getattr(key, "vk", None)
    numpad_vks = {
        96: "<num_0>",
        97: "<num_1>",
        98: "<num_2>",
        99: "<num_3>",
        100: "<num_4>",
        101: "<num_5>",
        102: "<num_6>",
        103: "<num_7>",
        104: "<num_8>",
        105: "<num_9>",
        106: "<num_mul>",
        107: "<num_add>",
        109: "<num_sub>",
        110: "<num_dec>",
        111: "<num_div>",
    }
    if vk in numpad_vks:
        return numpad_vks[vk], False

    ch = getattr(key, "char", None)
    if ch:
        # Control chars when Ctrl is held on Windows ('\x01'..'\\x1a')
        code = ord(ch)
        if 1 <= code <= 26:
            return chr(ord("a") + code - 1), False
        return ch.lower(), False
    return "", False


def _compact_proc_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


class WindowPickerSession:
    """Captures window-relative clicks, scrolls, and hotkeys inside a target app."""

    def __init__(
        self,
        os_bridge: OSBridge,
        window_patterns: list[str],
        ignore_rects_provider: Callable[[], list[tuple[int, int, int, int]]] | None = None,
        on_step: Callable[[ActionStep], None] | None = None,
        on_stop_requested: Callable[[], None] | None = None,
        process_name: str = "",
        executable: str = "",
    ) -> None:
        self._os = os_bridge
        self._patterns = window_patterns
        self._ignore_rects = ignore_rects_provider
        self._on_step = on_step
        self._on_stop = on_stop_requested
        self._proc_needles: list[str] = []
        for raw in (Path(executable.strip()).stem if executable.strip() else "", process_name.strip()):
            comp = _compact_proc_name(raw)
            if comp and comp not in self._proc_needles:
                self._proc_needles.append(comp)
        self._pid_match_cache: dict[int, bool] = {}
        self._lock = threading.RLock()
        self._steps: list[ActionStep] = []
        self._active = False
        self._last_event_ts = 0.0
        self._last_click_xy: tuple[int, int] | None = None
        self._held_mods: set[str] = set()
        self._held_keys: set[str] = set()
        self._mouse_listener = None
        self._kb_listener = None

    @property
    def steps(self) -> list[ActionStep]:
        with self._lock:
            return list(self._steps)

    def start(self) -> tuple[bool, str]:
        with self._lock:
            if self._active:
                return True, "Picking già attivo"
            try:
                from pynput import keyboard, mouse
            except Exception as exc:
                return False, f"pynput non disponibile: {exc}"

            self._steps.clear()
            self._held_mods.clear()
            self._held_keys.clear()
            self._last_event_ts = 0.0
            self._last_click_xy = None
            self._active = True

            self._mouse_listener = mouse.Listener(
                on_click=self._handle_click,
                on_scroll=self._handle_scroll,
            )
            self._kb_listener = keyboard.Listener(
                on_press=self._handle_key_press,
                on_release=self._handle_key_release,
            )
            self._mouse_listener.daemon = True
            self._kb_listener.daemon = True
            self._mouse_listener.start()
            self._kb_listener.start()
            return True, "Modalità Picking avviata"

    def stop(self) -> list[ActionStep]:
        with self._lock:
            self._active = False
            ml = self._mouse_listener
            kl = self._kb_listener
            self._mouse_listener = None
            self._kb_listener = None
            steps_copy = list(self._steps)
        if ml is not None:
            try:
                ml.stop()
            except Exception:
                pass
        if kl is not None:
            try:
                kl.stop()
            except Exception:
                pass
        return steps_copy

    def _is_ignored_point(self, x: int, y: int) -> bool:
        if self._ignore_rects is None:
            return False
        for rx, ry, rw, rh in self._ignore_rects():
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                return True
        return False

    def _matches_target_process(self, pid: int) -> bool:
        if not self._proc_needles or pid <= 0:
            return False
        cached = self._pid_match_cache.get(pid)
        if cached is not None:
            return cached
        matched = False
        try:
            import psutil

            proc = psutil.Process(pid)
            pname = _compact_proc_name(Path(proc.name() or "").stem)
            try:
                exe = proc.exe() or ""
            except Exception:
                exe = ""
            pexe = _compact_proc_name(Path(exe).stem) if exe else ""
            matched = any(
                (pname and (n == pname or n in pname))
                or (pexe and (n == pexe or n in pexe))
                for n in self._proc_needles
            )
        except Exception:
            matched = False
        self._pid_match_cache[pid] = matched
        return matched

    def _is_art_director_window(self, fg) -> bool:
        if fg is None:
            return False
        fg_title_l = fg.title.lower()
        return (
            "art director" in fg_title_l
            or "picking su " in fg_title_l
            or "nuova funzione / macro" in fg_title_l
        )

    def _is_target_foreground(self, fg) -> bool:
        if fg is None or self._is_art_director_window(fg):
            return False
        if not (self._patterns or self._proc_needles):
            return True
        fg_title_l = fg.title.lower()
        norm_pats = [p.strip().lower() for p in self._patterns if p.strip()]
        if any(pat in fg_title_l for pat in norm_pats):
            return True
        if self._matches_target_process(fg.pid):
            return True
        target = self._os.find_window(self._patterns) if self._patterns else None
        if target is None:
            return False
        same_proc = bool(target.pid and fg.pid and target.pid == fg.pid)
        return target.handle == fg.handle or same_proc

    def _resolve_target_rect(self) -> tuple[int, int, int, int] | None:
        fg = self._os.get_foreground_window()
        if not self._is_target_foreground(fg):
            return None
        if self._patterns or self._proc_needles:
            fg_title_l = fg.title.lower()
            norm_pats = [p.strip().lower() for p in self._patterns if p.strip()]
            if not any(pat in fg_title_l for pat in norm_pats) and not self._matches_target_process(
                fg.pid
            ):
                target = self._os.find_window(self._patterns) if self._patterns else None
                if target is not None:
                    return self._os.get_window_rect(target.handle)
        return self._os.get_window_rect(fg.handle)

    def _point_to_relative(self, x: int, y: int) -> tuple[float, float] | None:
        if self._is_ignored_point(x, y):
            return None
        rect = self._resolve_target_rect()
        if rect is None:
            return None
        left, top, width, height = rect
        if width <= 0 or height <= 0:
            return None
        if not (left <= x <= left + width and top <= y <= top + height):
            return None
        rel_x = max(0.0, min(1.0, (x - left) / float(width)))
        rel_y = max(0.0, min(1.0, (y - top) / float(height)))
        return rel_x, rel_y

    def _maybe_append_wait(self, now: float) -> None:
        if self._steps and self._last_event_ts > 0:
            gap_ms = int(round((now - self._last_event_ts) * 1000.0))
            if gap_ms >= 200:
                wait_step = ActionStep(kind="wait", delay_ms=min(8000, gap_ms))
                self._steps.append(wait_step)
                if self._on_step:
                    self._on_step(wait_step)

    def _handle_click(self, x: int, y: int, button, pressed: bool) -> None:
        if not pressed or not self._active:
            return
        rel = self._point_to_relative(int(x), int(y))
        if rel is None:
            return
        rel_x, rel_y = rel
        btn_name = getattr(button, "name", "left")
        kind = "right_click" if btn_name == "right" else "click"
        now = time.monotonic()

        with self._lock:
            if not self._active:
                return
            if (
                kind == "click"
                and self._steps
                and self._steps[-1].kind == "click"
                and self._last_click_xy is not None
                and (now - self._last_event_ts) < 0.40
                and abs(x - self._last_click_xy[0]) <= 8
                and abs(y - self._last_click_xy[1]) <= 8
            ):
                self._steps[-1].kind = "double_click"
                self._last_event_ts = now
                if self._on_step:
                    self._on_step(self._steps[-1])
                return

            self._maybe_append_wait(now)
            step = ActionStep(kind=kind, rel_x=rel_x, rel_y=rel_y)
            self._steps.append(step)
            self._last_event_ts = now
            self._last_click_xy = (int(x), int(y))
            if self._on_step:
                self._on_step(step)

    def _handle_scroll(self, x: int, y: int, dx: int, dy: int) -> None:  # noqa: ARG002
        if not self._active or dy == 0:
            return
        rel = self._point_to_relative(int(x), int(y))
        if rel is None:
            return
        rel_x, rel_y = rel
        kind = "scroll_up" if dy > 0 else "scroll_down"
        now = time.monotonic()

        with self._lock:
            if not self._active:
                return
            if (
                self._steps
                and self._steps[-1].kind == kind
                and (now - self._last_event_ts) < 0.35
            ):
                self._steps[-1].scroll_clicks += abs(int(dy))
                self._last_event_ts = now
                return
            self._maybe_append_wait(now)
            step = ActionStep(
                kind=kind, rel_x=rel_x, rel_y=rel_y, scroll_clicks=max(1, abs(int(dy)))
            )
            self._steps.append(step)
            self._last_event_ts = now
            if self._on_step:
                self._on_step(step)

    def _handle_key_press(self, key) -> None:
        if not self._active:
            return
        tok, is_mod = _format_pynput_key(key)
        if not tok:
            return
        if tok == "<f9>":
            if self._on_stop:
                self._on_stop()
            return
        if is_mod:
            self._held_mods.add(tok)
            return

        # Ignore Windows key auto-repeat while the same key is still held down
        if tok in self._held_keys:
            return
        self._held_keys.add(tok)

        fg = self._os.get_foreground_window()
        if not self._is_target_foreground(fg):
            self._held_mods.clear()
            return

        # Ignore OS window-switching shortcuts like Alt+Tab or Win+...
        if ("alt" in self._held_mods and tok in ("tab", "esc", "<f4>")) or "cmd" in self._held_mods:
            self._held_mods.clear()
            return

        mods_order = [m for m in ("ctrl", "alt", "shift", "cmd") if m in self._held_mods]
        combo = "+".join([*(f"<{m}>" for m in mods_order), tok])
        now = time.monotonic()
        with self._lock:
            if not self._active:
                return
            self._maybe_append_wait(now)
            step = ActionStep(kind="hotkey", hotkey=combo)
            self._steps.append(step)
            self._last_event_ts = now
            if self._on_step:
                self._on_step(step)

    def _handle_key_release(self, key) -> None:
        tok, is_mod = _format_pynput_key(key)
        if is_mod:
            self._held_mods.discard(tok)
        elif tok:
            self._held_keys.discard(tok)
