"""Thread-safe event bus connecting audio/STT/controller workers with UI & Tray."""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable


@dataclass
class AppEvent:
    topic: str
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


class EventBus:
    """Simple synchronous/thread-safe publish-subscribe event bus."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._subscribers: dict[str, list[Callable[[AppEvent], None]]] = defaultdict(list)

    def subscribe(self, topic: str, callback: Callable[[AppEvent], None]) -> None:
        with self._lock:
            if callback not in self._subscribers[topic]:
                self._subscribers[topic].append(callback)

    def unsubscribe(self, topic: str, callback: Callable[[AppEvent], None]) -> None:
        with self._lock:
            if callback in self._subscribers[topic]:
                self._subscribers[topic].remove(callback)

    def publish(self, topic: str, **payload: Any) -> None:
        event = AppEvent(topic=topic, payload=payload)
        with self._lock:
            callbacks = list(self._subscribers.get(topic, [])) + list(
                self._subscribers.get("*", [])
            )
        for cb in callbacks:
            try:
                cb(event)
            except Exception:
                # Never let a subscriber crash the audio/STT pipeline.
                pass
