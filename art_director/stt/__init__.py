"""100% offline voice recognition: acoustic samples (MFCC+DTW) and STT engines."""

from .base import BaseSTTEngine, STTResult
from .manager import STTManager, build_sample_entries_from_config, discover_local_models
from .sample_matcher import (
    AcousticSampleLibrary,
    SampleEntry,
    SampleMatch,
    dtw_similarity,
    extract_mfcc_features,
    load_wav_float32,
    sanitize_sample_filename,
    save_wav_pcm16,
    trim_silence,
)
from .vosk_engine import VoskSTTEngine, is_valid_vosk_model_dir
from .whisper_engine import FasterWhisperSTTEngine, is_valid_whisper_model_dir

__all__ = [
    "AcousticSampleLibrary",
    "BaseSTTEngine",
    "FasterWhisperSTTEngine",
    "STTManager",
    "STTResult",
    "SampleEntry",
    "SampleMatch",
    "VoskSTTEngine",
    "build_sample_entries_from_config",
    "discover_local_models",
    "dtw_similarity",
    "extract_mfcc_features",
    "is_valid_vosk_model_dir",
    "is_valid_whisper_model_dir",
    "load_wav_float32",
    "sanitize_sample_filename",
    "save_wav_pcm16",
    "trim_silence",
]
