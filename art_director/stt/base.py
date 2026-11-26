"""Base interface for offline Speech-to-Text engines."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..audio.dsp import VADChunkResult


@dataclass
class STTResult:
    text: str
    is_final: bool = True
    confidence: float = 1.0
    latency_ms: float = 0.0
    engine: str = ""


class BaseSTTEngine(ABC):
    """Interface implemented by offline streaming or utterance-based STT engines."""

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def is_loaded(self) -> bool:
        ...

    @abstractmethod
    def load(self) -> tuple[bool, str]:
        ...

    @abstractmethod
    def unload(self) -> None:
        ...

    @abstractmethod
    def reset(self) -> None:
        ...

    @abstractmethod
    def process_chunk(self, chunk: VADChunkResult) -> list[STTResult]:
        ...
