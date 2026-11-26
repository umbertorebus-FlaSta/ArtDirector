"""Tests for VirtualDJ target (sidelist load, play/pause, mix, gain, EQ, cue, stop)."""

from __future__ import annotations

import pytest

from art_director.config import AppConfig
from art_director.core.event_bus import EventBus
from art_director.core.state import CancellationToken
from art_director.targets import TargetContext, VirtualDJTarget
from test_targets_cakewalk import FakeMidi, FakeOSBridge


def test_virtualdj_all_deck_controls():
    cfg = AppConfig()
    cfg.virtualdj.transport_mode = "osc"
    osc_sent: list[tuple[str, int, str, float]] = []
    midi = FakeMidi()
    os_b = FakeOSBridge()
    target = VirtualDJTarget(
        midi=midi,  # type: ignore[arg-type]
        osc_sender=lambda h, p, a, v: osc_sent.append((h, p, a, v)),
    )
    ctx = TargetContext(cfg, os_b, CancellationToken(), EventBus())

    assert target.handle("carica da lista su deck 2", ctx).handled
    assert osc_sent[-1][2:] == ("/vdj/deck/2/load_sidelist", 1.0)

    # Active deck is now 2 -> next cue targets Deck 2
    assert target.handle("vai al prossimo cue", ctx).handled
    assert osc_sent[-1][2:] == ("/vdj/deck/2/goto_cue", 1.0)

    assert target.handle("deck 1 gain 80 percento", ctx).handled
    assert osc_sent[-1][2] == "/vdj/deck/1/gain"
    assert osc_sent[-1][3] == pytest.approx(0.8)

    assert target.handle("deck 2 bassi kill", ctx).handled
    assert osc_sent[-1][2:] == ("/vdj/deck/2/eq_low", 0.0)

    assert target.handle("mix verso deck 2", ctx).handled
    assert osc_sent[-1][2:] == ("/vdj/crossfader", 1.0)

    assert target.handle("play deck 1", ctx).handled
    assert osc_sent[-1][2:] == ("/vdj/deck/1/play_pause", 1.0)

    assert target.handle("stop deck 1", ctx).handled
    assert osc_sent[-1][2:] == ("/vdj/deck/1/stop", 1.0)
    assert target.handle("stop deck 2", ctx).handled
    assert osc_sent[-1][2:] == ("/vdj/deck/2/stop", 1.0)

    assert target.panic(ctx)
