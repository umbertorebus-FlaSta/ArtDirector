"""Cross-platform microphone input device enumeration and selection."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AudioInputDevice:
    index: int
    name: str
    hostapi_name: str
    max_input_channels: int
    default_samplerate: float
    is_default: bool = False

    @property
    def display_label(self) -> str:
        default_tag = " [Default]" if self.is_default else ""
        return f"[{self.index}] {self.name} ({self.hostapi_name}){default_tag}"


def list_input_devices() -> list[AudioInputDevice]:
    """Return all available audio input devices cross-platform via sounddevice."""
    try:
        import sounddevice as sd
    except Exception:
        return []

    devices_raw = sd.query_devices()
    hostapis = sd.query_hostapis()
    default_in = None
    try:
        default_pair = sd.default.device
        if isinstance(default_pair, (list, tuple)) and len(default_pair) >= 1:
            default_in = default_pair[0]
        elif isinstance(default_pair, int):
            default_in = default_pair
    except Exception:
        pass

    result: list[AudioInputDevice] = []
    for idx, dev in enumerate(devices_raw):
        max_in = int(dev.get("max_input_channels", 0))
        if max_in <= 0:
            continue
        ha_idx = int(dev.get("hostapi", 0))
        ha_name = (
            hostapis[ha_idx].get("name", "")
            if 0 <= ha_idx < len(hostapis)
            else ""
        )
        result.append(
            AudioInputDevice(
                index=idx,
                name=str(dev.get("name", f"Input {idx}")),
                hostapi_name=str(ha_name),
                max_input_channels=max_in,
                default_samplerate=float(dev.get("default_samplerate", 16000.0)),
                is_default=(idx == default_in),
            )
        )
    return result


def resolve_input_device(
    saved_index: int | None, saved_name: str = ""
) -> AudioInputDevice | None:
    """Resolve saved microphone by exact/partial name first, then index, then default."""
    devices = list_input_devices()
    if not devices:
        return None

    if saved_name:
        saved_l = saved_name.strip().lower()
        for dev in devices:
            if dev.name.lower() == saved_l:
                return dev
        for dev in devices:
            if saved_l in dev.name.lower():
                return dev

    if saved_index is not None:
        for dev in devices:
            if dev.index == saved_index:
                return dev

    for dev in devices:
        if dev.is_default:
            return dev
    return devices[0]
