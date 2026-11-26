"""Tests for configuration schema and atomic persistence."""

from __future__ import annotations

from art_director.config import (
    AppConfig,
    ConfigManager,
    StageAppEntry,
    get_default_config_dir,
    get_resource_path,
    is_portable_mode,
)
from art_director.config import manager as cfg_mod
from art_director.os_layer.installer import enable_portable_mode


def test_config_roundtrip_preserves_dynamic_prefixes_and_apps(tmp_path):
    cfg_path = tmp_path / "config.json"
    mgr = ConfigManager(cfg_path)
    cfg = mgr.config

    # Replace default prefixes completely to prove zero hardcoding
    cfg.prefix_routes["xr18"].prefixes = ["alfa", "console live"]
    cfg.sleep_wake.wake_emoji = "👍"
    cfg.sleep_wake.sleep_emoji = "👋"
    cfg.stage_launcher.launch_apps_on_art_director_start = True
    cfg.stage_launcher.apps.append(
        StageAppEntry(
            id="obs",
            name="OBS Studio",
            aliases=["obs", "video"],
            executable="/usr/bin/obs",
            delay_after_sec=2.0,
            launch_on_startup=True,
        )
    )
    mgr.save(cfg)

    mgr2 = ConfigManager(cfg_path)
    loaded = mgr2.config
    assert loaded.prefix_routes["xr18"].prefixes == ["alfa", "console live"]
    assert loaded.stage_launcher.launch_apps_on_art_director_start is True
    assert any(a.id == "obs" and a.executable == "/usr/bin/obs" for a in loaded.stage_launcher.apps)


def test_corrupt_config_creates_backup_and_falls_back(tmp_path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text("{not valid json", encoding="utf-8")
    mgr = ConfigManager(cfg_path)
    assert isinstance(mgr.config, AppConfig)
    assert (tmp_path / "config.corrupt.json").exists()


def test_portable_mode_and_bundled_icons(tmp_path, monkeypatch):
    monkeypatch.setattr(cfg_mod, "get_app_base_dir", lambda: tmp_path)
    monkeypatch.setattr("art_director.os_layer.installer.get_app_base_dir", lambda: tmp_path)

    assert is_portable_mode() is False
    ok, _msg = enable_portable_mode(AppConfig())
    assert ok is True
    assert (tmp_path / "portable.flag").exists()
    assert (tmp_path / "config.json").exists()
    assert (tmp_path / "models").is_dir()
    assert is_portable_mode() is True
    assert get_default_config_dir() == tmp_path
    assert get_resource_path("assets/art_director.ico").exists()
    assert get_resource_path("assets/art_director.png").exists()
