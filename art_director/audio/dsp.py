"""Anti-feedback DSP: High-Pass Filter, RMS/Peak dBFS metering, and Noise-Gate VAD."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


def compute_rms_and_peak_db(samples: np.ndarray) -> tuple[float, float]:
    """Return (rms_db, peak_db) in dBFS within [-90.0, 0.0]."""
    if samples.size == 0:
        return -90.0, -90.0
    arr = samples.astype(np.float32, copy=False)
    rms = float(np.sqrt(np.mean(arr * arr)))
    peak = float(np.max(np.abs(arr)))
    rms_db = max(-90.0, min(0.0, 20.0 * math.log10(rms))) if rms > 1e-5 else -90.0
    peak_db = max(-90.0, min(0.0, 20.0 * math.log10(peak))) if peak > 1e-5 else -90.0
    return rms_db, peak_db


class HighPassFilter:
    """First-order IIR high-pass filter to attenuate stage subwoofer & monitor bleed."""

    def __init__(self, cutoff_hz: float = 100.0, sample_rate: int = 16000) -> None:
        self.cutoff_hz = cutoff_hz
        self.sample_rate = sample_rate
        self._prev_x = 0.0
        self._prev_y = 0.0
        self._alpha = self._compute_alpha(cutoff_hz, sample_rate)

    @staticmethod
    def _compute_alpha(cutoff_hz: float, sample_rate: int) -> float:
        if cutoff_hz <= 0 or sample_rate <= 0:
            return 0.0
        rc = 1.0 / (2.0 * math.pi * cutoff_hz)
        dt = 1.0 / float(sample_rate)
        return rc / (rc + dt)

    def configure(self, cutoff_hz: float, sample_rate: int) -> None:
        self.cutoff_hz = cutoff_hz
        self.sample_rate = sample_rate
        self._alpha = self._compute_alpha(cutoff_hz, sample_rate)

    def reset(self) -> None:
        self._prev_x = 0.0
        self._prev_y = 0.0

    def process(self, samples: np.ndarray) -> np.ndarray:
        if samples.size == 0 or self._alpha <= 0.0:
            return samples
        x = samples.astype(np.float32, copy=False)
        y = np.empty_like(x, dtype=np.float32)
        alpha = self._alpha
        prev_x = self._prev_x
        prev_y = self._prev_y
        for i in range(x.shape[0]):
            xi = float(x[i])
            yi = alpha * (prev_y + xi - prev_x)
            y[i] = yi
            prev_x = xi
            prev_y = yi
        self._prev_x = prev_x
        self._prev_y = prev_y
        return y


@dataclass
class VADChunkResult:
    processed_float32: np.ndarray
    pcm16_bytes: bytes
    rms_db: float
    peak_db: float
    gate_open: bool
    completed_utterance: np.ndarray | None = None


class NoiseGateVAD:
    """Stage noise gate with hangover timer and utterance segmentation."""

    def __init__(
        self,
        threshold_db: float = -42.0,
        hangover_ms: int = 350,
        max_utterance_sec: float = 6.0,
        sample_rate: int = 16000,
    ) -> None:
        self.threshold_db = threshold_db
        self.hangover_ms = hangover_ms
        self.max_utterance_sec = max_utterance_sec
        self.sample_rate = sample_rate
        self._hangover_samples_left = 0
        self._active_frames: list[np.ndarray] = []
        self._total_active_samples = 0
        self._pre_roll: np.ndarray | None = None

    def configure(
        self,
        threshold_db: float,
        hangover_ms: int,
        max_utterance_sec: float,
        sample_rate: int,
    ) -> None:
        self.threshold_db = threshold_db
        self.hangover_ms = hangover_ms
        self.max_utterance_sec = max_utterance_sec
        self.sample_rate = sample_rate

    def reset(self) -> None:
        self._hangover_samples_left = 0
        self._active_frames.clear()
        self._total_active_samples = 0
        self._pre_roll = None

    def step(self, samples: np.ndarray, rms_db: float) -> tuple[bool, np.ndarray | None]:
        """Advance gate state; returns (gate_open, completed_utterance_or_None)."""
        n = int(samples.shape[0])
        hangover_samples = int(self.sample_rate * (self.hangover_ms / 1000.0))
        max_samples = int(self.sample_rate * self.max_utterance_sec)

        is_speech = rms_db >= self.threshold_db
        completed: np.ndarray | None = None

        if is_speech:
            if not self._active_frames and self._pre_roll is not None:
                self._active_frames.append(self._pre_roll)
                self._total_active_samples += int(self._pre_roll.shape[0])
            self._hangover_samples_left = hangover_samples
            self._active_frames.append(samples.copy())
            self._total_active_samples += n
            gate_open = True
        elif self._hangover_samples_left > 0:
            self._hangover_samples_left = max(0, self._hangover_samples_left - n)
            self._active_frames.append(samples.copy())
            self._total_active_samples += n
            gate_open = True
        else:
            gate_open = False
            if self._active_frames:
                completed = np.concatenate(self._active_frames)
                self._active_frames.clear()
                self._total_active_samples = 0
            self._pre_roll = samples.copy()

        if self._active_frames and self._total_active_samples >= max_samples:
            completed = np.concatenate(self._active_frames)
            self._active_frames.clear()
            self._total_active_samples = 0
            self._hangover_samples_left = 0

        return gate_open, completed

    def flush(self, min_samples: int = 1600) -> np.ndarray | None:
        """Finalize and return any buffered speech (used when PTT button is released)."""
        self._hangover_samples_left = 0
        self._pre_roll = None
        if not self._active_frames:
            self._total_active_samples = 0
            return None
        if self._total_active_samples < min_samples:
            self._active_frames.clear()
            self._total_active_samples = 0
            return None
        completed = np.concatenate(self._active_frames)
        self._active_frames.clear()
        self._total_active_samples = 0
        return completed


class AudioDSPProcessor:
    """Combines input gain, high-pass filter, level metering, and noise-gate VAD."""

    def __init__(
        self,
        sample_rate: int = 16000,
        highpass_enabled: bool = True,
        highpass_cutoff_hz: float = 100.0,
        noise_gate_db: float = -42.0,
        hangover_ms: int = 350,
        max_utterance_sec: float = 6.0,
        input_gain: float = 1.0,
    ) -> None:
        self.sample_rate = sample_rate
        self.highpass_enabled = highpass_enabled
        self.input_gain = input_gain
        self.hpf = HighPassFilter(cutoff_hz=highpass_cutoff_hz, sample_rate=sample_rate)
        self.vad = NoiseGateVAD(
            threshold_db=noise_gate_db,
            hangover_ms=hangover_ms,
            max_utterance_sec=max_utterance_sec,
            sample_rate=sample_rate,
        )

    def update_params(
        self,
        sample_rate: int,
        highpass_enabled: bool,
        highpass_cutoff_hz: float,
        noise_gate_db: float,
        hangover_ms: int,
        max_utterance_sec: float,
        input_gain: float,
    ) -> None:
        self.sample_rate = sample_rate
        self.highpass_enabled = highpass_enabled
        self.input_gain = input_gain
        self.hpf.configure(highpass_cutoff_hz, sample_rate)
        self.vad.configure(noise_gate_db, hangover_ms, max_utterance_sec, sample_rate)

    def reset(self) -> None:
        self.hpf.reset()
        self.vad.reset()

    def flush_pending(self) -> VADChunkResult | None:
        """Emit any captured in-progress utterance cleanly (for Push-to-Talk release)."""
        min_samples = max(400, int(self.sample_rate * 0.10))
        completed = self.vad.flush(min_samples=min_samples)
        if completed is None or completed.size == 0:
            return None
        return VADChunkResult(
            processed_float32=np.zeros(0, dtype=np.float32),
            pcm16_bytes=b"",
            rms_db=-90.0,
            peak_db=-90.0,
            gate_open=False,
            completed_utterance=completed,
        )

    def process_block(self, raw_mono: np.ndarray) -> VADChunkResult:
        arr = raw_mono.astype(np.float32, copy=False)
        if self.input_gain != 1.0:
            arr = arr * float(self.input_gain)
        if self.highpass_enabled:
            arr = self.hpf.process(arr)
        arr = np.clip(arr, -1.0, 1.0)
        rms_db, peak_db = compute_rms_and_peak_db(arr)
        gate_open, completed = self.vad.step(arr, rms_db)

        if gate_open:
            pcm = (arr * 32767.0).astype(np.int16).tobytes()
        else:
            # Feed silence while noise gate is closed so stage monitor rumble never reaches STT
            pcm = b"\x00\x00" * int(arr.shape[0])

        return VADChunkResult(
            processed_float32=arr,
            pcm16_bytes=pcm,
            rms_db=rms_db,
            peak_db=peak_db,
            gate_open=gate_open,
            completed_utterance=completed,
        )
