"""Audio input device management, anti-feedback DSP, and streaming."""

from .devices import AudioInputDevice, list_input_devices, resolve_input_device
from .dsp import AudioDSPProcessor, HighPassFilter, NoiseGateVAD, compute_rms_and_peak_db
from .input_stream import AudioCaptureService

__all__ = [
    "AudioCaptureService",
    "AudioDSPProcessor",
    "AudioInputDevice",
    "HighPassFilter",
    "NoiseGateVAD",
    "compute_rms_and_peak_db",
    "list_input_devices",
    "resolve_input_device",
]
