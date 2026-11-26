"""Base target handler interface and shared MIDI output helper."""

from __future__ import annotations

import socket
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..config.schema import AppConfig
    from ..core.event_bus import EventBus
    from ..core.state import CancellationToken
    from ..os_layer.base import OSBridge


def query_osc_value(
    host: str, port: int, address: str, timeout_sec: float = 0.08
) -> float | int | None:
    """Send an argumentless OSC query datagram and return one numeric reply if supported."""
    addr_clean = address.strip()
    if not addr_clean:
        return None
    try:
        from pythonosc.osc_message import OscMessage
        from pythonosc.osc_message_builder import OscMessageBuilder

        payload = OscMessageBuilder(address=addr_clean).build().dgram
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout_sec)
            sock.sendto(payload, (host, int(port)))
            data, _ = sock.recvfrom(4096)
        msg = OscMessage(data)
        if msg.address == addr_clean and msg.params:
            first = msg.params[0]
            if isinstance(first, bool):
                return int(first)
            if isinstance(first, (int, float)):
                return first
    except Exception:
        return None
    return None


@dataclass
class TargetContext:
    config: AppConfig
    os_bridge: OSBridge
    cancel_token: CancellationToken
    bus: EventBus


@dataclass
class CommandExecutionResult:
    handled: bool
    target_id: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


class MidiOutputHelper:
    """Thread-safe cross-platform MIDI output port sender via mido/python-rtmidi."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._port_name = ""
        self._port = None

    @staticmethod
    def list_output_ports() -> list[str]:
        try:
            import mido

            return list(mido.get_output_names())
        except Exception:
            return []

    def _ensure_port(self, port_name: str):
        if not port_name.strip():
            return None
        if self._port is not None and self._port_name == port_name:
            return self._port
        self.close()
        try:
            import mido

            available = mido.get_output_names()
            chosen = None
            for name in available:
                if name.lower() == port_name.lower() or port_name.lower() in name.lower():
                    chosen = name
                    break
            if chosen is None:
                return None
            self._port = mido.open_output(chosen)
            self._port_name = port_name
            return self._port
        except Exception:
            self._port = None
            return None

    def send_cc(self, port_name: str, channel: int, control: int, value: int) -> bool:
        with self._lock:
            port = self._ensure_port(port_name)
            if port is None:
                return False
            try:
                import mido

                ch = max(0, min(15, int(channel) - 1))
                cc = max(0, min(127, int(control)))
                val = max(0, min(127, int(value)))
                port.send(mido.Message("control_change", channel=ch, control=cc, value=val))
                return True
            except Exception:
                return False

    def send_note(self, port_name: str, channel: int, note: int, velocity: int = 127) -> bool:
        with self._lock:
            port = self._ensure_port(port_name)
            if port is None:
                return False
            try:
                import mido

                ch = max(0, min(15, int(channel) - 1))
                n = max(0, min(127, int(note)))
                vel = max(0, min(127, int(velocity)))
                port.send(mido.Message("note_on", channel=ch, note=n, velocity=vel))
                port.send(mido.Message("note_off", channel=ch, note=n, velocity=0))
                return True
            except Exception:
                return False

    def send_program_change(
        self,
        port_name: str,
        channel: int,
        program: int,
        bank_msb: int = -1,
        bank_lsb: int = -1,
    ) -> bool:
        with self._lock:
            port = self._ensure_port(port_name)
            if port is None:
                return False
            try:
                import mido

                ch = max(0, min(15, int(channel) - 1))
                if int(bank_msb) >= 0:
                    msb = max(0, min(127, int(bank_msb)))
                    port.send(mido.Message("control_change", channel=ch, control=0, value=msb))
                if int(bank_lsb) >= 0:
                    lsb = max(0, min(127, int(bank_lsb)))
                    port.send(mido.Message("control_change", channel=ch, control=32, value=lsb))
                pgm = max(0, min(127, int(program)))
                port.send(mido.Message("program_change", channel=ch, program=pgm))
                return True
            except Exception:
                return False

    def close(self) -> None:
        with self._lock:
            if self._port is not None:
                try:
                    self._port.close()
                except Exception:
                    pass
                self._port = None
                self._port_name = ""


class BaseTarget(ABC):
    """Abstract base class for stage hardware/software target modules."""

    @property
    @abstractmethod
    def target_id(self) -> str:
        ...

    @abstractmethod
    def handle(self, remainder: str, ctx: TargetContext) -> CommandExecutionResult:
        ...

    def panic(self, ctx: TargetContext) -> list[str]:  # noqa: ARG002
        return []

    def close(self) -> None:
        pass
