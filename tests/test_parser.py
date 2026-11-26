"""Tests for dynamic prefix routing, spoken number conversion, and sleep gating."""

from __future__ import annotations

from art_director.config import AppConfig
from art_director.core.parser import CommandRouter, extract_numbers, replace_spoken_numbers


def test_spoken_numbers_italian_and_signed():
    assert replace_spoken_numbers("alza di piu tre db") == "alza di +3 db"
    assert replace_spoken_numbers("soglia meno venticinque db") == "soglia -25 db"
    assert extract_numbers("canale tre al settanta cinque percento") == [3.0, 75.0]


def test_dynamic_prefix_routing_customizable():
    cfg = AppConfig()
    # Replace prefixes with completely arbitrary custom words
    cfg.prefix_routes["xr18"].prefixes = ["mario", "banco audio"]
    cfg.prefix_routes["cakewalk"].prefixes = ["regia studio"]
    cfg.prefix_routes["qlc"].prefixes = ["fari"]

    router = CommandRouter(cfg)

    # Old non-definitive defaults must NOT match once replaced
    old = router.route("uehberi canale 1 muta")
    assert old.kind == "unmatched"

    # New custom prefixes must match cleanly
    r1 = router.route("Mario canale 1 volume 75")
    assert r1.kind == "target"
    assert r1.target_id == "xr18"
    assert r1.remainder == "canale 1 volume 75"

    r2 = router.route("Regia Studio apri progetto concerto")
    assert r2.kind == "target"
    assert r2.target_id == "cakewalk"
    assert r2.remainder == "apri progetto concerto"

    # Fuzzy match for slight STT variation
    r3 = router.route("banco audioo master 80")
    assert r3.kind == "target"
    assert r3.target_id == "xr18"


def test_sleep_mode_blocks_targets_but_allows_wake_and_panic():
    cfg = AppConfig()
    router = CommandRouter(cfg)

    blocked = router.route("UehBerì muta canale 1", is_sleeping=True)
    assert blocked.kind == "unmatched"

    wake = router.route("Sveglia", is_sleeping=True)
    assert wake.kind == "wake"

    panic = router.route("PANIC", is_sleeping=True)
    assert panic.kind == "panic"


def test_popup_and_launcher_detection():
    cfg = AppConfig()
    router = CommandRouter(cfg)

    pop = router.route("chiudi avviso", is_sleeping=False)
    assert pop.kind == "popup"

    launch = router.route("avvia tutto", is_sleeping=False)
    assert launch.kind == "launch_apps"

    launch_one = router.route("apri cakewalk", is_sleeping=False)
    assert launch_one.kind == "launch_apps"
