"""Behringer XR18 / X-Air Edit OSC UDP 10024 controller."""

from __future__ import annotations

import math
import re
from typing import Callable

from pythonosc.udp_client import SimpleUDPClient

from ..config.schema import XR18Settings
from ..core.parser import extract_numbers, normalize_text, replace_spoken_numbers
from .base import BaseTarget, CommandExecutionResult, TargetContext, query_osc_value

_COMP_RATIOS = [1.1, 1.3, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0, 10.0, 20.0, 100.0]

# Verified X-AIR-Edit v1.8.0 Tab bar order (anchored at Tab 0 via <tab>)
_XAIR_TAB_INDEX: dict[str, int] = {
    "mixer": 0,
    "home": 0,
    "channel": 1,
    "input": 2,
    "ingresso": 2,
    "channel input": 2,
    "gate": 3,
    "eq": 4,
    "equalizzatore": 4,
    "comp": 5,
    "compressore": 5,
    "dynamics": 5,
    "sends": 6,
    "mandate": 6,
    "main": 7,
    "fx": 8,
    "effetti": 8,
    "meter": 9,
}

# Verified X-AIR-Edit v1.8.0 Shortcut Keys utility windows
_XAIR_WINDOW_HOTKEYS: list[tuple[tuple[str, ...], str, str]] = [
    (("fx 1", "fx1", "effetto 1"), "<f1>", "FX1"),
    (("fx 2", "fx2", "effetto 2"), "<f2>", "FX2"),
    (("fx 3", "fx3", "effetto 3"), "<f3>", "FX3"),
    (("fx 4", "fx4", "effetto 4"), "<f4>", "FX4"),
    (("in/out", "inout", "in out", "routing"), "<f10>", "In/Out"),
    (("setup", "impostazioni"), "<f9>", "Setup"),
    (("snapshot", "scene"), "<shift>+<f2>", "Snapshot"),
    (("recorder", "registratore"), "<shift>+<f3>", "Recorder"),
    (("finestra meter", "meters"), "<shift>+<f4>", "Meter"),
    (("rta", "analizzatore"), "<shift>+<f6>", "RTA"),
    (("dca spill", "spill"), "<ctrl>+d", "DCA Spill"),
    (("dca",), "<shift>+<f10>", "DCA"),
    (("user 1", "user1"), "<shift>+<f11>", "User 1"),
    (("user 2", "user2"), "<shift>+<f12>", "User 2"),
    (("buses",), "<insert>", "Buses"),
    (("rinomina", "colore"), "<ctrl>+n", "Rinomina/Colore"),
]


def _strip_target_tokens(text: str) -> str:
    """Strip 'canale N' / 'bus N' / 'send N' phrases so target indices aren't mistaken for dB/% values."""
    cleaned = re.sub(r"\b(?:canali|canale|can|ch|channel)\s*\d{1,2}\b", " ", text)
    cleaned = re.sub(r"\b(?:aux|bus|spia|monitor|fx|effetto|send|return|ritorno|rtn)\s*\d\b", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _looks_relative_fader_cmd(text: str) -> bool:
    return any(
        w in text
        for w in (
            "alza",
            "aumenta",
            "piu",
            "tira su",
            "porta su",
            "vai su",
            "salire",
            "abbassa",
            "riduci",
            "scendi",
            "tira giu",
            "porta giu",
            "vai giu",
        )
    )


def db_to_fader(db: float) -> float:
    """Convert dB [-90..+10] to Behringer X-Air normalized fader [0.0..1.0]."""
    db = max(-90.0, min(10.0, float(db)))
    if db >= -10.0:
        return max(0.0, min(1.0, (db / 40.0) + 0.75))
    if db >= -30.0:
        return max(0.0, min(1.0, ((db + 10.0) / 80.0) + 0.5))
    if db >= -60.0:
        return max(0.0, min(1.0, ((db + 30.0) / 160.0) + 0.25))
    return max(0.0, min(1.0, ((db + 60.0) / 480.0) + 0.0625))


def fader_to_db(f: float) -> float:
    """Convert Behringer X-Air normalized fader [0.0..1.0] to dB [-90..+10]."""
    f = max(0.0, min(1.0, float(f)))
    if f >= 0.5:
        return (f - 0.75) * 40.0
    if f >= 0.25:
        return (f - 0.5) * 80.0 - 10.0
    if f >= 0.0625:
        return (f - 0.25) * 160.0 - 30.0
    return (f - 0.0625) * 480.0 - 60.0


def freq_to_osc(hz: float, min_hz: float = 20.0, max_hz: float = 20000.0) -> float:
    hz = max(min_hz, min(max_hz, float(hz)))
    return math.log(hz / min_hz) / math.log(max_hz / min_hz)


def osc_to_freq(v: float, min_hz: float = 20.0, max_hz: float = 20000.0) -> float:
    v = max(0.0, min(1.0, float(v)))
    return min_hz * ((max_hz / min_hz) ** v)


def q_to_osc(q: float) -> float:
    """Convert EQ Q factor [0.3..10.0] to Behringer X-Air 72-step normalized float."""
    q = max(0.3, min(10.0, float(q)))
    raw = math.log(q / 10.0) / math.log(0.3 / 10.0)
    return round(max(0.0, min(1.0, raw)) * 71.0) / 71.0


def osc_to_q(v: float) -> float:
    v = max(0.0, min(1.0, float(v)))
    return 10.0 * ((0.3 / 10.0) ** v)


def _log_curve_to_osc(val: float, vmin: float, vmax: float, steps: int = 100) -> float:
    val = max(vmin, min(vmax, float(val)))
    raw = math.log(val / vmin) / math.log(vmax / vmin)
    return round(max(0.0, min(1.0, raw)) * steps) / float(steps)


def _osc_to_log_curve(v: float, vmin: float, vmax: float) -> float:
    v = max(0.0, min(1.0, float(v)))
    return vmin * ((vmax / vmin) ** v)


_EQ_MODE_NAMES = ("LCut", "LShv", "PEQ", "VEQ", "HShv", "HCut")

_GATE_MODE_ALIASES: list[tuple[tuple[str, ...], int, str]] = [
    (("exp 2:1", "exp2:1", "exp 2", "exp2", "expander 2"), 0, "Exp 2:1"),
    (("exp 3:1", "exp3:1", "exp 3", "exp3", "expander 3"), 1, "Exp 3:1"),
    (("exp 4:1", "exp4:1", "exp 4", "exp4", "expander 4"), 2, "Exp 4:1"),
    (("ducker", "duck"), 4, "Ducker"),
    (("gate",), 3, "Gate"),
]

_SC_FILTER_TYPES: list[tuple[tuple[str, ...], int, str]] = [
    (("lc12", "lc 12"), 1, "LC12"),
    (("lc6", "lc 6"), 0, "LC6"),
    (("hc12", "hc 12"), 3, "HC12"),
    (("hc6", "hc 6"), 2, "HC6"),
    (("10.0", "10,0", "10"), 8, "10.0"),
    (("5.0", "5,0", "5"), 7, "5.0"),
    (("3.0", "3,0", "3"), 6, "3.0"),
    (("2.0", "2,0", "2"), 5, "2.0"),
    (("1.0", "1,0", "1"), 4, "1.0"),
]

_SEND_TAP_ALIASES: list[tuple[tuple[str, ...], int, str]] = [
    (("sub group", "subgroup", "sub"), 5, "Sub Group"),
    (("post fader", "postfader"), 4, "Post Fader"),
    (("pre fader", "prefader"), 3, "Pre Fader"),
    (("post eq", "posteq"), 2, "Post EQ"),
    (("pre eq", "preeq"), 1, "Pre EQ"),
    (("input", "in/lc"), 0, "Input"),
]

_EQ_MODE_ALIASES: list[tuple[tuple[str, ...], int]] = [
    (("lcut", "low cut", "lowcut", "passa alto"), 0),
    (("lshv", "low shelf", "lowshelf", "shelf bassi"), 1),
    (("peq", "parametrico", "parametric", "bell", "campana"), 2),
    (("veq", "vintage"), 3),
    (("hshv", "high shelf", "highshelf", "shelf alti"), 4),
    (("hcut", "high cut", "highcut", "passa basso"), 5),
]

# X-AIR Edit default 4-band Channel EQ reset curves (band -> (type_idx, freq_osc, gain_osc, q_osc))
_XR18_EQ_DEFAULTS: dict[int, tuple[int, float, float, float]] = {
    1: (1, 0.235, 0.5, 33.0 / 71.0),  # LShv ~101 Hz, 0.0 dB, Q 2.0
    2: (2, 0.465, 0.5, 33.0 / 71.0),  # PEQ  496.6 Hz, 0.0 dB, Q 2.0
    3: (2, 0.665, 0.5, 33.0 / 71.0),  # PEQ  1k97 Hz, 0.0 dB, Q 2.0
    4: (4, 0.900, 0.5, 33.0 / 71.0),  # HShv 10k02 Hz, 0.0 dB, Q 2.0
}

# X-AIR Edit default 6-band Main LR / Bus 1-6 EQ reset curves (verified from /node lr/eq, NO LCut/HCut)
_XR18_BUS_LR_EQ_DEFAULTS: dict[int, tuple[int, float, float, float]] = {
    1: (1, 0.200, 0.5, 33.0 / 71.0),  # LShv 79.6 Hz, 0.0 dB, Q 2.0
    2: (2, 0.300, 0.5, 33.0 / 71.0),  # PEQ  158.9 Hz, 0.0 dB, Q 2.0
    3: (2, 0.465, 0.5, 33.0 / 71.0),  # PEQ  496.6 Hz, 0.0 dB, Q 2.0
    4: (2, 0.665, 0.5, 33.0 / 71.0),  # PEQ  1k98 Hz, 0.0 dB, Q 2.0
    5: (2, 0.800, 0.5, 33.0 / 71.0),  # PEQ  5k02 Hz, 0.0 dB, Q 2.0
    6: (4, 0.900, 0.5, 33.0 / 71.0),  # HShv 10k02 Hz, 0.0 dB, Q 2.0
}


class BehringerXR18Target(BaseTarget):
    """Translates voice intents into Behringer XR18 / X-Air OSC UDP messages."""

    def __init__(
        self,
        osc_sender: Callable[[str, int, str, object], None] | None = None,
        osc_querier: Callable[[str, int, str], float | int | None] | None = None,
    ) -> None:
        self._custom_sender = osc_sender
        self._custom_querier = osc_querier
        self._client: SimpleUDPClient | None = None
        self._client_addr: tuple[str, int] | None = None
        # Shadow state for smooth relative adjustments ("alza", "abbassa", "+3 dB")
        self._ch_faders: dict[int, float] = {i: 0.75 for i in range(1, 17)}
        self._ch_gains: dict[int, float] = {i: 0.35 for i in range(1, 17)}
        self._ch_trims: dict[int, float] = {i: 0.5 for i in range(1, 17)}
        self._ch_phantoms: dict[int, int] = {i: 0 for i in range(1, 17)}
        self._ch_inverts: dict[int, int] = {i: 0 for i in range(1, 17)}
        self._ch_rtnsws: dict[int, int] = {i: 0 for i in range(1, 17)}
        self._ch_links: dict[str, int] = {}
        self._eq_on: dict[str, int] = {}
        self._eq_gains: dict[tuple[str, int], float] = {}
        self._eq_freqs: dict[tuple[str, int], float] = {}
        self._eq_qs: dict[tuple[str, int], float] = {}
        self._gate_on: dict[int, int] = {}
        self._dyn_on: dict[int, int] = {}
        self._lr_assign: dict[int, int] = {i: 1 for i in range(1, 17)}
        self._ch_pans: dict[int, float] = {i: 0.5 for i in range(1, 17)}
        self._dca_masks: dict[int, int] = {}
        self._mute_masks: dict[int, int] = {}
        self._global_mutes: dict[int, int] = {}
        self._fx_inserts: dict[int, int] = {}
        self._scalar_cache: dict[str, float] = {}
        self._bus_faders: dict[int, float] = {i: 0.75 for i in range(1, 11)}
        self._send_levels: dict[tuple[int, int], float] = {}
        self._lr_fader: float = 0.75

    @property
    def target_id(self) -> str:
        return "xr18"

    def _query_osc_or_shadow(
        self, cfg: XR18Settings, address: str, fallback: float
    ) -> float:
        live: float | int | None = None
        if self._custom_querier is not None:
            live = self._custom_querier(cfg.host, cfg.port, address)
        elif self._custom_sender is None:
            live = query_osc_value(cfg.host, cfg.port, address)
        if live is not None:
            return float(live)
        return fallback

    def _send_osc(self, cfg: XR18Settings, address: str, value: int | float) -> None:
        if self._custom_sender is not None:
            self._custom_sender(cfg.host, cfg.port, address, value)
            return
        addr = (cfg.host, int(cfg.port))
        if self._client is None or self._client_addr != addr:
            self._client = SimpleUDPClient(cfg.host, int(cfg.port))
            self._client_addr = addr
        self._client.send_message(address, value)

    def handle(self, remainder: str, ctx: TargetContext) -> CommandExecutionResult:
        cfg = ctx.config.xr18
        text = replace_spoken_numbers(remainder)
        if not text:
            return CommandExecutionResult(False, self.target_id, "Comando XR18 vuoto")

        # 0. X-AIR-Edit v1.8.0 Tab / Utility Window / Channel selection (keyboard shortcuts)
        nav_res = self._maybe_handle_ui_navigation(text, cfg, ctx)
        if nav_res is not None:
            return nav_res

        # 0b. RTA hardware controls (Pre/Post & Source)
        if re.search(r"\brta\b", text):
            return self._handle_rta(text, cfg)

        # 1. Snapshot / Scene recall
        if any(w in text for w in ("scena", "snapshot", "scene", "preset")):
            scene_idx = self._resolve_scene(text, cfg)
            if scene_idx is not None:
                self._send_osc(cfg, "/-snap/load", int(scene_idx))
                return CommandExecutionResult(
                    True,
                    self.target_id,
                    f"XR18: richiamata Scena/Snapshot {scene_idx}",
                    {"address": "/-snap/load", "value": scene_idx},
                )

        # 2. Resolve channel (number or stage alias) and bus/fx
        ch = self._resolve_channel(text, cfg)
        bus = self._resolve_bus(text, cfg)

        # 3. Global (channel-less) controls: Mute Groups, AutoMix enable, FX Send/Return/Insert masters, Main LR, Bus 1..6
        if ch is None:
            glob_res = self._maybe_handle_global_masters(text, bus, cfg)
            if glob_res is not None:
                return glob_res

        # 4. Sends / Mandate & Tap points (channel -> aux/bus/fx), unless Sidechain KeySrc
        is_sidechain_ctx = any(
            w in text for w in ("gate", "comp", "compressore", "dinamica", "dyn", "keysrc", "sidechain", "insert")
        )
        if ch is not None and bus is not None and not is_sidechain_ctx and (
            any(w in text for w in ("manda", "mandata", "send", "su ", "in ", "verso ", "aux", "spia", "monitor", "fx", "riverbero", "delay", "bus", "tap", "fader", "eq", "sub"))
            or re.search(r"\bpan\b", text)
        ):
            return self._handle_channel_send(text, ch, bus, cfg)

        # 5. Aux / Bus master control (when bus mentioned without channel)
        if ch is None and bus is not None and 1 <= bus <= 6:
            return self._handle_bus_master(text, bus, cfg)

        if ch is None:
            return CommandExecutionResult(
                False,
                self.target_id,
                f"XR18: canale o comando non riconosciuto in '{remainder}'",
            )

        # 6. Channel Insert & FX slot routing
        if "insert" in text:
            return self._handle_channel_insert(text, ch, cfg)

        # 7. Main Tab Assignments (LR Stereo assign, Pan, DCA 1-4, Mute Group 1-4, AutoMix X/Y & Weight)
        if self._is_channel_main_command(text):
            return self._handle_channel_main_assignments(text, ch, cfg)

        # 8. Stereo Channel Link (1-2, 3-4, ..., 15-16)
        if any(w in text for w in ("link", "collega", "separa", "scollega", "unlink", "stereo link")):
            return self._handle_channel_link(text, ch, cfg)

        # 9. Processors: Noise Gate, Compressor, EQ, HPF
        if any(w in text for w in ("gate", "noise gate", "ducker", "exp2", "exp3", "exp4")):
            return self._handle_gate(text, ch, cfg)
        if any(w in text for w in ("compressore", "comp", "dinamica", "dyn", "makeup", "mgain", "knee", "auto time", "rms")):
            return self._handle_compressor(text, ch, cfg)
        if self._is_eq_command(text):
            return self._handle_eq(text, ch, cfg)

        # 8. Channel Input Controls (Phantom 48V, Phase Invert, USB Switch, USB Trim, Analog Gain)
        if any(w in text for w in ("phantom", "48v", "48 v")):
            return self._handle_phantom(text, ch, cfg)
        if any(w in text for w in ("fase", "polarita", "invert")):
            return self._handle_phase_invert(text, ch, cfg)
        if "trim" in text or "rtntrim" in text:
            return self._handle_trim(text, ch, cfg)
        if any(w in text for w in ("usb", "sorgente", "analogic", "rtnsw")):
            return self._handle_usb_switch(text, ch, cfg)
        if any(w in text for w in ("gain", "guadagno", "preamp")):
            return self._handle_gain(text, ch, cfg)

        # 8. Mute / Unmute
        if self._is_mute_command(text) or self._is_unmute_command(text):
            unmute = self._is_unmute_command(text)
            val = 1 if unmute else 0
            addr = f"/ch/{ch:02d}/mix/on"
            self._send_osc(cfg, addr, val)
            state_str = "attivo (unmute)" if unmute else "mutato"
            return CommandExecutionResult(
                True,
                self.target_id,
                f"XR18: Canale {ch} {state_str}",
                {"address": addr, "value": val},
            )

        # 9. Channel Fader / Volume
        addr = f"/ch/{ch:02d}/mix/fader"
        clean_fader_text = _strip_target_tokens(text)
        cur_fader = (
            self._query_osc_or_shadow(cfg, addr, self._ch_faders.get(ch, 0.75))
            if _looks_relative_fader_cmd(clean_fader_text)
            else self._ch_faders.get(ch, 0.75)
        )
        new_fader, desc = self._compute_new_fader(clean_fader_text, cur_fader, cfg.step_db)
        if new_fader is not None:
            self._ch_faders[ch] = new_fader
            self._send_osc(cfg, addr, float(new_fader))
            return CommandExecutionResult(
                True,
                self.target_id,
                f"XR18: Fader Canale {ch} -> {desc}",
                {"address": addr, "value": round(new_fader, 4)},
            )

        return CommandExecutionResult(
            False,
            self.target_id,
            f"XR18: azione non riconosciuta per canale {ch} in '{remainder}'",
        )

    def panic(self, ctx: TargetContext) -> list[str]:
        cfg = ctx.config.xr18
        actions: list[str] = []
        if cfg.panic_mute_lr:
            self._send_osc(cfg, "/lr/mix/on", 0)
            actions.append("XR18: Master LR mutato")
        for ch in cfg.panic_mute_channels:
            if 1 <= int(ch) <= 16:
                self._send_osc(cfg, f"/ch/{int(ch):02d}/mix/on", 0)
                actions.append(f"XR18: Canale {ch} mutato")
        return actions

    def _resolve_scene(self, text: str, cfg: XR18Settings) -> int | None:
        for alias, idx in sorted(
            cfg.scene_aliases.items(), key=lambda kv: len(kv[0]), reverse=True
        ):
            a = normalize_text(alias)
            if a and a in text:
                return max(1, min(64, int(idx)))
        nums = extract_numbers(text)
        if nums:
            return max(1, min(64, int(round(nums[0]))))
        return None

    def _resolve_channel(self, text: str, cfg: XR18Settings) -> int | None:
        m = re.search(r"\b(?:canali|canale|can|ch|channel)\s+(\d{1,2})\b", text)
        if m:
            ch = int(m.group(1))
            if 1 <= ch <= 16:
                return ch
        for alias, ch in sorted(
            cfg.channel_aliases.items(), key=lambda kv: len(kv[0]), reverse=True
        ):
            a = normalize_text(alias)
            if a and f" {a} " in f" {text} ":
                if 1 <= int(ch) <= 16:
                    return int(ch)
        return None

    def _resolve_bus(self, text: str, cfg: XR18Settings) -> int | None:
        m_fx = re.search(r"\b(?:fx|effetto)\s*(\d)\b", text)
        if m_fx:
            fx = int(m_fx.group(1))
            if 1 <= fx <= 4:
                return 6 + fx
        m_aux = re.search(r"\b(?:aux|bus|spia|monitor)\s*(\d)\b", text)
        if m_aux:
            aux = int(m_aux.group(1))
            if 1 <= aux <= 6:
                return aux
        for alias, bus in sorted(
            cfg.aux_aliases.items(), key=lambda kv: len(kv[0]), reverse=True
        ):
            a = normalize_text(alias)
            if a and f" {a} " in f" {text} ":
                if 1 <= int(bus) <= 10:
                    return int(bus)
        return None

    @staticmethod
    def _is_master_command(text: str) -> bool:
        return any(w in text for w in ("master", " lr", "lr ", "generale", "main"))

    @staticmethod
    def _is_unmute_command(text: str) -> bool:
        return any(w in text for w in ("smuta", "unmute", "apri ", "riattiva"))

    @staticmethod
    def _is_mute_command(text: str) -> bool:
        if BehringerXR18Target._is_unmute_command(text):
            return False
        return any(w in text for w in ("muta", "mute", "silenzia", "chiudi "))

    def _handle_master(self, text: str, cfg: XR18Settings) -> CommandExecutionResult:
        if self._is_eq_command(text):
            return self._handle_eq_for_prefix(
                text,
                prefix="/lr",
                target_label="Main LR",
                cfg=cfg,
                max_bands=6,
                allow_cuts=False,
            )
        if self._is_mute_command(text) or self._is_unmute_command(text):
            unmute = self._is_unmute_command(text)
            val = 1 if unmute else 0
            self._send_osc(cfg, "/lr/mix/on", val)
            return CommandExecutionResult(
                True,
                self.target_id,
                f"XR18: Master LR {'attivo' if unmute else 'mutato'}",
                {"address": "/lr/mix/on", "value": val},
            )
        clean_fader_text = _strip_target_tokens(text)
        cur_lr = (
            self._query_osc_or_shadow(cfg, "/lr/mix/fader", self._lr_fader)
            if _looks_relative_fader_cmd(clean_fader_text)
            else self._lr_fader
        )
        new_fader, desc = self._compute_new_fader(clean_fader_text, cur_lr, cfg.step_db)
        if new_fader is not None:
            self._lr_fader = new_fader
            self._send_osc(cfg, "/lr/mix/fader", float(new_fader))
            return CommandExecutionResult(
                True,
                self.target_id,
                f"XR18: Master LR -> {desc}",
                {"address": "/lr/mix/fader", "value": round(new_fader, 4)},
            )
        return CommandExecutionResult(False, self.target_id, "XR18: parametro Master mancante")

    def _handle_bus_master(
        self, text: str, bus: int, cfg: XR18Settings
    ) -> CommandExecutionResult:
        if self._is_eq_command(text):
            return self._handle_eq_for_prefix(
                text,
                prefix=f"/bus/{bus}",
                target_label=f"Bus {bus}",
                cfg=cfg,
                max_bands=6,
                allow_cuts=False,
            )
        if self._is_mute_command(text) or self._is_unmute_command(text):
            unmute = self._is_unmute_command(text)
            val = 1 if unmute else 0
            addr = f"/bus/{bus}/mix/on"
            self._send_osc(cfg, addr, val)
            return CommandExecutionResult(
                True,
                self.target_id,
                f"XR18: Bus {bus} {'attivo' if unmute else 'mutato'}",
                {"address": addr, "value": val},
            )
        addr = f"/bus/{bus}/mix/fader"
        clean_fader_text = _strip_target_tokens(text)
        cur_bus = (
            self._query_osc_or_shadow(cfg, addr, self._bus_faders.get(bus, 0.75))
            if _looks_relative_fader_cmd(clean_fader_text)
            else self._bus_faders.get(bus, 0.75)
        )
        new_fader, desc = self._compute_new_fader(clean_fader_text, cur_bus, cfg.step_db)
        if new_fader is not None:
            self._bus_faders[bus] = new_fader
            self._send_osc(cfg, addr, float(new_fader))
            return CommandExecutionResult(
                True,
                self.target_id,
                f"XR18: Bus {bus} -> {desc}",
                {"address": addr, "value": round(new_fader, 4)},
            )
        return CommandExecutionResult(False, self.target_id, f"XR18: azione Bus {bus} non valida")

    def _maybe_handle_global_masters(
        self, text: str, bus: int | None, cfg: XR18Settings
    ) -> CommandExecutionResult | None:
        # Global Mute Groups 1..4 (/config/mute/1..4)
        m_mg = re.search(r"\b(?:mute\s*group|mutegroup|gruppo\s*mute)\s*([1-4])\b", text)
        if m_mg:
            grp = int(m_mg.group(1))
            addr = f"/config/mute/{grp}"
            val = self._resolve_binary_state(
                text, cfg, addr, self._global_mutes.get(grp, 0)
            )
            self._global_mutes[grp] = val
            self._send_osc(cfg, addr, int(val))
            return CommandExecutionResult(
                True,
                self.target_id,
                f"XR18: Mute Group {grp} {'ATTIVO' if val else 'SPENTO'}",
                {"address": addr, "value": val},
            )

        # Global AutoMix Group X / Y enable (/config/amixenable/X|Y)
        if "automix" in text:
            grp_letter = "Y" if re.search(r"\by\b", text) else "X"
            addr = f"/config/amixenable/{grp_letter}"
            val = self._resolve_binary_state(text, cfg, addr, 0)
            self._send_osc(cfg, addr, int(val))
            return CommandExecutionResult(
                True,
                self.target_id,
                f"XR18: AutoMix {grp_letter} {'ON' if val else 'OFF'}",
                {"address": addr, "value": val},
            )

        # FX Slot Insert toggle (/fx/1..4/insert) & Delay Time (/fx/{slot}/par/02)
        m_fx_slot = re.search(r"\b(?:fx|effetto)\s*([1-4])\b", text)
        if m_fx_slot and "insert" in text:
            slot = int(m_fx_slot.group(1))
            addr = f"/fx/{slot}/insert"
            val = self._resolve_binary_state(
                text, cfg, addr, self._fx_inserts.get(slot, 0)
            )
            self._fx_inserts[slot] = val
            self._send_osc(cfg, addr, int(val))
            return CommandExecutionResult(
                True,
                self.target_id,
                f"XR18: FX {slot} Insert {'ON' if val else 'OFF'}",
                {"address": addr, "value": val},
            )

        # Aux / USB Return master (/rtn/aux/mix/fader|on)
        if any(w in text for w in ("aux return", "usb return", "ritorno aux", "ritorno usb")):
            return self._handle_strip_fader_or_mute(
                text, "/rtn/aux/mix", "Aux/USB Return", cfg, shadow_key=99
            )

        # FX Send 1..4 / FX Return 1..4 masters (supports both 'fx send 2'/'fx return 2' and 'send 2'/'return 2')
        m_rtn = re.search(r"\b(?:fx\s*)?(?:return|ritorno|rtn)\s*([1-4])\b", text)
        if m_rtn:
            slot = int(m_rtn.group(1))
            return self._handle_strip_fader_or_mute(
                text, f"/rtn/{slot}/mix", f"FX {slot} Return", cfg, shadow_key=20 + slot
            )

        m_snd = re.search(r"\b(?:fx\s*)?(?:send|mandata)\s*([1-4])\b", text)
        if m_snd:
            slot = int(m_snd.group(1))
            return self._handle_strip_fader_or_mute(
                text, f"/fxsend/{slot}/mix", f"FX {slot} Send", cfg, shadow_key=10 + slot
            )

        if m_fx_slot:
            slot = int(m_fx_slot.group(1))
            if any(w in text for w in ("return", "ritorno", "rtn")):
                return self._handle_strip_fader_or_mute(
                    text, f"/rtn/{slot}/mix", f"FX {slot} Return", cfg, shadow_key=20 + slot
                )
            if any(w in text for w in ("send", "mandata")) or (
                not self._is_master_command(text) and bus is not None
            ):
                return self._handle_strip_fader_or_mute(
                    text, f"/fxsend/{slot}/mix", f"FX {slot} Send", cfg, shadow_key=10 + slot
                )

        if self._is_master_command(text):
            return self._handle_master(text, cfg)
        return None

    def _handle_strip_fader_or_mute(
        self, text: str, mix_prefix: str, label: str, cfg: XR18Settings, shadow_key: int
    ) -> CommandExecutionResult:
        if self._is_mute_command(text) or self._is_unmute_command(text) or re.search(
            r"\b(?:on|off|toggle|attiva|disattiva)\b", text
        ):
            addr = f"{mix_prefix}/on"
            val = self._resolve_binary_state(text, cfg, addr, 1)
            self._send_osc(cfg, addr, int(val))
            return CommandExecutionResult(
                True,
                self.target_id,
                f"XR18: {label} {'ON' if val else 'OFF'}",
                {"address": addr, "value": val},
            )
        addr = f"{mix_prefix}/fader"
        clean_fader_text = _strip_target_tokens(text)
        cur_f = (
            self._query_osc_or_shadow(cfg, addr, self._bus_faders.get(shadow_key, 0.75))
            if _looks_relative_fader_cmd(clean_fader_text)
            else self._bus_faders.get(shadow_key, 0.75)
        )
        new_f, desc = self._compute_new_fader(clean_fader_text, cur_f, cfg.step_db)
        if new_f is not None:
            self._bus_faders[shadow_key] = new_f
            self._send_osc(cfg, addr, float(new_f))
            return CommandExecutionResult(
                True,
                self.target_id,
                f"XR18: {label} -> {desc}",
                {"address": addr, "value": round(new_f, 4)},
            )
        return CommandExecutionResult(False, self.target_id, f"XR18: parametro {label} mancante")

    def _handle_channel_send(
        self, text: str, ch: int, bus: int, cfg: XR18Settings
    ) -> CommandExecutionResult:
        # Tap point (Input=0, Pre EQ=1, Post EQ=2, Pre Fader=3, Post Fader=4, Sub Group=5)
        for aliases, tap_idx, tap_lbl in _SEND_TAP_ALIASES:
            for alias in aliases:
                if re.search(rf"\b{re.escape(alias)}\b", text):
                    # Guard: 'input' alone shouldn't trigger tap unless 'tap' or 'bus' is explicit
                    if alias in ("input", "in/lc", "sub") and not any(
                        w in text for w in ("tap", "sorgente", "sub group", "subgroup", "bus")
                    ):
                        continue
                    addr = f"/ch/{ch:02d}/mix/{bus:02d}/tap"
                    self._send_osc(cfg, addr, tap_idx)
                    return CommandExecutionResult(
                        True,
                        self.target_id,
                        f"XR18: Mandata Ch {ch} -> Bus {bus:02d} Tap {tap_lbl}",
                        {"address": addr, "value": tap_idx},
                    )

        if re.search(r"\b(?:pan|panorama)\b", text):
            addr = f"/ch/{ch:02d}/mix/{bus:02d}/pan"
            clean = _strip_target_tokens(text)
            pan_val = self._compute_pan_value(clean)
            if pan_val is not None:
                self._send_osc(cfg, addr, float(pan_val))
                pct = round((pan_val - 0.5) * 200)
                return CommandExecutionResult(
                    True,
                    self.target_id,
                    f"XR18: Pan Mandata Ch {ch} -> Bus {bus:02d}: {pct:+d}",
                    {"address": addr, "value": round(pan_val, 4)},
                )

        if self._is_mute_command(text) or self._is_unmute_command(text) or re.search(
            r"\b(?:on|off|toggle|attiva|disattiva)\b", text
        ):
            addr = f"/ch/{ch:02d}/mix/{bus:02d}/on"
            on_val = self._resolve_binary_state(text, cfg, addr, 1)
            self._send_osc(cfg, addr, on_val)
            return CommandExecutionResult(
                True,
                self.target_id,
                f"XR18: Mandata Ch {ch} -> Bus {bus:02d} {'ON' if on_val else 'OFF'}",
                {"address": addr, "value": on_val},
            )
        key = (ch, bus)
        addr = f"/ch/{ch:02d}/mix/{bus:02d}/level"
        clean_fader_text = _strip_target_tokens(text)
        cur_send = (
            self._query_osc_or_shadow(cfg, addr, self._send_levels.get(key, 0.5))
            if _looks_relative_fader_cmd(clean_fader_text)
            else self._send_levels.get(key, 0.5)
        )
        new_level, desc = self._compute_new_fader(clean_fader_text, cur_send, cfg.step_db)
        if new_level is not None:
            self._send_levels[key] = new_level
            self._send_osc(cfg, addr, float(new_level))
            return CommandExecutionResult(
                True,
                self.target_id,
                f"XR18: Mandata Ch {ch} -> Bus {bus:02d}: {desc}",
                {"address": addr, "value": round(new_level, 4)},
            )
        return CommandExecutionResult(
            False, self.target_id, f"XR18: specifica il livello mandata Ch {ch} -> Bus {bus}"
        )

    def _handle_gain(
        self, text: str, ch: int, cfg: XR18Settings
    ) -> CommandExecutionResult:
        addr = f"/headamp/{ch:02d}/gain"
        clean_text = _strip_target_tokens(text)
        cur = (
            self._query_osc_or_shadow(cfg, addr, self._ch_gains.get(ch, 0.35))
            if _looks_relative_fader_cmd(clean_text)
            else self._ch_gains.get(ch, 0.35)
        )
        nums = extract_numbers(clean_text)
        if any(w in clean_text for w in ("alza", "aumenta", "tira su", "porta su")) and not nums:
            val = min(1.0, cur + 0.05)
        elif any(w in clean_text for w in ("abbassa", "riduci", "tira giu", "porta giu")) and not nums:
            val = max(0.0, cur - 0.05)
        elif nums:
            target = nums[-1]
            if "%" in clean_text or "percento" in clean_text:
                val = max(0.0, min(1.0, target / 100.0))
            elif any(w in clean_text for w in ("alza", "aumenta", "piu")):
                cur_db = cur * 72.0 - 12.0
                val = max(0.0, min(1.0, (cur_db + abs(target) + 12.0) / 72.0))
            elif any(w in clean_text for w in ("abbassa", "riduci")):
                cur_db = cur * 72.0 - 12.0
                val = max(0.0, min(1.0, (cur_db - abs(target) + 12.0) / 72.0))
            else:
                # Treat explicit value as dB [-12..+60]
                val = max(0.0, min(1.0, (target + 12.0) / 72.0))
        else:
            return CommandExecutionResult(False, self.target_id, "XR18: valore gain mancante")

        self._ch_gains[ch] = val
        self._send_osc(cfg, addr, float(val))
        gain_db = val * 72.0 - 12.0
        return CommandExecutionResult(
            True,
            self.target_id,
            f"XR18: Gain Ch {ch} -> {gain_db:+.1f} dB",
            {"address": addr, "value": round(val, 4)},
        )

    def _xair_window_patterns(self, ctx: TargetContext) -> list[str]:
        patterns: list[str] = []
        for prog in ctx.config.programs:
            if any(k in prog.name.lower() or k in prog.id.lower() for k in ("x-air", "x air", "xr18")):
                patterns.extend([p for p in prog.window_title_patterns if p.strip()])
        for default_pat in ("X-AIR-Edit", "X AIR Edit"):
            if default_pat not in patterns:
                patterns.append(default_pat)
        return patterns

    def _send_hotkey_seq(
        self, ctx: TargetContext, keys: list[str], delay_s: float = 0.03
    ) -> bool:
        for i, key in enumerate(keys):
            if ctx.cancel_token.is_cancelled:
                return False
            if not ctx.os_bridge.send_hotkey(key):
                return False
            if i < len(keys) - 1 and delay_s > 0:
                if ctx.cancel_token.wait(delay_s):
                    return False
        return True

    def _maybe_handle_ui_navigation(
        self, text: str, cfg: XR18Settings, ctx: TargetContext
    ) -> CommandExecutionResult | None:
        nav_words = (
            "tab",
            "scheda",
            "linguetta",
            "pagina",
            "schermata",
            "finestra",
            "apri",
            "vai",
            "mostra",
            "entra",
            "seleziona",
        )
        if not any(re.search(rf"\b{w}\b", text) for w in nav_words):
            return None

        # Match explicit utility / floating window shortcuts when asked
        explicit_win_word = any(
            re.search(rf"\b{w}\b", text)
            for w in ("finestra", "rta", "setup", "in/out", "inout", "routing", "dca", "recorder", "registratore", "buses", "user 1", "user1", "user 2", "user2", "rinomina")
        )
        is_explicit_open = any(re.search(rf"\b{w}\b", text) for w in ("apri", "mostra", "vai", "finestra", "entra"))
        if explicit_win_word or "finestra " in text:
            for triggers, hk, label in _XAIR_WINDOW_HOTKEYS:
                for trig in triggers:
                    if re.search(rf"\b{re.escape(trig)}\b", text):
                        if label.startswith("FX") and "finestra" not in text:
                            continue
                        if label == "Snapshot" and "finestra" not in text:
                            continue
                        if not ctx.os_bridge.focus_window(self._xair_window_patterns(ctx)):
                            return CommandExecutionResult(
                                False, self.target_id, "X-AIR Edit non trovato sullo schermo"
                            )
                        ctx.cancel_token.wait(0.08)
                        ok = self._send_hotkey_seq(ctx, [hk])
                        return CommandExecutionResult(
                            ok,
                            self.target_id,
                            f"X-AIR Edit: Finestra {label} ({hk})" if ok else f"Errore invio {hk}",
                            {"hotkey": hk},
                        )

        # Match one of the 10 main X-AIR-Edit tabs (Mixer .. Meter)
        matched_tab: tuple[str, int] | None = None
        for key, idx in sorted(_XAIR_TAB_INDEX.items(), key=lambda kv: len(kv[0]), reverse=True):
            if re.search(rf"\b{re.escape(key)}\b", text):
                # Require explicit tab/nav framing so 'apri main' / 'canale 1 eq' doesn't steal OSC verbs
                if key == "main" and not any(w in text for w in ("tab", "scheda", "linguetta", "pagina", "schermata", "mostra", "vai")):
                    continue
                if key in ("channel", "canale") and not any(w in text for w in ("tab", "scheda", "linguetta", "pagina", "schermata", "vai")):
                    continue
                if key in ("eq", "gate", "comp", "fx") and not is_explicit_open and not any(
                    w in text for w in ("tab", "scheda", "linguetta", "pagina", "schermata")
                ):
                    continue
                matched_tab = (key, idx)
                break

        ch = self._resolve_channel(text, cfg)
        wants_select = bool(re.search(r"\bseleziona\b", text)) and ch is not None
        if matched_tab is None and not wants_select:
            return None

        if not ctx.os_bridge.focus_window(self._xair_window_patterns(ctx)):
            return CommandExecutionResult(
                False, self.target_id, "X-AIR Edit non trovato sullo schermo"
            )
        if ctx.cancel_token.wait(0.08):
            return CommandExecutionResult(False, self.target_id, "Comando interrotto da PANIC")

        seq: list[str] = ["<tab>"] if matched_tab is not None else []
        if ch is not None:
            if not seq:
                seq.append("<tab>")
            seq.append("<home>")
            seq.extend(["<right>"] * (ch - 1))
        if matched_tab is not None:
            seq.extend(["<shift>+<right>"] * matched_tab[1])

        ok = self._send_hotkey_seq(ctx, seq, delay_s=0.03)
        parts: list[str] = []
        if ch is not None:
            parts.append(f"Canale {ch}")
        if matched_tab is not None:
            parts.append(f"Tab {matched_tab[0].title()}")
        desc = " -> ".join(parts) if parts else "Navigazione"
        return CommandExecutionResult(
            ok,
            self.target_id,
            f"X-AIR Edit: {desc}" if ok else f"X-AIR Edit: errore sequenza {desc}",
            {"tab_index": matched_tab[1] if matched_tab else None, "channel": ch, "keys": seq},
        )

    def _resolve_binary_state(
        self,
        text: str,
        cfg: XR18Settings,
        addr: str,
        shadow_val: int,
        extra_on: tuple[str, ...] = (),
        extra_off: tuple[str, ...] = (),
    ) -> int:
        off_words = ("off", "disattiva", "spegni", "disabilita", "normale", "chiudi") + extra_off
        on_words = ("on", "attiva", "accendi", "abilita", "apri") + extra_on
        if any(re.search(rf"\b{w}\b", text) for w in off_words):
            return 0
        if re.search(r"\b(?:toggle|cambia|scambia)\b", text):
            cur = int(round(self._query_osc_or_shadow(cfg, addr, float(shadow_val))))
            return 0 if cur >= 1 else 1
        if any(re.search(rf"\b{w}\b", text) for w in on_words):
            return 1
        cur = int(round(self._query_osc_or_shadow(cfg, addr, float(shadow_val))))
        return 0 if cur >= 1 else 1

    def _handle_phantom(
        self, text: str, ch: int, cfg: XR18Settings
    ) -> CommandExecutionResult:
        addr = f"/headamp/{ch:02d}/phantom"
        val = self._resolve_binary_state(text, cfg, addr, self._ch_phantoms.get(ch, 0))
        self._ch_phantoms[ch] = val
        self._send_osc(cfg, addr, int(val))
        return CommandExecutionResult(
            True,
            self.target_id,
            f"XR18: +48V Phantom Ch {ch} {'ON' if val else 'OFF'}",
            {"address": addr, "value": val},
        )

    def _handle_phase_invert(
        self, text: str, ch: int, cfg: XR18Settings
    ) -> CommandExecutionResult:
        addr = f"/ch/{ch:02d}/preamp/invert"
        val = self._resolve_binary_state(text, cfg, addr, self._ch_inverts.get(ch, 0))
        self._ch_inverts[ch] = val
        self._send_osc(cfg, addr, int(val))
        return CommandExecutionResult(
            True,
            self.target_id,
            f"XR18: Fase (Invert Ø) Ch {ch} {'ON' if val else 'OFF'}",
            {"address": addr, "value": val},
        )

    def _handle_usb_switch(
        self, text: str, ch: int, cfg: XR18Settings
    ) -> CommandExecutionResult:
        addr = f"/ch/{ch:02d}/preamp/rtnsw"
        val = self._resolve_binary_state(
            text,
            cfg,
            addr,
            self._ch_rtnsws.get(ch, 0),
            extra_on=("usb",),
            extra_off=("analogico", "analogica", "analog", "mic", "preamp"),
        )
        # If user wrote e.g. 'canale 1 usb off', off_words already returned 0 before extra_on
        self._ch_rtnsws[ch] = val
        self._send_osc(cfg, addr, int(val))
        src_lbl = "USB" if val else "Analogico"
        return CommandExecutionResult(
            True,
            self.target_id,
            f"XR18: Sorgente Input Ch {ch} -> {src_lbl}",
            {"address": addr, "value": val},
        )

    def _handle_trim(
        self, text: str, ch: int, cfg: XR18Settings
    ) -> CommandExecutionResult:
        addr = f"/ch/{ch:02d}/preamp/rtntrim"
        clean_text = _strip_target_tokens(text)
        cur = (
            self._query_osc_or_shadow(cfg, addr, self._ch_trims.get(ch, 0.5))
            if _looks_relative_fader_cmd(clean_text)
            else self._ch_trims.get(ch, 0.5)
        )
        nums = extract_numbers(clean_text)
        if any(w in clean_text for w in ("alza", "aumenta", "tira su", "porta su")) and not nums:
            val = min(1.0, cur + (2.0 / 36.0))
        elif any(w in clean_text for w in ("abbassa", "riduci", "tira giu", "porta giu")) and not nums:
            val = max(0.0, cur - (2.0 / 36.0))
        elif nums:
            target = nums[-1]
            cur_db = cur * 36.0 - 18.0
            if any(w in clean_text for w in ("alza", "aumenta", "piu")):
                new_db = cur_db + abs(target)
            elif any(w in clean_text for w in ("abbassa", "riduci")):
                new_db = cur_db - abs(target)
            else:
                new_db = target
            val = max(0.0, min(1.0, (new_db + 18.0) / 36.0))
        else:
            return CommandExecutionResult(False, self.target_id, "XR18: valore Trim mancante")

        self._ch_trims[ch] = val
        self._send_osc(cfg, addr, float(val))
        trim_db = val * 36.0 - 18.0
        return CommandExecutionResult(
            True,
            self.target_id,
            f"XR18: USB Trim Ch {ch} -> {trim_db:+.1f} dB",
            {"address": addr, "value": round(val, 4)},
        )

    def _handle_channel_link(
        self, text: str, ch: int, cfg: XR18Settings
    ) -> CommandExecutionResult:
        odd_ch = ch if (ch % 2 == 1) else (ch - 1)
        pair = f"{odd_ch}-{odd_ch + 1}"
        addr = f"/config/chlink/{pair}"
        val = self._resolve_binary_state(
            text,
            cfg,
            addr,
            self._ch_links.get(pair, 0),
            extra_on=("collega", "linka", "unisci", "link", "stereo"),
            extra_off=("separa", "scollega", "unlink"),
        )
        self._ch_links[pair] = val
        self._send_osc(cfg, addr, int(val))
        return CommandExecutionResult(
            True,
            self.target_id,
            f"XR18: Stereo Link Canali {pair} {'ON' if val else 'OFF'}",
            {"address": addr, "value": val},
        )

    @staticmethod
    def _is_channel_main_command(text: str) -> bool:
        if any(w in text for w in ("dca", "mute group", "mutegroup", "gruppo mute", "automix", "weight", "peso", "main stereo", "panorama")):
            return True
        if re.search(r"\b(?:pan|lr)\b", text):
            return True
        if "main" in text and "eq" not in text and "equalizz" not in text:
            return True
        return False

    @staticmethod
    def _compute_pan_value(clean_text: str) -> float | None:
        if any(w in clean_text for w in ("centro", "center", "centrale", "zero")):
            return 0.5
        nums = extract_numbers(clean_text)
        is_left = any(w in clean_text for w in ("sinistra", "left", " sx"))
        is_right = any(w in clean_text for w in ("destra", "right", " dx"))
        if is_left and not nums:
            return 0.0
        if is_right and not nums:
            return 1.0
        if nums:
            raw = float(nums[-1])
            if is_left and raw > 0:
                raw = -raw
            val = 0.5 + (max(-100.0, min(100.0, raw)) / 200.0)
            return max(0.0, min(1.0, val))
        return None

    def _toggle_bitmask_flag(
        self, text: str, cfg: XR18Settings, addr: str, bit_one_based: int, cache: dict[str, int]
    ) -> tuple[int, bool]:
        cur = int(round(self._query_osc_or_shadow(cfg, addr, float(cache.get(addr, 0)))))
        mask_bit = 1 << (bit_one_based - 1)
        if re.search(r"\b(?:off|disattiva|spegni|togli|rimuovi|escludi)\b", text):
            new_mask = cur & ~mask_bit
        elif re.search(r"\b(?:on|attiva|accendi|assegna|metti|aggiungi)\b", text):
            new_mask = cur | mask_bit
        else:
            new_mask = cur ^ mask_bit
        cache[addr] = new_mask
        return new_mask, bool(new_mask & mask_bit)

    def _handle_channel_insert(
        self, text: str, ch: int, cfg: XR18Settings
    ) -> CommandExecutionResult:
        m_fx = re.search(r"\b(?:fx|effetto)\s*([1-4])\b", text)
        if m_fx:
            slot = int(m_fx.group(1))
            # Channel insert selection (0=OFF, 1..8 = FX1L..FX4R)
            sel_idx = (slot - 1) * 2 + (2 if "destra" in text or " r" in text else 1)
            self._send_osc(cfg, f"/ch/{ch:02d}/insert/sel", sel_idx)
            self._send_osc(cfg, f"/ch/{ch:02d}/insert/on", 1)
            return CommandExecutionResult(
                True,
                self.target_id,
                f"XR18: Insert Ch {ch} -> FX {slot} (ON)",
                {"address": f"/ch/{ch:02d}/insert/sel", "value": sel_idx},
            )
        addr = f"/ch/{ch:02d}/insert/on"
        val = self._resolve_binary_state(text, cfg, addr, 0)
        self._send_osc(cfg, addr, int(val))
        return CommandExecutionResult(
            True,
            self.target_id,
            f"XR18: Insert Ch {ch} {'ON' if val else 'OFF'}",
            {"address": addr, "value": val},
        )

    def _handle_channel_main_assignments(
        self, text: str, ch: int, cfg: XR18Settings
    ) -> CommandExecutionResult:
        m_dca = re.search(r"\bdca(?:\s+group)?\s*([1-4])\b", text)
        if m_dca:
            idx = int(m_dca.group(1))
            addr = f"/ch/{ch:02d}/grp/dca"
            mask, is_on = self._toggle_bitmask_flag(
                text, cfg, addr, idx, cache={k: v for k, v in self._scalar_cache.items()}
            )
            self._scalar_cache[addr] = float(mask)
            self._send_osc(cfg, addr, int(mask))
            return CommandExecutionResult(
                True,
                self.target_id,
                f"XR18: Ch {ch} DCA {idx} {'ON' if is_on else 'OFF'}",
                {"address": addr, "value": mask},
            )

        m_mg = re.search(r"\b(?:mute\s*group|mutegroup|gruppo\s*mute)\s*([1-4])\b", text)
        if m_mg:
            idx = int(m_mg.group(1))
            addr = f"/ch/{ch:02d}/grp/mute"
            mask, is_on = self._toggle_bitmask_flag(
                text, cfg, addr, idx, cache={k: v for k, v in self._scalar_cache.items()}
            )
            self._scalar_cache[addr] = float(mask)
            self._send_osc(cfg, addr, int(mask))
            return CommandExecutionResult(
                True,
                self.target_id,
                f"XR18: Ch {ch} Mute Group {idx} {'ON' if is_on else 'OFF'}",
                {"address": addr, "value": mask},
            )

        if "automix" in text or "weight" in text or "peso" in text:
            if "weight" in text or "peso" in text or any(w in text for w in ("db", "alza", "abbassa", "zero")):
                addr = f"/ch/{ch:02d}/automix/weight"
                clean = _strip_target_tokens(text)
                val, disp = self._adjust_linear_param(
                    cfg, addr, clean, 0.5, -12.0, 12.0, default_delta=2.0, unit="dB"
                )
                if val is not None:
                    self._send_osc(cfg, addr, float(val))
                    return CommandExecutionResult(
                        True,
                        self.target_id,
                        f"XR18: AutoMix Ch {ch} Weight -> {disp}",
                        {"address": addr, "value": round(val, 4)},
                    )
            grp_val = 0 if re.search(r"\b(?:off|disattiva|nessuno)\b", text) else (
                2 if re.search(r"\by\b", text) else 1
            )
            addr = f"/ch/{ch:02d}/automix/group"
            self._send_osc(cfg, addr, grp_val)
            grp_lbl = ("OFF", "X", "Y")[grp_val]
            return CommandExecutionResult(
                True,
                self.target_id,
                f"XR18: AutoMix Ch {ch} -> {grp_lbl}",
                {"address": addr, "value": grp_val},
            )

        if re.search(r"\b(?:pan|panorama)\b", text):
            addr = f"/ch/{ch:02d}/mix/pan"
            clean = _strip_target_tokens(text)
            pan_val = self._compute_pan_value(clean)
            if pan_val is None and any(w in clean for w in ("alza", "destra", "sposta", "abbassa", "sinistra")):
                cur = self._query_osc_or_shadow(cfg, addr, self._ch_pans.get(ch, 0.5))
                step = 0.1
                delta = step if ("destra" in clean or "dx" in clean or "alza" in clean) else -step
                pan_val = max(0.0, min(1.0, cur + delta))
            if pan_val is not None:
                self._ch_pans[ch] = pan_val
                self._send_osc(cfg, addr, float(pan_val))
                pct = round((pan_val - 0.5) * 200)
                return CommandExecutionResult(
                    True,
                    self.target_id,
                    f"XR18: Pan Ch {ch} -> {pct:+d}",
                    {"address": addr, "value": round(pan_val, 4)},
                )
            return CommandExecutionResult(False, self.target_id, "XR18: direzione/valore Pan mancante")

        addr = f"/ch/{ch:02d}/mix/lr"
        val = self._resolve_binary_state(text, cfg, addr, self._lr_assign.get(ch, 1))
        self._lr_assign[ch] = val
        self._send_osc(cfg, addr, int(val))
        return CommandExecutionResult(
            True,
            self.target_id,
            f"XR18: Ch {ch} Main Stereo (LR) {'ON' if val else 'OFF'}",
            {"address": addr, "value": val},
        )

    def _adjust_linear_param(
        self,
        cfg: XR18Settings,
        addr: str,
        clean_text: str,
        fallback_norm: float,
        vmin: float,
        vmax: float,
        default_delta: float,
        unit: str = "",
    ) -> tuple[float | None, str]:
        span = vmax - vmin
        cur_norm = self._query_osc_or_shadow(cfg, addr, self._scalar_cache.get(addr, fallback_norm))
        cur_real = vmin + cur_norm * span
        nums = extract_numbers(clean_text)
        is_up = any(w in clean_text for w in ("alza", "aumenta", "piu", "su"))
        is_down = any(w in clean_text for w in ("abbassa", "riduci", "togli", "meno", "giu"))
        if "zero" in clean_text or "0 db" in clean_text:
            target = max(vmin, min(vmax, 0.0))
        elif (is_up or is_down) and (not nums or "di " in clean_text or not re.search(r"\b(?:a|al)\s*[+-]?\d", clean_text)):
            delta = abs(nums[-1]) if nums else default_delta
            target = max(vmin, min(vmax, cur_real + (delta if is_up else -delta)))
        elif nums:
            target = max(vmin, min(vmax, float(nums[-1])))
        else:
            return None, ""
        norm = max(0.0, min(1.0, (target - vmin) / span))
        self._scalar_cache[addr] = norm
        u_str = f" {unit}" if unit else ""
        return norm, f"{target:.1f}{u_str}"

    def _handle_sidechain_filter(
        self, text: str, base_prefix: str, block_label: str, cfg: XR18Settings
    ) -> CommandExecutionResult:
        if "keysrc" in text or "key src" in text or "sorgente" in text:
            addr = f"{base_prefix}/keysrc"
            bus = self._resolve_bus(text, cfg)
            if "self" in text:
                val, lbl = 0, "Self"
            elif bus is not None and 1 <= bus <= 6:
                val, lbl = 16 + bus, f"Bus {bus}"
            else:
                after_src = re.split(r"\b(?:key\s*src|keysrc|sorgente)\b", text)[-1]
                ch_src = self._resolve_channel(after_src, cfg) or self._resolve_channel(text, cfg)
                if ch_src and 1 <= ch_src <= 16:
                    val, lbl = ch_src, f"Canale {ch_src}"
                else:
                    return CommandExecutionResult(False, self.target_id, f"XR18: KeySrc non valido ({block_label})")
            self._send_osc(cfg, addr, int(val))
            return CommandExecutionResult(
                True,
                self.target_id,
                f"XR18: {block_label} KeySrc -> {lbl}",
                {"address": addr, "value": val},
            )

        clean = _strip_target_tokens(text)
        if any(w in clean for w in ("type", "tipo", "lc6", "lc12", "hc6", "hc12")):
            for aliases, idx, lbl in _SC_FILTER_TYPES:
                for alias in aliases:
                    if re.search(rf"\b{re.escape(alias)}\b", clean):
                        addr = f"{base_prefix}/filter/type"
                        self._send_osc(cfg, addr, idx)
                        return CommandExecutionResult(
                            True,
                            self.target_id,
                            f"XR18: {block_label} Filter Type -> {lbl}",
                            {"address": addr, "value": idx},
                        )

        if any(w in clean for w in ("hz", "khz", "freq", "frequenza")) or re.search(r"\b\d{1,2}k\d{1,2}\b", clean):
            hz = self._parse_freq_hz(clean)
            if hz is not None:
                val = freq_to_osc(hz, 20.0, 20000.0)
                addr = f"{base_prefix}/filter/f"
                self._send_osc(cfg, addr, float(val))
                return CommandExecutionResult(
                    True,
                    self.target_id,
                    f"XR18: {block_label} Filter Freq -> {hz:.0f} Hz",
                    {"address": addr, "value": round(val, 4)},
                )

        addr = f"{base_prefix}/filter/on"
        val = self._resolve_binary_state(text, cfg, addr, 0)
        self._send_osc(cfg, addr, int(val))
        return CommandExecutionResult(
            True,
            self.target_id,
            f"XR18: {block_label} Sidechain Filter {'ON' if val else 'OFF'}",
            {"address": addr, "value": val},
        )

    def _handle_gate(
        self, text: str, ch: int, cfg: XR18Settings
    ) -> CommandExecutionResult:
        prefix = f"/ch/{ch:02d}/gate"
        clean = _strip_target_tokens(text)

        if any(w in clean for w in ("filter", "filtro", "keysrc", "key src")):
            return self._handle_sidechain_filter(text, prefix, f"Gate Ch {ch}", cfg)

        if any(w in clean for w in ("mode", "modo", "exp", "ducker", "duck")):
            for aliases, idx, lbl in _GATE_MODE_ALIASES:
                for alias in aliases:
                    if alias in clean:
                        addr = f"{prefix}/mode"
                        self._send_osc(cfg, addr, idx)
                        return CommandExecutionResult(
                            True, self.target_id, f"XR18: Gate Ch {ch} Mode -> {lbl}", {"address": addr, "value": idx}
                        )

        if any(w in clean for w in ("soglia", "threshold", "thr")):
            addr = f"{prefix}/thr"
            val, disp = self._adjust_linear_param(cfg, addr, clean, 0.325, -80.0, 0.0, 3.0, "dB")
            if val is None:
                return CommandExecutionResult(False, self.target_id, "XR18: soglia gate mancante")
            self._send_osc(cfg, addr, float(val))
            return CommandExecutionResult(
                True, self.target_id, f"XR18: Gate Ch {ch} Soglia -> {disp}", {"address": addr, "value": round(val, 4)}
            )

        if "range" in clean:
            addr = f"{prefix}/range"
            val, disp = self._adjust_linear_param(cfg, addr, clean, 1.0, 3.0, 60.0, 5.0, "dB")
            if val is None:
                return CommandExecutionResult(False, self.target_id, "XR18: range gate mancante")
            self._send_osc(cfg, addr, float(val))
            return CommandExecutionResult(
                True, self.target_id, f"XR18: Gate Ch {ch} Range -> {disp}", {"address": addr, "value": round(val, 4)}
            )

        if any(w in clean for w in ("attack", "attacco")):
            addr = f"{prefix}/attack"
            val, disp = self._adjust_linear_param(cfg, addr, clean, 0.01, 0.0, 120.0, 5.0, "ms")
            if val is None:
                return CommandExecutionResult(False, self.target_id, "XR18: attack gate mancante")
            self._send_osc(cfg, addr, float(val))
            return CommandExecutionResult(
                True, self.target_id, f"XR18: Gate Ch {ch} Attack -> {disp}", {"address": addr, "value": round(val, 4)}
            )

        if "hold" in clean or "release" in clean or "rilascio" in clean:
            is_hold = "hold" in clean
            vmin, vmax = (0.02, 2000.0) if is_hold else (5.0, 4000.0)
            addr = f"{prefix}/{'hold' if is_hold else 'release'}"
            nums = extract_numbers(clean)
            if not nums:
                return CommandExecutionResult(False, self.target_id, f"XR18: valore {'Hold' if is_hold else 'Release'} mancante")
            val = _log_curve_to_osc(nums[-1], vmin, vmax)
            self._send_osc(cfg, addr, float(val))
            return CommandExecutionResult(
                True, self.target_id, f"XR18: Gate Ch {ch} {'Hold' if is_hold else 'Release'} -> {nums[-1]:.2f} ms", {"address": addr, "value": round(val, 4)}
            )

        addr = f"{prefix}/on"
        on_val = self._resolve_binary_state(text, cfg, addr, self._gate_on.get(ch, 0))
        self._gate_on[ch] = on_val
        self._send_osc(cfg, addr, on_val)
        return CommandExecutionResult(
            True, self.target_id, f"XR18: Gate Ch {ch} {'ON' if on_val else 'OFF'}", {"address": addr, "value": on_val}
        )

    def _handle_compressor(
        self, text: str, ch: int, cfg: XR18Settings
    ) -> CommandExecutionResult:
        prefix = f"/ch/{ch:02d}/dyn"
        clean = _strip_target_tokens(text)

        if any(w in clean for w in ("filter", "filtro", "keysrc", "key src")):
            return self._handle_sidechain_filter(text, prefix, f"Comp Ch {ch}", cfg)

        if "auto" in clean:
            addr = f"{prefix}/auto"
            val = self._resolve_binary_state(text, cfg, addr, 0)
            self._send_osc(cfg, addr, int(val))
            return CommandExecutionResult(
                True, self.target_id, f"XR18: Comp Ch {ch} Auto Time {'ON' if val else 'OFF'}", {"address": addr, "value": val}
            )

        if "mode" in clean or re.search(r"\bexp\b", clean):
            val = 1 if re.search(r"\b(?:exp|expander)\b", clean) else 0
            addr = f"{prefix}/mode"
            self._send_osc(cfg, addr, val)
            return CommandExecutionResult(
                True, self.target_id, f"XR18: Comp Ch {ch} Mode -> {'Exp' if val else 'Comp'}", {"address": addr, "value": val}
            )

        if any(w in clean for w in ("rms", "peak")):
            val = 1 if "rms" in clean else 0
            addr = f"{prefix}/det"
            self._send_osc(cfg, addr, val)
            return CommandExecutionResult(
                True, self.target_id, f"XR18: Comp Ch {ch} Detector -> {'RMS' if val else 'Peak'}", {"address": addr, "value": val}
            )

        if re.search(r"\b(?:lin|log)\b", clean):
            val = 1 if re.search(r"\blog\b", clean) else 0
            addr = f"{prefix}/env"
            self._send_osc(cfg, addr, val)
            return CommandExecutionResult(
                True, self.target_id, f"XR18: Comp Ch {ch} Envelope -> {'Log' if val else 'Lin'}", {"address": addr, "value": val}
            )

        if "knee" in clean:
            nums = extract_numbers(clean)
            if not nums:
                return CommandExecutionResult(False, self.target_id, "XR18: valore Knee (0..5) mancante")
            k = max(0, min(5, int(round(nums[-1]))))
            val = k / 5.0
            addr = f"{prefix}/knee"
            self._send_osc(cfg, addr, float(val))
            return CommandExecutionResult(
                True, self.target_id, f"XR18: Comp Ch {ch} Knee -> {k}", {"address": addr, "value": round(val, 4)}
            )

        if any(w in clean for w in ("soglia", "threshold", "thr")):
            addr = f"{prefix}/thr"
            val, disp = self._adjust_linear_param(cfg, addr, clean, 0.575, -60.0, 0.0, 3.0, "dB")
            if val is None:
                return CommandExecutionResult(False, self.target_id, "XR18: soglia compressore mancante")
            self._send_osc(cfg, addr, float(val))
            return CommandExecutionResult(
                True, self.target_id, f"XR18: Compressore Ch {ch} Soglia -> {disp}", {"address": addr, "value": round(val, 4)}
            )

        if "ratio" in clean or "rapporto" in clean:
            nums = extract_numbers(clean)
            if not nums:
                return CommandExecutionResult(False, self.target_id, "XR18: ratio compressore mancante")
            target_r = nums[-1]
            idx = min(range(len(_COMP_RATIOS)), key=lambda i: abs(_COMP_RATIOS[i] - target_r))
            addr = f"{prefix}/ratio"
            self._send_osc(cfg, addr, idx)
            return CommandExecutionResult(
                True, self.target_id, f"XR18: Compressore Ch {ch} Ratio -> {_COMP_RATIOS[idx]}:1", {"address": addr, "value": idx}
            )

        if "mix" in clean:
            addr = f"{prefix}/mix"
            val, disp = self._adjust_linear_param(cfg, addr, clean, 1.0, 0.0, 100.0, 10.0, "%")
            if val is None:
                return CommandExecutionResult(False, self.target_id, "XR18: mix compressore (0..100%) mancante")
            self._send_osc(cfg, addr, float(val))
            return CommandExecutionResult(
                True, self.target_id, f"XR18: Comp Ch {ch} Mix -> {disp}", {"address": addr, "value": round(val, 4)}
            )

        if any(w in clean for w in ("makeup", "mgain", "gain")):
            addr = f"{prefix}/mgain"
            val, disp = self._adjust_linear_param(cfg, addr, clean, 0.0, 0.0, 24.0, 1.5, "dB")
            if val is None:
                return CommandExecutionResult(False, self.target_id, "XR18: gain/makeup compressore mancante")
            self._send_osc(cfg, addr, float(val))
            return CommandExecutionResult(
                True, self.target_id, f"XR18: Comp Ch {ch} Makeup Gain -> {disp}", {"address": addr, "value": round(val, 4)}
            )

        if any(w in clean for w in ("attack", "attacco")):
            addr = f"{prefix}/attack"
            val, disp = self._adjust_linear_param(cfg, addr, clean, 0.08, 0.0, 120.0, 5.0, "ms")
            if val is None:
                return CommandExecutionResult(False, self.target_id, "XR18: attack compressore mancante")
            self._send_osc(cfg, addr, float(val))
            return CommandExecutionResult(
                True, self.target_id, f"XR18: Comp Ch {ch} Attack -> {disp}", {"address": addr, "value": round(val, 4)}
            )

        if "hold" in clean or "release" in clean or "rilascio" in clean:
            is_hold = "hold" in clean
            vmin, vmax = (0.02, 2000.0) if is_hold else (5.0, 4000.0)
            addr = f"{prefix}/{'hold' if is_hold else 'release'}"
            nums = extract_numbers(clean)
            if not nums:
                return CommandExecutionResult(False, self.target_id, f"XR18: valore {'Hold' if is_hold else 'Release'} mancante")
            val = _log_curve_to_osc(nums[-1], vmin, vmax)
            self._send_osc(cfg, addr, float(val))
            return CommandExecutionResult(
                True, self.target_id, f"XR18: Comp Ch {ch} {'Hold' if is_hold else 'Release'} -> {nums[-1]:.2f} ms", {"address": addr, "value": round(val, 4)}
            )

        addr = f"{prefix}/on"
        on_val = self._resolve_binary_state(text, cfg, addr, self._dyn_on.get(ch, 0))
        self._dyn_on[ch] = on_val
        self._send_osc(cfg, addr, on_val)
        return CommandExecutionResult(
            True, self.target_id, f"XR18: Compressore Ch {ch} {'ON' if on_val else 'OFF'}", {"address": addr, "value": on_val}
        )

    @staticmethod
    def _is_eq_command(text: str) -> bool:
        if any(
            w in text
            for w in (
                "eq",
                "equalizzatore",
                "equalizzazione",
                "low cut",
                "taglia bassi",
                "hpf",
                "banda",
                "bassi",
                "medi",
                "alti",
                "lomid",
                "lo mid",
                "low mid",
                "himid",
                "hi mid",
                "high mid",
                "lcut",
                "lshv",
                "peq",
                "veq",
                "hshv",
                "hcut",
                "geq",
                "teq",
                "flat",
                "qual",
                "stringi",
                "allarga",
            )
        ):
            return True
        return bool(re.search(r"\b(?:q|b[1-6]|reset)\b", text))

    @staticmethod
    def _strip_eq_tokens(text: str) -> str:
        cleaned = _strip_target_tokens(text)
        cleaned = re.sub(r"\b(?:master|generale|main|lr)\b", " ", cleaned)
        cleaned = re.sub(r"\b(?:banda|band)\s*[1-6]\b", " ", cleaned)
        cleaned = re.sub(r"\bb[1-6]\b", " ", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip()

    @staticmethod
    def _resolve_eq_band(text: str, max_bands: int = 4) -> int | None:
        m_band = re.search(r"\b(?:banda|band)\s*([1-6])\b", text)
        if m_band:
            return int(m_band.group(1))
        m_short = re.search(r"\bb([1-6])\b", text)
        if m_short:
            return int(m_short.group(1))
        if any(w in text for w in ("medio bassi", "medio-bassi", "lo mid", "lomid", "low mid")):
            return 2
        if any(w in text for w in ("medio alti", "medio-alti", "hi mid", "himid", "high mid")):
            return 4 if max_bands == 6 else 3
        if any(w in text for w in ("bassi", "low")):
            return 1
        if any(w in text for w in ("medi", "mid")):
            return 3 if max_bands == 6 else 2
        if any(w in text for w in ("alti", "high")):
            return max_bands
        return None

    @staticmethod
    def _resolve_eq_mode(text: str) -> tuple[int, str] | None:
        for aliases, mode_idx in _EQ_MODE_ALIASES:
            for alias in aliases:
                if re.search(rf"\b{re.escape(alias)}\b", text):
                    return mode_idx, _EQ_MODE_NAMES[mode_idx]
        return None

    @staticmethod
    def _parse_freq_hz(clean_text: str) -> float | None:
        m_k = re.search(r"\b(\d{1,2})\s*k\s*(\d{1,2})\b", clean_text)
        if m_k:
            return float(f"{m_k.group(1)}.{m_k.group(2)}") * 1000.0
        m_khz = re.search(r"(\d+(?:[.,]\d+)?)\s*khz\b", clean_text)
        if m_khz:
            return float(m_khz.group(1).replace(",", ".")) * 1000.0
        nums = [n for n in extract_numbers(clean_text) if n >= 20.0]
        if nums:
            return float(nums[-1])
        return None

    def _handle_rta(self, text: str, cfg: XR18Settings) -> CommandExecutionResult:
        if "pre" in text or "post" in text:
            val = 0 if re.search(r"\bpre\b", text) else 1
            addr = "/-stat/rta/pos"
            self._send_osc(cfg, addr, val)
            return CommandExecutionResult(
                True,
                self.target_id,
                f"XR18: RTA posizione -> {'PRE-EQ' if val == 0 else 'POST-EQ'}",
                {"address": addr, "value": val},
            )
        ch = self._resolve_channel(text, cfg)
        if ch is not None:
            idx = ch - 1
            addr = "/-stat/rta/source"
            self._send_osc(cfg, addr, idx)
            return CommandExecutionResult(
                True,
                self.target_id,
                f"XR18: RTA sorgente -> Canale {ch}",
                {"address": addr, "value": idx},
            )
        if any(w in text for w in ("monitor", "mon", "solo")):
            addr = "/-stat/rta/source"
            self._send_osc(cfg, addr, 32)
            return CommandExecutionResult(
                True,
                self.target_id,
                "XR18: RTA sorgente -> Monitor",
                {"address": addr, "value": 32},
            )
        return CommandExecutionResult(
            False,
            self.target_id,
            "XR18: specifica 'rta pre', 'rta post', 'rta canale N' (o 'finestra rta')",
        )

    def _handle_eq_reset_or_flat(
        self,
        text: str,
        prefix: str,
        target_label: str,
        cfg: XR18Settings,
        defaults: dict[int, tuple[int, float, float, float]],
    ) -> CommandExecutionResult:
        is_reset = bool(re.search(r"\b(?:reset|azzera|ripristina)\b", text))
        for b, (m_idx, f_osc, g_osc, q_osc) in defaults.items():
            if is_reset:
                self._send_osc(cfg, f"{prefix}/eq/{b}/type", m_idx)
                self._send_osc(cfg, f"{prefix}/eq/{b}/f", float(f_osc))
                self._send_osc(cfg, f"{prefix}/eq/{b}/q", float(q_osc))
                self._eq_freqs[(prefix, b)] = f_osc
                self._eq_qs[(prefix, b)] = q_osc
            self._send_osc(cfg, f"{prefix}/eq/{b}/g", float(g_osc))
            self._eq_gains[(prefix, b)] = g_osc
        n_bands = len(defaults)
        action_lbl = f"Reset completo {n_bands} bande" if is_reset else f"Flat 0.0 dB su {n_bands} bande"
        return CommandExecutionResult(
            True,
            self.target_id,
            f"XR18: EQ {target_label} {action_lbl}",
            {"address": f"{prefix}/eq/{'reset' if is_reset else 'flat'}"},
        )

    def _handle_eq(
        self, text: str, ch: int, cfg: XR18Settings
    ) -> CommandExecutionResult:
        return self._handle_eq_for_prefix(
            text,
            prefix=f"/ch/{ch:02d}",
            target_label=f"Ch {ch}",
            cfg=cfg,
            max_bands=4,
            allow_cuts=True,
        )

    def _handle_eq_for_prefix(
        self,
        text: str,
        prefix: str,
        target_label: str,
        cfg: XR18Settings,
        max_bands: int = 4,
        allow_cuts: bool = True,
    ) -> CommandExecutionResult:
        band = self._resolve_eq_band(text, max_bands=max_bands)
        if band is not None and band > max_bands:
            return CommandExecutionResult(
                False,
                self.target_id,
                f"XR18: {target_label} ha {max_bands} bande EQ (banda {band} non valida)",
            )

        # Low Cut / HPF (dedicated channel preamp filter, when not targeting an EQ band's Mode)
        if band is None and any(w in text for w in ("low cut", "taglia bassi", "hpf")):
            if not allow_cuts:
                return CommandExecutionResult(
                    False,
                    self.target_id,
                    f"XR18: {target_label} (6 bande) non dispone di Low Cut / High Cut",
                )
            nums = [n for n in extract_numbers(text) if n >= 20]
            if nums:
                hz = max(20.0, min(400.0, nums[-1]))
                val = freq_to_osc(hz, 20.0, 400.0)
                self._send_osc(cfg, f"{prefix}/preamp/hpon", 1)
                self._send_osc(cfg, f"{prefix}/preamp/hpf", float(val))
                return CommandExecutionResult(
                    True,
                    self.target_id,
                    f"XR18: HPF {target_label} a {hz:.0f} Hz",
                    {"address": f"{prefix}/preamp/hpf", "value": round(val, 4)},
                )
            on_val = self._resolve_binary_state(text, cfg, f"{prefix}/preamp/hpon", 1)
            addr = f"{prefix}/preamp/hpon"
            self._send_osc(cfg, addr, on_val)
            return CommandExecutionResult(
                True,
                self.target_id,
                f"XR18: HPF {target_label} {'ON' if on_val else 'OFF'}",
                {"address": addr, "value": on_val},
            )

        defaults = _XR18_BUS_LR_EQ_DEFAULTS if max_bands == 6 else _XR18_EQ_DEFAULTS

        # Bus/Main global EQ Mode (PEQ=0, GEQ=1, TEQ=2) when no band is specified
        if band is None and max_bands == 6:
            for m_tok, m_val, m_lbl in (("geq", 1, "GEQ"), ("teq", 2, "TEQ"), ("peq", 0, "PEQ")):
                if re.search(rf"\b{m_tok}\b", text):
                    addr = f"{prefix}/eq/mode"
                    self._send_osc(cfg, addr, m_val)
                    return CommandExecutionResult(
                        True,
                        self.target_id,
                        f"XR18: EQ {target_label} Mode -> {m_lbl}",
                        {"address": addr, "value": m_val},
                    )

        # Whole-strip EQ Reset or Flat
        if band is None and re.search(r"\b(?:reset|azzera|ripristina|flat)\b", text):
            return self._handle_eq_reset_or_flat(text, prefix, target_label, cfg, defaults)

        if band is not None:
            clean_eq = self._strip_eq_tokens(text)

            # 1) Band Filter Mode (Channel: LCut..HCut; Bus/Main 6-band: LShv, PEQ, VEQ, HShv only)
            mode_match = self._resolve_eq_mode(clean_eq)
            if mode_match is not None or "mode" in clean_eq or "tipo" in clean_eq:
                if mode_match is None:
                    valid_txt = "LCut, LShv, PEQ, VEQ, HShv, HCut" if allow_cuts else "LShv, PEQ, VEQ, HShv"
                    return CommandExecutionResult(
                        False, self.target_id, f"XR18: Mode EQ valido per {target_label}: {valid_txt}"
                    )
                mode_idx, mode_name = mode_match
                if not allow_cuts and mode_idx in (0, 5):
                    return CommandExecutionResult(
                        False,
                        self.target_id,
                        f"XR18: su {target_label} (6 bande) non esistono LCut e HCut (usa LShv, PEQ, VEQ, HShv)",
                    )
                addr = f"{prefix}/eq/{band}/type"
                self._send_osc(cfg, addr, mode_idx)
                return CommandExecutionResult(
                    True,
                    self.target_id,
                    f"XR18: EQ {target_label} Banda {band} Mode -> {mode_name}",
                    {"address": addr, "value": mode_idx},
                )

            # 2) Band Q / Quality Factor (0.3 .. 10.0)
            if re.search(r"\b(?:q|qual|qualita|stringi|allarga)\b", clean_eq):
                addr = f"{prefix}/eq/{band}/q"
                cur_v = self._query_osc_or_shadow(
                    cfg, addr, self._eq_qs.get((prefix, band), q_to_osc(2.0))
                )
                cur_q = osc_to_q(cur_v)
                nums = extract_numbers(clean_eq)
                is_narrower = any(w in clean_eq for w in ("stringi", "alza", "aumenta", "piu"))
                is_wider = any(w in clean_eq for w in ("allarga", "abbassa", "riduci", "meno"))
                if is_narrower and not nums:
                    new_q = min(10.0, cur_q * 1.35)
                elif is_wider and not nums:
                    new_q = max(0.3, cur_q / 1.35)
                elif nums and ("di " in clean_eq or (is_narrower or is_wider)):
                    delta = abs(nums[-1])
                    new_q = cur_q + delta if is_narrower else cur_q - delta
                elif nums:
                    new_q = nums[-1]
                else:
                    return CommandExecutionResult(False, self.target_id, f"XR18: valore Q banda {band} mancante")

                val = q_to_osc(new_q)
                self._eq_qs[(prefix, band)] = val
                self._send_osc(cfg, addr, float(val))
                return CommandExecutionResult(
                    True,
                    self.target_id,
                    f"XR18: EQ {target_label} Banda {band} Qual -> {osc_to_q(val):.2f}",
                    {"address": addr, "value": round(val, 4)},
                )

            # 3) Band Frequency (20 Hz .. 20 kHz)
            if any(w in clean_eq for w in ("hz", "khz", "freq", "frequenza")) or re.search(
                r"\b\d{1,2}k\d{1,2}\b", clean_eq
            ):
                addr = f"{prefix}/eq/{band}/f"
                hz = self._parse_freq_hz(clean_eq)
                if hz is not None:
                    val = freq_to_osc(hz, 20.0, 20000.0)
                else:
                    cur_f = self._query_osc_or_shadow(
                        cfg, addr, self._eq_freqs.get((prefix, band), defaults[band][1])
                    )
                    if any(w in clean_eq for w in ("alza", "aumenta", "piu", "su")):
                        val = min(1.0, cur_f + 0.025)
                    elif any(w in clean_eq for w in ("abbassa", "riduci", "meno", "giu")):
                        val = max(0.0, cur_f - 0.025)
                    else:
                        return CommandExecutionResult(
                            False, self.target_id, f"XR18: frequenza EQ banda {band} mancante"
                        )
                self._eq_freqs[(prefix, band)] = val
                self._send_osc(cfg, addr, float(val))
                return CommandExecutionResult(
                    True,
                    self.target_id,
                    f"XR18: EQ {target_label} Banda {band} Freq -> {osc_to_freq(val):.0f} Hz",
                    {"address": addr, "value": round(val, 4)},
                )

            # 4) Band Gain (-15 .. +15 dB, supports exact & live relative)
            addr = f"{prefix}/eq/{band}/g"
            nums = extract_numbers(clean_eq)
            is_rel_up = any(w in clean_eq for w in ("alza", "aumenta"))
            is_rel_down = any(w in clean_eq for w in ("abbassa", "riduci", "togli"))
            if "flat" in clean_eq or "zero" in clean_eq or "reset" in clean_eq:
                db = 0.0
            elif is_rel_up or is_rel_down or "di " in clean_eq:
                cur_g = self._query_osc_or_shadow(cfg, addr, self._eq_gains.get((prefix, band), 0.5))
                cur_db = cur_g * 30.0 - 15.0
                delta = abs(nums[-1]) if nums else max(1.0, min(6.0, float(cfg.step_db)))
                db = max(-15.0, min(15.0, cur_db + (delta if (is_rel_up or not is_rel_down) else -delta)))
            elif nums:
                db = max(-15.0, min(15.0, nums[-1]))
                if "meno" in clean_eq and db > 0:
                    db = -db
            elif "piu" in clean_eq:
                cur_g = self._query_osc_or_shadow(cfg, addr, self._eq_gains.get((prefix, band), 0.5))
                db = max(-15.0, min(15.0, (cur_g * 30.0 - 15.0) + max(1.0, min(6.0, float(cfg.step_db)))))
            elif "meno" in clean_eq:
                cur_g = self._query_osc_or_shadow(cfg, addr, self._eq_gains.get((prefix, band), 0.5))
                db = max(-15.0, min(15.0, (cur_g * 30.0 - 15.0) - max(1.0, min(6.0, float(cfg.step_db)))))
            else:
                return CommandExecutionResult(False, self.target_id, f"XR18: valore EQ banda {band} mancante")

            val = (db + 15.0) / 30.0
            self._eq_gains[(prefix, band)] = val
            self._send_osc(cfg, addr, float(val))
            return CommandExecutionResult(
                True,
                self.target_id,
                f"XR18: EQ {target_label} Banda {band} -> {db:+.1f} dB",
                {"address": addr, "value": round(val, 4)},
            )

        # Strip Master EQ On / Off / Toggle
        addr = f"{prefix}/eq/on"
        on_val = self._resolve_binary_state(
            text, cfg, addr, self._eq_on.get(prefix, 1), extra_off=("bypass",)
        )
        self._eq_on[prefix] = on_val
        self._send_osc(cfg, addr, on_val)
        return CommandExecutionResult(
            True,
            self.target_id,
            f"XR18: EQ {target_label} {'ON' if on_val else 'OFF'}",
            {"address": addr, "value": on_val},
        )

    def _compute_new_fader(
        self, text: str, current_fader: float, step_db: float
    ) -> tuple[float | None, str]:
        if "a zero db" in text or "0 db" in text or "unity" in text:
            return 0.75, "0.0 dB (75%)"
        if "al massimo" in text or "massimo" in text:
            return 1.0, "+10.0 dB (100%)"
        if "al minimo" in text or "a zero" in text:
            return 0.0, "-inf dB (0%)"

        nums = extract_numbers(text)
        is_up = any(
            w in text
            for w in ("alza", "aumenta", "piu", "tira su", "porta su", "vai su", "salire")
        )
        is_down = any(
            w in text
            for w in ("abbassa", "riduci", "scendi", "tira giu", "porta giu", "vai giu")
        )

        explicit_target: float | None = None
        is_relative_num = False
        if nums:
            m_val = re.search(
                r"(?:(volume|fader|livello|a|al|di)\s+)?([+-]?\d+(?:[.,]\d+)?)\s*(%|percento|db)?\s*$",
                text,
            )
            if m_val:
                prep = m_val.group(1) or ""
                explicit_target = float(m_val.group(2).replace(",", "."))
                if prep == "di":
                    is_relative_num = True
                elif prep in ("a", "al"):
                    is_relative_num = False
                elif is_up or is_down:
                    is_relative_num = True
            elif "db" in text or "%" in text or "percento" in text:
                explicit_target = nums[-1]
                is_relative_num = is_up or is_down

        if explicit_target is not None:
            if "db" in text:
                if is_relative_num and (is_up or is_down):
                    cur_db = fader_to_db(current_fader)
                    delta = abs(explicit_target) if is_up else -abs(explicit_target)
                    nf = db_to_fader(cur_db + delta)
                    return nf, f"{fader_to_db(nf):+.1f} dB"
                nf = db_to_fader(explicit_target)
                return nf, f"{explicit_target:+.1f} dB"
            if is_relative_num and (is_up or is_down):
                delta_f = abs(explicit_target) / 100.0
                nf = max(0.0, min(1.0, current_fader + (delta_f if is_up else -delta_f)))
                return nf, f"{round(nf * 100)}%"
            nf = max(0.0, min(1.0, explicit_target / 100.0))
            return nf, f"{round(nf * 100)}% ({fader_to_db(nf):+.1f} dB)"

        if is_up:
            cur_db = fader_to_db(current_fader)
            nf = db_to_fader(max(-60.0, cur_db) + step_db)
            return nf, f"{fader_to_db(nf):+.1f} dB"
        if is_down:
            cur_db = fader_to_db(current_fader)
            nf = db_to_fader(cur_db - step_db)
            return nf, f"{fader_to_db(nf):+.1f} dB"

        return None, ""
