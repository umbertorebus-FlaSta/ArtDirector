"""VirtualDJ controller supporting Hybrid Hotkeys, MIDI, and OSC."""

from __future__ import annotations

import re
import time
from typing import Callable

from pythonosc.udp_client import SimpleUDPClient

from ..config.schema import VirtualDJSettings
from ..core.parser import extract_numbers, replace_spoken_numbers
from .base import BaseTarget, CommandExecutionResult, MidiOutputHelper, TargetContext


class VirtualDJTarget(BaseTarget):
    """Controls VirtualDJ decks, sidelist loading, mix/crossfade, gain, EQ, cues, and stop."""

    def __init__(
        self,
        midi: MidiOutputHelper | None = None,
        osc_sender: Callable[[str, int, str, float], None] | None = None,
    ) -> None:
        self._midi = midi or MidiOutputHelper()
        self._custom_osc = osc_sender
        self._osc_client: SimpleUDPClient | None = None
        self._osc_addr: tuple[str, int] | None = None
        self._active_deck = 1
        self._deck_gain: dict[int, float] = {1: 0.5, 2: 0.5}
        self._deck_eq: dict[tuple[int, str], float] = {}
        self._crossfader: float = 0.5

    @property
    def target_id(self) -> str:
        return "virtualdj"

    def close(self) -> None:
        self._midi.close()

    def _focus_if_enabled(self, ctx: TargetContext) -> None:
        route = ctx.config.prefix_routes.get(self.target_id)
        if route and route.auto_focus_window and route.window_title_patterns:
            ctx.os_bridge.focus_window(route.window_title_patterns)
            time.sleep(0.05)

    def _send_osc(self, cfg: VirtualDJSettings, path: str, value: float) -> None:
        if self._custom_osc is not None:
            self._custom_osc(cfg.osc_host, cfg.osc_port, path, value)
            return
        addr = (cfg.osc_host, int(cfg.osc_port))
        if self._osc_client is None or self._osc_addr != addr:
            self._osc_client = SimpleUDPClient(cfg.osc_host, int(cfg.osc_port))
            self._osc_addr = addr
        self._osc_client.send_message(path, float(value))

    def _send_midi_mapping(
        self, cfg: VirtualDJSettings, mapping_key: str, value_norm: float | None = None
    ) -> bool:
        if not cfg.midi_port_name.strip():
            return False
        m = cfg.midi_mappings.get(mapping_key)
        if not m:
            return False
        ch = int(m.get("channel", 1))
        cc = int(m.get("cc", -1))
        note = int(m.get("note", -1))
        if cc >= 0 and value_norm is not None:
            val_7bit = max(0, min(127, int(round(value_norm * 127.0))))
            return self._midi.send_cc(cfg.midi_port_name, ch, cc, val_7bit)
        if note >= 0:
            return self._midi.send_note(cfg.midi_port_name, ch, note, 127)
        return False

    def _trigger_action(
        self,
        cfg: VirtualDJSettings,
        ctx: TargetContext,
        shortcut_key: str,
        midi_key: str = "",
        osc_path: str = "",
        osc_val: float = 1.0,
    ) -> None:
        mode = cfg.transport_mode
        if mode in ("osc", "hybrid") and osc_path and mode == "osc":
            self._send_osc(cfg, osc_path, osc_val)
            return
        if mode in ("midi", "hybrid") and midi_key:
            if self._send_midi_mapping(cfg, midi_key, osc_val):
                return
        if mode in ("shortcuts", "hybrid") and shortcut_key:
            hk = cfg.shortcuts.get(shortcut_key, "")
            if hk:
                self._focus_if_enabled(ctx)
                ctx.os_bridge.send_hotkey(hk)
                return
        if osc_path:
            self._send_osc(cfg, osc_path, osc_val)

    def handle(self, remainder: str, ctx: TargetContext) -> CommandExecutionResult:
        cfg = ctx.config.virtualdj
        if self._active_deck not in (1, 2):
            self._active_deck = cfg.active_deck
        text = replace_spoken_numbers(remainder)
        if not text:
            return CommandExecutionResult(False, self.target_id, "Comando VirtualDJ vuoto")

        deck = self._extract_deck(text)
        if deck is not None:
            self._active_deck = deck
        target_deck = deck if deck is not None else self._active_deck

        # 1. STOP for Deck 1, Deck 2, or both
        if any(w in text for w in ("stop", "ferma")):
            if any(w in text for w in ("entrambi", "tutti", "due")):
                self._trigger_action(
                    cfg, ctx, "stop_deck_1", "deck_1_stop", "/vdj/deck/1/stop", 1.0
                )
                self._trigger_action(
                    cfg, ctx, "stop_deck_2", "deck_2_stop", "/vdj/deck/2/stop", 1.0
                )
                return CommandExecutionResult(
                    True, self.target_id, "VirtualDJ: STOP Deck 1 e Deck 2"
                )
            self._trigger_action(
                cfg,
                ctx,
                f"stop_deck_{target_deck}",
                f"deck_{target_deck}_stop",
                f"/vdj/deck/{target_deck}/stop",
                1.0,
            )
            return CommandExecutionResult(
                True, self.target_id, f"VirtualDJ: STOP Deck {target_deck}"
            )

        # 2. Goto Next Cue on active deck
        if "cue" in text:
            self._trigger_action(
                cfg,
                ctx,
                "goto_next_cue",
                f"deck_{target_deck}_next_cue",
                f"/vdj/deck/{target_deck}/goto_cue",
                1.0,
            )
            return CommandExecutionResult(
                True,
                self.target_id,
                f"VirtualDJ: Goto Next Cue su Deck attivo ({target_deck})",
            )

        # 3. Load from active side list / browser navigation
        if any(w in text for w in ("lista", "sidelist", "brano successivo", "prossimo brano")):
            if "prossimo" in text or "giu" in text or "avanti" in text:
                self._trigger_action(cfg, ctx, "browser_next", "", "/vdj/browser/next", 1.0)
                if "carica" not in text:
                    return CommandExecutionResult(
                        True, self.target_id, "VirtualDJ: seleziona brano successivo in lista"
                    )
            if "precedente" in text or "su" in text or "indietro" in text:
                self._trigger_action(cfg, ctx, "browser_prev", "", "/vdj/browser/prev", 1.0)
                if "carica" not in text:
                    return CommandExecutionResult(
                        True, self.target_id, "VirtualDJ: seleziona brano precedente in lista"
                    )
        if any(w in text for w in ("carica", "load")):
            if "sidelist" in text or "lista" in text:
                self._trigger_action(
                    cfg,
                    ctx,
                    "load_sidelist",
                    f"deck_{target_deck}_load",
                    f"/vdj/deck/{target_deck}/load_sidelist",
                    1.0,
                )
                return CommandExecutionResult(
                    True,
                    self.target_id,
                    f"VirtualDJ: caricato brano da lista laterale su Deck {target_deck}",
                )
            sc = f"load_deck_{deck}" if deck in (1, 2) else "load_active"
            self._trigger_action(
                cfg,
                ctx,
                sc,
                f"deck_{target_deck}_load",
                f"/vdj/deck/{target_deck}/load",
                1.0,
            )
            return CommandExecutionResult(
                True,
                self.target_id,
                f"VirtualDJ: caricato brano selezionato su Deck {target_deck}",
            )

        # 4. Gain per deck
        if any(w in text for w in ("gain", "guadagno")):
            cur = self._deck_gain.get(target_deck, 0.5)
            new_val = self._compute_normalized_knob(text, cur, deck)
            if new_val is None:
                return CommandExecutionResult(
                    False, self.target_id, f"VirtualDJ: specifica livello gain per Deck {target_deck}"
                )
            self._deck_gain[target_deck] = new_val
            self._trigger_action(
                cfg,
                ctx,
                "",
                f"deck_{target_deck}_gain",
                f"/vdj/deck/{target_deck}/gain",
                new_val,
            )
            return CommandExecutionResult(
                True,
                self.target_id,
                f"VirtualDJ: Gain Deck {target_deck} -> {round(new_val * 100)}%",
                {"deck": target_deck, "gain": round(new_val, 3)},
            )

        # 5. EQ per deck (Low / Mid / High)
        eq_band = self._extract_eq_band(text)
        if eq_band is not None:
            key = (target_deck, eq_band)
            cur = self._deck_eq.get(key, 0.5)
            new_val = self._compute_normalized_knob(text, cur, deck)
            if new_val is None:
                return CommandExecutionResult(
                    False, self.target_id, f"VirtualDJ: specifica valore EQ {eq_band} per Deck {target_deck}"
                )
            self._deck_eq[key] = new_val
            self._trigger_action(
                cfg,
                ctx,
                "",
                f"deck_{target_deck}_eq_{eq_band}",
                f"/vdj/deck/{target_deck}/eq_{eq_band}",
                new_val,
            )
            return CommandExecutionResult(
                True,
                self.target_id,
                f"VirtualDJ: EQ {eq_band.upper()} Deck {target_deck} -> {round(new_val * 100)}%",
                {"deck": target_deck, "band": eq_band, "value": round(new_val, 3)},
            )

        # 6. Mix / Crossfade
        if any(w in text for w in ("mix", "automix", "crossfader", "crossfade", "passa")):
            if "deck 1" in text or "sinistra" in text:
                self._crossfader = 0.0
                self._active_deck = 1
                self._trigger_action(
                    cfg, ctx, "crossfade_deck_1", "crossfader", "/vdj/crossfader", 0.0
                )
                return CommandExecutionResult(True, self.target_id, "VirtualDJ: Mix verso Deck 1")
            if "deck 2" in text or "destra" in text:
                self._crossfader = 1.0
                self._active_deck = 2
                self._trigger_action(
                    cfg, ctx, "crossfade_deck_2", "crossfader", "/vdj/crossfader", 1.0
                )
                return CommandExecutionResult(True, self.target_id, "VirtualDJ: Mix verso Deck 2")
            nums = extract_numbers(text)
            if nums:
                cf = max(0.0, min(1.0, nums[-1] / 100.0 if nums[-1] > 1.0 else nums[-1]))
                self._crossfader = cf
                self._trigger_action(cfg, ctx, "", "crossfader", "/vdj/crossfader", cf)
                return CommandExecutionResult(
                    True, self.target_id, f"VirtualDJ: Crossfader -> {round(cf * 100)}%"
                )
            self._trigger_action(cfg, ctx, "mix_automix", "", "/vdj/automix", 1.0)
            return CommandExecutionResult(True, self.target_id, "VirtualDJ: Mix / Automix attivato")

        # 7. Play / Pause
        if any(w in text for w in ("play", "pausa", "avvia", "riproduci")):
            sc = f"play_pause_deck_{deck}" if deck in (1, 2) else "play_pause_active"
            self._trigger_action(
                cfg,
                ctx,
                sc,
                f"deck_{target_deck}_play",
                f"/vdj/deck/{target_deck}/play_pause",
                1.0,
            )
            return CommandExecutionResult(
                True, self.target_id, f"VirtualDJ: Play / Pausa Deck {target_deck}"
            )

        return CommandExecutionResult(
            False, self.target_id, f"VirtualDJ: comando non riconosciuto '{remainder}'"
        )

    def panic(self, ctx: TargetContext) -> list[str]:
        if not ctx.config.virtualdj.panic_stop_decks:
            return []
        cfg = ctx.config.virtualdj
        self._trigger_action(cfg, ctx, "stop_deck_1", "deck_1_stop", "/vdj/deck/1/stop", 1.0)
        self._trigger_action(cfg, ctx, "stop_deck_2", "deck_2_stop", "/vdj/deck/2/stop", 1.0)
        return ["VirtualDJ: STOP Deck 1 e Deck 2"]

    @staticmethod
    def _extract_deck(text: str) -> int | None:
        m = re.search(r"\bdeck\s*([12])\b", text)
        if m:
            return int(m.group(1))
        if "deck a" in text:
            return 1
        if "deck b" in text:
            return 2
        return None

    @staticmethod
    def _extract_eq_band(text: str) -> str | None:
        if any(w in text for w in ("bassi", "low", "sub")):
            return "low"
        if any(w in text for w in ("medi", "mid")):
            return "mid"
        if any(w in text for w in ("alti", "high", "acuti")):
            return "high"
        return None

    @staticmethod
    def _compute_normalized_knob(
        text: str, current: float, deck_num: int | None
    ) -> float | None:
        if "kill" in text or "minimo" in text:
            return 0.0
        if "flat" in text or "centro" in text or "meta" in text or "zero" in text:
            return 0.5
        if "massimo" in text:
            return 1.0
        nums = extract_numbers(text)
        if deck_num is not None and nums and int(nums[0]) == deck_num and len(nums) > 1:
            nums = nums[1:]
        elif deck_num is not None and nums == [float(deck_num)] and not ("%" in text or "percento" in text):
            nums = []

        if nums:
            raw = nums[-1]
            if any(w in text for w in ("alza", "aumenta", "piu")):
                return max(0.0, min(1.0, current + (abs(raw) / 100.0)))
            if any(w in text for w in ("abbassa", "riduci", "meno")):
                return max(0.0, min(1.0, current - (abs(raw) / 100.0)))
            return max(0.0, min(1.0, raw / 100.0 if raw > 1.0 else raw))

        if any(w in text for w in ("alza", "aumenta", "tira su", "porta su")):
            return min(1.0, current + 0.1)
        if any(w in text for w in ("abbassa", "riduci", "tira giu", "porta giu")):
            return max(0.0, current - 0.1)
        return None
