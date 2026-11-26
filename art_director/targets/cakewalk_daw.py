"""Sonar Cakewalk / Cross-Platform DAW controller."""

from __future__ import annotations

import re
import time
from difflib import SequenceMatcher
from pathlib import Path

from ..config.schema import CakewalkSettings
from ..core.parser import (
    extract_numbers,
    normalize_compact,
    normalize_text,
    replace_spoken_numbers,
)
from .base import BaseTarget, CommandExecutionResult, MidiOutputHelper, TargetContext


def find_project_by_unique_name(
    query: str,
    workspace_folders: list[str],
    extensions: list[str],
) -> tuple[Path | None, list[Path], str]:
    """Locate a project file in workspace folders by unique spoken name."""
    norm_q = normalize_text(query)
    compact_q = normalize_compact(query)
    if not norm_q:
        return None, [], "Nome progetto vuoto"

    exts = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in extensions if e.strip()}
    if not exts:
        exts = {".cwp", ".cwb", ".wrk", ".rpp"}

    candidates: list[Path] = []
    for folder in workspace_folders:
        root = Path(folder.strip())
        if not root.exists() or not root.is_dir():
            continue
        for p in root.rglob("*"):
            if p.is_file() and p.suffix.lower() in exts:
                candidates.append(p)

    if not candidates:
        return None, [], "Nessun file progetto trovato nelle cartelle di lavoro configurate"

    primary_candidates = [
        p
        for p in candidates
        if not p.stem.lower().startswith(
            ("salva automaticamente copia di ", "auto-save copy of ")
        )
    ]
    if primary_candidates:
        candidates = primary_candidates

    exact: list[Path] = []
    substring: list[Path] = []
    fuzzy: list[tuple[float, Path]] = []

    for path in candidates:
        stem_norm = normalize_text(path.stem)
        stem_compact = normalize_compact(path.stem)
        stem_clean = re.sub(r"\b(?:44\s*1|48|96)\s*khz\b.*$", "", stem_norm).strip() or stem_norm
        stem_clean_compact = normalize_compact(stem_clean)
        if stem_norm == norm_q or stem_compact == compact_q or stem_clean == norm_q:
            exact.append(path)
        elif norm_q in stem_norm or (compact_q and compact_q in stem_compact):
            substring.append(path)
        else:
            score = max(
                SequenceMatcher(None, norm_q, stem_norm).ratio(),
                SequenceMatcher(None, compact_q, stem_compact).ratio(),
                SequenceMatcher(None, norm_q, stem_clean).ratio(),
                SequenceMatcher(None, compact_q, stem_clean_compact).ratio(),
            )
            if score >= 0.72:
                fuzzy.append((score, path))

    if len(exact) == 1:
        return exact[0], exact, f"Trovato progetto esatto: {exact[0].name}"
    if len(exact) > 1:
        return None, exact, f"Trovati più file con nome identico '{query}': {[p.name for p in exact]}"

    if len(substring) == 1:
        return substring[0], substring, f"Trovato progetto univoco: {substring[0].name}"
    if len(substring) > 1:
        # Check if one starts with query and others don't
        starts = [p for p in substring if normalize_text(p.stem).startswith(norm_q)]
        if len(starts) == 1:
            return starts[0], starts, f"Trovato progetto univoco: {starts[0].name}"
        return None, substring, f"Nome progetto non univoco ('{query}'): {[p.name for p in substring[:5]]}"

    if fuzzy:
        fuzzy.sort(key=lambda item: item[0], reverse=True)
        top_score, top_path = fuzzy[0]
        if len(fuzzy) == 1 or (top_score - fuzzy[1][0]) >= 0.08:
            return top_path, [top_path], f"Trovato progetto (match {top_score:.0%}): {top_path.name}"
        ambiguous = [p for _, p in fuzzy[:4]]
        return None, ambiguous, f"Corrispondenza ambigua per '{query}': {[p.name for p in ambiguous]}"

    return None, [], f"Nessun progetto corrispondente a '{query}'"


class CakewalkDAWTarget(BaseTarget):
    """Controls Sonar Cakewalk / DAW transport, markers, projects, and named tracks."""

    def __init__(self, midi: MidiOutputHelper | None = None) -> None:
        self._midi = midi or MidiOutputHelper()
        self._track_volumes: dict[str, int] = {}

    @property
    def target_id(self) -> str:
        return "cakewalk"

    def close(self) -> None:
        self._midi.close()

    def _focus_if_enabled(self, ctx: TargetContext) -> None:
        route = ctx.config.prefix_routes.get(self.target_id)
        if route and route.auto_focus_window and route.window_title_patterns:
            ctx.os_bridge.focus_window(route.window_title_patterns)
            time.sleep(0.06)

    def handle(self, remainder: str, ctx: TargetContext) -> CommandExecutionResult:
        cfg = ctx.config.cakewalk
        text = replace_spoken_numbers(remainder)
        if not text:
            return CommandExecutionResult(False, self.target_id, "Comando DAW vuoto")

        # 1. Project switching: clean close + unique-name open
        if any(w in text for w in ("apri progetto", "carica progetto", "cambia progetto", "nuovo progetto")):
            return self._handle_switch_project(remainder, cfg, ctx)
        if any(w in text for w in ("chiudi progetto", "salva e chiudi")):
            self._close_current_project(cfg, ctx)
            return CommandExecutionResult(True, self.target_id, "DAW: chiuso progetto corrente in modo pulito")

        # 2. Track commands by unique track name (volume, mute, edit FX)
        track_name, track_cfg = self._resolve_track(text, cfg)
        if track_name is not None and track_cfg is not None:
            return self._handle_track_command(text, track_name, track_cfg, cfg, ctx)

        # 3. Marker navigation
        if "marker" in text or "marcatore" in text or "segnalibro" in text:
            return self._handle_marker(text, cfg, ctx)

        # 4. Transport: Play, Stop, Record, Rewind
        if any(w in text for w in ("registra", "registrazione", "rec")):
            return self._send_transport("record", "Registrazione avviata", cfg, ctx)
        if any(w in text for w in ("riavvolgi", "inizio", "rewind", "torna a zero")):
            return self._send_transport("rewind", "Riavvolto a inizio progetto", cfg, ctx)
        if any(w in text for w in ("stop", "ferma")):
            return self._send_transport("stop", "Stop trasporto", cfg, ctx)
        if any(w in text for w in ("play", "pausa", "avvia", "riproduci", "suona")):
            return self._send_transport("play_pause", "Play / Pausa", cfg, ctx)

        return CommandExecutionResult(
            False, self.target_id, f"DAW: comando non riconosciuto '{remainder}'"
        )

    def panic(self, ctx: TargetContext) -> list[str]:
        if not ctx.config.cakewalk.panic_send_stop:
            return []
        self._focus_if_enabled(ctx)
        hotkey = ctx.config.cakewalk.shortcuts.get("stop", "space")
        ctx.os_bridge.send_hotkey(hotkey)
        return ["DAW: inviato Stop trasporto"]

    def _send_transport(
        self, action_key: str, label: str, cfg: CakewalkSettings, ctx: TargetContext
    ) -> CommandExecutionResult:
        self._focus_if_enabled(ctx)
        hotkey = cfg.shortcuts.get(action_key, "")
        if not hotkey:
            return CommandExecutionResult(False, self.target_id, f"Shortcut '{action_key}' non configurato")
        ok = ctx.os_bridge.send_hotkey(hotkey)
        return CommandExecutionResult(
            ok, self.target_id, f"DAW: {label} ({hotkey})", {"shortcut": hotkey}
        )

    def _handle_marker(
        self, text: str, cfg: CakewalkSettings, ctx: TargetContext
    ) -> CommandExecutionResult:
        if any(w in text for w in ("prossimo", "successivo", "avanti", "next")):
            return self._send_transport("next_marker", "Marker successivo", cfg, ctx)
        if any(w in text for w in ("precedente", "indietro", "prima", "prev")):
            return self._send_transport("prev_marker", "Marker precedente", cfg, ctx)
        return self._send_transport("insert_marker", "Inserito Marker", cfg, ctx)

    def _close_current_project(self, cfg: CakewalkSettings, ctx: TargetContext) -> None:
        self._focus_if_enabled(ctx)
        if cfg.save_before_close:
            save_hk = cfg.shortcuts.get("save_project", "<ctrl>+s")
            if save_hk:
                ctx.os_bridge.send_hotkey(save_hk)
                if ctx.cancel_token.wait(0.35):
                    return
        close_hk = cfg.shortcuts.get("close_project", "<ctrl>+w")
        if close_hk:
            ctx.os_bridge.send_hotkey(close_hk)
            if ctx.cancel_token.wait(0.25):
                return
        if cfg.close_unsaved_policy == "save":
            ctx.os_bridge.send_hotkey("enter")
        elif cfg.close_unsaved_policy == "discard":
            ctx.os_bridge.send_hotkey("n")

    def _handle_switch_project(
        self, remainder: str, cfg: CakewalkSettings, ctx: TargetContext
    ) -> CommandExecutionResult:
        # Extract project name after "apri progetto" / "carica progetto" / etc.
        norm_rem = normalize_text(remainder)
        cleaned = re.sub(
            r"^(?:apri|carica|cambia|nuovo)\s+(?:il\s+)?(?:progetto|file|brano)\s*",
            "",
            norm_rem,
        ).strip()
        if not cleaned:
            return CommandExecutionResult(False, self.target_id, "DAW: specifica il nome univoco del progetto")

        matched, _all_matches, find_msg = find_project_by_unique_name(
            cleaned, cfg.workspace_folders, cfg.project_extensions
        )
        if matched is None:
            return CommandExecutionResult(False, self.target_id, f"DAW: {find_msg}")

        self._close_current_project(cfg, ctx)
        if ctx.cancel_token.wait(max(0.1, cfg.close_wait_ms / 1000.0)):
            return CommandExecutionResult(False, self.target_id, "DAW: cambio progetto interrotto da PANIC")

        if cfg.executable_path.strip():
            ok, open_msg = ctx.os_bridge.launch_executable(
                cfg.executable_path, f'"{matched}"', str(matched.parent)
            )
        else:
            ok, open_msg = ctx.os_bridge.open_document_or_file(matched)

        return CommandExecutionResult(
            ok,
            self.target_id,
            f"DAW: chiusura pulita eseguita -> apertura '{matched.name}' ({open_msg})",
            {"project_path": str(matched)},
        )

    def _resolve_track(
        self, text: str, cfg: CakewalkSettings
    ) -> tuple[str | None, dict | None]:
        for name, track_cfg in sorted(
            cfg.tracks.items(), key=lambda kv: len(kv[0]), reverse=True
        ):
            n = normalize_text(name)
            if n and f" {n} " in f" {text} ":
                return name, track_cfg
        return None, None

    def _handle_track_command(
        self,
        text: str,
        track_name: str,
        track_cfg: dict,
        cfg: CakewalkSettings,
        ctx: TargetContext,
    ) -> CommandExecutionResult:
        midi_ch = int(track_cfg.get("midi_channel", 1))
        use_midi = cfg.transport_mode in ("hybrid", "midi") and bool(cfg.midi_port_name.strip())

        # 1. Edit / Open Track Effects
        if any(w in text for w in ("effetti", "effetto", "fx", "plugin", "vst", "edit")):
            fx_hk = str(track_cfg.get("fx_hotkey", "")).strip()
            if fx_hk:
                self._focus_if_enabled(ctx)
                ok = ctx.os_bridge.send_hotkey(fx_hk)
                return CommandExecutionResult(
                    ok, self.target_id, f"DAW: aperti effetti traccia '{track_name}' ({fx_hk})"
                )
            fx_cc = int(track_cfg.get("fx_cc", -1))
            if use_midi and fx_cc >= 0:
                ok = self._midi.send_cc(cfg.midi_port_name, midi_ch, fx_cc, 127)
                if ok:
                    return CommandExecutionResult(
                        True,
                        self.target_id,
                        f"DAW: inviato edit FX MIDI CC{fx_cc} per traccia '{track_name}'",
                        {"midi_cc": fx_cc},
                    )
            # Keyboard / Find-track fallback
            self._focus_if_enabled(ctx)
            edit_fx_hk = cfg.shortcuts.get("edit_fx", "<alt>+f")
            if edit_fx_hk:
                ctx.os_bridge.send_hotkey(edit_fx_hk)
            return CommandExecutionResult(
                True,
                self.target_id,
                f"DAW: inviato comando Edit Effetti ({edit_fx_hk}) per traccia '{track_name}'",
            )

        # 2. Track Mute
        if any(w in text for w in ("muta", "mute", "smuta", "unmute")):
            unmute = "smuta" in text or "unmute" in text
            mute_cc = int(track_cfg.get("mute_cc", -1))
            if use_midi and mute_cc >= 0:
                ok = self._midi.send_cc(
                    cfg.midi_port_name, midi_ch, mute_cc, 0 if unmute else 127
                )
                return CommandExecutionResult(
                    ok,
                    self.target_id,
                    f"DAW: traccia '{track_name}' {'unmute' if unmute else 'mutata'} (CC{mute_cc})",
                )
            self._focus_if_enabled(ctx)
            ctx.os_bridge.send_hotkey("m")
            return CommandExecutionResult(
                True, self.target_id, f"DAW: toggle Mute traccia '{track_name}'"
            )

        # 3. Track Volume
        vol_cc = int(track_cfg.get("volume_cc", 7))
        cur_val = self._track_volumes.get(track_name, 100)
        nums = extract_numbers(text)
        target_midi: int | None = None
        if nums:
            pct = max(0.0, min(100.0, nums[-1]))
            target_midi = int(round((pct / 100.0) * 127.0))
        elif any(w in text for w in ("alza", "aumenta", "piu")):
            target_midi = min(127, cur_val + 10)
        elif any(w in text for w in ("abbassa", "riduci", "meno")):
            target_midi = max(0, cur_val - 10)
        elif "zero" in text or "minimo" in text:
            target_midi = 0
        elif "massimo" in text:
            target_midi = 127

        if target_midi is not None:
            self._track_volumes[track_name] = target_midi
            if use_midi and vol_cc >= 0:
                ok = self._midi.send_cc(cfg.midi_port_name, midi_ch, vol_cc, target_midi)
                return CommandExecutionResult(
                    ok,
                    self.target_id,
                    f"DAW: volume traccia '{track_name}' -> {round(target_midi / 127.0 * 100)}% (MIDI CC{vol_cc}={target_midi})",
                    {"midi_cc": vol_cc, "value": target_midi},
                )
            return CommandExecutionResult(
                False,
                self.target_id,
                f"DAW: configura una porta MIDI (es. loopMIDI) nei Settings per regolare volume traccia '{track_name}'",
            )

        return CommandExecutionResult(
            False, self.target_id, f"DAW: azione su traccia '{track_name}' non riconosciuta"
        )
