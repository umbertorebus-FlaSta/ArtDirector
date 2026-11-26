"""Cross-platform stage application launcher (startup boot sequence + voice launch)."""

from __future__ import annotations

import threading
from pathlib import Path

import psutil

from ..config.schema import PrefixRouteConfig, StageAppEntry, StageLauncherSettings
from ..os_layer.base import OSBridge
from .app_discovery import discover_stage_app_executables, infer_app_target_id
from .event_bus import EventBus
from .parser import normalize_compact, normalize_text
from .state import CancellationToken


def is_process_running(process_name: str, executable: str = "") -> bool:
    """Check via psutil whether a target stage app process is already active."""
    needles: list[str] = []
    if executable.strip():
        stem = normalize_compact(Path(executable.strip()).stem)
        if stem:
            needles.append(stem)
    if process_name.strip():
        p_compact = normalize_compact(process_name.strip())
        if p_compact and p_compact not in needles:
            needles.append(p_compact)
    if not needles:
        return False

    for proc in psutil.process_iter(attrs=["name", "exe"]):
        try:
            pname = normalize_compact(Path(proc.info.get("name") or "").stem)
            pexe = proc.info.get("exe") or ""
            pexe_stem = normalize_compact(Path(pexe).stem) if pexe else ""
            if any(
                (pname and (n == pname or n in pname))
                or (pexe_stem and (n == pexe_stem or n in pexe_stem))
                for n in needles
            ):
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return False


class StageAppLauncher:
    """Launches configured stage software at OS startup or via voice/UI triggers."""

    def __init__(
        self,
        settings: StageLauncherSettings,
        os_bridge: OSBridge,
        bus: EventBus,
    ) -> None:
        self._settings = settings
        self._os = os_bridge
        self._bus = bus
        self._lock = threading.Lock()

    def update_settings(self, settings: StageLauncherSettings) -> None:
        with self._lock:
            self._settings = settings

    def launch_app(
        self, app: StageAppEntry, focus_patterns: list[str] | None = None
    ) -> tuple[bool, str]:
        if not app.executable.strip():
            tid = infer_app_target_id(app)
            if tid:
                found = discover_stage_app_executables().get(tid, "")
                if found:
                    app.executable = found
        if not app.executable.strip():
            return False, (
                f"Percorso non configurato per '{app.name}'. "
                "Impostalo in Settings -> Avvio App Palco."
            )
        if app.skip_if_running and is_process_running(app.process_name, app.executable):
            patterns = list(focus_patterns or [])
            if app.name and app.name not in patterns:
                patterns.append(app.name)
            focused = self._os.focus_window(patterns) if patterns else False
            if focused:
                return True, f"'{app.name}' già aperto (finestra in primo piano)"
            return True, f"'{app.name}' già in esecuzione (saltato)"
        ok, msg = self._os.launch_executable(
            app.executable, app.arguments, app.working_dir
        )
        self._bus.publish(
            "launcher_event", app_name=app.name, success=ok, message=msg
        )
        return ok, msg

    def find_app_for_target(self, target_id: str) -> StageAppEntry | None:
        tid = target_id.strip().lower()
        if not tid:
            return None
        with self._lock:
            apps = list(self._settings.apps)
        for app in apps:
            if infer_app_target_id(app) == tid:
                return app
        return None

    def launch_or_focus_target(
        self,
        target_id: str,
        prefix_routes: dict[str, PrefixRouteConfig] | None = None,
    ) -> tuple[bool, str]:
        app = self.find_app_for_target(target_id)
        if app is None:
            return False, f"Nessuna applicazione associata al target '{target_id}'"
        patterns = (
            list(prefix_routes[target_id].window_title_patterns)
            if prefix_routes and target_id in prefix_routes
            else []
        )
        return self.launch_app(app, focus_patterns=patterns)

    def launch_all_startup_apps(
        self,
        cancel_token: CancellationToken | None = None,
        only_flagged: bool = True,
        initial_delay: bool = True,
    ) -> list[str]:
        with self._lock:
            settings = self._settings
            apps = [
                a for a in settings.apps
                if a.executable.strip() and (not only_flagged or a.launch_on_startup)
            ]

        if not apps:
            return ["Nessuna applicazione configurata con percorso valido per l'avvio."]

        if initial_delay and settings.initial_startup_delay_sec > 0:
            if cancel_token and cancel_token.wait(settings.initial_startup_delay_sec):
                return ["Sequenza avvio applicazioni interrotta da PANIC."]

        logs: list[str] = []
        for idx, app in enumerate(apps):
            if cancel_token and cancel_token.is_cancelled:
                logs.append("Sequenza avvio applicazioni interrotta da PANIC.")
                break
            _, msg = self.launch_app(app)
            logs.append(msg)
            if idx < len(apps) - 1 and app.delay_after_sec > 0:
                if cancel_token and cancel_token.wait(app.delay_after_sec):
                    logs.append("Sequenza avvio applicazioni interrotta da PANIC.")
                    break
        return logs

    def handle_voice_command(
        self,
        remainder: str,
        cancel_token: CancellationToken | None = None,
        prefix_routes: dict[str, PrefixRouteConfig] | None = None,
    ) -> tuple[bool, str]:
        norm = normalize_text(remainder)
        with self._lock:
            settings = self._settings

        # 1. Launch all configured startup apps
        for phrase in settings.voice_launch_all_triggers:
            p = normalize_text(phrase)
            if p and (norm == p or p in norm):
                logs = self.launch_all_startup_apps(
                    cancel_token=cancel_token, only_flagged=True, initial_delay=False
                )
                return True, " | ".join(logs)

        # 2. Launch a single app by name/alias or linked target dynamic prefixes
        for app in settings.apps:
            tid = infer_app_target_id(app)
            route = prefix_routes.get(tid) if prefix_routes and tid else None
            names = [app.name, *app.aliases, *(route.prefixes if route else [])]
            for name in names:
                n = normalize_text(name)
                if n and (norm == n or norm.endswith(" " + n) or f" {n} " in f" {norm} "):
                    return self.launch_app(
                        app, focus_patterns=(route.window_title_patterns if route else None)
                    )

        return False, f"Applicazione non riconosciuta nel comando '{remainder}'"
