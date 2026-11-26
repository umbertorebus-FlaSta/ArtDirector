"""QLC+ lighting controller via OSC, Art-Net (ArtDmx UDP 6454), and WebSocket."""

from __future__ import annotations

import socket
import struct
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Callable

from pythonosc.udp_client import SimpleUDPClient

from ..config.schema import QLCSettings
from ..core.parser import extract_numbers, normalize_compact, normalize_text, replace_spoken_numbers
from .base import BaseTarget, CommandExecutionResult, TargetContext


def build_artnet_dmx_packet(
    universe: int, dmx_channels: bytes | bytearray, sequence: int = 1
) -> bytes:
    """Build a standard Art-Net 4 ArtDmx UDP packet (OpCode 0x5000)."""
    data = bytes(dmx_channels[:512]).ljust(512, b"\x00")
    sub_uni = int(universe) & 0xFF
    net = (int(universe) >> 8) & 0x7F
    header = struct.pack(
        "<8sH",
        b"Art-Net\x00",
        0x5000,  # OpDmx little-endian
    )
    meta = struct.pack(
        ">HBBBBH",
        14,  # ProtVer 14 big-endian
        max(0, min(255, int(sequence))),
        0,  # Physical
        sub_uni,
        net,
        len(data),
    )
    return header + meta + data


def parse_qlc_qxw_buttons(qxw_path: str | Path) -> dict[str, dict[str, Any]]:
    """Extract Virtual Console buttons and optional OSC/Input mappings from a QLC+ .qxw file."""
    path = Path(qxw_path)
    if not path.exists() or not path.is_file():
        return {}
    tree = ET.parse(path)
    root = tree.getroot()
    discovered: dict[str, dict[str, Any]] = {}

    for btn in root.iter("Button"):
        caption = (btn.attrib.get("Caption") or "").strip()
        widget_id = (btn.attrib.get("ID") or "").strip()
        if not caption:
            continue
        key = caption.lower()
        slug = normalize_compact(caption) or f"btn_{widget_id}"
        osc_path = f"/vc/{slug}"
        artnet_ch = 0

        inp = btn.find("Input")
        if inp is not None:
            ch_str = inp.attrib.get("Channel", "")
            if ch_str.isdigit():
                ch_num = int(ch_str)
                if 1 <= ch_num <= 512:
                    artnet_ch = ch_num

        discovered[key] = {
            "osc_path": osc_path,
            "widget_id": widget_id,
            "artnet_channel": artnet_ch,
            "momentary": False,
        }
    return discovered


class QLCPlusTarget(BaseTarget):
    """Controls QLC+ Virtual Console unique buttons, Grand Master, and Blackout."""

    def __init__(
        self,
        osc_sender: Callable[[str, int, str, float], None] | None = None,
        artnet_sender: Callable[[str, int, bytes], None] | None = None,
        ws_sender: Callable[[str, int, str], None] | None = None,
    ) -> None:
        self._custom_osc = osc_sender
        self._custom_artnet = artnet_sender
        self._custom_ws = ws_sender
        self._osc_client: SimpleUDPClient | None = None
        self._osc_addr: tuple[str, int] | None = None
        self._dmx_buffer = bytearray(512)
        self._sequence = 1
        self._grandmaster: float = 1.0
        self._blackout_active: bool = False
        self._button_states: dict[str, bool] = {}

    @property
    def target_id(self) -> str:
        return "qlc"

    def _send_osc(self, cfg: QLCSettings, path: str, value: float) -> None:
        if self._custom_osc is not None:
            self._custom_osc(cfg.host, cfg.osc_port, path, value)
            return
        addr = (cfg.host, int(cfg.osc_port))
        if self._osc_client is None or self._osc_addr != addr:
            self._osc_client = SimpleUDPClient(cfg.host, int(cfg.osc_port))
            self._osc_addr = addr
        self._osc_client.send_message(path, float(value))

    def _send_artnet(self, cfg: QLCSettings) -> None:
        packet = build_artnet_dmx_packet(
            cfg.artnet_universe, self._dmx_buffer, self._sequence
        )
        self._sequence = 1 if self._sequence >= 255 else self._sequence + 1
        if self._custom_artnet is not None:
            self._custom_artnet(cfg.artnet_host, cfg.artnet_port, packet)
            return
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(packet, (cfg.artnet_host, int(cfg.artnet_port)))

    def _send_ws(self, cfg: QLCSettings, message: str) -> None:
        if self._custom_ws is not None:
            self._custom_ws(cfg.host, cfg.websocket_port, message)
            return
        try:
            import websocket

            ws = websocket.create_connection(
                f"ws://{cfg.host}:{int(cfg.websocket_port)}/qlcplusWS", timeout=0.6
            )
            try:
                ws.send(message)
            finally:
                ws.close()
        except Exception:
            pass

    def handle(self, remainder: str, ctx: TargetContext) -> CommandExecutionResult:
        cfg = ctx.config.qlc
        text = replace_spoken_numbers(remainder)
        if not text:
            return CommandExecutionResult(False, self.target_id, "Comando QLC+ vuoto")

        # 1. General Blackout
        if any(w in text for w in ("blackout", "black out", "buio", "oscura tutto", "spegni tutto")):
            turn_off = any(w in text for w in ("togli", "disattiva", "off", "esci", "riaccendi"))
            return self._apply_blackout(not turn_off, cfg)

        # 2. Grand Master Fader
        if any(w in text for w in ("master", "grandmaster", "grand master", "generale", "fader", "dimmer")):
            return self._handle_grandmaster(text, cfg)

        # 3. Virtual Console Button by unique name
        btn_name, btn_cfg = self._resolve_button(text, cfg)
        if btn_name is not None and btn_cfg is not None:
            return self._trigger_button(text, btn_name, btn_cfg, cfg, ctx)

        return CommandExecutionResult(
            False, self.target_id, f"QLC+: pulsante Virtual Console o comando non riconosciuto in '{remainder}'"
        )

    def panic(self, ctx: TargetContext) -> list[str]:
        if not ctx.config.qlc.panic_blackout:
            return []
        res = self._apply_blackout(True, ctx.config.qlc)
        return [res.summary]

    def _apply_blackout(self, enable: bool, cfg: QLCSettings) -> CommandExecutionResult:
        self._blackout_active = enable
        mode = cfg.mode
        val = 1.0 if enable else 0.0

        if mode in ("osc", "osc_and_artnet"):
            self._send_osc(cfg, cfg.osc_blackout_path, val)
        if mode in ("artnet", "osc_and_artnet"):
            if enable:
                self._dmx_buffer = bytearray(512)
            self._send_artnet(cfg)
        if mode == "websocket":
            # QLC+ WebSocket toggles or sets widgets/blackout depending on QLC+ version
            self._send_ws(cfg, f"QLC+API|setBlackout|{1 if enable else 0}")

        return CommandExecutionResult(
            True,
            self.target_id,
            f"QLC+: Blackout generale {'ATTIVATO' if enable else 'DISATTIVATO'}",
            {"blackout": enable},
        )

    def _handle_grandmaster(
        self, text: str, cfg: QLCSettings
    ) -> CommandExecutionResult:
        nums = extract_numbers(text)
        level: float | None = None
        if nums:
            raw = nums[-1]
            level = max(0.0, min(1.0, raw / 100.0 if raw > 1.0 else raw))
        elif "massimo" in text or "cento" in text or "pieno" in text:
            level = 1.0
        elif "minimo" in text or "zero" in text:
            level = 0.0
        elif any(w in text for w in ("alza", "aumenta", "tira su", "porta su")):
            level = min(1.0, self._grandmaster + 0.1)
        elif any(w in text for w in ("abbassa", "riduci", "tira giu", "porta giu")):
            level = max(0.0, self._grandmaster - 0.1)

        if level is None:
            return CommandExecutionResult(False, self.target_id, "QLC+: specifica livello Grand Master (0-100%)")

        self._grandmaster = level
        dmx_val = int(round(level * 255.0))
        mode = cfg.mode
        if mode in ("osc", "osc_and_artnet"):
            self._send_osc(cfg, cfg.osc_grandmaster_path, level)
        if mode in ("artnet", "osc_and_artnet") and 1 <= cfg.artnet_grandmaster_channel <= 512:
            self._dmx_buffer[cfg.artnet_grandmaster_channel - 1] = dmx_val
            self._send_artnet(cfg)
        if mode == "websocket":
            self._send_ws(cfg, f"QLC+API|setGMValue|{dmx_val}")

        return CommandExecutionResult(
            True,
            self.target_id,
            f"QLC+: Fader Generale (Grand Master) -> {round(level * 100)}% (DMX {dmx_val})",
            {"grandmaster": round(level, 4), "dmx": dmx_val},
        )

    def _resolve_button(
        self, text: str, cfg: QLCSettings
    ) -> tuple[str | None, dict | None]:
        for name, bcfg in sorted(
            cfg.buttons.items(), key=lambda kv: len(kv[0]), reverse=True
        ):
            n = normalize_text(name)
            if n and (f" {n} " in f" {text} " or normalize_compact(n) in normalize_compact(text)):
                return name, bcfg
        return None, None

    def _trigger_button(
        self,
        text: str,
        btn_name: str,
        btn_cfg: dict,
        cfg: QLCSettings,
        ctx: TargetContext,
    ) -> CommandExecutionResult:
        if any(w in text for w in ("spegni", "disattiva", "off", "ferma", "stop")):
            target_on = False
        elif any(w in text for w in ("accendi", "attiva", "avvia", "on", "premi")):
            target_on = True
        else:
            target_on = not self._button_states.get(btn_name, False)

        self._button_states[btn_name] = target_on
        val_f = 1.0 if target_on else 0.0
        dmx_val = 255 if target_on else 0

        mode = cfg.mode
        osc_path = str(btn_cfg.get("osc_path") or f"/vc/{normalize_compact(btn_name)}")
        widget_id = str(btn_cfg.get("widget_id") or "")
        art_ch = int(btn_cfg.get("artnet_channel") or 0)
        momentary = bool(btn_cfg.get("momentary", False))

        if mode in ("osc", "osc_and_artnet"):
            self._send_osc(cfg, osc_path, 1.0 if momentary else val_f)
            if momentary and not ctx.cancel_token.wait(0.08):
                self._send_osc(cfg, osc_path, 0.0)
        if mode in ("artnet", "osc_and_artnet") and 1 <= art_ch <= 512:
            self._dmx_buffer[art_ch - 1] = 255 if momentary else dmx_val
            self._send_artnet(cfg)
            if momentary and not ctx.cancel_token.wait(0.08):
                self._dmx_buffer[art_ch - 1] = 0
                self._send_artnet(cfg)
        if mode == "websocket" and widget_id:
            self._send_ws(cfg, f"{widget_id}|{255 if momentary else dmx_val}")
            if momentary and not ctx.cancel_token.wait(0.08):
                self._send_ws(cfg, f"{widget_id}|0")

        return CommandExecutionResult(
            True,
            self.target_id,
            f"QLC+: Pulsante '{btn_name}' -> {'ON' if target_on else 'OFF'} ({osc_path})",
            {"button": btn_name, "osc_path": osc_path, "state": target_on},
        )
