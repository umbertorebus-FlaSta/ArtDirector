"""Background voice recognition worker (Acoustic Samples MFCC+DTW & Offline STT)."""

from __future__ import annotations

import queue
import re
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import numpy as np

from ..audio.dsp import VADChunkResult
from ..config.manager import get_app_base_dir, get_default_config_dir, get_samples_dir
from ..config.schema import AppConfig
from .base import BaseSTTEngine, STTResult
from .sample_matcher import AcousticSampleLibrary, SampleEntry, SampleMatch, trim_silence
from .vosk_engine import VoskSTTEngine, is_valid_vosk_model_dir
from .whisper_engine import FasterWhisperSTTEngine, is_valid_whisper_model_dir

if TYPE_CHECKING:
    from ..core.event_bus import EventBus


def _clean_song_title_for_prompt(stem: str) -> str:
    """Strip studio metadata (sample rate, duration, karaoke tags) from a project filename."""
    cleaned = re.sub(r"\(?\s*(?:44\s*\.?\s*1|48|96)\s*k?hz\s*\)?", " ", stem, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bkarum\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b\d+\s*'\s*\d*", " ", cleaned)
    cleaned = re.sub(r"[-_()]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned.isupper():
        cleaned = cleaned.title()
    return cleaned


def _foreign_title_priority(title: str) -> tuple[int, int, str]:
    """Rank shorter English/non-Italian titles higher for compact Whisper prompt priming."""
    low = title.lower()
    words = low.split()
    foreign_markers = (
        "k",
        "w",
        "y",
        "x",
        "j",
        "'s",
        "th",
        "sh",
        "the",
        "of",
        "you",
        "and",
        "my",
        "love",
        "time",
        "money",
        "hotel",
        "way",
        "night",
    )
    has_foreign = any(m in low for m in foreign_markers) or any(
        w.isalpha() and w[-1] not in "aeiou" for w in words
    )
    return (0 if has_foreign else 1, len(title), low)


def build_whisper_initial_prompt(config: AppConfig, max_chars: int = 165) -> str:
    """Build a short natural-language prompt so Whisper spells foreign song titles cleanly."""
    cmd_stems: list[str] = []
    project_sources: list[tuple[list[str], list[str]]] = []

    for prog in config.programs:
        if not prog.enabled:
            continue
        for fn in prog.functions:
            for cmd in fn.commands:
                stem = re.sub(r"\{[a-zA-Z0-9_]+\}", "", cmd).strip()
                stem = re.sub(r"\s+", " ", stem)
                if stem and stem.lower() not in {c.lower() for c in cmd_stems}:
                    cmd_stems.append(stem)
            for step in fn.steps:
                if step.kind == "open_project" and step.project_folders:
                    project_sources.append((step.project_folders, step.project_extensions))

    if config.cakewalk.workspace_folders:
        project_sources.append(
            (config.cakewalk.workspace_folders, config.cakewalk.project_extensions)
        )

    titles: list[str] = []
    seen_titles: set[str] = set()
    for folders, extensions in project_sources:
        exts = {
            e.lower() if e.startswith(".") else f".{e.lower()}" for e in extensions if e.strip()
        } or {".cwp", ".cwb", ".wrk", ".rpp"}
        for folder in folders:
            root = Path(folder.strip())
            if not root.exists() or not root.is_dir():
                continue
            try:
                for p in root.rglob("*"):
                    if not p.is_file() or p.suffix.lower() not in exts:
                        continue
                    low_name = p.stem.lower()
                    if low_name.startswith(("salva automaticamente copia di ", "auto-save copy of ")):
                        continue
                    title = _clean_song_title_for_prompt(p.stem)
                    if title and title.lower() not in seen_titles:
                        seen_titles.add(title.lower())
                        titles.append(title)
            except OSError:
                continue

    if not cmd_stems and not titles:
        return ""

    lead = f"Comandi: {cmd_stems[0]}" if cmd_stems else "Brani:"
    if not titles:
        return (lead + ".")[:max_chars]

    titles.sort(key=_foreign_title_priority)
    chosen: list[str] = []
    cur_len = len(lead) + 2
    for title in titles:
        extra = (2 if chosen else 1) + len(title)
        if cur_len + extra > max_chars:
            continue
        chosen.append(title)
        cur_len += extra
        if len(chosen) >= 6:
            break
    if not chosen:
        return (lead + ".")[:max_chars]
    return f"{lead} {', '.join(chosen)}."


def discover_local_models() -> dict[str, list[Path]]:
    """Scan standard local directories for installed offline Vosk / Whisper models."""
    search_roots = [
        get_app_base_dir() / "models",
        Path.cwd() / "models",
        get_default_config_dir() / "models",
    ]
    vosk_models: list[Path] = []
    whisper_models: list[Path] = []

    for root in search_roots:
        if not root.exists() or not root.is_dir():
            continue
        for entry in sorted(root.rglob("*")):
            if not entry.is_dir():
                continue
            if is_valid_vosk_model_dir(entry):
                if entry not in vosk_models:
                    vosk_models.append(entry)
            elif is_valid_whisper_model_dir(entry):
                if entry not in whisper_models:
                    whisper_models.append(entry)

    return {"vosk": vosk_models, "faster_whisper": whisper_models}


def build_sample_entries_from_config(config: AppConfig) -> list[SampleEntry]:
    """Collect all configured WAV sample files from system and dynamic program profiles."""
    entries: list[SampleEntry] = []
    for sf in config.panic.voice_samples:
        entries.append(SampleEntry(sample_file=sf, kind="panic", label="PANIC"))
    for sf in config.sleep_wake.wake_samples:
        entries.append(SampleEntry(sample_file=sf, kind="wake", label="Wake"))
    for sf in config.sleep_wake.sleep_samples:
        entries.append(SampleEntry(sample_file=sf, kind="sleep", label="Sleep"))
    for sf in config.popup_handler.voice_samples:
        entries.append(SampleEntry(sample_file=sf, kind="popup", label="Chiudi Pop-up"))
    for sf in config.stage_launcher.launch_all_samples:
        entries.append(SampleEntry(sample_file=sf, kind="launch_all", label="Avvia Tutto"))

    for prog in config.programs:
        if not prog.enabled:
            continue
        for sf in prog.open_samples:
            entries.append(
                SampleEntry(
                    sample_file=sf,
                    kind="program_open",
                    label=prog.primary_open_command or prog.name,
                    program_id=prog.id,
                )
            )
        for fn in prog.functions:
            is_parameterized = any("{" in c and "}" in c for c in fn.commands) or any(
                s.kind == "open_project" and s.use_spoken_param for s in fn.steps
            )
            if is_parameterized:
                continue
            for sf in fn.sample_files:
                entries.append(
                    SampleEntry(
                        sample_file=sf,
                        kind="program_func",
                        label=fn.primary_command or fn.id,
                        program_id=prog.id,
                        function_id=fn.id,
                    )
                )
    return entries


class STTManager:
    """Runs acoustic sample matching and/or offline Vosk/Whisper on a worker thread."""

    def __init__(
        self,
        config: AppConfig,
        bus: EventBus,
        on_result: Callable[[STTResult], None],
        on_sample_match: Callable[[SampleMatch], None] | None = None,
        is_sleeping_fn: Callable[[], bool] | None = None,
        preferred_program_fn: Callable[[], str] | None = None,
    ) -> None:
        self._config = config
        self._bus = bus
        self._on_result = on_result
        self._on_sample_match = on_sample_match
        self._is_sleeping_fn = is_sleeping_fn or (lambda: False)
        self._preferred_program_fn = preferred_program_fn or (lambda: "")

        self._lock = threading.RLock()
        self._queue: queue.Queue[VADChunkResult | None] = queue.Queue(maxsize=128)
        self._engine: BaseSTTEngine | None = None
        self._worker: threading.Thread | None = None
        self._running = False

        samples_root = (
            Path(config.stt.samples_dir)
            if config.stt.samples_dir.strip()
            else get_samples_dir()
        )
        self.sample_library = AcousticSampleLibrary(
            samples_dir=samples_root, sample_rate=config.audio.sample_rate
        )

        # Live sample recording state
        self._rec_lock = threading.Lock()
        self._rec_active = False
        self._rec_chunks: list[np.ndarray] = []
        self._rec_callback: Callable[[np.ndarray], None] | None = None

    @property
    def engine_name(self) -> str:
        with self._lock:
            return self._config.stt.engine

    @property
    def is_model_loaded(self) -> bool:
        with self._lock:
            if self._config.stt.engine in ("samples_only", "samples_hybrid"):
                return self.sample_library.count > 0 or (
                    self._engine is not None and self._engine.is_loaded
                )
            return self._engine is not None and self._engine.is_loaded

    @property
    def samples_dir(self) -> Path:
        return self.sample_library.samples_dir

    def reload_samples(self, config: AppConfig | None = None) -> int:
        if config is not None:
            self._config = config
        samples_root = (
            Path(self._config.stt.samples_dir)
            if self._config.stt.samples_dir.strip()
            else get_samples_dir()
        )
        self.sample_library.samples_dir = samples_root
        self.sample_library.sample_rate = self._config.audio.sample_rate
        return self.sample_library.rebuild(build_sample_entries_from_config(self._config))

    def update_config(self, config: AppConfig, reload_model: bool = True) -> tuple[bool, str]:
        self._config = config
        self.reload_samples(config)
        if reload_model:
            return self.load_engine()
        return True, "Configurazione riconoscimento aggiornata"

    def _create_stt_engine(self, engine_kind: str) -> BaseSTTEngine | None:
        stt_cfg = self._config.stt
        if engine_kind == "faster_whisper":
            model_target = stt_cfg.whisper_model_path_or_size.strip()
            if not model_target or not is_valid_whisper_model_dir(Path(model_target)):
                found = discover_local_models().get("faster_whisper", [])
                if found:
                    wanted = model_target.lower()
                    exact = [
                        p
                        for p in found
                        if wanted and (p.name.lower() == wanted or p.name.lower().endswith(f"-{wanted}"))
                    ]
                    model_target = str(exact[0] if exact else found[0])
            return FasterWhisperSTTEngine(
                model_path_or_size=model_target or "base",
                device=stt_cfg.whisper_device,
                compute_type=stt_cfg.whisper_compute_type,
                beam_size=stt_cfg.whisper_beam_size,
                language=self._config.general.language,
                sample_rate=self._config.audio.sample_rate,
                initial_prompt=build_whisper_initial_prompt(self._config),
            )
        if engine_kind == "vosk":
            model_path = stt_cfg.vosk_model_path
            if not model_path or not is_valid_vosk_model_dir(Path(model_path)):
                found = discover_local_models().get("vosk", [])
                if found:
                    model_path = str(found[0])
            return VoskSTTEngine(
                model_path=model_path,
                sample_rate=self._config.audio.sample_rate,
                use_partial=stt_cfg.vosk_use_partial_triggers,
            )
        return None

    def load_engine(self) -> tuple[bool, str]:
        with self._lock:
            if self._engine is not None:
                self._engine.unload()
                self._engine = None

            n_samples = self.reload_samples(self._config)
            mode = self._config.stt.engine

            if mode == "samples_only":
                msg = f"Campioni Audio attivi ({n_samples} campioni caricati)"
                self._bus.publish("stt_status", engine="samples_only", loaded=True, message=msg)
                return True, msg

            if mode == "samples_hybrid":
                fb_kind = self._config.stt.hybrid_fallback_engine
                fb_engine = self._create_stt_engine(fb_kind) if fb_kind != "none" else None
                fb_ok = False
                fb_msg = "nessun fallback STT"
                if fb_engine is not None:
                    fb_ok, fb_msg = fb_engine.load()
                    if fb_ok:
                        self._engine = fb_engine
                    else:
                        fb_engine.unload()
                msg = (
                    f"Ibrido: {n_samples} campioni audio + fallback {fb_kind} "
                    f"({'pronto' if fb_ok else 'non attivo: ' + fb_msg})"
                )
                ok = n_samples > 0 or fb_ok
                self._bus.publish(
                    "stt_status", engine="samples_hybrid", loaded=ok, message=msg
                )
                return ok, msg

            engine = self._create_stt_engine(mode)
            if engine is None:
                return False, f"Motore STT sconosciuto: {mode}"
            ok, msg = engine.load()
            self._engine = engine
            self._bus.publish(
                "stt_status", engine=engine.name, loaded=ok, message=msg
            )
            return ok, msg

    def start(self, load_models: bool = True) -> tuple[bool, str]:
        with self._lock:
            if self._running:
                return True, "Worker STT già attivo"
            self._running = True
            self._worker = threading.Thread(
                target=self._run_loop, name="ArtDirector-STT", daemon=True
            )
            self._worker.start()
        if not load_models:
            n_samples = self.reload_samples(self._config)
            return True, f"Worker STT avviato ({n_samples} campioni caricati)"
        return self.load_engine()

    def stop(self) -> None:
        with self._lock:
            self._running = False
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass
            worker = self._worker
            self._worker = None
        if worker and worker.is_alive():
            worker.join(timeout=1.5)
        with self._lock:
            if self._engine is not None:
                self._engine.unload()
                self._engine = None

    def flush(self) -> None:
        """Discard queued audio chunks and reset recognizer state (e.g. on Panic)."""
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        with self._lock:
            if self._engine is not None:
                self._engine.reset()

    def start_sample_recording(
        self, on_captured: Callable[[np.ndarray], None]
    ) -> None:
        """Capture the next spoken utterance directly from the live audio stream."""
        with self._rec_lock:
            self._rec_chunks.clear()
            self._rec_callback = on_captured
            self._rec_active = True

    def stop_sample_recording(self) -> np.ndarray | None:
        """Finalize recording manually and return captured float32 audio (or None)."""
        with self._rec_lock:
            self._rec_active = False
            chunks = list(self._rec_chunks)
            self._rec_chunks.clear()
            self._rec_callback = None
        if not chunks:
            return None
        merged = np.concatenate(chunks)
        trimmed = trim_silence(merged, sample_rate=self._config.audio.sample_rate)
        return trimmed if trimmed.size > 0 else merged

    def submit_chunk(self, chunk: VADChunkResult) -> None:
        if not self._running:
            return
        with self._rec_lock:
            if self._rec_active:
                if chunk.gate_open:
                    self._rec_chunks.append(chunk.processed_float32.copy())
                if chunk.completed_utterance is not None and chunk.completed_utterance.size > 0:
                    cb = self._rec_callback
                    self._rec_active = False
                    self._rec_chunks.clear()
                    self._rec_callback = None
                    if cb is not None:
                        cb(chunk.completed_utterance.copy())
                return

        try:
            self._queue.put_nowait(chunk)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(chunk)
            except queue.Empty:
                pass

    def _run_loop(self) -> None:
        while self._running:
            try:
                chunk = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            if chunk is None:
                break

            mode = self._config.stt.engine
            with self._lock:
                engine = self._engine

            if mode in ("samples_only", "samples_hybrid"):
                if chunk.completed_utterance is None:
                    continue
                if self.sample_library.count > 0:
                    allowed = {"wake", "panic"} if self._is_sleeping_fn() else None
                    match = self.sample_library.match(
                        chunk.completed_utterance,
                        threshold=self._config.stt.sample_match_threshold,
                        allowed_kinds=allowed,
                        preferred_program_id=self._preferred_program_fn(),
                    )
                    if match is not None:
                        self._bus.publish(
                            "stt_transcript",
                            text=f"{match.entry.label} ({match.score * 100:.0f}%)",
                            is_final=True,
                            latency_ms=round(match.latency_ms, 1),
                            engine="campione",
                        )
                        if self._on_sample_match is not None:
                            self._on_sample_match(match)
                        continue

                if mode == "samples_hybrid" and engine is not None and engine.is_loaded:
                    if isinstance(engine, VoskSTTEngine):
                        res = engine.transcribe_utterance(chunk.completed_utterance)
                        results = [res] if res is not None else []
                    else:
                        results = engine.process_chunk(chunk)
                    for res in results:
                        if res and res.text:
                            self._bus.publish(
                                "stt_transcript",
                                text=res.text,
                                is_final=res.is_final,
                                latency_ms=round(res.latency_ms, 1),
                                engine=res.engine,
                            )
                            self._on_result(res)
                continue

            if engine is None or not engine.is_loaded:
                continue
            results = engine.process_chunk(chunk)
            for res in results:
                if res.text:
                    self._bus.publish(
                        "stt_transcript",
                        text=res.text,
                        is_final=res.is_final,
                        latency_ms=round(res.latency_ms, 1),
                        engine=res.engine,
                    )
                    self._on_result(res)
