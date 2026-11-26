"""Main orchestration controller tying audio, offline STT, routing, hotkeys, and targets."""

from __future__ import annotations

import queue
import threading
import time

import numpy as np

from ..audio.input_stream import AudioCaptureService
from ..config.manager import ConfigManager
from ..config.schema import AppConfig
from ..os_layer import (
    GlobalHotkeyManager,
    OSBridge,
    create_os_bridge,
    get_launch_command_parts,
)
from ..stt.base import STTResult
from ..stt.manager import STTManager
from ..stt.sample_matcher import (
    SampleMatch,
    load_wav_float32,
    sanitize_sample_filename,
    save_wav_pcm16,
)
from ..targets import (
    BaseTarget,
    BehringerXR18Target,
    CakewalkDAWTarget,
    CommandExecutionResult,
    PopupHandlerTarget,
    QLCPlusTarget,
    SystemTarget,
    TargetContext,
    VirtualDJTarget,
)
from .app_discovery import auto_populate_missing_executables
from .app_launcher import StageAppLauncher
from .event_bus import EventBus
from .executor import ProgramExecutor
from .parser import CommandRouter, RouteMatch, normalize_text
from .state import ListeningMode, StateManager


class ArtDirectorController:
    """Thread-safe coordinator for Art Director."""

    def __init__(
        self,
        config_manager: ConfigManager | None = None,
        os_bridge: OSBridge | None = None,
        targets_override: dict[str, BaseTarget] | None = None,
        enable_audio: bool = True,
        enable_hotkeys: bool = True,
    ) -> None:
        self.config_manager = config_manager or ConfigManager()
        self.config: AppConfig = self.config_manager.config
        self.bus = EventBus()
        self.os_bridge = os_bridge or create_os_bridge()
        self.state = StateManager(self.config.sleep_wake, self.bus)
        self.router = CommandRouter(self.config)
        self.launcher = StageAppLauncher(
            self.config.stage_launcher, self.os_bridge, self.bus
        )
        self.popup_handler = PopupHandlerTarget()

        default_targets: dict[str, BaseTarget] = {
            "xr18": BehringerXR18Target(),
            "cakewalk": CakewalkDAWTarget(),
            "qlc": QLCPlusTarget(),
            "virtualdj": VirtualDJTarget(),
            "system": SystemTarget(self.popup_handler, self.launcher),
        }
        if targets_override:
            default_targets.update(targets_override)
        self.targets: dict[str, BaseTarget] = default_targets
        xr18_tgt = default_targets.get("xr18")
        self.program_executor = ProgramExecutor(
            self.os_bridge,
            xr18_target=xr18_tgt if isinstance(xr18_tgt, BehringerXR18Target) else None,
            config_provider=lambda: self.config,
            bus=self.bus,
        )

        self._enable_audio = enable_audio
        self._enable_hotkeys = enable_hotkeys

        self._cmd_queue: queue.Queue[tuple[RouteMatch, str] | None] = queue.Queue(maxsize=64)
        self._cmd_worker: threading.Thread | None = None
        self._running = False
        self._voice_capture_mode = False
        self._recent_partial_ts: dict[str, float] = {}
        self._active_program_id: str = ""
        self._active_program_ts: float = 0.0
        self._stop_event = threading.Event()
        self._auto_sleep_worker: threading.Thread | None = None
        self._wake_activity_ts: float = time.monotonic()
        self._ptt_grace_until: float = 0.0

        self.stt = STTManager(
            self.config,
            self.bus,
            self._on_stt_result,
            on_sample_match=self._on_sample_match,
            is_sleeping_fn=lambda: (
                self.state.mode == ListeningMode.SLEEP
                and time.monotonic() >= self._ptt_grace_until
            ),
            preferred_program_fn=self._get_preferred_program_id,
        )
        self.audio = AudioCaptureService(
            self.config.audio, self.bus, on_chunk=self.stt.submit_chunk
        )
        self.hotkeys = GlobalHotkeyManager()

        self.config_manager.on_change(self._on_config_saved)
        self.bus.subscribe("mode_changed", self._on_mode_changed)

    def start(self, launched_at_boot: bool = False) -> None:
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._wake_activity_ts = time.monotonic()
        self._cmd_worker = threading.Thread(
            target=self._command_loop, name="ArtDirector-Cmd", daemon=True
        )
        self._cmd_worker.start()
        self._auto_sleep_worker = threading.Thread(
            target=self._auto_sleep_loop, name="ArtDirector-AutoSleep", daemon=True
        )
        self._auto_sleep_worker.start()

        if self.os_bridge.platform_name != "mock":
            discovered = auto_populate_missing_executables(self.config.stage_launcher.apps)
            if discovered:
                self.config_manager.save(self.config)
                self.bus.publish(
                    "log",
                    level="info",
                    message="App rilevate automaticamente: " + " | ".join(discovered),
                )

        if self._enable_audio:
            self.stt.start()
            self.audio.start()
            self._sync_mic_mute_with_mode()
        else:
            self.stt.reload_samples(self.config)

        if self._enable_hotkeys:
            self._register_hotkeys()

        # Optional automatic stage applications startup
        sl = self.config.stage_launcher
        if sl.launch_apps_on_art_director_start:
            if (not sl.launch_apps_only_on_boot_flag) or launched_at_boot:
                threading.Thread(
                    target=self._run_startup_apps,
                    name="ArtDirector-AppBoot",
                    daemon=True,
                ).start()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        self.hotkeys.stop()
        self.audio.stop()
        self.stt.stop()
        try:
            self._cmd_queue.put_nowait(None)
        except queue.Full:
            pass
        if self._cmd_worker and self._cmd_worker.is_alive():
            self._cmd_worker.join(timeout=1.5)
        if self._auto_sleep_worker and self._auto_sleep_worker.is_alive():
            self._auto_sleep_worker.join(timeout=1.0)
        for target in self.targets.values():
            target.close()
        self.program_executor.close()

    def set_voice_capture_mode(self, active: bool) -> None:
        """Pause command execution while recording voice phrases in the Setup Wizard."""
        self._voice_capture_mode = active

    def _launch_configured_programs(self, initial_delay: bool) -> list[str]:
        progs = [
            p for p in self.config.programs
            if p.enabled and p.launch_on_startup and p.executable.strip()
        ]
        if not progs:
            return self.launcher.launch_all_startup_apps(
                cancel_token=self.state.panic_token,
                only_flagged=True,
                initial_delay=initial_delay,
            )
        if initial_delay and self.config.stage_launcher.initial_startup_delay_sec > 0:
            if self.state.panic_token.wait(self.config.stage_launcher.initial_startup_delay_sec):
                return ["Sequenza avvio applicazioni interrotta da PANIC."]
        logs: list[str] = []
        for idx, prog in enumerate(progs):
            if self.state.panic_token.is_cancelled:
                logs.append("Sequenza avvio applicazioni interrotta da PANIC.")
                break
            res = self.program_executor.open_or_focus_program(prog, self.state.panic_token)
            logs.append(res.summary)
            if idx < len(progs) - 1 and prog.startup_delay_sec > 0:
                if self.state.panic_token.wait(prog.startup_delay_sec):
                    logs.append("Sequenza avvio applicazioni interrotta da PANIC.")
                    break
        return logs

    def _run_startup_apps(self) -> None:
        for line in self._launch_configured_programs(initial_delay=True):
            self.bus.publish("log", level="info", message=f"[Avvio App] {line}")

    def launch_stage_apps_now(self) -> None:
        threading.Thread(
            target=lambda: [
                self.bus.publish("log", level="info", message=f"[Avvio App] {line}")
                for line in self._launch_configured_programs(initial_delay=False)
            ],
            name="ArtDirector-ManualLaunch",
            daemon=True,
        ).start()

    def _register_hotkeys(self) -> None:
        bindings = {}
        if self.config.sleep_wake.toggle_hotkey.strip():
            bindings[self.config.sleep_wake.toggle_hotkey] = lambda: self.toggle_sleep_wake(
                source="hotkey"
            )
        if self.config.panic.hotkey.strip():
            bindings[self.config.panic.hotkey] = lambda: self.trigger_panic(source="hotkey")
        ok, msg = self.hotkeys.start(
            bindings,
            ptt_hotkey=self.config.sleep_wake.ptt_hotkey,
            on_ptt_press=self._on_ptt_press,
            on_ptt_release=self._on_ptt_release,
        )
        self.bus.publish("log", level="info" if ok else "warning", message=msg)

    def _on_ptt_press(self) -> None:
        self._ptt_grace_until = 0.0
        self._wake_activity_ts = time.monotonic()
        if self.state.mode != ListeningMode.WAKE:
            self.set_wake_mode(source="ptt")

    def _on_ptt_release(self) -> None:
        self._ptt_grace_until = time.monotonic() + 0.75
        self.audio.set_muted(True, flush_pending=True)
        if self.state.mode != ListeningMode.SLEEP:
            self.set_sleep_mode(source="ptt")

    def _auto_sleep_loop(self) -> None:
        while self._running and not self._stop_event.wait(0.5):
            timeout = float(self.config.sleep_wake.auto_sleep_after_sec or 0.0)
            if timeout <= 0.0:
                continue
            if (
                self.state.mode == ListeningMode.WAKE
                and not self._voice_capture_mode
                and not self.hotkeys.is_ptt_held
                and (time.monotonic() - self._wake_activity_ts) >= timeout
            ):
                self.set_sleep_mode(source="auto_timeout")

    def _on_mode_changed(self, _event) -> None:
        self._sync_mic_mute_with_mode()

    def _sync_mic_mute_with_mode(self) -> None:
        is_sleep = self.state.mode == ListeningMode.SLEEP
        sw = self.config.sleep_wake
        should_mute = is_sleep and (sw.mute_mic_in_sleep or bool(sw.ptt_hotkey.strip()))
        self.audio.set_muted(should_mute)

    def _get_preferred_program_id(self) -> str:
        if self._active_program_id and (time.monotonic() - self._active_program_ts) <= 20.0:
            return self._active_program_id
        return ""

    def save_recorded_sample(self, label: str, audio_samples: np.ndarray) -> str:
        """Save float32 audio into the campioni/ folder and return the relative WAV filename."""
        fname = sanitize_sample_filename(label)
        target_path = self.stt.samples_dir / fname
        save_wav_pcm16(target_path, audio_samples, sample_rate=self.config.audio.sample_rate)
        return fname

    def play_sample_file(self, sample_file: str) -> tuple[bool, str]:
        """Play back a saved WAV sample cleanly on the default output device."""
        try:
            import sounddevice as sd

            wav_path = self.stt.sample_library.resolve_path(sample_file)
            if not wav_path.exists():
                return False, f"File campione non trovato: {wav_path}"
            audio, sr = load_wav_float32(wav_path)
            sd.play(audio, samplerate=sr)
            return True, f"Riproduzione: {wav_path.name}"
        except Exception as exc:
            return False, f"Errore riproduzione campione: {exc}"

    def _on_config_saved(self, new_config: AppConfig) -> None:
        prev_stt = (
            self.config.stt.engine,
            self.config.stt.hybrid_fallback_engine,
            self.config.stt.vosk_model_path,
            self.config.stt.whisper_model_path_or_size,
            self.config.stt.whisper_compute_type,
            self.config.stt.whisper_beam_size,
            self.config.stt.vosk_use_partial_triggers,
            self.config.general.language,
        )
        new_stt = (
            new_config.stt.engine,
            new_config.stt.hybrid_fallback_engine,
            new_config.stt.vosk_model_path,
            new_config.stt.whisper_model_path_or_size,
            new_config.stt.whisper_compute_type,
            new_config.stt.whisper_beam_size,
            new_config.stt.vosk_use_partial_triggers,
            new_config.general.language,
        )
        self.config = new_config
        self.state.update_settings(new_config.sleep_wake)
        self.router.update_config(new_config)
        self.launcher.update_settings(new_config.stage_launcher)
        self.audio.update_settings(new_config.audio, restart_if_device_changed=True)
        self.stt.update_config(
            new_config, reload_model=(self._enable_audio and prev_stt != new_stt)
        )
        if self._enable_hotkeys:
            self._register_hotkeys()
        self._sync_mic_mute_with_mode()

        # Sync OS autostart setting
        ok, msg = self.os_bridge.set_autostart(
            enabled=new_config.general.autostart_at_os_boot,
            script_or_exe=get_launch_command_parts(),
            background=new_config.general.autostart_in_background,
        )
        self.bus.publish("log", level="info" if ok else "warning", message=msg)

    def _on_sample_match(self, sample_match: SampleMatch) -> None:
        if self._voice_capture_mode:
            return
        self._wake_activity_ts = time.monotonic()
        entry = sample_match.entry
        score_pct = f"{sample_match.score * 100:.0f}%"
        if entry.kind == "panic":
            self.trigger_panic(source=f"campione:{score_pct}")
            return
        if entry.kind == "wake":
            self.set_wake_mode(source=f"campione:{score_pct}")
            return
        if entry.kind == "sleep":
            self.set_sleep_mode(source=f"campione:{score_pct}")
            return
        if entry.kind == "popup":
            self._dispatch_match(
                RouteMatch(kind="popup", raw_text=entry.label, normalized_text=entry.label),
                source=f"campione:{score_pct}",
            )
            return
        if entry.kind == "launch_all":
            self._dispatch_match(
                RouteMatch(kind="launch_apps", raw_text=entry.label, normalized_text="avvia tutto"),
                source=f"campione:{score_pct}",
            )
            return
        if entry.kind == "program_open":
            self._active_program_id = entry.program_id
            self._active_program_ts = time.monotonic()
            self._dispatch_match(
                RouteMatch(
                    kind="program_open",
                    raw_text=entry.label,
                    normalized_text=entry.label,
                    target_id=entry.program_id,
                    program_id=entry.program_id,
                ),
                source=f"campione:{score_pct}",
            )
            return
        if entry.kind == "program_func":
            self._active_program_id = entry.program_id
            self._active_program_ts = time.monotonic()
            self._dispatch_match(
                RouteMatch(
                    kind="program_func",
                    raw_text=entry.label,
                    normalized_text=entry.label,
                    target_id=entry.program_id,
                    program_id=entry.program_id,
                    function_id=entry.function_id,
                ),
                source=f"campione:{score_pct}",
            )

    def _on_stt_result(self, result: STTResult) -> None:
        if self._voice_capture_mode:
            return
        if not result.is_final:
            # Debounce partial commands to prevent repeated triggers
            now = time.monotonic()
            norm_key = result.text.strip().lower()
            if now - self._recent_partial_ts.get(norm_key, 0.0) < 1.5:
                return
            match = self.router.route(
                result.text, is_sleeping=(self.state.mode == ListeningMode.SLEEP)
            )
            if match.kind in ("panic", "wake", "sleep", "popup"):
                self._recent_partial_ts[norm_key] = now
                self._dispatch_match(match, source="stt_partial")
            return

        self.process_text_command(result.text, source="stt")

    def process_text_command(self, raw_text: str, source: str = "ui") -> RouteMatch:
        """Route and execute a spoken or simulated text command."""
        is_sleep = self.state.mode == ListeningMode.SLEEP
        match = self.router.route(raw_text, is_sleeping=is_sleep)
        self._dispatch_match(match, source=source)
        return match

    def _dispatch_match(self, match: RouteMatch, source: str) -> None:
        if match.kind == "panic":
            self.trigger_panic(source=f"{source}:{match.raw_text}")
            return
        if match.kind == "wake":
            self.set_wake_mode(source=source)
            return
        if match.kind == "sleep":
            self.set_sleep_mode(source=source)
            return
        if match.kind == "unmatched":
            if match.normalized_text:
                self.bus.publish(
                    "command_ignored",
                    text=match.raw_text,
                    sleeping=(self.state.mode == ListeningMode.SLEEP),
                    source=source,
                )
            return

        self._wake_activity_ts = time.monotonic()
        try:
            self._cmd_queue.put_nowait((match, source))
        except queue.Full:
            self.bus.publish(
                "log", level="warning", message="Coda comandi piena, comando scartato"
            )

    def _command_loop(self) -> None:
        while self._running:
            try:
                item = self._cmd_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            if item is None:
                break
            match, source = item
            if self.state.panic_token.is_cancelled:
                continue
            self._execute_route_match(match, source)

    def _execute_route_match(self, match: RouteMatch, source: str) -> None:
        ctx = TargetContext(
            config=self.config,
            os_bridge=self.os_bridge,
            cancel_token=self.state.panic_token,
            bus=self.bus,
        )

        if match.kind == "popup":
            res = self.popup_handler.handle(match.remainder, ctx)
        elif match.kind == "program_open":
            self._active_program_id = match.program_id
            self._active_program_ts = time.monotonic()
            prog = next((p for p in self.config.programs if p.id == match.program_id), None)
            if prog is None:
                res = CommandExecutionResult(False, match.program_id, "Programma non trovato")
            else:
                res = self.program_executor.open_or_focus_program(prog, ctx.cancel_token)
        elif match.kind == "program_func":
            self._active_program_id = match.program_id
            self._active_program_ts = time.monotonic()
            prog = next((p for p in self.config.programs if p.id == match.program_id), None)
            fn = next((f for f in prog.functions if f.id == match.function_id), None) if prog else None
            if prog is None or fn is None:
                res = CommandExecutionResult(False, match.program_id, "Funzione non trovata")
            else:
                res = self.program_executor.execute_function(
                    prog, fn, match.params, ctx.cancel_token
                )
        elif match.kind == "launch_apps":
            rem_norm = normalize_text(match.remainder)
            is_launch_all = any(
                normalize_text(p) in rem_norm
                for p in ctx.config.stage_launcher.voice_launch_all_triggers
                if p.strip()
            )
            if is_launch_all:
                logs = self._launch_configured_programs(initial_delay=False)
                res = CommandExecutionResult(True, "launcher", " | ".join(logs))
            else:
                ok, msg = self.launcher.handle_voice_command(
                    match.remainder,
                    cancel_token=ctx.cancel_token,
                    prefix_routes=ctx.config.prefix_routes,
                )
                res = CommandExecutionResult(ok, "launcher", msg)
        elif match.kind == "target":
            rem_norm = normalize_text(match.remainder)
            launch_verbs = {
                "",
                "apri",
                "avvia",
                "lancia",
                "mostra",
                "focus",
                "open",
                "start",
            }
            if rem_norm in launch_verbs and self.launcher.find_app_for_target(match.target_id) is not None:
                ok, msg = self.launcher.launch_or_focus_target(
                    match.target_id, self.config.prefix_routes
                )
                res = CommandExecutionResult(ok, "launcher", msg, {"target_id": match.target_id})
            else:
                target = self.targets.get(match.target_id)
                if target is None:
                    res = CommandExecutionResult(
                        False,
                        match.target_id,
                        f"Target '{match.target_id}' non registrato",
                    )
                else:
                    res = target.handle(match.remainder, ctx)
        else:
            return

        self.bus.publish(
            "command_executed",
            source=source,
            raw_text=match.raw_text,
            target_id=res.target_id,
            prefix=match.matched_prefix,
            remainder=match.remainder,
            success=res.handled,
            summary=res.summary,
            details=res.details,
        )
        self.bus.publish(
            "log",
            level="info" if res.handled else "warning",
            message=res.summary,
        )

    def set_wake_mode(self, source: str = "manual") -> ListeningMode:
        self._wake_activity_ts = time.monotonic()
        mode = self.state.set_wake(source=source)
        self.bus.publish("log", level="info", message=f"👍 Wake Mode attivata ({source})")
        return mode

    def set_sleep_mode(self, source: str = "manual") -> ListeningMode:
        mode = self.state.set_sleep(source=source)
        self.bus.publish("log", level="info", message=f"👋 Sleep Mode attivata ({source})")
        return mode

    def toggle_sleep_wake(self, source: str = "manual") -> ListeningMode:
        self._wake_activity_ts = time.monotonic()
        mode = self.state.toggle_sleep_wake(source=source)
        msg = (
            "👍 Wake Mode attivata"
            if mode == ListeningMode.WAKE
            else "👋 Sleep Mode attivata"
        )
        self.bus.publish("log", level="info", message=f"{msg} ({source})")
        return mode

    def trigger_panic(self, source: str = "manual") -> list[str]:
        """Immediately halt all queued/running actions and reset critical stage parameters."""
        token = self.state.trigger_panic(source=source)
        # Clear pending queued commands & STT backlog immediately
        while True:
            try:
                self._cmd_queue.get_nowait()
            except queue.Empty:
                break
        self.stt.flush()

        ctx = TargetContext(
            config=self.config,
            os_bridge=self.os_bridge,
            cancel_token=token,
            bus=self.bus,
        )
        actions: list[str] = ["Coda comandi e macro interrotte"]
        for target in self.targets.values():
            try:
                actions.extend(target.panic(ctx))
            except Exception as exc:
                actions.append(f"Errore panic {target.target_id}: {exc}")

        self.bus.publish("panic_triggered", source=source, actions=actions)
        self.bus.publish(
            "log",
            level="error",
            message=f"🚨 PANIC ({source}): " + " | ".join(actions),
        )
        self.state.finish_panic(enter_sleep=self.config.panic.enter_sleep_mode)
        return actions
