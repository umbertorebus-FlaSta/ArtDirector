"""Runtime mode and cooperative cancellation management for Art Director."""

from __future__ import annotations

import threading
from enum import Enum

from ..config.schema import SleepWakeSettings
from .event_bus import EventBus


class ListeningMode(str, Enum):
    WAKE = "wake"
    SLEEP = "sleep"
    PANIC = "panic"


class CancellationToken:
    """Thread-safe cancellation token reset after Panic clears."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def reset(self) -> None:
        self._event.clear()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self, seconds: float) -> bool:
        """Sleep up to `seconds`; returns True immediately if cancelled."""
        return self._event.wait(timeout=max(0.0, seconds))


class StateManager:
    """Manages WAKE / SLEEP / PANIC transitions and visual feedback state."""

    def __init__(self, settings: SleepWakeSettings, bus: EventBus) -> None:
        self._lock = threading.RLock()
        self._settings = settings
        self._bus = bus
        self._mode = (
            ListeningMode.SLEEP
            if settings.start_in_sleep_mode
            else ListeningMode.WAKE
        )
        self._panic_token = CancellationToken()

    def update_settings(self, settings: SleepWakeSettings) -> None:
        with self._lock:
            self._settings = settings

    @property
    def mode(self) -> ListeningMode:
        with self._lock:
            return self._mode

    @property
    def panic_token(self) -> CancellationToken:
        return self._panic_token

    @property
    def emoji(self) -> str:
        with self._lock:
            if self._mode == ListeningMode.WAKE:
                return self._settings.wake_emoji
            if self._mode == ListeningMode.SLEEP:
                return self._settings.sleep_emoji
            return self._settings.panic_emoji

    @property
    def label(self) -> str:
        with self._lock:
            if self._mode == ListeningMode.WAKE:
                return "WAKE MODE (Attivo)"
            if self._mode == ListeningMode.SLEEP:
                return "SLEEP MODE (In Pausa)"
            return "PANIC / EMERGENCY"

    def set_wake(self, source: str = "system") -> ListeningMode:
        with self._lock:
            self._panic_token.reset()
            prev = self._mode
            self._mode = ListeningMode.WAKE
            emoji = self._settings.wake_emoji
            label = "WAKE MODE (Attivo)"
        if prev != ListeningMode.WAKE:
            self._bus.publish(
                "mode_changed",
                mode=ListeningMode.WAKE.value,
                emoji=emoji,
                label=label,
                source=source,
            )
        return ListeningMode.WAKE

    def set_sleep(self, source: str = "system") -> ListeningMode:
        with self._lock:
            prev = self._mode
            self._mode = ListeningMode.SLEEP
            emoji = self._settings.sleep_emoji
            label = "SLEEP MODE (In Pausa)"
        if prev != ListeningMode.SLEEP:
            self._bus.publish(
                "mode_changed",
                mode=ListeningMode.SLEEP.value,
                emoji=emoji,
                label=label,
                source=source,
            )
        return ListeningMode.SLEEP

    def toggle_sleep_wake(self, source: str = "hotkey") -> ListeningMode:
        with self._lock:
            currently_wake = self._mode == ListeningMode.WAKE
        return self.set_sleep(source=source) if currently_wake else self.set_wake(source=source)

    def trigger_panic(self, source: str = "manual") -> CancellationToken:
        with self._lock:
            self._panic_token.cancel()
            self._mode = ListeningMode.PANIC
            emoji = self._settings.panic_emoji
        self._bus.publish(
            "mode_changed",
            mode=ListeningMode.PANIC.value,
            emoji=emoji,
            label="PANIC / EMERGENCY",
            source=source,
        )
        return self._panic_token

    def finish_panic(self, enter_sleep: bool) -> ListeningMode:
        with self._lock:
            self._panic_token = CancellationToken()
        if enter_sleep:
            return self.set_sleep(source="panic_recovery")
        return self.set_wake(source="panic_recovery")
