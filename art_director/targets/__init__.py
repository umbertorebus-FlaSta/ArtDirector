"""Target stage software/hardware modules."""

from .base import BaseTarget, CommandExecutionResult, MidiOutputHelper, TargetContext
from .behringer_xr18 import BehringerXR18Target, db_to_fader, fader_to_db
from .cakewalk_daw import CakewalkDAWTarget, find_project_by_unique_name
from .popup_handler import PopupHandlerTarget
from .qlc_plus import QLCPlusTarget, build_artnet_dmx_packet, parse_qlc_qxw_buttons
from .system_target import SystemTarget
from .virtualdj import VirtualDJTarget

__all__ = [
    "BaseTarget",
    "BehringerXR18Target",
    "CakewalkDAWTarget",
    "CommandExecutionResult",
    "MidiOutputHelper",
    "PopupHandlerTarget",
    "QLCPlusTarget",
    "SystemTarget",
    "TargetContext",
    "VirtualDJTarget",
    "build_artnet_dmx_packet",
    "db_to_fader",
    "fader_to_db",
    "find_project_by_unique_name",
    "parse_qlc_qxw_buttons",
]
