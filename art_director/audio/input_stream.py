"""Real-time audio capture service with automatic resampling and meter callbacks."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Callable

import numpy as np

from ..config.schema import AudioSettings
from .devices import AudioInputDevice, resolve_input_device
from .dsp import AudioDSPProcessor, VADChunkResult

if TYPE_CHECKING:
    from ..core.event_bus import EventBus


def _resample_linear(samples: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    if src_rate == dst_rate or samples.size == 0:
        return samples
    new_len = max(1, int(round(samples.shape[0] * float(dst_rate) / float(src_rate))))
    x_old = np.linspace(0.0, 1.0, num=samples.shape[0], endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=new_len, endpoint=False)
    return np.interp(x_new, x_old, samples).astype(np.float32)


class AudioCaptureService:
    """Captures microphone audio via PortAudio and feeds AudioDSPProcessor."""

    def __init__(
        self,
        settings: AudioSettings,
        bus: EventBus,
        on_chunk: Callable[[VADChunkResult], None] | None = None,
    ) -> None:
        self._settings = settings
        self._bus = bus
        self._on_chunk = on_chunk
        self._lock = threading.RLock()
        self._stream = None
        self._running = False
        self._muted = False
        self._active_device: AudioInputDevice | None = None
        self._hw_samplerate = settings.sample_rate
        self._last_meter_emit = 0.0
        self.dsp = AudioDSPProcessor(
            sample_rate=settings.sample_rate,
            highpass_enabled=settings.highpass_enabled,
            highpass_cutoff_hz=settings.highpass_cutoff_hz,
            noise_gate_db=settings.noise_gate_db,
            hangover_ms=settings.vad_hangover_ms,
            max_utterance_sec=settings.max_utterance_sec,
            input_gain=settings.input_gain,
        )

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._running

    @property
    def active_device(self) -> AudioInputDevice | None:
        with self._lock:
            return self._active_device

    def set_muted(self, muted: bool, flush_pending: bool = False) -> None:
        flushed_chunk = None
        with self._lock:
            self._muted = muted
            if muted:
                if flush_pending:
                    flushed_chunk = self.dsp.flush_pending()
                self.dsp.reset()
        if flushed_chunk is not None and self._on_chunk is not None:
            self._on_chunk(flushed_chunk)

    def update_settings(self, settings: AudioSettings, restart_if_device_changed: bool = True) -> None:
        with self._lock:
            prev_dev_idx = self._settings.input_device_index
            prev_dev_name = self._settings.input_device_name
            self._settings = settings
            self.dsp.update_params(
                sample_rate=settings.sample_rate,
                highpass_enabled=settings.highpass_enabled,
                highpass_cutoff_hz=settings.highpass_cutoff_hz,
                noise_gate_db=settings.noise_gate_db,
                hangover_ms=settings.vad_hangover_ms,
                max_utterance_sec=settings.max_utterance_sec,
                input_gain=settings.input_gain,
            )
            device_changed = (
                prev_dev_idx != settings.input_device_index
                or prev_dev_name != settings.input_device_name
            )
            was_running = self._running
        if was_running and restart_if_device_changed and device_changed:
            self.stop()
            self.start()

    def start(self) -> tuple[bool, str]:
        with self._lock:
            if self._running:
                return True, "Stream audio già attivo"
            try:
                import sounddevice as sd
            except Exception as exc:
                msg = f"sounddevice non disponibile: {exc}"
                self._bus.publish("audio_error", message=msg)
                return False, msg

            dev = resolve_input_device(
                self._settings.input_device_index, self._settings.input_device_name
            )
            if dev is None:
                msg = "Nessuna periferica microfonica rilevata"
                self._bus.publish("audio_error", message=msg)
                return False, msg

            target_sr = self._settings.sample_rate
            hw_sr = target_sr
            try:
                sd.check_input_settings(
                    device=dev.index,
                    channels=1,
                    samplerate=target_sr,
                    dtype="float32",
                )
            except Exception:
                hw_sr = int(dev.default_samplerate or 44100)

            self._hw_samplerate = hw_sr
            hw_block = max(
                256,
                int(round(self._settings.block_size * float(hw_sr) / float(target_sr))),
            )

            try:
                self.dsp.reset()
                self._stream = sd.InputStream(
                    device=dev.index,
                    channels=1,
                    samplerate=hw_sr,
                    blocksize=hw_block,
                    dtype="float32",
                    callback=self._audio_callback,
                )
                self._stream.start()
                self._active_device = dev
                self._running = True
                self._bus.publish(
                    "audio_started",
                    device_name=dev.name,
                    device_index=dev.index,
                    samplerate=hw_sr,
                )
                return True, f"Microfono attivo: {dev.name} @ {hw_sr} Hz"
            except Exception as exc:
                self._stream = None
                self._running = False
                msg = f"Errore apertura microfono '{dev.name}': {exc}"
                self._bus.publish("audio_error", message=msg)
                return False, msg

    def stop(self) -> None:
        with self._lock:
            stream = self._stream
            self._stream = None
            self._running = False
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        self._bus.publish("audio_stopped")

    def _audio_callback(self, indata, frames, time_info, status) -> None:  # noqa: ARG002
        if self._muted:
            return
        mono = indata[:, 0] if indata.ndim > 1 else indata.reshape(-1)
        if self._hw_samplerate != self._settings.sample_rate:
            mono = _resample_linear(
                mono, self._hw_samplerate, self._settings.sample_rate
            )
        chunk = self.dsp.process_block(mono)
        now = time.monotonic()
        if now - self._last_meter_emit >= 0.05:
            self._last_meter_emit = now
            self._bus.publish(
                "audio_level",
                rms_db=chunk.rms_db,
                peak_db=chunk.peak_db,
                gate_open=chunk.gate_open,
            )
        if self._on_chunk is not None:
            self._on_chunk(chunk)

    @staticmethod
    def run_mic_test_sample(
        device_index: int | None,
        duration_sec: float = 2.0,
        playback: bool = True,
    ) -> tuple[bool, float, str]:
        """Record a short test sample from a mic to check peak level & optional loopback."""
        try:
            import sounddevice as sd
        except Exception as exc:
            return False, -90.0, f"sounddevice non disponibile: {exc}"
        try:
            dev_info = sd.query_devices(device_index, kind="input")
            sr = int(dev_info.get("default_samplerate", 16000))
            frames = max(1024, int(sr * duration_sec))
            rec = sd.rec(
                frames,
                samplerate=sr,
                channels=1,
                dtype="float32",
                device=device_index,
            )
            sd.wait()
            flat = rec.reshape(-1)
            peak = float(np.max(np.abs(flat))) if flat.size else 0.0
            peak_db = 20.0 * np.log10(peak) if peak > 1e-5 else -90.0
            if playback and flat.size:
                sd.play(flat, samplerate=sr)
                sd.wait()
            return (
                True,
                float(peak_db),
                f"Test OK ({dev_info.get('name', 'Mic')}): picco {peak_db:.1f} dBFS",
            )
        except Exception as exc:
            return False, -90.0, f"Errore test microfono: {exc}"
