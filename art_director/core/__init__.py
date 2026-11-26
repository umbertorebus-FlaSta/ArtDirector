"""Core orchestration, routing, state, and application launcher modules."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .app_discovery import InstalledProgram, discover_all_installed_programs
from .app_launcher import StageAppLauncher, is_process_running
from .event_bus import AppEvent, EventBus
from .executor import ProgramExecutor
from .parser import CommandRouter, RouteMatch, extract_numbers, normalize_text, replace_spoken_numbers
from .state import CancellationToken, ListeningMode, StateManager

if TYPE_CHECKING:
    from .controller import ArtDirectorController


def __getattr__(name: str):
    if name == "ArtDirectorController":
        from .controller import ArtDirectorController

        return ArtDirectorController
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "AppEvent",
    "ArtDirectorController",
    "CancellationToken",
    "CommandRouter",
    "EventBus",
    "InstalledProgram",
    "ListeningMode",
    "ProgramExecutor",
    "RouteMatch",
    "StageAppLauncher",
    "StateManager",
    "discover_all_installed_programs",
    "extract_numbers",
    "is_process_running",
    "normalize_text",
    "replace_spoken_numbers",
]
