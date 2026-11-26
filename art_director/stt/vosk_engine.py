"""Offline streaming Vosk STT engine with low-latency endpoint flushing."""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from ..audio.dsp import VADChunkResult
from .base import BaseSTTEngine, STTResult


def is_valid_vosk_model_dir(path: Path) -> bool:
    """Return True if directory contains required offline Vosk model files."""
    return (
        path.exists()
        and path.is_dir()
        and (
            (path / "am" / "final.mdl").exists()
            or (path / "conf" / "mfcc.conf").exists()
        )
    )


class VoskSTTEngine(BaseSTTEngine):
    """Low-latency 100% offline Vosk speech recognition engine."""

    def __init__(
        self,
        model_path: str,
        sample_rate: int = 16000,
        use_partial: bool = False,
        grammar: list[str] | None = None,
    ) -> None:
        self.model_path = model_path
        self.sample_rate = sample_rate
        self.use_partial = use_partial
        self.grammar = grammar
        self._model = None
        self._recognizer = None
        self._was_gate_open = False
        self._last_partial = ""

    @property
    def name(self) -> str:
        return "vosk"

    @property
    def is_loaded(self) -> bool:
        return self._model is not None and self._recognizer is not None

    def load(self) -> tuple[bool, str]:
        path = Path(self.model_path.strip()) if self.model_path.strip() else None
        if path is None or not path.exists() or not path.is_dir():
            return False, (
                "Percorso modello Vosk non impostato o inesistente. "
                "Seleziona o scarica un modello Vosk offline nei Settings -> STT Offline."
            )
        if not is_valid_vosk_model_dir(path):
            return False, (
                f"La cartella '{path.name}' NON contiene un modello Vosk valido "
                "(mancano am/final.mdl o conf/mfcc.conf). Vai in Settings -> STT Offline."
            )
        try:
            from vosk import KaldiRecognizer, Model, SetLogLevel

            SetLogLevel(-1)
            self._model = Model(str(path))
            self._create_recognizer(KaldiRecognizer)
            return True, f"Modello Vosk caricato offline: {path.name}"
        except Exception as exc:
            self._model = None
            self._recognizer = None
            return False, f"Errore caricamento Vosk: {exc}"

    def _create_recognizer(self, kaldi_cls) -> None:
        if self.grammar:
            clean = [g.strip().lower() for g in self.grammar if g.strip()]
            self._recognizer = kaldi_cls(
                self._model, float(self.sample_rate), json.dumps(clean)
            )
        else:
            self._recognizer = kaldi_cls(self._model, float(self.sample_rate))
        self._recognizer.SetWords(False)

    def unload(self) -> None:
        self._recognizer = None
        self._model = None
        self._was_gate_open = False
        self._last_partial = ""

    def reset(self) -> None:
        if self._recognizer is not None:
            try:
                self._recognizer.Reset()
            except Exception:
                pass
        self._was_gate_open = False
        self._last_partial = ""

    def process_chunk(self, chunk: VADChunkResult) -> list[STTResult]:
        if self._recognizer is None:
            return []

        results: list[STTResult] = []
        t0 = time.perf_counter()

        if chunk.gate_open:
            self._was_gate_open = True
            if self._recognizer.AcceptWaveform(chunk.pcm16_bytes):
                data = json.loads(self._recognizer.Result())
                txt = str(data.get("text", "")).strip()
                if txt:
                    results.append(
                        STTResult(
                            text=txt,
                            is_final=True,
                            latency_ms=(time.perf_counter() - t0) * 1000.0,
                            engine=self.name,
                        )
                    )
                    self._last_partial = ""
            elif self.use_partial:
                pdata = json.loads(self._recognizer.PartialResult())
                ptxt = str(pdata.get("partial", "")).strip()
                if ptxt and ptxt != self._last_partial:
                    self._last_partial = ptxt
                    results.append(
                        STTResult(
                            text=ptxt,
                            is_final=False,
                            latency_ms=(time.perf_counter() - t0) * 1000.0,
                            engine=self.name,
                        )
                    )
        elif self._was_gate_open or chunk.completed_utterance is not None:
            # Flush immediately on noise-gate close to eliminate trailing silence delay
            self._was_gate_open = False
            data = json.loads(self._recognizer.FinalResult())
            txt = str(data.get("text", "")).strip()
            self._last_partial = ""
            if txt:
                results.append(
                    STTResult(
                        text=txt,
                        is_final=True,
                        latency_ms=(time.perf_counter() - t0) * 1000.0,
                        engine=self.name,
                    )
                )
        return results

    def transcribe_utterance(self, samples: np.ndarray) -> STTResult | None:
        """One-shot offline transcription for a completed VAD audio buffer."""
        if self._recognizer is None or samples.size < 1600:
            return None
        t0 = time.perf_counter()
        self.reset()
        pcm16 = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()
        self._recognizer.AcceptWaveform(pcm16)
        data = json.loads(self._recognizer.FinalResult())
        txt = str(data.get("text", "")).strip()
        if not txt:
            return None
        return STTResult(
            text=txt,
            is_final=True,
            latency_ms=(time.perf_counter() - t0) * 1000.0,
            engine=self.name,
        )
