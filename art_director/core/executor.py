"""Executes dynamically configured program actions, macros, and background protocols."""

from __future__ import annotations

import copy
import socket
import time
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from pythonosc.udp_client import SimpleUDPClient

from ..config.schema import ActionStep, AppConfig, ProgramFunction, ProgramProfile
from ..os_layer.base import OSBridge
from ..targets.base import CommandExecutionResult, MidiOutputHelper, TargetContext, query_osc_value
from ..targets.qlc_plus import build_artnet_dmx_packet
from .app_launcher import is_process_running
from .event_bus import EventBus
from .state import CancellationToken

if TYPE_CHECKING:
    from ..targets.behringer_xr18 import BehringerXR18Target


class ProgramExecutor:
    """Runs ProgramProfile open/focus requests and ProgramFunction macro/protocol steps."""

    def __init__(
        self,
        os_bridge: OSBridge,
        midi: MidiOutputHelper | None = None,
        osc_sender: Callable[[str, int, str, object], None] | None = None,
        artnet_sender: Callable[[str, int, bytes], None] | None = None,
        osc_querier: Callable[[str, int, str], float | int | None] | None = None,
        xr18_target: BehringerXR18Target | None = None,
        config_provider: Callable[[], AppConfig] | None = None,
        bus: EventBus | None = None,
    ) -> None:
        from ..targets.behringer_xr18 import BehringerXR18Target
        from ..targets.cakewalk_daw import find_project_by_unique_name

        self._find_project = find_project_by_unique_name
        self._os = os_bridge
        self._midi = midi or MidiOutputHelper()
        self._custom_osc = osc_sender
        self._custom_artnet = artnet_sender
        self._custom_osc_querier = osc_querier
        self._config_provider = config_provider
        self._bus = bus
        self._osc_clients: dict[tuple[str, int], SimpleUDPClient] = {}
        self._osc_state: dict[tuple[str, int, str], float] = {}
        self._xr18_target = xr18_target or BehringerXR18Target(
            osc_sender=osc_sender, osc_querier=osc_querier
        )
        self._dmx_buffers: dict[tuple[str, int, int], bytearray] = {}
        self._artnet_seq = 1

    def close(self) -> None:
        self._midi.close()

    def _patterns_for(self, prog: ProgramProfile) -> list[str]:
        patterns = list(prog.window_title_patterns)
        if prog.name and prog.name not in patterns:
            patterns.append(prog.name)
        if prog.executable:
            stem = Path(prog.executable).stem
            if stem and stem not in patterns:
                patterns.append(stem)
        return patterns

    def open_or_focus_program(
        self, prog: ProgramProfile, cancel_token: CancellationToken | None = None
    ) -> CommandExecutionResult:
        patterns = self._patterns_for(prog)
        running = is_process_running(prog.process_name, prog.executable)
        if running:
            focused = self._os.focus_window(patterns)
            msg = (
                f"'{prog.name}' già aperto -> finestra in primo piano"
                if focused
                else f"'{prog.name}' già in esecuzione"
            )
            return CommandExecutionResult(True, prog.id, msg)

        if not prog.executable.strip():
            return CommandExecutionResult(
                False, prog.id, f"Percorso eseguibile mancante per '{prog.name}'"
            )

        ok, msg = self._os.launch_executable(
            prog.executable, prog.arguments, prog.working_dir
        )
        if ok and cancel_token:
            # Give window a moment to appear if caller expects immediate follow-up
            cancel_token.wait(0.25)
        return CommandExecutionResult(ok, prog.id, f"{prog.name}: {msg}")

    def execute_function(
        self,
        prog: ProgramProfile,
        fn: ProgramFunction,
        params: dict[str, str],
        cancel_token: CancellationToken,
    ) -> CommandExecutionResult:
        if not fn.steps:
            return CommandExecutionResult(
                False, prog.id, f"Nessun passo configurato per '{fn.primary_command}'"
            )

        # Safety pre-check: resolve dynamic project files BEFORE executing closing steps!
        resolved_projects: dict[int, Path] = {}
        for idx, step in enumerate(fn.steps):
            if step.kind == "open_project":
                if step.use_spoken_param:
                    query = next(iter(params.values()), "").strip()
                    if not query:
                        return CommandExecutionResult(
                            False,
                            prog.id,
                            f"{prog.name}: specifica il nome del file/progetto da aprire",
                        )
                    matched, _cands, find_msg = self._find_project(
                        query, step.project_folders, step.project_extensions
                    )
                    if matched is None:
                        return CommandExecutionResult(
                            False,
                            prog.id,
                            f"{prog.name}: {find_msg} (chiusura annullata per sicurezza)",
                        )
                    resolved_projects[idx] = matched
                else:
                    p = Path(step.fixed_file_path.strip())
                    if not p.exists():
                        return CommandExecutionResult(
                            False, prog.id, f"{prog.name}: file non trovato '{p}'"
                        )
                    resolved_projects[idx] = p

        needs_gui = any(
            s.kind
            in (
                "click",
                "double_click",
                "right_click",
                "scroll_up",
                "scroll_down",
                "hotkey",
                "hotkey_if_dialog",
                "paste_text",
            )
            for s in fn.steps
        )
        patterns = self._patterns_for(prog)

        if needs_gui and fn.focus_before_run:
            win = self._os.find_window(patterns)
            if win is None and fn.launch_if_closed and prog.executable.strip():
                self._os.launch_executable(
                    prog.executable, prog.arguments, prog.working_dir
                )
                deadline = time.monotonic() + 5.0
                while time.monotonic() < deadline:
                    if cancel_token.wait(0.25):
                        return CommandExecutionResult(False, prog.id, "Macro interrotta da PANIC")
                    win = self._os.find_window(patterns)
                    if win is not None:
                        break
            self._os.focus_window(patterns)
            if cancel_token.wait(0.15):
                return CommandExecutionResult(False, prog.id, "Macro interrotta da PANIC")

        base_fg = self._os.get_foreground_window() if needs_gui else None
        executed_labels: list[str] = []
        for idx, step in enumerate(fn.steps):
            if cancel_token.is_cancelled:
                return CommandExecutionResult(False, prog.id, f"{prog.name}: macro interrotta da PANIC")

            ok, detail = self._execute_step(
                prog,
                patterns,
                step,
                resolved_projects.get(idx),
                cancel_token,
                base_fg,
                params,
            )
            if not ok:
                return CommandExecutionResult(False, prog.id, f"{prog.name}: {detail}")
            if detail:
                executed_labels.append(detail)

        summary = f"{prog.name} [{fn.primary_command}]: " + (
            " -> ".join(executed_labels) if executed_labels else "eseguito"
        )
        return CommandExecutionResult(
            True,
            prog.id,
            summary,
            {"function": fn.primary_command, "params": params},
        )

    def _wait_for_dialog(
        self,
        base_fg,
        timeout_ms: int,
        cancel_token: CancellationToken,
    ):
        deadline = time.monotonic() + max(0.05, timeout_ms / 1000.0)
        while time.monotonic() < deadline:
            if cancel_token.is_cancelled:
                return None
            fg = self._os.get_foreground_window()
            if fg is not None:
                same_pid_new_win = (
                    base_fg is not None
                    and fg.handle != base_fg.handle
                    and bool(base_fg.pid)
                    and fg.pid == base_fg.pid
                )
                if fg.is_dialog or same_pid_new_win:
                    return fg
            if cancel_token.wait(0.05):
                return None
        return None

    def _open_project_via_hotkey(
        self,
        patterns: list[str],
        open_hotkey: str,
        resolved_project: Path,
        cancel_token: CancellationToken,
    ) -> tuple[bool, str] | None:
        running_win = self._os.find_window(patterns)
        if running_win is None or not open_hotkey.strip():
            return None
        self._os.focus_window(patterns)
        if cancel_token.wait(0.12):
            return False, "interrotto"
        prev_fg = self._os.get_foreground_window() or running_win
        if not self._os.send_hotkey(open_hotkey.strip()):
            return None
        dialog_win = self._wait_for_dialog(prev_fg, timeout_ms=2500, cancel_token=cancel_token)
        if dialog_win is None:
            return None
        if cancel_token.wait(0.12):
            return False, "interrotto"
        if not self._os.set_clipboard_text(str(resolved_project)):
            return None
        self._os.send_hotkey("<ctrl>+a")
        if cancel_token.wait(0.03):
            return False, "interrotto"
        self._os.send_hotkey("<ctrl>+v")
        if cancel_token.wait(0.10):
            return False, "interrotto"
        ok = self._os.send_hotkey("enter")
        return ok, f"aperto '{resolved_project.name}' via {open_hotkey.strip()}"

    def _send_osc_value(self, host: str, port: int, address: str, val: int | float) -> None:
        if self._custom_osc is not None:
            self._custom_osc(host, int(port), address, val)
            return
        addr = (host, int(port))
        client = self._osc_clients.get(addr)
        if client is None:
            client = SimpleUDPClient(addr[0], addr[1])
            self._osc_clients[addr] = client
        client.send_message(address, val)

    def _read_osc_current(self, step: ActionStep) -> float | None:
        key = (step.osc_host, int(step.osc_port), step.osc_address.strip())
        if step.osc_query_before_update:
            live: float | int | None = None
            if self._custom_osc_querier is not None:
                live = self._custom_osc_querier(step.osc_host, int(step.osc_port), key[2])
            elif self._custom_osc is None:
                live = query_osc_value(step.osc_host, int(step.osc_port), key[2])
            if live is not None:
                return float(live)
        return self._osc_state.get(key)

    def _execute_osc_step(self, step: ActionStep) -> tuple[bool, str]:
        addr = step.osc_address.strip()
        if not addr:
            return False, "Indirizzo OSC mancante"
        key = (step.osc_host, int(step.osc_port), addr)
        mode = (step.osc_mode or "set").strip().lower()
        vmin = min(float(step.osc_min), float(step.osc_max))
        vmax = max(float(step.osc_min), float(step.osc_max))

        if mode == "relative":
            cur = self._read_osc_current(step)
            if cur is None:
                cur = 0.5 * (vmin + vmax)
            raw_next = max(vmin, min(vmax, float(cur) + float(step.osc_value)))
        elif mode == "toggle":
            cur = self._read_osc_current(step)
            if cur is None:
                raw_next = vmax
            else:
                span = max(1e-6, abs(vmax - vmin))
                raw_next = vmin if abs(float(cur) - vmax) <= 0.05 * span else vmax
        else:
            raw_next = float(step.osc_value)

        val: int | float = int(round(raw_next)) if step.osc_type == "int" else float(raw_next)
        self._osc_state[key] = float(val)
        self._send_osc_value(step.osc_host, int(step.osc_port), addr, val)
        val_txt = str(val) if isinstance(val, int) else f"{val:.3f}"
        return True, f"OSC {addr}={val_txt}"

    def _execute_xr18_cmd_step(
        self,
        step: ActionStep,
        params: dict[str, str] | None,
        cancel_token: CancellationToken,
    ) -> tuple[bool, str]:
        raw_cmd = step.xr18_command
        if params:
            for k, v in params.items():
                raw_cmd = raw_cmd.replace(f"{{{k}}}", v)
        cmd = raw_cmd.strip()
        if not cmd:
            return False, "Comando Behringer XR18 vuoto"

        base_cfg = copy.deepcopy(self._config_provider()) if self._config_provider else AppConfig()
        if step.osc_host.strip():
            base_cfg.xr18.host = step.osc_host.strip()
        if step.osc_port:
            base_cfg.xr18.port = int(step.osc_port)
        if step.xr18_step_db > 0:
            base_cfg.xr18.step_db = float(step.xr18_step_db)

        ctx = TargetContext(
            config=base_cfg,
            os_bridge=self._os,
            cancel_token=cancel_token,
            bus=self._bus or EventBus(),
        )
        res = self._xr18_target.handle(cmd, ctx)
        return res.handled, res.summary

    def _execute_step(
        self,
        prog: ProgramProfile,
        patterns: list[str],
        step: ActionStep,
        resolved_project: Path | None,
        cancel_token: CancellationToken,
        base_fg=None,
        params: dict[str, str] | None = None,
    ) -> tuple[bool, str]:
        if step.kind == "wait":
            cancelled = cancel_token.wait(max(0.0, step.delay_ms / 1000.0))
            return (not cancelled), ("interrotto" if cancelled else "")

        if step.kind in ("click", "double_click", "right_click", "scroll_up", "scroll_down"):
            win = self._os.find_window(patterns)
            fg = self._os.get_foreground_window()
            if (
                fg is not None
                and fg.is_dialog
                and win is not None
                and win.pid
                and fg.pid == win.pid
            ):
                win = fg
            elif win is None:
                win = fg
            if win is None:
                return False, f"finestra '{prog.name}' non trovata"
            rect = self._os.get_window_rect(win.handle)
            if rect is None:
                return False, f"impossibile leggere coordinate finestra '{prog.name}'"
            left, top, width, height = rect
            abs_x = int(round(left + step.rel_x * width))
            abs_y = int(round(top + step.rel_y * height))

            if step.kind == "click":
                ok = self._os.mouse_click_at(abs_x, abs_y, button="left", clicks=1)
            elif step.kind == "double_click":
                ok = self._os.mouse_click_at(abs_x, abs_y, button="left", clicks=2)
            elif step.kind == "right_click":
                ok = self._os.mouse_click_at(abs_x, abs_y, button="right", clicks=1)
            elif step.kind == "scroll_up":
                ok = self._os.mouse_scroll_at(abs_x, abs_y, dy=abs(step.scroll_clicks))
            else:
                ok = self._os.mouse_scroll_at(abs_x, abs_y, dy=-abs(step.scroll_clicks))
            return ok, step.describe()

        if step.kind == "hotkey":
            ok = self._os.send_hotkey(step.hotkey)
            return ok, f"Tasto {step.hotkey}"

        if step.kind == "hotkey_if_dialog":
            dialog_win = self._wait_for_dialog(
                base_fg, timeout_ms=step.delay_ms, cancel_token=cancel_token
            )
            if cancel_token.is_cancelled:
                return False, "interrotto"
            if dialog_win is None:
                return True, "Nessun pop-up comparso (ok)"
            ok = self._os.send_hotkey(step.hotkey)
            return ok, f"Pop-up '{dialog_win.title}' -> Tasto {step.hotkey}"

        if step.kind == "osc":
            return self._execute_osc_step(step)

        if step.kind == "xr18_cmd":
            return self._execute_xr18_cmd_step(step, params, cancel_token)

        if step.kind == "artnet":
            key = (step.artnet_host, int(step.artnet_port), int(step.artnet_universe))
            buf = self._dmx_buffers.setdefault(key, bytearray(512))
            if step.artnet_blackout:
                buf[:] = b"\x00" * 512
            elif 1 <= int(step.artnet_channel) <= 512:
                buf[int(step.artnet_channel) - 1] = max(0, min(255, int(step.artnet_value)))
            pkt = build_artnet_dmx_packet(int(step.artnet_universe), buf, self._artnet_seq)
            self._artnet_seq = 1 if self._artnet_seq >= 255 else self._artnet_seq + 1
            if self._custom_artnet is not None:
                self._custom_artnet(step.artnet_host, int(step.artnet_port), pkt)
            else:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                    sock.sendto(pkt, (step.artnet_host, int(step.artnet_port)))
            return True, step.describe()

        if step.kind == "midi_cc":
            ok = self._midi.send_cc(
                step.midi_port, step.midi_channel, step.midi_control, step.midi_value
            )
            return ok, step.describe()

        if step.kind == "midi_note":
            ok = self._midi.send_note(
                step.midi_port, step.midi_channel, step.midi_control, step.midi_value
            )
            return ok, step.describe()

        if step.kind == "midi_pc":
            ok = self._midi.send_program_change(
                step.midi_port,
                step.midi_channel,
                step.midi_value,
                bank_msb=step.midi_bank_msb,
                bank_lsb=step.midi_bank_lsb,
            )
            return ok, step.describe()

        if step.kind == "open_project":
            if resolved_project is None:
                return False, "file progetto non risolto"
            if step.open_hotkey.strip():
                via_hk = self._open_project_via_hotkey(
                    patterns, step.open_hotkey, resolved_project, cancel_token
                )
                if via_hk is not None:
                    return via_hk
            if prog.executable.strip():
                ok, msg = self._os.launch_executable(
                    prog.executable, f'"{resolved_project}"', str(resolved_project.parent)
                )
            else:
                ok, msg = self._os.open_document_or_file(resolved_project)
            return ok, f"aperto '{resolved_project.name}' ({msg})"

        if step.kind == "paste_text":
            raw_text = step.paste_text
            if params:
                for k, v in params.items():
                    raw_text = raw_text.replace(f"{{{k}}}", v)
            text = raw_text.strip()

            if step.paste_before_hotkey.strip():
                self._os.send_hotkey(step.paste_before_hotkey.strip())
                if cancel_token.wait(0.08):
                    return False, "interrotto"

            if step.paste_clear_first:
                self._os.send_hotkey("<ctrl>+a")
                if cancel_token.wait(0.03):
                    return False, "interrotto"

            if text:
                if not self._os.set_clipboard_text(text):
                    return False, "impossibile copiare il testo negli appunti"
                self._os.send_hotkey("<ctrl>+v")
                if cancel_token.wait(0.06):
                    return False, "interrotto"
            elif step.paste_clear_first:
                self._os.send_hotkey("backspace")
                if cancel_token.wait(0.03):
                    return False, "interrotto"

            if step.paste_after_hotkey.strip():
                self._os.send_hotkey(step.paste_after_hotkey.strip())
            return True, step.describe()

        return False, f"tipo step sconosciuto '{step.kind}'"
