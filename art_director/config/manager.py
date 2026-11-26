"""Thread-safe configuration persistence for Art Director."""

from __future__ import annotations

import copy
import json
import os
import re
import sys
import tempfile
import threading
import zipfile
from pathlib import Path
from typing import Any, Callable

from .schema import AppConfig


def get_app_base_dir() -> Path:
    """Return the directory of the frozen executable or project root."""
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        # On macOS .app bundle (<App>.app/Contents/MacOS/<exe>), keep bundle parent as portable base
        if sys.platform == "darwin" and exe_dir.name == "MacOS" and exe_dir.parent.name == "Contents":
            return exe_dir.parent.parent.parent
        return exe_dir
    return Path(__file__).resolve().parents[2]


def get_resource_path(relative_path: str) -> Path:
    """Resolve bundled data/asset paths under PyInstaller (_MEIPASS) or source tree."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = Path(meipass) / relative_path
        if candidate.exists():
            return candidate
    return Path(__file__).resolve().parents[1] / relative_path


def is_portable_mode() -> bool:
    """True when running with --portable, portable.flag, or local config.json beside executable."""
    if "--portable" in sys.argv:
        return True
    base = get_app_base_dir()
    return (base / "portable.flag").exists() or (
        getattr(sys, "frozen", False) and (base / "config.json").exists()
    )


def get_default_config_dir() -> Path:
    """Return portable executable folder (if enabled) or OS user config directory."""
    if is_portable_mode():
        return get_app_base_dir()
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "ArtDirector"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ArtDirector"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base_dir = Path(xdg) if xdg else Path.home() / ".config"
    return base_dir / "art-director"


def get_default_config_path() -> Path:
    return get_default_config_dir() / "config.json"


def get_samples_dir() -> Path:
    """Return the directory storing recorded WAV voice command samples."""
    return get_default_config_dir() / "campioni"


def get_configs_dir(base_dir: Path | None = None) -> Path:
    """Return the folder storing saved multi-program configuration presets."""
    root = Path(base_dir) if base_dir is not None else get_default_config_dir()
    return root / "configurazioni"


def sanitize_profile_filename(name: str, ext: str = ".json") -> str:
    """Turn a human setup title into a safe cross-platform filename."""
    clean_ext = ext if ext.startswith(".") else f".{ext}"
    slug = re.sub(r'[\\/:*?"<>|]+', "_", name.strip())
    slug = re.sub(r"\s+", "_", slug).strip("._ ")
    if not slug:
        slug = "configurazione"
    return f"{slug[:80]}{clean_ext.lower()}"


def collect_referenced_samples(config: AppConfig) -> list[str]:
    """Return unique WAV sample filenames referenced anywhere in config."""
    seen: set[str] = set()
    ordered: list[str] = []

    def _add_many(items: list[str]) -> None:
        for item in items:
            s = item.strip()
            if s and s not in seen:
                seen.add(s)
                ordered.append(s)

    _add_many(config.panic.voice_samples)
    _add_many(config.sleep_wake.wake_samples)
    _add_many(config.sleep_wake.sleep_samples)
    _add_many(config.popup_handler.voice_samples)
    _add_many(config.stage_launcher.launch_all_samples)
    for prog in config.programs:
        _add_many(prog.open_samples)
        for fn in prog.functions:
            _add_many(fn.sample_files)
    return ordered


def build_subset_config(
    config: AppConfig,
    selected_program_ids: set[str] | None = None,
    profile_name: str = "",
) -> AppConfig:
    """Clone config optionally filtering down to only the selected dynamic programs."""
    cloned = copy.deepcopy(config)
    if selected_program_ids is not None:
        cloned.programs = [p for p in cloned.programs if p.id in selected_program_ids]
    if profile_name.strip():
        cloned.general.active_profile_name = profile_name.strip()
    return cloned


def merge_loaded_config(
    loaded: AppConfig,
    current: AppConfig,
    keep_audio_and_stt: bool = False,
    profile_name: str = "",
) -> AppConfig:
    """Prepare a loaded config for activation, optionally preserving local mic/audio/STT settings."""
    merged = copy.deepcopy(loaded)
    if keep_audio_and_stt:
        merged.audio = copy.deepcopy(current.audio)
        merged.stt = copy.deepcopy(current.stt)
        merged.general.minimize_on_close = current.general.minimize_on_close
        merged.general.start_minimized_to_tray = current.general.start_minimized_to_tray
        merged.general.autostart_at_os_boot = current.general.autostart_at_os_boot
        merged.general.autostart_in_background = current.general.autostart_in_background
        merged.general.confirm_quit = current.general.confirm_quit
    if profile_name.strip():
        merged.general.active_profile_name = profile_name.strip()
    return merged


def _atomic_write_bytes(dest_path: Path, write_fn: Callable[[Path], None]) -> None:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=".cfg_", suffix=dest_path.suffix or ".tmp", dir=str(dest_path.parent)
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        write_fn(tmp_path)
        os.replace(tmp_path, dest_path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def export_config_file(
    config: AppConfig,
    dest_path: str | Path,
    samples_dir: Path | None = None,
) -> tuple[Path, int]:
    """Save config to standalone .json or portable .zip (with referenced .wav samples)."""
    target = Path(dest_path)
    if target.suffix.lower() not in (".json", ".zip"):
        target = target.with_suffix(".json")

    payload = json.dumps(config.to_dict(), indent=2, ensure_ascii=False)
    sample_root = Path(samples_dir) if samples_dir is not None else get_samples_dir()

    if target.suffix.lower() == ".zip":
        exported_wavs = 0

        def _write_zip(tmp: Path) -> None:
            nonlocal exported_wavs
            exported_wavs = 0
            with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("config.json", payload.encode("utf-8"))
                for sf in collect_referenced_samples(config):
                    src = Path(sf) if Path(sf).is_absolute() else sample_root / sf
                    if src.is_file():
                        zf.write(src, arcname=f"campioni/{src.name}")
                        exported_wavs += 1

        _atomic_write_bytes(target, _write_zip)
        return target, exported_wavs

    _atomic_write_bytes(
        target, lambda tmp: tmp.write_text(payload, encoding="utf-8")
    )
    return target, len(collect_referenced_samples(config))


def _parse_config_payload(raw_bytes: bytes) -> AppConfig:
    try:
        raw = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"JSON non valido: {exc}") from exc
    if not isinstance(raw, dict) or not any(
        k in raw for k in ("programs", "general", "audio", "stt", "version")
    ):
        raise ValueError("Il file non contiene una configurazione Art Director valida.")
    return AppConfig.from_dict(raw)


def inspect_config_file(src_path: str | Path) -> tuple[AppConfig, list[str]]:
    """Read and validate a .json or .zip configuration without modifying disk state."""
    path = Path(src_path)
    if not path.is_file():
        raise FileNotFoundError(f"File non trovato: {path}")

    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path, "r") as zf:
            names = zf.namelist()
            cfg_member = next(
                (n for n in names if Path(n).name == "config.json" and not n.endswith("/")),
                None,
            )
            if cfg_member is None:
                raise ValueError("Archivio .zip privo di config.json.")
            cfg = _parse_config_payload(zf.read(cfg_member))
            wavs = [
                Path(n).name
                for n in names
                if not n.endswith("/") and n.lower().endswith(".wav") and Path(n).name
            ]
            return cfg, wavs

    cfg = _parse_config_payload(path.read_bytes())
    return cfg, []


def import_config_file(
    src_path: str | Path,
    samples_dir: Path | None = None,
    overwrite_samples: bool = False,
) -> tuple[AppConfig, int]:
    """Load a .json or .zip configuration, safely extracting any bundled .wav samples."""
    path = Path(src_path)
    cfg, _ = inspect_config_file(path)
    extracted = 0
    if path.suffix.lower() == ".zip":
        dst_root = Path(samples_dir) if samples_dir is not None else get_samples_dir()
        dst_root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "r") as zf:
            for member in zf.infolist():
                if member.is_dir() or not member.filename.lower().endswith(".wav"):
                    continue
                safe_name = Path(member.filename).name
                if not safe_name or safe_name in (".", ".."):
                    continue
                target_wav = dst_root / safe_name
                if target_wav.exists() and not overwrite_samples:
                    continue
                data = zf.read(member.filename)
                _atomic_write_bytes(target_wav, lambda tmp, b=data: tmp.write_bytes(b))
                extracted += 1
    return cfg, extracted


def list_saved_configs(configs_dir: Path | None = None) -> list[dict[str, Any]]:
    """List saved .json and .zip configuration presets sorted alphabetically."""
    folder = Path(configs_dir) if configs_dir is not None else get_configs_dir()
    if not folder.exists() or not folder.is_dir():
        return []
    items: list[dict[str, Any]] = []
    candidates = sorted(
        (
            p
            for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in (".json", ".zip")
        ),
        key=lambda p: p.stem.lower(),
    )
    for path in candidates:
        try:
            cfg, wavs = inspect_config_file(path)
        except Exception:
            continue
        display = cfg.general.active_profile_name.strip() or path.stem.replace("_", " ")
        fn_count = sum(len(p.functions) for p in cfg.programs)
        items.append(
            {
                "name": display,
                "path": path,
                "is_zip": path.suffix.lower() == ".zip",
                "programs": [p.name for p in cfg.programs],
                "program_ids": [p.id for p in cfg.programs],
                "function_count": fn_count,
                "sample_count": len(wavs) if wavs else len(collect_referenced_samples(cfg)),
                "mtime": path.stat().st_mtime,
            }
        )
    return items


class ConfigManager:
    """Loads, validates, and atomically persists AppConfig."""

    def __init__(self, config_path: str | Path | None = None) -> None:
        self.path = Path(config_path) if config_path else get_default_config_path()
        self._lock = threading.RLock()
        self._listeners: list[Callable[[AppConfig], None]] = []
        self._config = self.load()

    @property
    def config(self) -> AppConfig:
        with self._lock:
            return self._config

    def on_change(self, callback: Callable[[AppConfig], None]) -> None:
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def load(self) -> AppConfig:
        with self._lock:
            if not self.path.exists():
                cfg = AppConfig()
                self._config = cfg
                return cfg
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                cfg = AppConfig.from_dict(raw)
            except Exception:
                # Preserve corrupt file as backup and return clean defaults.
                backup = self.path.with_suffix(".corrupt.json")
                try:
                    self.path.replace(backup)
                except OSError:
                    pass
                cfg = AppConfig()
            self._config = cfg
            return cfg

    def save(self, config: AppConfig | None = None) -> AppConfig:
        with self._lock:
            if config is not None:
                self._config = config
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(self._config.to_dict(), indent=2, ensure_ascii=False)
            fd, tmp_name = tempfile.mkstemp(
                prefix=".config_", suffix=".tmp", dir=str(self.path.parent)
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                os.replace(tmp_name, self.path)
            except Exception:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
            listeners = list(self._listeners)
        for cb in listeners:
            cb(self._config)
        return self._config

    def update(self, mutator: Callable[[AppConfig], None]) -> AppConfig:
        with self._lock:
            mutator(self._config)
            return self.save(self._config)
