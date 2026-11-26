"""Tests for QLC+ OSC, Art-Net ArtDmx, and .qxw Virtual Console XML importer."""

from __future__ import annotations

import pytest

from art_director.config import AppConfig
from art_director.core.event_bus import EventBus
from art_director.core.state import CancellationToken
from art_director.os_layer import create_os_bridge
from art_director.targets import (
    QLCPlusTarget,
    TargetContext,
    build_artnet_dmx_packet,
    parse_qlc_qxw_buttons,
)


def _ctx(cfg: AppConfig) -> TargetContext:
    return TargetContext(
        config=cfg,
        os_bridge=create_os_bridge(),
        cancel_token=CancellationToken(),
        bus=EventBus(),
    )


def test_artnet_packet_structure():
    buf = bytearray(512)
    buf[0] = 255
    buf[9] = 128
    pkt = build_artnet_dmx_packet(universe=2, dmx_channels=buf, sequence=7)
    assert pkt[:8] == b"Art-Net\x00"
    assert pkt[8:10] == b"\x00\x50"  # OpCode 0x5000 LE
    assert pkt[10:12] == b"\x00\x0e"  # ProtVer 14 BE
    assert pkt[12] == 7
    assert pkt[14] == 2
    assert len(pkt) == 18 + 512
    assert pkt[18] == 255
    assert pkt[18 + 9] == 128


def test_qxw_parser_discovers_unique_virtual_console_buttons(tmp_path):
    qxw = tmp_path / "show.qxw"
    qxw.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<Workspace>
  <VirtualConsole>
    <Frame>
      <Button Caption="Strobo Rapido" ID="12">
        <Input Universe="0" Channel="25"/>
      </Button>
      <Button Caption="Acustica Calda" ID="15"/>
    </Frame>
  </VirtualConsole>
</Workspace>
""",
        encoding="utf-8",
    )
    buttons = parse_qlc_qxw_buttons(qxw)
    assert "strobo rapido" in buttons
    assert buttons["strobo rapido"]["widget_id"] == "12"
    assert buttons["strobo rapido"]["artnet_channel"] == 25
    assert "acustica calda" in buttons


def test_qlc_buttons_grandmaster_and_blackout():
    osc_sent: list[tuple[str, int, str, float]] = []
    art_sent: list[tuple[str, int, bytes]] = []
    target = QLCPlusTarget(
        osc_sender=lambda h, p, a, v: osc_sent.append((h, p, a, v)),
        artnet_sender=lambda h, p, pkt: art_sent.append((h, p, pkt)),
    )
    cfg = AppConfig()
    cfg.qlc.buttons["strobo"]["artnet_channel"] = 10
    ctx = _ctx(cfg)

    r1 = target.handle("attiva strobo", ctx)
    assert r1.handled
    assert osc_sent[-1][2:] == ("/vc/strobo", 1.0)
    assert art_sent[-1][2][18 + 9] == 255

    r2 = target.handle("fader generale al 60 percento", ctx)
    assert r2.handled
    assert osc_sent[-1][2] == "/grandmaster"
    assert osc_sent[-1][3] == pytest.approx(0.6)

    r3 = target.handle("blackout", ctx)
    assert r3.handled
    assert osc_sent[-1][2:] == ("/blackout", 1.0)
    # Art-Net buffer zeroed on blackout
    assert all(b == 0 for b in art_sent[-1][2][18:])

    assert target.panic(ctx)
