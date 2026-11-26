"""Speaker-dependent acoustic voice sample matcher using MFCC + CMVN + Delta + DTW."""

from __future__ import annotations

import math
import re
import threading
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


def _hz_to_mel(hz: np.ndarray | float) -> np.ndarray | float:
    return 2595.0 * np.log10(1.0 + np.asarray(hz, dtype=np.float64) / 700.0)


def _mel_to_hz(mel: np.ndarray | float) -> np.ndarray | float:
    return 700.0 * (10.0 ** (np.asarray(mel, dtype=np.float64) / 2595.0) - 1.0)


def _build_mel_filterbank(
    sample_rate: int = 16000,
    n_fft: int = 512,
    n_mels: int = 26,
    fmin: float = 80.0,
    fmax: float = 7600.0,
) -> np.ndarray:
    fmax_eff = min(float(fmax), float(sample_rate) * 0.48)
    mel_pts = np.linspace(
        float(_hz_to_mel(fmin)), float(_hz_to_mel(fmax_eff)), n_mels + 2
    )
    hz_pts = _mel_to_hz(mel_pts)
    bins = np.floor((n_fft + 1) * hz_pts / float(sample_rate)).astype(int)
    bins = np.clip(bins, 0, n_fft // 2)

    fbank = np.zeros((n_mels, n_fft // 2 + 1), dtype=np.float32)
    for m in range(1, n_mels + 1):
        left, center, right = int(bins[m - 1]), int(bins[m]), int(bins[m + 1])
        if center <= left:
            center = min(n_fft // 2, left + 1)
        if right <= center:
            right = min(n_fft // 2, center + 1)
        for k in range(left, center):
            fbank[m - 1, k] = float(k - left) / float(max(1, center - left))
        for k in range(center, right):
            fbank[m - 1, k] = float(right - k) / float(max(1, right - center))
    return fbank


def _build_dct_matrix(n_mfcc: int = 13, n_mels: int = 26) -> np.ndarray:
    # Ortho-normalized DCT-II matrix skipping C0 (indices 1..n_mfcc)
    k = np.arange(1, n_mfcc + 1, dtype=np.float32)[:, None]
    n = np.arange(n_mels, dtype=np.float32)[None, :]
    scale = math.sqrt(2.0 / float(n_mels))
    return (scale * np.cos(math.pi * k * (n + 0.5) / float(n_mels))).astype(np.float32)


_MEL_FBANK_16K = _build_mel_filterbank(16000, 512, 26, 80.0, 7600.0)
_DCT_13_26 = _build_dct_matrix(13, 26)


def trim_silence(
    samples: np.ndarray,
    sample_rate: int = 16000,
    pad_ms: int = 45,
) -> np.ndarray:
    """Trim leading and trailing silence using short-time frame RMS envelope."""
    arr = samples.astype(np.float32, copy=False).reshape(-1)
    if arr.size < int(sample_rate * 0.08):
        return arr

    peak = float(np.max(np.abs(arr)))
    if peak < 1e-4:
        return np.zeros(0, dtype=np.float32)

    win = max(64, int(sample_rate * 0.015))
    hop = max(32, win // 2)
    n_frames = 1 + max(0, (arr.size - win) // hop)
    if n_frames <= 1:
        return arr

    rms = np.empty(n_frames, dtype=np.float32)
    for i in range(n_frames):
        seg = arr[i * hop : i * hop + win]
        rms[i] = float(np.sqrt(np.mean(seg * seg)))

    thresh = max(0.012 * peak, float(np.max(rms)) * 0.14)
    active = np.where(rms >= thresh)[0]
    if active.size == 0:
        return arr

    pad_samples = int(sample_rate * (pad_ms / 1000.0))
    start = max(0, int(active[0]) * hop - pad_samples)
    end = min(arr.size, int(active[-1]) * hop + win + pad_samples)
    return arr[start:end].copy()


def extract_mfcc_features(
    samples: np.ndarray,
    sample_rate: int = 16000,
    trim: bool = True,
) -> np.ndarray | None:
    """Extract 16kHz-normalized MFCC + Delta acoustic feature matrix (T, 26)."""
    arr = samples.astype(np.float32, copy=False).reshape(-1)
    if trim:
        arr = trim_silence(arr, sample_rate=sample_rate)

    # Require at least 110ms of active speech to avoid mic bumps / clicks
    if arr.size < int(sample_rate * 0.11):
        return None

    peak = float(np.max(np.abs(arr)))
    if peak < 1e-4:
        return None
    arr = arr * (0.707 / peak)

    # Normalize sample rate to 16 kHz so 25ms frames fit n_fft=512 cleanly at any mic rate (e.g. 48 kHz)
    if sample_rate != 16000 and arr.size > 0:
        if sample_rate >= 32000:
            arr = np.convolve(
                arr, np.array([0.25, 0.5, 0.25], dtype=np.float32), mode="same"
            )
        new_len = max(1, int(round(arr.size * 16000.0 / float(sample_rate))))
        x_old = np.linspace(0.0, 1.0, num=arr.size, endpoint=False)
        x_new = np.linspace(0.0, 1.0, num=new_len, endpoint=False)
        arr = np.interp(x_new, x_old, arr).astype(np.float32)

    # Pre-emphasis filter
    emphasized = np.empty_like(arr)
    emphasized[0] = arr[0]
    emphasized[1:] = arr[1:] - 0.97 * arr[:-1]

    frame_len = 400  # 25ms @ 16kHz
    hop_len = 160    # 10ms @ 16kHz
    n_fft = 512
    if emphasized.size < frame_len:
        emphasized = np.pad(emphasized, (0, frame_len - emphasized.size))

    n_frames = 1 + (emphasized.size - frame_len) // hop_len
    indices = (
        np.arange(frame_len, dtype=np.int32)[None, :]
        + np.arange(n_frames, dtype=np.int32)[:, None] * hop_len
    )
    frames = emphasized[indices]
    window = np.hamming(frame_len).astype(np.float32)
    frames = frames * window[None, :]

    spec = np.fft.rfft(frames, n=n_fft, axis=1)
    power = (spec.real * spec.real + spec.imag * spec.imag) / float(n_fft)

    mel_energy = np.maximum(power @ _MEL_FBANK_16K.T, 1e-10)
    log_mel = np.log(mel_energy)
    mfcc = (log_mel @ _DCT_13_26.T).astype(np.float32)

    # First-order Delta features
    if mfcc.shape[0] >= 3:
        padded = np.pad(mfcc, ((1, 1), (0, 0)), mode="edge")
        delta = 0.5 * (padded[2:] - padded[:-2])
    else:
        delta = np.zeros_like(mfcc)

    return np.hstack([mfcc, 0.7 * delta]).astype(np.float32)


def dtw_similarity(feat_a: np.ndarray, feat_b: np.ndarray) -> float:
    """Compute similarity score in [0.0, 1.0] via Sakoe-Chiba cosine DTW."""
    n, d1 = feat_a.shape
    m, d2 = feat_b.shape
    if n == 0 or m == 0 or d1 != d2:
        return 0.0

    # Reject extreme length mismatches (> 2.4x speed ratio) quickly
    if min(n, m) / float(max(n, m)) < 0.42:
        return 0.0

    # Frame-wise L2-normalized cosine distance matrix (n, m)
    norm_a = feat_a / (np.linalg.norm(feat_a, axis=1, keepdims=True) + 1e-6)
    norm_b = feat_b / (np.linalg.norm(feat_b, axis=1, keepdims=True) + 1e-6)
    dist = 1.0 - np.clip(norm_a @ norm_b.T, -1.0, 1.0)

    band = max(8, abs(n - m) + int(round(0.28 * max(n, m))))
    inf = 1e9
    dp = np.full((n + 1, m + 1), inf, dtype=np.float64)
    dp[0, 0] = 0.0

    for i in range(1, n + 1):
        j_center = int(round(i * m / float(n)))
        j_start = max(1, j_center - band)
        j_end = min(m, j_center + band)
        row_d = dist[i - 1]
        prev_row = dp[i - 1]
        cur_row = dp[i]
        for j in range(j_start, j_end + 1):
            cost = float(row_d[j - 1])
            best_prev = min(prev_row[j], cur_row[j - 1], prev_row[j - 1])
            cur_row[j] = cost + best_prev

    total_cost = dp[n, m]
    if total_cost >= inf * 0.5:
        return 0.0

    avg_dist = total_cost / float(max(n, m))
    # Calibrated on real 48kHz->16kHz mic takes: same word ~0.70..0.88, different <0.65
    score = math.exp(-1.20 * max(0.0, avg_dist))
    return max(0.0, min(1.0, float(score)))


def save_wav_pcm16(path: Path, samples: np.ndarray, sample_rate: int = 16000) -> Path:
    """Trim silence, normalize slightly, and write mono 16-bit PCM WAV file."""
    trimmed = trim_silence(samples, sample_rate=sample_rate)
    if trimmed.size == 0:
        trimmed = samples.astype(np.float32, copy=False).reshape(-1)
    peak = float(np.max(np.abs(trimmed))) if trimmed.size else 0.0
    if peak > 1e-4:
        trimmed = np.clip(trimmed * (0.8 / peak), -1.0, 1.0)
    pcm16 = (trimmed * 32767.0).astype(np.int16)

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(int(sample_rate))
        wf.writeframes(pcm16.tobytes())
    return path


def load_wav_float32(path: Path) -> tuple[np.ndarray, int]:
    """Read mono/stereo WAV file into float32 mono array and sample rate."""
    with wave.open(str(path), "rb") as wf:
        channels = wf.getnchannels()
        sampwidth = wf.getsampwidth()
        sr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())

    if sampwidth == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 4:
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        data = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0

    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)
    return data, int(sr)


def sanitize_sample_filename(label: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", label.strip().lower()).strip("_")
    slug = slug[:40] or "comando"
    ts = int(time.time() * 1000) % 10_000_000
    return f"{slug}_{ts}.wav"


@dataclass
class SampleEntry:
    """In-memory indexed acoustic template pointing to a WAV file on disk."""

    sample_file: str
    kind: str  # "panic" | "wake" | "sleep" | "popup" | "launch_all" | "program_open" | "program_func"
    label: str
    program_id: str = ""
    function_id: str = ""
    features: np.ndarray | None = field(default=None, repr=False)


@dataclass
class SampleMatch:
    entry: SampleEntry
    score: float
    latency_ms: float


class AcousticSampleLibrary:
    """Loads WAV voice samples from disk, extracts MFCCs, and matches live utterances."""

    def __init__(self, samples_dir: Path, sample_rate: int = 16000) -> None:
        self.samples_dir = Path(samples_dir)
        self.sample_rate = sample_rate
        self._lock = threading.RLock()
        self._entries: list[SampleEntry] = []

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._entries)

    def resolve_path(self, sample_file: str) -> Path:
        p = Path(sample_file)
        if p.is_absolute():
            return p
        return self.samples_dir / p

    def rebuild(self, entries: list[SampleEntry]) -> int:
        loaded: list[SampleEntry] = []
        for item in entries:
            wav_path = self.resolve_path(item.sample_file)
            if not wav_path.exists():
                continue
            try:
                audio, sr = load_wav_float32(wav_path)
                feats = extract_mfcc_features(audio, sample_rate=sr, trim=True)
                if feats is not None:
                    item.features = feats
                    loaded.append(item)
            except Exception:
                continue
        with self._lock:
            self._entries = loaded
            return len(self._entries)

    def match(
        self,
        samples: np.ndarray,
        threshold: float = 0.68,
        allowed_kinds: set[str] | None = None,
        preferred_program_id: str = "",
    ) -> SampleMatch | None:
        t0 = time.perf_counter()
        query_feats = extract_mfcc_features(samples, sample_rate=self.sample_rate, trim=True)
        if query_feats is None:
            return None

        with self._lock:
            candidates = list(self._entries)

        if not candidates:
            return None

        best_entry: SampleEntry | None = None
        best_score = 0.0
        best_effective = 0.0

        for entry in candidates:
            if allowed_kinds is not None and entry.kind not in allowed_kinds:
                continue
            if entry.features is None:
                continue
            score = dtw_similarity(query_feats, entry.features)
            # Tiny context boost (+0.03) when user already focused/selected that program
            effective = score + (
                0.03
                if preferred_program_id and entry.program_id == preferred_program_id
                else 0.0
            )
            if score >= threshold and effective > best_effective:
                best_effective = effective
                best_score = score
                best_entry = entry

        if best_entry is None:
            return None

        return SampleMatch(
            entry=best_entry,
            score=best_score,
            latency_ms=(time.perf_counter() - t0) * 1000.0,
        )
