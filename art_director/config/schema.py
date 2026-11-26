"""Typed configuration schema for Art Director."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class GeneralSettings:
    language: str = "it"
    start_minimized_to_tray: bool = False
    minimize_on_close: bool = True
    autostart_at_os_boot: bool = False
    autostart_in_background: bool = True
    confirm_quit: bool = False
    active_profile_name: str = ""


@dataclass
class SleepWakeSettings:
    start_in_sleep_mode: bool = False
    sleep_keywords: list[str] = field(
        default_factory=lambda: ["dormi", "pausa", "sleep", "riposo"]
    )
    wake_keywords: list[str] = field(
        default_factory=lambda: ["sveglia", "riprendi", "wake", "attiva"]
    )
    sleep_samples: list[str] = field(default_factory=list)
    wake_samples: list[str] = field(default_factory=list)
    toggle_hotkey: str = "<ctrl>+<alt>+s"
    ptt_hotkey: str = ""
    mute_mic_in_sleep: bool = False
    auto_sleep_after_sec: float = 0.0
    wake_emoji: str = "👍"
    sleep_emoji: str = "👋"
    panic_emoji: str = "🚨"
    enter_sleep_after_panic: bool = True


@dataclass
class AudioSettings:
    input_device_index: int | None = None
    input_device_name: str = ""
    sample_rate: int = 16000
    block_size: int = 1024
    channels: int = 1
    highpass_enabled: bool = True
    highpass_cutoff_hz: float = 100.0
    noise_gate_db: float = -42.0
    vad_hangover_ms: int = 350
    max_utterance_sec: float = 6.0
    input_gain: float = 1.0


@dataclass
class STTSettings:
    engine: str = "samples_hybrid"  # "samples_hybrid" | "samples_only" | "vosk" | "faster_whisper"
    sample_match_threshold: float = 0.68
    hybrid_fallback_engine: str = "vosk"  # "none" | "vosk" | "faster_whisper"
    samples_dir: str = ""
    vosk_model_path: str = ""
    vosk_use_partial_triggers: bool = False
    vosk_use_grammar: bool = False
    whisper_model_path_or_size: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"
    whisper_beam_size: int = 1


@dataclass
class PrefixRouteConfig:
    target_id: str
    display_name: str
    enabled: bool = True
    prefixes: list[str] = field(default_factory=list)
    fuzzy_matching: bool = True
    fuzzy_threshold: float = 0.82
    auto_focus_window: bool = True
    window_title_patterns: list[str] = field(default_factory=list)


def default_prefix_routes() -> dict[str, PrefixRouteConfig]:
    """Editable default prefix routes; nothing is hardcoded in routing logic."""
    return {
        "xr18": PrefixRouteConfig(
            target_id="xr18",
            display_name="Behringer XR18 / X-Air Edit",
            enabled=True,
            prefixes=["uehberi", "ueh beri", "mixer", "behringer"],
            auto_focus_window=False,
            window_title_patterns=["X-AIR-Edit", "X AIR", "XR18"],
        ),
        "cakewalk": PrefixRouteConfig(
            target_id="cakewalk",
            display_name="Sonar Cakewalk / DAW",
            enabled=True,
            prefixes=["uehsona", "ueh sona", "cakewalk", "sonar", "daw"],
            auto_focus_window=True,
            window_title_patterns=["Cakewalk", "SONAR", "REAPER", "Logic"],
        ),
        "qlc": PrefixRouteConfig(
            target_id="qlc",
            display_name="QLC+ Luci (OSC / Art-Net)",
            enabled=True,
            prefixes=["uehma", "ueh ma", "luci", "qlc"],
            auto_focus_window=False,
            window_title_patterns=["Q Light Controller", "QLC+"],
        ),
        "virtualdj": PrefixRouteConfig(
            target_id="virtualdj",
            display_name="VirtualDJ",
            enabled=True,
            prefixes=["virtualdj", "virtual dj", "vdj", "console"],
            auto_focus_window=True,
            window_title_patterns=["VirtualDJ"],
        ),
        "system": PrefixRouteConfig(
            target_id="system",
            display_name="Sistema & Gestione Palco",
            enabled=True,
            prefixes=["sistema", "regia", "art director"],
            auto_focus_window=False,
            window_title_patterns=[],
        ),
    }


@dataclass
class XR18Settings:
    host: str = "192.168.1.100"
    port: int = 10024
    channel_aliases: dict[str, int] = field(
        default_factory=lambda: {
            "voce": 1,
            "voce 1": 1,
            "voce 2": 2,
            "cori": 2,
            "chitarra": 3,
            "basso": 4,
            "tastiera": 5,
            "cassa": 6,
            "rullante": 7,
        }
    )
    aux_aliases: dict[str, int] = field(
        default_factory=lambda: {
            "aux 1": 1,
            "spia 1": 1,
            "monitor 1": 1,
            "aux 2": 2,
            "spia 2": 2,
            "monitor 2": 2,
            "aux 3": 3,
            "aux 4": 4,
            "aux 5": 5,
            "aux 6": 6,
            "fx 1": 7,
            "riverbero": 7,
            "fx 2": 8,
            "delay": 8,
            "fx 3": 9,
            "fx 4": 10,
        }
    )
    scene_aliases: dict[str, int] = field(
        default_factory=lambda: {
            "iniziale": 1,
            "acustica": 2,
            "rock": 3,
        }
    )
    step_db: float = 3.0
    panic_mute_lr: bool = True
    panic_mute_channels: list[int] = field(default_factory=list)


@dataclass
class CakewalkSettings:
    executable_path: str = ""
    workspace_folders: list[str] = field(default_factory=list)
    project_extensions: list[str] = field(
        default_factory=lambda: [".cwp", ".cwb", ".wrk", ".rpp"]
    )
    save_before_close: bool = True
    close_unsaved_policy: str = "save"  # "save" | "discard" | "prompt"
    close_wait_ms: int = 1200
    transport_mode: str = "hybrid"  # "hybrid" | "shortcuts" | "midi"
    midi_port_name: str = ""
    shortcuts: dict[str, str] = field(
        default_factory=lambda: {
            "play_pause": "space",
            "stop": "space",
            "record": "r",
            "rewind": "w",
            "insert_marker": "m",
            "next_marker": "<ctrl>+<shift>+<page_down>",
            "prev_marker": "<ctrl>+<shift>+<page_up>",
            "save_project": "<ctrl>+s",
            "close_project": "<ctrl>+w",
            "find_track": "<ctrl>+f",
            "edit_fx": "<alt>+f",
        }
    )
    tracks: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {
            "voce": {"index": 1, "midi_channel": 1, "volume_cc": 7, "mute_cc": 16, "fx_cc": 20, "fx_hotkey": ""},
            "basi": {"index": 2, "midi_channel": 1, "volume_cc": 8, "mute_cc": 17, "fx_cc": 21, "fx_hotkey": ""},
            "click": {"index": 3, "midi_channel": 1, "volume_cc": 9, "mute_cc": 18, "fx_cc": 22, "fx_hotkey": ""},
        }
    )
    panic_send_stop: bool = True


@dataclass
class QLCSettings:
    mode: str = "osc_and_artnet"  # "osc" | "artnet" | "websocket" | "osc_and_artnet"
    host: str = "127.0.0.1"
    osc_port: int = 7700
    osc_grandmaster_path: str = "/grandmaster"
    osc_blackout_path: str = "/blackout"
    artnet_host: str = "127.0.0.1"
    artnet_port: int = 6454
    artnet_universe: int = 0
    artnet_grandmaster_channel: int = 0
    websocket_port: int = 9999
    workspace_qxw_path: str = ""
    buttons: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {
            "strobo": {"osc_path": "/vc/strobo", "widget_id": "", "artnet_channel": 0, "momentary": False},
            "fumo": {"osc_path": "/vc/fumo", "widget_id": "", "artnet_channel": 0, "momentary": False},
            "acustica": {"osc_path": "/vc/acustica", "widget_id": "", "artnet_channel": 0, "momentary": False},
        }
    )
    panic_blackout: bool = True


@dataclass
class VirtualDJSettings:
    transport_mode: str = "hybrid"  # "hybrid" | "shortcuts" | "midi" | "osc"
    osc_host: str = "127.0.0.1"
    osc_port: int = 9000
    midi_port_name: str = ""
    active_deck: int = 1
    shortcuts: dict[str, str] = field(
        default_factory=lambda: {
            "play_pause_deck_1": "<ctrl>+1",
            "play_pause_deck_2": "<ctrl>+2",
            "play_pause_active": "space",
            "stop_deck_1": "<ctrl>+<shift>+1",
            "stop_deck_2": "<ctrl>+<shift>+2",
            "load_deck_1": "<ctrl>+<left>",
            "load_deck_2": "<ctrl>+<right>",
            "load_active": "enter",
            "load_sidelist": "<alt>+l",
            "browser_next": "down",
            "browser_prev": "up",
            "goto_next_cue": "n",
            "mix_automix": "<ctrl>+m",
            "crossfade_deck_1": "<ctrl>+<alt>+1",
            "crossfade_deck_2": "<ctrl>+<alt>+2",
        }
    )
    midi_mappings: dict[str, dict[str, int]] = field(
        default_factory=lambda: {
            "deck_1_play": {"channel": 1, "note": 60, "cc": -1},
            "deck_2_play": {"channel": 2, "note": 60, "cc": -1},
            "deck_1_stop": {"channel": 1, "note": 61, "cc": -1},
            "deck_2_stop": {"channel": 2, "note": 61, "cc": -1},
            "deck_1_load": {"channel": 1, "note": 62, "cc": -1},
            "deck_2_load": {"channel": 2, "note": 62, "cc": -1},
            "deck_1_gain": {"channel": 1, "note": -1, "cc": 10},
            "deck_2_gain": {"channel": 2, "note": -1, "cc": 10},
            "deck_1_eq_low": {"channel": 1, "note": -1, "cc": 11},
            "deck_1_eq_mid": {"channel": 1, "note": -1, "cc": 12},
            "deck_1_eq_high": {"channel": 1, "note": -1, "cc": 13},
            "deck_2_eq_low": {"channel": 2, "note": -1, "cc": 11},
            "deck_2_eq_mid": {"channel": 2, "note": -1, "cc": 12},
            "deck_2_eq_high": {"channel": 2, "note": -1, "cc": 13},
            "crossfader": {"channel": 1, "note": -1, "cc": 8},
            "deck_1_next_cue": {"channel": 1, "note": 63, "cc": -1},
            "deck_2_next_cue": {"channel": 2, "note": 63, "cc": -1},
        }
    )
    panic_stop_decks: bool = True


@dataclass
class PopupHandlerSettings:
    enabled: bool = True
    voice_triggers: list[str] = field(
        default_factory=lambda: [
            "chiudi avviso",
            "chiudi popup",
            "chiudi finestra",
            "chiudi errore",
            "chiudi banner",
            "ignora avviso",
            "ignora errore",
        ]
    )
    allow_without_prefix: bool = True
    strategy: str = "smart"  # "smart" | "esc" | "enter" | "wm_close" | "esc_then_close"
    known_dialog_keywords: list[str] = field(
        default_factory=lambda: [
            "error",
            "errore",
            "warning",
            "avviso",
            "audio",
            "device",
            "periferica",
            "asio",
            "driver",
            "missing",
            "splash",
            "notice",
            "alert",
            "vst",
            "midi",
        ]
    )
    protect_main_windows: bool = True
    voice_samples: list[str] = field(default_factory=list)


@dataclass
class StageAppEntry:
    id: str
    name: str
    aliases: list[str] = field(default_factory=list)
    executable: str = ""
    arguments: str = ""
    working_dir: str = ""
    delay_after_sec: float = 1.5
    launch_on_startup: bool = True
    skip_if_running: bool = True
    process_name: str = ""
    target_id: str = ""


@dataclass
class StageLauncherSettings:
    launch_apps_on_art_director_start: bool = False
    launch_apps_only_on_boot_flag: bool = False
    initial_startup_delay_sec: float = 2.0
    voice_launch_all_triggers: list[str] = field(
        default_factory=lambda: [
            "avvia tutto",
            "apri tutto",
            "apri applicazioni",
            "avvia applicazioni",
            "prepara palco",
        ]
    )
    voice_launch_one_verbs: list[str] = field(
        default_factory=lambda: ["apri", "avvia", "lancia"]
    )
    allow_without_prefix: bool = True
    launch_all_samples: list[str] = field(default_factory=list)
    apps: list[StageAppEntry] = field(
        default_factory=lambda: [
            StageAppEntry(
                id="xair_edit",
                name="X-AIR Edit",
                aliases=["mixer", "xair", "x air", "behringer"],
                executable="",
                delay_after_sec=1.5,
                launch_on_startup=True,
                process_name="X-AIR-Edit",
                target_id="xr18",
            ),
            StageAppEntry(
                id="cakewalk",
                name="Cakewalk",
                aliases=["cakewalk", "sonar", "daw"],
                executable="",
                delay_after_sec=2.5,
                launch_on_startup=True,
                process_name="Cakewalk",
                target_id="cakewalk",
            ),
            StageAppEntry(
                id="qlc_plus",
                name="QLC+",
                aliases=["luci", "qlc", "qlc plus"],
                executable="",
                arguments="-w",
                delay_after_sec=1.5,
                launch_on_startup=True,
                process_name="qlcplus",
                target_id="qlc",
            ),
            StageAppEntry(
                id="virtualdj",
                name="VirtualDJ",
                aliases=["virtualdj", "virtual dj", "vdj"],
                executable="",
                delay_after_sec=2.0,
                launch_on_startup=False,
                process_name="virtualdj",
                target_id="virtualdj",
            ),
        ]
    )


@dataclass
class PanicSettings:
    hotkey: str = "<ctrl>+<alt>+<esc>"
    voice_keywords: list[str] = field(
        default_factory=lambda: [
            "panic",
            "emergenza",
            "stop tutto",
            "ferma tutto",
            "blocco totale",
        ]
    )
    allow_without_prefix: bool = True
    enter_sleep_mode: bool = True
    voice_samples: list[str] = field(default_factory=list)


@dataclass
class ActionStep:
    """Single step inside a picked function, advanced action, or multi-step macro."""

    kind: str = "click"  # click | double_click | right_click | scroll_up | scroll_down | hotkey | hotkey_if_dialog | wait | osc | xr18_cmd | artnet | midi_cc | midi_note | open_project | paste_text
    rel_x: float = 0.0
    rel_y: float = 0.0
    uia_name: str = ""
    uia_automation_id: str = ""
    uia_control_type: str = ""
    hotkey: str = ""
    delay_ms: int = 150
    scroll_clicks: int = 3
    osc_host: str = "127.0.0.1"
    osc_port: int = 10024
    osc_address: str = ""
    osc_value: float = 1.0
    osc_type: str = "float"  # float | int
    osc_mode: str = "set"  # set | relative | toggle
    osc_min: float = 0.0
    osc_max: float = 1.0
    osc_query_before_update: bool = True
    xr18_command: str = ""
    xr18_step_db: float = 3.0
    artnet_host: str = "127.0.0.1"
    artnet_port: int = 6454
    artnet_universe: int = 0
    artnet_channel: int = 1
    artnet_value: int = 255
    artnet_blackout: bool = False
    midi_port: str = ""
    midi_channel: int = 1
    midi_control: int = 7
    midi_value: int = 127
    midi_bank_msb: int = -1
    midi_bank_lsb: int = -1
    project_folders: list[str] = field(default_factory=list)
    project_extensions: list[str] = field(
        default_factory=lambda: [".cwp", ".cwb", ".wrk", ".rpp"]
    )
    use_spoken_param: bool = True
    fixed_file_path: str = ""
    open_hotkey: str = ""
    paste_text: str = ""
    paste_clear_first: bool = True
    paste_before_hotkey: str = ""
    paste_after_hotkey: str = ""

    def describe(self) -> str:
        if self.kind in ("click", "double_click", "right_click"):
            label = f"{self.kind} ({self.rel_x * 100:.1f}%, {self.rel_y * 100:.1f}%)"
            return f"{label} [{self.uia_name}]" if self.uia_name else label
        if self.kind in ("scroll_up", "scroll_down"):
            return f"{self.kind} x{self.scroll_clicks} ({self.rel_x * 100:.1f}%, {self.rel_y * 100:.1f}%)"
        if self.kind == "hotkey":
            return f"Tasto {self.hotkey}"
        if self.kind == "hotkey_if_dialog":
            return f"Tasto {self.hotkey} su eventuale Pop-up (entro {self.delay_ms} ms)"
        if self.kind == "wait":
            return f"Attendi {self.delay_ms} ms"
        if self.kind == "osc":
            if self.osc_mode == "relative":
                return (
                    f"OSC {self.osc_host}:{self.osc_port} {self.osc_address} "
                    f"{self.osc_value:+g} ({self.osc_min:g}..{self.osc_max:g})"
                )
            if self.osc_mode == "toggle":
                return (
                    f"OSC {self.osc_host}:{self.osc_port} {self.osc_address} "
                    f"Toggle ({self.osc_min:g}/{self.osc_max:g})"
                )
            return f"OSC {self.osc_host}:{self.osc_port} {self.osc_address}={self.osc_value}"
        if self.kind == "xr18_cmd":
            cmd = self.xr18_command.strip() or "<vuoto>"
            return f"XR18 Smart ({self.osc_host}:{self.osc_port}): '{cmd}'"
        if self.kind == "artnet":
            return (
                f"Art-Net U{self.artnet_universe} Blackout"
                if self.artnet_blackout
                else f"Art-Net U{self.artnet_universe} Ch{self.artnet_channel}={self.artnet_value}"
            )
        if self.kind in ("midi_cc", "midi_note"):
            return f"{self.kind.upper()} Ch{self.midi_channel} #{self.midi_control}={self.midi_value}"
        if self.kind == "midi_pc":
            banks: list[str] = []
            if self.midi_bank_msb >= 0:
                banks.append(f"MSB={self.midi_bank_msb}")
            if self.midi_bank_lsb >= 0:
                banks.append(f"LSB={self.midi_bank_lsb}")
            bank_txt = f" ({', '.join(banks)})" if banks else ""
            return f"MIDI ProgChg Ch{self.midi_channel} Pgm={self.midi_value}{bank_txt}"
        if self.kind == "open_project":
            target = "{nome}" if self.use_spoken_param else self.fixed_file_path
            hk_note = f" (via {self.open_hotkey})" if self.open_hotkey.strip() else ""
            return f"Apri file '{target}' da cartella{hk_note}"
        if self.kind == "paste_text":
            txt = self.paste_text.strip() or "<svuota ricerca>"
            parts = []
            if self.paste_before_hotkey.strip():
                parts.append(self.paste_before_hotkey.strip())
            parts.append(f"'{txt}'")
            if self.paste_after_hotkey.strip():
                parts.append(self.paste_after_hotkey.strip())
            return "Cerca/Incolla " + " -> ".join(parts)
        return self.kind


@dataclass
class ProgramFunction:
    """A voice-triggered single control, macro sequence, or advanced protocol action."""

    id: str
    commands: list[str] = field(default_factory=list)  # [0]=primary, [1:]=aliases
    signature: str = ""
    steps: list[ActionStep] = field(default_factory=list)
    focus_before_run: bool = True
    launch_if_closed: bool = True
    allow_without_prefix: bool = False
    sample_files: list[str] = field(default_factory=list)

    @property
    def primary_command(self) -> str:
        return self.commands[0] if self.commands else ""

    @property
    def aliases(self) -> list[str]:
        return self.commands[1:] if len(self.commands) > 1 else []


@dataclass
class ProgramProfile:
    """Arbitrary dynamically-added program with its own Settings tab, open phrases, and functions."""

    id: str
    name: str
    executable: str = ""
    arguments: str = ""
    working_dir: str = ""
    process_name: str = ""
    window_title_patterns: list[str] = field(default_factory=list)
    enabled: bool = True
    fuzzy_matching: bool = True
    fuzzy_threshold: float = 0.80
    launch_on_startup: bool = False
    startup_delay_sec: float = 1.5
    open_commands: list[str] = field(default_factory=list)  # [0]=primary prefix, [1:]=aliases
    open_samples: list[str] = field(default_factory=list)
    functions: list[ProgramFunction] = field(default_factory=list)

    @property
    def primary_open_command(self) -> str:
        return self.open_commands[0] if self.open_commands else ""


def compute_function_signature(steps: list[ActionStep]) -> str:
    """Compute canonical signature to detect repeat picks of the same control as aliases."""
    parts: list[str] = []
    for s in steps:
        if s.kind == "wait":
            continue
        if s.kind in ("click", "double_click", "right_click", "scroll_up", "scroll_down"):
            if s.uia_automation_id.strip():
                parts.append(f"uia:{s.kind}:{s.uia_automation_id.strip().lower()}")
            else:
                bx = round(s.rel_x / 0.018)
                by = round(s.rel_y / 0.018)
                parts.append(f"pos:{s.kind}:{bx}:{by}")
        elif s.kind == "hotkey":
            parts.append(f"hk:{s.hotkey.strip().lower()}")
        elif s.kind == "hotkey_if_dialog":
            parts.append(f"hkdlg:{s.hotkey.strip().lower()}")
        elif s.kind == "osc":
            parts.append(f"osc:{s.osc_host}:{s.osc_port}:{s.osc_address}:{s.osc_value}")
        elif s.kind == "artnet":
            parts.append(
                f"artnet:{s.artnet_universe}:{s.artnet_channel}:{s.artnet_value}:{s.artnet_blackout}"
            )
        elif s.kind in ("midi_cc", "midi_note"):
            parts.append(f"midi:{s.kind}:{s.midi_channel}:{s.midi_control}:{s.midi_value}")
        elif s.kind == "midi_pc":
            parts.append(
                f"midipc:{s.midi_channel}:{s.midi_bank_msb}:{s.midi_bank_lsb}:{s.midi_value}"
            )
        elif s.kind == "open_project":
            parts.append(f"open:{s.use_spoken_param}:{','.join(s.project_folders)}:{s.open_hotkey.strip().lower()}")
        else:
            parts.append(s.kind)
    return "|".join(parts)


def _steps_close_enough(a: list[ActionStep], b: list[ActionStep]) -> bool:
    non_wait_a = [s for s in a if s.kind != "wait"]
    non_wait_b = [s for s in b if s.kind != "wait"]
    if len(non_wait_a) != len(non_wait_b) or not non_wait_a:
        return False
    for sa, sb in zip(non_wait_a, non_wait_b):
        if sa.kind != sb.kind:
            return False
        if sa.kind in ("click", "double_click", "right_click", "scroll_up", "scroll_down"):
            if sa.uia_automation_id and sb.uia_automation_id:
                if sa.uia_automation_id != sb.uia_automation_id:
                    return False
            elif abs(sa.rel_x - sb.rel_x) > 0.02 or abs(sa.rel_y - sb.rel_y) > 0.02:
                return False
        elif compute_function_signature([sa]) != compute_function_signature([sb]):
            return False
    return True


def register_or_merge_function(
    profile: ProgramProfile,
    commands: list[str],
    steps: list[ActionStep],
    focus_before_run: bool = True,
    launch_if_closed: bool = True,
    sample_files: list[str] | None = None,
    allow_without_prefix: bool = False,
) -> tuple[ProgramFunction, bool]:
    """Add a function or merge new voice commands/samples as aliases if control already picked."""
    clean_cmds: list[str] = []
    for c in commands:
        cs = c.strip()
        if cs and cs.lower() not in [x.lower() for x in clean_cmds]:
            clean_cmds.append(cs)
    clean_samples = [s.strip() for s in (sample_files or []) if s.strip()]

    sig = compute_function_signature(steps)
    for existing in profile.functions:
        if (sig and existing.signature == sig) or _steps_close_enough(existing.steps, steps):
            for cmd in clean_cmds:
                if cmd.lower() not in [c.lower() for c in existing.commands]:
                    existing.commands.append(cmd)
            for sf in clean_samples:
                if sf not in existing.sample_files:
                    existing.sample_files.append(sf)
            if allow_without_prefix:
                existing.allow_without_prefix = True
            return existing, True

    fn = ProgramFunction(
        id=f"fn_{len(profile.functions) + 1}_{abs(hash(sig)) % 100000}",
        commands=clean_cmds,
        signature=sig,
        steps=steps,
        focus_before_run=focus_before_run,
        launch_if_closed=launch_if_closed,
        allow_without_prefix=allow_without_prefix,
        sample_files=clean_samples,
    )
    profile.functions.append(fn)
    return fn, False


@dataclass
class AppConfig:
    version: int = 2
    general: GeneralSettings = field(default_factory=GeneralSettings)
    sleep_wake: SleepWakeSettings = field(default_factory=SleepWakeSettings)
    audio: AudioSettings = field(default_factory=AudioSettings)
    stt: STTSettings = field(default_factory=STTSettings)
    programs: list[ProgramProfile] = field(default_factory=list)
    prefix_routes: dict[str, PrefixRouteConfig] = field(
        default_factory=default_prefix_routes
    )
    xr18: XR18Settings = field(default_factory=XR18Settings)
    cakewalk: CakewalkSettings = field(default_factory=CakewalkSettings)
    qlc: QLCSettings = field(default_factory=QLCSettings)
    virtualdj: VirtualDJSettings = field(default_factory=VirtualDJSettings)
    popup_handler: PopupHandlerSettings = field(default_factory=PopupHandlerSettings)
    stage_launcher: StageLauncherSettings = field(
        default_factory=StageLauncherSettings
    )
    panic: PanicSettings = field(default_factory=PanicSettings)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        if not isinstance(data, dict):
            return cls()

        def _build_dc(dc_cls: type, raw: Any):
            if not isinstance(raw, dict):
                return dc_cls()
            valid = {f for f in dc_cls.__dataclass_fields__}
            filtered = {k: v for k, v in raw.items() if k in valid}
            return dc_cls(**filtered)

        routes = default_prefix_routes()
        raw_routes = data.get("prefix_routes")
        if isinstance(raw_routes, dict):
            for key, raw_route in raw_routes.items():
                if isinstance(raw_route, dict):
                    valid = {f for f in PrefixRouteConfig.__dataclass_fields__}
                    merged = {"target_id": key, "display_name": key}
                    if key in routes:
                        merged = asdict(routes[key])
                    merged.update({k: v for k, v in raw_route.items() if k in valid})
                    routes[key] = PrefixRouteConfig(**merged)

        raw_launcher = data.get("stage_launcher")
        launcher = _build_dc(StageLauncherSettings, raw_launcher)
        if isinstance(raw_launcher, dict) and isinstance(raw_launcher.get("apps"), list):
            parsed_apps: list[StageAppEntry] = []
            for item in raw_launcher["apps"]:
                if isinstance(item, dict) and item.get("name"):
                    valid = {f for f in StageAppEntry.__dataclass_fields__}
                    filtered = {k: v for k, v in item.items() if k in valid}
                    if "id" not in filtered or not filtered["id"]:
                        filtered["id"] = filtered["name"].lower().replace(" ", "_")
                    parsed_apps.append(StageAppEntry(**filtered))
            if parsed_apps or raw_launcher.get("apps") == []:
                launcher.apps = parsed_apps

        parsed_programs: list[ProgramProfile] = []
        raw_programs = data.get("programs")
        if isinstance(raw_programs, list):
            for p_raw in raw_programs:
                if not isinstance(p_raw, dict) or not p_raw.get("name"):
                    continue
                valid_p = {f for f in ProgramProfile.__dataclass_fields__}
                p_filtered = {
                    k: v for k, v in p_raw.items() if k in valid_p and k != "functions"
                }
                if "id" not in p_filtered or not p_filtered["id"]:
                    p_filtered["id"] = p_filtered["name"].lower().replace(" ", "_")

                parsed_fns: list[ProgramFunction] = []
                for f_raw in p_raw.get("functions", []):
                    if not isinstance(f_raw, dict):
                        continue
                    valid_f = {f for f in ProgramFunction.__dataclass_fields__}
                    f_filtered = {
                        k: v for k, v in f_raw.items() if k in valid_f and k != "steps"
                    }
                    if "id" not in f_filtered or not f_filtered["id"]:
                        f_filtered["id"] = f"fn_{len(parsed_fns) + 1}"
                    parsed_steps: list[ActionStep] = []
                    for s_raw in f_raw.get("steps", []):
                        if isinstance(s_raw, dict):
                            parsed_steps.append(_build_dc(ActionStep, s_raw))
                    f_filtered["steps"] = parsed_steps
                    parsed_fns.append(ProgramFunction(**f_filtered))
                p_filtered["functions"] = parsed_fns
                parsed_programs.append(ProgramProfile(**p_filtered))

        return cls(
            version=int(data.get("version", 2)),
            general=_build_dc(GeneralSettings, data.get("general")),
            sleep_wake=_build_dc(SleepWakeSettings, data.get("sleep_wake")),
            audio=_build_dc(AudioSettings, data.get("audio")),
            stt=_build_dc(STTSettings, data.get("stt")),
            programs=parsed_programs,
            prefix_routes=routes,
            xr18=_build_dc(XR18Settings, data.get("xr18")),
            cakewalk=_build_dc(CakewalkSettings, data.get("cakewalk")),
            qlc=_build_dc(QLCSettings, data.get("qlc")),
            virtualdj=_build_dc(VirtualDJSettings, data.get("virtualdj")),
            popup_handler=_build_dc(PopupHandlerSettings, data.get("popup_handler")),
            stage_launcher=launcher,
            panic=_build_dc(PanicSettings, data.get("panic")),
        )
