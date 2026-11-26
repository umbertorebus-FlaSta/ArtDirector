"""100% offline Faster-Whisper STT engine driven by VAD utterance bursts."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from ..audio.dsp import VADChunkResult
from .base import BaseSTTEngine, STTResult


def is_valid_whisper_model_dir(path: Path) -> bool:
    """Return True if directory contains required offline CTranslate2 Whisper files."""
    return (
        path.exists()
        and path.is_dir()
        and (path / "model.bin").exists()
        and (path / "config.json").exists()
    )


def _looks_like_path(value: str) -> bool:
    return any(sep in value for sep in ("/", "\\", ":")) or value.startswith(".")


class FasterWhisperSTTEngine(BaseSTTEngine):
    """Offline CTranslate2 Whisper engine operating strictly from local files."""

    def __init__(
        self,
        model_path_or_size: str = "base",
        device: str = "cpu",
        compute_type: str = "int8",
        beam_size: int = 1,
        language: str = "it",
        sample_rate: int = 16000,
        initial_prompt: str = "",
        hotwords: str = "",
    ) -> None:
        self.model_path_or_size = model_path_or_size
        self.device = device
        self.compute_type = compute_type
        self.beam_size = beam_size
        self.language = language
        self.sample_rate = int(sample_rate) if sample_rate else 16000
        self.initial_prompt = initial_prompt
        self.hotwords = hotwords
        self._model = None

    @property
    def name(self) -> str:
        return "faster_whisper"

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> tuple[bool, str]:
        target = self.model_path_or_size.strip() or "base"
        path_candidate = Path(target)
        if (path_candidate.exists() or _looks_like_path(target)) and not is_valid_whisper_model_dir(
            path_candidate
        ):
            self._model = None
            return False, (
                f"La cartella '{path_candidate.name or target}' NON contiene un modello "
                "Faster-Whisper valido (mancano model.bin o config.json)."
            )
        try:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                target,
                device=self.device,
                compute_type=self.compute_type,
                local_files_only=True,
            )
            return True, f"Modello Faster-Whisper caricato offline: {target}"
        except Exception as exc:
            self._model = None
            return False, (
                f"Modello Faster-Whisper '{target}' non trovato in locale ({exc}). "
                "Specifica o scarica una cartella modello CTranslate2 locale nei Settings."
            )

    def unload(self) -> None:
        self._model = None

    def reset(self) -> None:
        pass

    def process_chunk(self, chunk: VADChunkResult) -> list[STTResult]:
        if self._model is None or chunk.completed_utterance is None:
            return []
        audio = np.asarray(chunk.completed_utterance, dtype=np.float32)
        if self.sample_rate > 0 and self.sample_rate != 16000:
            from ..audio.input_stream import _resample_linear

            audio = _resample_linear(audio, self.sample_rate, 16000)
        # Ignore sub-180ms impulse clicks (drum hits, mic bumps) at 16 kHz
        if audio.shape[0] < 2880:
            return []

        t0 = time.perf_counter()
        try:
            kwargs: dict[str, object] = {
                "language": self.language or None,
                "beam_size": max(1, int(self.beam_size)),
                "temperature": 0.0,
                "without_timestamps": True,
                "vad_filter": False,
                "condition_on_previous_text": False,
            }
            if self.initial_prompt.strip():
                kwargs["initial_prompt"] = self.initial_prompt.strip()
            if self.hotwords.strip():
                kwargs["hotwords"] = self.hotwords.strip()
            segments, _info = self._model.transcribe(audio, **kwargs)
            text = " ".join(seg.text.strip() for seg in segments if seg.text).strip()
            if not text:
                return []
            return [
                STTResult(
                    text=text,
                    is_final=True,
                    latency_ms=(time.perf_counter() - t0) * 1000.0,
                    engine=self.name,
                )
            ]
        except Exception:
            return []
