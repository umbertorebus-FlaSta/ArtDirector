"""Tests for Behringer XR18 / X-Air Edit OSC UDP 10024 target."""

from __future__ import annotations

import pytest

from art_director.config import AppConfig
from art_director.core.event_bus import EventBus
from art_director.core.state import CancellationToken
from art_director.os_layer import create_os_bridge
from art_director.targets import BehringerXR18Target, TargetContext, db_to_fader, fader_to_db


def _make_ctx(cfg: AppConfig) -> TargetContext:
    return TargetContext(
        config=cfg,
        os_bridge=create_os_bridge(),
        cancel_token=CancellationToken(),
        bus=EventBus(),
    )


def test_xr18_fader_db_conversion():
    assert db_to_fader(0.0) == pytest.approx(0.75)
    assert db_to_fader(10.0) == pytest.approx(1.0)
    assert db_to_fader(-10.0) == pytest.approx(0.5)
    assert fader_to_db(0.75) == pytest.approx(0.0)


def test_xr18_channels_processors_sends_master_scenes():
    sent: list[tuple[str, int, str, object]] = []
    target = BehringerXR18Target(osc_sender=lambda h, p, a, v: sent.append((h, p, a, v)))
    cfg = AppConfig()
    ctx = _make_ctx(cfg)

    # Channel fader by alias ("voce" -> 1)
    r = target.handle("voce fader a 0 db", ctx)
    assert r.handled
    assert sent[-1][1] == 10024
    assert sent[-1][2] == "/ch/01/mix/fader"
    assert sent[-1][3] == pytest.approx(0.75)

    # Mute & Unmute
    assert target.handle("muta canale 3", ctx).handled
    assert sent[-1][2:] == ("/ch/03/mix/on", 0)
    assert target.handle("smuta canale 3", ctx).handled
    assert sent[-1][2:] == ("/ch/03/mix/on", 1)

    # Preamp Gain
    assert target.handle("canale 2 gain +24 db", ctx).handled
    assert sent[-1][2] == "/headamp/02/gain"
    assert sent[-1][3] == pytest.approx((24.0 + 12.0) / 72.0)

    # Noise Gate, Compressor, EQ, HPF
    assert target.handle("canale 1 gate soglia -40 db", ctx).handled
    assert sent[-1][2] == "/ch/01/gate/thr"
    assert target.handle("canale 1 compressore on", ctx).handled
    assert sent[-1][2:] == ("/ch/01/dyn/on", 1)
    assert target.handle("canale 1 eq banda 2 piu 4 db", ctx).handled
    assert sent[-1][2] == "/ch/01/eq/2/g"
    assert target.handle("canale 1 hpf 100 hz", ctx).handled
    assert sent[-1][2] == "/ch/01/preamp/hpf"

    # Sends (Mandata voce -> FX1 / bus 7)
    assert target.handle("manda voce su riverbero al 50 percento", ctx).handled
    assert sent[-1][2] == "/ch/01/mix/07/level"
    assert sent[-1][3] == pytest.approx(0.5)

    # Master LR & Snapshot
    assert target.handle("master volume 80 percento", ctx).handled
    assert sent[-1][2] == "/lr/mix/fader"
    assert sent[-1][3] == pytest.approx(0.8)

    assert target.handle("richiama scena acustica", ctx).handled
    assert sent[-1][2:] == ("/-snap/load", 2)

    # Panic mutes LR
    panic_logs = target.panic(ctx)
    assert panic_logs
    assert sent[-1][2:] == ("/lr/mix/on", 0)


def test_xr18_relative_channel_number_strip_and_live_query():
    sent: list[tuple[str, int, str, object]] = []
    live_state = {"/ch/07/mix/fader": 0.50}  # -10.0 dB on hardware mixer

    target = BehringerXR18Target(
        osc_sender=lambda h, p, a, v: (sent.append((h, p, a, v)), live_state.__setitem__(a, v)),
        osc_querier=lambda _h, _p, a: live_state.get(a),
    )
    cfg = AppConfig()
    cfg.xr18.step_db = 3.0
    ctx = _make_ctx(cfg)

    # "alza canale 7" must NOT treat '7' as +7%; must add +3.0 dB to live -10.0 dB -> -7.0 dB (0.5375)
    r1 = target.handle("alza canale 7", ctx)
    assert r1.handled
    assert sent[-1][2] == "/ch/07/mix/fader"
    assert sent[-1][3] == pytest.approx(db_to_fader(-7.0), abs=1e-4)

    # Subsequent raise uses updated value (-7 dB + 2 dB = -5 dB)
    r2 = target.handle("alza canale 7 di 2 db", ctx)
    assert r2.handled
    assert sent[-1][3] == pytest.approx(db_to_fader(-5.0), abs=1e-4)


def test_xr18_channel_input_controls_and_tab_keyboard_navigation():
    sent: list[tuple[str, int, str, object]] = []
    live_state: dict[str, float | int] = {
        "/ch/03/preamp/invert": 0,
        "/ch/01/preamp/rtntrim": 0.5,  # 0.0 dB
    }

    target = BehringerXR18Target(
        osc_sender=lambda h, p, a, v: (sent.append((h, p, a, v)), live_state.__setitem__(a, v)),
        osc_querier=lambda _h, _p, a: live_state.get(a),
    )
    cfg = AppConfig()
    ctx = _make_ctx(cfg)

    # Channel Input OSC controls
    assert target.handle("canale 1 phantom on", ctx).handled
    assert sent[-1][2:] == ("/headamp/01/phantom", 1)
    assert target.handle("canale 1 phantom off", ctx).handled
    assert sent[-1][2:] == ("/headamp/01/phantom", 0)

    # Phase invert toggles cleanly via live query (0 -> 1 -> 0)
    assert target.handle("inverti fase canale 3", ctx).handled
    assert sent[-1][2:] == ("/ch/03/preamp/invert", 1)
    assert target.handle("inverti fase canale 3", ctx).handled
    assert sent[-1][2:] == ("/ch/03/preamp/invert", 0)

    # USB switch & USB digital trim (-18..+18 dB)
    assert target.handle("canale 1 sorgente usb", ctx).handled
    assert sent[-1][2:] == ("/ch/01/preamp/rtnsw", 1)
    assert target.handle("canale 1 sorgente analogica", ctx).handled
    assert sent[-1][2:] == ("/ch/01/preamp/rtnsw", 0)

    assert target.handle("canale 1 trim -6 db", ctx).handled
    assert sent[-1][2] == "/ch/01/preamp/rtntrim"
    assert sent[-1][3] == pytest.approx((-6.0 + 18.0) / 36.0)
    assert target.handle("alza trim canale 1 di 2 db", ctx).handled
    assert sent[-1][3] == pytest.approx((-4.0 + 18.0) / 36.0)

    # Stereo Channel Link (snaps to odd-even pair 3-4)
    assert target.handle("collega canali 3 4", ctx).handled
    assert sent[-1][2:] == ("/config/chlink/3-4", 1)
    assert target.handle("separa canali 3 4", ctx).handled
    assert sent[-1][2:] == ("/config/chlink/3-4", 0)

    # Keyboard tab + channel + utility window navigation using mock OSBridge
    class _NavBridge:
        def __init__(self) -> None:
            self.focused: list[list[str]] = []
            self.hotkeys: list[str] = []

        def focus_window(self, patterns: list[str]) -> bool:
            self.focused.append(list(patterns))
            return True

        def send_hotkey(self, hotkey: str) -> bool:
            self.hotkeys.append(hotkey)
            return True

    nav = _NavBridge()
    nav_ctx = TargetContext(
        config=cfg,
        os_bridge=nav,  # type: ignore[arg-type]
        cancel_token=CancellationToken(),
        bus=EventBus(),
    )

    # Jump to Channel 3 -> Input tab (Tab 2): <tab>, <home>, 2x <right>, 2x <shift>+<right>
    r_tab = target.handle("apri input canale 3", nav_ctx)
    assert r_tab.handled
    assert nav.hotkeys == ["<tab>", "<home>", "<right>", "<right>", "<shift>+<right>", "<shift>+<right>"]

    # Pure tab jump: Gate (Tab 3)
    nav.hotkeys.clear()
    assert target.handle("tab gate", nav_ctx).handled
    assert nav.hotkeys == ["<tab>", "<shift>+<right>", "<shift>+<right>", "<shift>+<right>"]

    # Verified utility windows
    nav.hotkeys.clear()
    assert target.handle("finestra rta", nav_ctx).handled
    assert nav.hotkeys == ["<shift>+<f6>"]
    nav.hotkeys.clear()
    assert target.handle("apri buses", nav_ctx).handled
    assert nav.hotkeys == ["<insert>"]


def test_xr18_full_eq_modes_reset_q_freq_gain_and_rta():
    sent: list[tuple[str, int, str, object]] = []
    live_state: dict[str, float | int] = {
        "/ch/01/eq/on": 1,
        "/ch/01/eq/2/g": 0.5,  # 0.0 dB
        "/ch/01/eq/2/f": 0.465,  # 496.6 Hz
        "/ch/01/eq/2/q": 33.0 / 71.0,  # Q ~2.0
    }

    target = BehringerXR18Target(
        osc_sender=lambda h, p, a, v: (sent.append((h, p, a, v)), live_state.__setitem__(a, v)),
        osc_querier=lambda _h, _p, a: live_state.get(a),
    )
    cfg = AppConfig()
    ctx = _make_ctx(cfg)

    # EQ Toggle & explicit On/Off
    assert target.handle("canale 1 eq toggle", ctx).handled
    assert sent[-1][2:] == ("/ch/01/eq/on", 0)
    assert target.handle("canale 1 eq on", ctx).handled
    assert sent[-1][2:] == ("/ch/01/eq/on", 1)

    # Mode per band (LCut=0, LShv=1, PEQ=2, VEQ=3, HShv=4, HCut=5)
    assert target.handle("canale 1 eq banda 1 mode lcut", ctx).handled
    assert sent[-1][2:] == ("/ch/01/eq/1/type", 0)
    assert target.handle("canale 1 eq hi mid mode veq", ctx).handled
    assert sent[-1][2:] == ("/ch/01/eq/3/type", 3)
    assert target.handle("canale 1 eq alti mode high cut", ctx).handled
    assert sent[-1][2:] == ("/ch/01/eq/4/type", 5)

    # Freq with '1k97', kHz decimals, and live relative nudge
    assert target.handle("canale 1 eq himid 1k97", ctx).handled
    assert sent[-1][2] == "/ch/01/eq/3/f"
    assert sent[-1][3] == pytest.approx(0.6645, abs=0.002)

    assert target.handle("canale 1 eq banda 3 2.5 khz", ctx).handled
    assert sent[-1][2] == "/ch/01/eq/3/f"
    assert sent[-1][3] > 0.68

    assert target.handle("alza freq eq lomid canale 1", ctx).handled
    assert sent[-1][2] == "/ch/01/eq/2/f"
    assert sent[-1][3] == pytest.approx(0.490, abs=1e-4)

    # Q factor (72-step curve matching XR18 hardware 33/71 for Q=2.0) + narrower/wider
    assert target.handle("canale 1 eq banda 2 q 2.0", ctx).handled
    assert sent[-1][2] == "/ch/01/eq/2/q"
    assert sent[-1][3] == pytest.approx(33.0 / 71.0, abs=0.02)

    assert target.handle("stringi q eq banda 2 canale 1", ctx).handled
    assert sent[-1][2] == "/ch/01/eq/2/q"
    assert sent[-1][3] < 33.0 / 71.0  # higher Q = lower normalized float

    # Gain live relative up/down and exact negative decimal
    assert target.handle("alza eq lomid canale 1 di 2 db", ctx).handled
    assert sent[-1][2] == "/ch/01/eq/2/g"
    assert sent[-1][3] == pytest.approx((2.0 + 15.0) / 30.0)

    assert target.handle("abbassa eq lomid canale 1 di 4 db", ctx).handled
    assert sent[-1][3] == pytest.approx((-2.0 + 15.0) / 30.0)

    assert target.handle("canale 1 eq low -5.5 db", ctx).handled
    assert sent[-1][2] == "/ch/01/eq/1/g"
    assert sent[-1][3] == pytest.approx((-5.5 + 15.0) / 30.0)

    # Whole-channel EQ Reset sends neutral curves to all 4 bands
    sent.clear()
    assert target.handle("reset eq canale 1", ctx).handled
    addrs_sent = {s[2] for s in sent}
    for b in (1, 2, 3, 4):
        assert f"/ch/01/eq/{b}/type" in addrs_sent
        assert f"/ch/01/eq/{b}/f" in addrs_sent
        assert f"/ch/01/eq/{b}/g" in addrs_sent
        assert f"/ch/01/eq/{b}/q" in addrs_sent

    # RTA Pre/Post & Source
    assert target.handle("rta pre", ctx).handled
    assert sent[-1][2:] == ("/-stat/rta/pos", 0)
    assert target.handle("rta post", ctx).handled
    assert sent[-1][2:] == ("/-stat/rta/pos", 1)
    assert target.handle("rta canale 7", ctx).handled
    assert sent[-1][2:] == ("/-stat/rta/source", 6)


def test_xr18_main_and_bus_6_band_eq_without_cuts():
    sent: list[tuple[str, int, str, object]] = []
    live_state: dict[str, float | int] = {"/lr/eq/on": 1, "/bus/1/eq/4/g": 0.5}

    target = BehringerXR18Target(
        osc_sender=lambda h, p, a, v: (sent.append((h, p, a, v)), live_state.__setitem__(a, v)),
        osc_querier=lambda _h, _p, a: live_state.get(a),
    )
    cfg = AppConfig()
    ctx = _make_ctx(cfg)

    # Main LR 6 bands: Band 5 & 6 work
    assert target.handle("main eq banda 5 +3 db", ctx).handled
    assert sent[-1][2] == "/lr/eq/5/g"
    assert sent[-1][3] == pytest.approx((3.0 + 15.0) / 30.0)

    assert target.handle("main eq banda 6 10k02", ctx).handled
    assert sent[-1][2] == "/lr/eq/6/f"

    assert target.handle("main eq toggle", ctx).handled
    assert sent[-1][2:] == ("/lr/eq/on", 0)

    assert target.handle("main eq geq", ctx).handled
    assert sent[-1][2:] == ("/lr/eq/mode", 1)

    # Main & Bus 6-band EQ MUST reject LCut & HCut
    r_lcut = target.handle("main eq banda 1 mode lcut", ctx)
    assert not r_lcut.handled
    r_hcut = target.handle("bus 1 eq banda 6 mode hcut", ctx)
    assert not r_hcut.handled

    # Bus 1 6-band EQ works including live relative & reset 6 bands
    assert target.handle("bus 1 eq banda 4 mode peq", ctx).handled
    assert sent[-1][2:] == ("/bus/1/eq/4/type", 2)

    assert target.handle("abbassa bus 1 eq banda 4 di 2 db", ctx).handled
    assert sent[-1][2] == "/bus/1/eq/4/g"
    assert sent[-1][3] == pytest.approx((-2.0 + 15.0) / 30.0)

    sent.clear()
    assert target.handle("reset eq main", ctx).handled
    lr_addrs = {s[2] for s in sent}
    for b in range(1, 7):
        assert f"/lr/eq/{b}/type" in lr_addrs
        assert f"/lr/eq/{b}/f" in lr_addrs
        assert f"/lr/eq/{b}/g" in lr_addrs
        assert f"/lr/eq/{b}/q" in lr_addrs

    # Channel only has 4 bands (band 5 must be rejected)
    assert not target.handle("canale 1 eq banda 5 +2 db", ctx).handled


def test_xr18_gate_comp_sends_main_assignments_fx_and_mute_groups():
    sent: list[tuple[str, int, str, object]] = []
    live_state: dict[str, float | int] = {
        "/ch/01/gate/thr": 0.325,  # -54.0 dB
        "/ch/01/dyn/thr": 0.575,  # -25.5 dB
        "/ch/01/dyn/mgain": 0.25,  # 6.0 dB
        "/ch/01/grp/dca": 1,  # DCA 1 already ON
        "/ch/01/grp/mute": 1,  # Mute Group 1 already ON
        "/fxsend/2/mix/fader": 0.50,  # -10.0 dB
        "/rtn/2/mix/fader": 0.75,  # 0.0 dB
    }

    target = BehringerXR18Target(
        osc_sender=lambda h, p, a, v: (sent.append((h, p, a, v)), live_state.__setitem__(a, v)),
        osc_querier=lambda _h, _p, a: live_state.get(a),
    )
    cfg = AppConfig()
    ctx = _make_ctx(cfg)

    # ---- Tab 1: Gate complete ----
    assert target.handle("canale 1 gate mode ducker", ctx).handled
    assert sent[-1][2:] == ("/ch/01/gate/mode", 4)
    assert target.handle("canale 1 gate mode exp 3:1", ctx).handled
    assert sent[-1][2:] == ("/ch/01/gate/mode", 1)

    assert target.handle("alza soglia gate canale 1 di 4 db", ctx).handled
    assert sent[-1][2] == "/ch/01/gate/thr"
    assert sent[-1][3] == pytest.approx((-50.0 + 80.0) / 80.0, abs=1e-3)

    assert target.handle("canale 1 gate range 45 db", ctx).handled
    assert sent[-1][2] == "/ch/01/gate/range"
    assert sent[-1][3] == pytest.approx((45.0 - 3.0) / 57.0, abs=1e-3)

    assert target.handle("canale 1 gate attack 12 ms", ctx).handled
    assert sent[-1][2:] == ("/ch/01/gate/attack", pytest.approx(0.1))
    assert target.handle("canale 1 gate hold 0.32 ms", ctx).handled
    assert sent[-1][2:] == ("/ch/01/gate/hold", pytest.approx(0.24, abs=0.01))
    assert target.handle("canale 1 gate release 5 ms", ctx).handled
    assert sent[-1][2:] == ("/ch/01/gate/release", pytest.approx(0.0, abs=0.01))

    assert target.handle("canale 1 gate keysrc chitarra", ctx).handled
    assert sent[-1][2:] == ("/ch/01/gate/keysrc", 3)
    assert target.handle("canale 1 gate filter on", ctx).handled
    assert sent[-1][2:] == ("/ch/01/gate/filter/on", 1)
    assert target.handle("canale 1 gate filter type 3.0", ctx).handled
    assert sent[-1][2:] == ("/ch/01/gate/filter/type", 6)
    assert target.handle("canale 1 gate filter freq 991 hz", ctx).handled
    assert sent[-1][2] == "/ch/01/gate/filter/f"

    # ---- Tab 2: Comp complete ----
    assert target.handle("canale 1 comp mode exp", ctx).handled
    assert sent[-1][2:] == ("/ch/01/dyn/mode", 1)
    assert target.handle("canale 1 comp rms", ctx).handled
    assert sent[-1][2:] == ("/ch/01/dyn/det", 1)
    assert target.handle("canale 1 comp lin", ctx).handled
    assert sent[-1][2:] == ("/ch/01/dyn/env", 0)
    assert target.handle("canale 1 comp knee 3", ctx).handled
    assert sent[-1][2:] == ("/ch/01/dyn/knee", pytest.approx(0.6))
    assert target.handle("canale 1 comp auto on", ctx).handled
    assert sent[-1][2:] == ("/ch/01/dyn/auto", 1)
    assert target.handle("canale 1 comp mix 80%", ctx).handled
    assert sent[-1][2:] == ("/ch/01/dyn/mix", pytest.approx(0.8))
    assert target.handle("alza comp makeup canale 1 di 2 db", ctx).handled
    assert sent[-1][2] == "/ch/01/dyn/mgain"
    assert sent[-1][3] == pytest.approx(8.0 / 24.0, abs=1e-4)
    assert target.handle("canale 1 comp hold 10 ms", ctx).handled
    assert sent[-1][2:] == ("/ch/01/dyn/hold", pytest.approx(0.54, abs=0.01))
    assert target.handle("canale 1 comp release 151 ms", ctx).handled
    assert sent[-1][2:] == ("/ch/01/dyn/release", pytest.approx(0.51, abs=0.01))
    assert target.handle("canale 1 comp keysrc bus 2", ctx).handled
    assert sent[-1][2:] == ("/ch/01/dyn/keysrc", 18)

    # ---- Tab 3: Sends tap point + pan + FX Send/Return masters ----
    assert target.handle("canale 1 bus 1 pre eq", ctx).handled
    assert sent[-1][2:] == ("/ch/01/mix/01/tap", 1)
    assert target.handle("canale 1 fx 2 post fader", ctx).handled
    assert sent[-1][2:] == ("/ch/01/mix/08/tap", 4)
    assert target.handle("canale 1 bus 1 pan sinistra 50", ctx).handled
    assert sent[-1][2:] == ("/ch/01/mix/01/pan", pytest.approx(0.25))

    assert target.handle("alza send 2", ctx).handled
    assert sent[-1][2] == "/fxsend/2/mix/fader"
    assert sent[-1][3] == pytest.approx(db_to_fader(-7.0), abs=1e-4)

    assert target.handle("abbassa return 2 di 3 db", ctx).handled
    assert sent[-1][2] == "/rtn/2/mix/fader"
    assert sent[-1][3] == pytest.approx(db_to_fader(-3.0), abs=1e-4)

    assert target.handle("muta aux return", ctx).handled
    assert sent[-1][2:] == ("/rtn/aux/mix/on", 0)

    # ---- Tab 4: Main LR Assign, Pan, DCA 1-4 bitmask, Mute Group, AutoMix ----
    assert target.handle("canale 1 main stereo off", ctx).handled
    assert sent[-1][2:] == ("/ch/01/mix/lr", 0)
    assert target.handle("pan canale 1 destra 50", ctx).handled
    assert sent[-1][2:] == ("/ch/01/mix/pan", pytest.approx(0.75))
    assert target.handle("pan canale 1 centro", ctx).handled
    assert sent[-1][2:] == ("/ch/01/mix/pan", pytest.approx(0.5))

    # Bitmask read-modify-write: DCA 1 (bit 0 = 1) + adding DCA 2 -> bitmask 3
    assert target.handle("canale 1 dca 2 on", ctx).handled
    assert sent[-1][2:] == ("/ch/01/grp/dca", 3)
    assert target.handle("canale 1 dca 1 off", ctx).handled
    assert sent[-1][2:] == ("/ch/01/grp/dca", 2)

    assert target.handle("canale 1 mute group 3 on", ctx).handled
    assert sent[-1][2:] == ("/ch/01/grp/mute", 5)

    assert target.handle("mute group 2 on", ctx).handled
    assert sent[-1][2:] == ("/config/mute/2", 1)

    assert target.handle("canale 1 automix y", ctx).handled
    assert sent[-1][2:] == ("/ch/01/automix/group", 2)
    assert target.handle("canale 1 automix weight +6 db", ctx).handled
    assert sent[-1][2] == "/ch/01/automix/weight"
    assert sent[-1][3] == pytest.approx((6.0 + 12.0) / 24.0)
    assert target.handle("automix x on", ctx).handled
    assert sent[-1][2:] == ("/config/amixenable/X", 1)

    # ---- Tab 5: FX Insert & Channel Insert ----
    assert target.handle("fx 1 insert on", ctx).handled
    assert sent[-1][2:] == ("/fx/1/insert", 1)
    assert target.handle("canale 1 insert fx 2", ctx).handled
    assert ("/ch/01/insert/sel", 3) in [s[2:] for s in sent]
    assert sent[-1][2:] == ("/ch/01/insert/on", 1)




