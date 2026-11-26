"""Unexpected dialog, error popup, and startup banner fast-dismissal target."""

from __future__ import annotations

from ..core.parser import normalize_text
from .base import BaseTarget, CommandExecutionResult, TargetContext


class PopupHandlerTarget(BaseTarget):
    """Intercepts and dismisses error dialogs, audio-device alerts, and splash banners."""

    @property
    def target_id(self) -> str:
        return "popup"

    def dismiss_now(self, ctx: TargetContext, strategy_override: str | None = None) -> CommandExecutionResult:
        cfg = ctx.config.popup_handler
        if not cfg.enabled:
            return CommandExecutionResult(False, self.target_id, "Gestione pop-up disabilitata")

        protected_patterns: list[str] = []
        for route in ctx.config.prefix_routes.values():
            protected_patterns.extend(route.window_title_patterns)

        strategy = strategy_override or cfg.strategy
        ok, msg = ctx.os_bridge.dismiss_popup(
            strategy=strategy,
            dialog_keywords=cfg.known_dialog_keywords,
            protect_main_windows=cfg.protect_main_windows,
            protected_patterns=protected_patterns,
        )
        return CommandExecutionResult(ok, self.target_id, msg)

    def handle(self, remainder: str, ctx: TargetContext) -> CommandExecutionResult:
        norm = normalize_text(remainder)
        if "invio" in norm or "enter" in norm or "conferma" in norm:
            return self.dismiss_now(ctx, strategy_override="enter")
        if "esc" in norm or "escape" in norm:
            return self.dismiss_now(ctx, strategy_override="esc")
        if "forza" in norm or "chiudi finestra" in norm:
            return self.dismiss_now(ctx, strategy_override="esc_then_close")
        return self.dismiss_now(ctx)
