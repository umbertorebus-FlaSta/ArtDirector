"""System target handling popup dismissal and stage app launches via system prefix."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.parser import normalize_text
from .base import BaseTarget, CommandExecutionResult, TargetContext
from .popup_handler import PopupHandlerTarget

if TYPE_CHECKING:
    from ..core.app_launcher import StageAppLauncher


class SystemTarget(BaseTarget):
    """Handles system-prefixed commands: popup dismissal & stage application launches."""

    def __init__(
        self,
        popup_handler: PopupHandlerTarget,
        launcher: StageAppLauncher,
    ) -> None:
        self._popup = popup_handler
        self._launcher = launcher

    @property
    def target_id(self) -> str:
        return "system"

    def handle(self, remainder: str, ctx: TargetContext) -> CommandExecutionResult:
        norm = normalize_text(remainder)
        if not norm:
            return CommandExecutionResult(False, self.target_id, "Comando di sistema vuoto")

        # 1. Popup / dialog / error dismissal
        if any(
            normalize_text(trig) in norm
            for trig in ctx.config.popup_handler.voice_triggers
            if trig.strip()
        ) or any(w in norm for w in ("popup", "avviso", "errore", "banner", "chiudi finestra", "esc", "invio")):
            return self._popup.handle(remainder, ctx)

        # 2. Launch stage apps (all or single app)
        if any(
            normalize_text(trig) in norm
            for trig in ctx.config.stage_launcher.voice_launch_all_triggers
            if trig.strip()
        ) or any(
            norm.startswith(normalize_text(v) + " ")
            for v in ctx.config.stage_launcher.voice_launch_one_verbs
            if v.strip()
        ):
            ok, msg = self._launcher.handle_voice_command(
                remainder,
                cancel_token=ctx.cancel_token,
                prefix_routes=ctx.config.prefix_routes,
            )
            return CommandExecutionResult(ok, "launcher", msg)

        return CommandExecutionResult(
            False, self.target_id, f"Sistema: comando non riconosciuto '{remainder}'"
        )
