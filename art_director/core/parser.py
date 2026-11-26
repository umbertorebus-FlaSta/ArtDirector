"""Dynamic prefix router and Italian/English voice command text normalizer."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from ..config.schema import (
    AppConfig,
    PrefixRouteConfig,
    ProgramFunction,
    ProgramProfile,
)

_UNITS_IT = {
    "zero": 0,
    "uno": 1,
    "una": 1,
    "un": 1,
    "due": 2,
    "tre": 3,
    "quattro": 4,
    "cinque": 5,
    "sei": 6,
    "sette": 7,
    "otto": 8,
    "nove": 9,
    "dieci": 10,
    "undici": 11,
    "dodici": 12,
    "tredici": 13,
    "quattordici": 14,
    "quindici": 15,
    "sedici": 16,
    "diciassette": 17,
    "diciotto": 18,
    "diciannove": 19,
}

_TENS_IT = {
    "venti": 20,
    "vent": 20,
    "trenta": 30,
    "trent": 30,
    "quaranta": 40,
    "quarant": 40,
    "cinquanta": 50,
    "cinquant": 50,
    "sessanta": 60,
    "sessant": 60,
    "settanta": 70,
    "settant": 70,
    "ottanta": 80,
    "ottant": 80,
    "novanta": 90,
    "novant": 90,
}

_UNITS_EN = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}

_TENS_EN = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}

_WORD_TO_INT: dict[str, int] = {
    **_UNITS_IT,
    **_UNITS_EN,
    "venti": 20,
    "trenta": 30,
    "quaranta": 40,
    "cinquanta": 50,
    "sessanta": 60,
    "settanta": 70,
    "ottanta": 80,
    "novanta": 90,
    "cento": 100,
    "hundred": 100,
    **_TENS_EN,
}

for _ten_word, _ten_val in _TENS_IT.items():
    for _unit_word, _unit_val in _UNITS_IT.items():
        if 1 <= _unit_val <= 9:
            if _ten_word.endswith(("a", "i")) and _unit_val in (1, 8):
                continue
            if not _ten_word.endswith(("a", "i")) and _unit_val not in (1, 8):
                continue
            _WORD_TO_INT[f"{_ten_word}{_unit_word}"] = _ten_val + _unit_val


def strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def normalize_text(text: str) -> str:
    """Lowercase, fold accents, remove noise punctuation while keeping +/-/%/digits."""
    folded = strip_accents(text).lower().strip()
    folded = re.sub(r"[,;!?\"'`()\[\]{}]+", " ", folded)
    folded = re.sub(r"\s+", " ", folded)
    return folded.strip()


def normalize_compact(text: str) -> str:
    """Remove all spaces and non-alphanumerics for phonetic prefix comparisons."""
    return re.sub(r"[^a-z0-9]", "", normalize_text(text))


def replace_spoken_numbers(text: str) -> str:
    """Convert spoken Italian/English numbers and signs into numeric tokens."""
    norm = normalize_text(text)
    tokens = norm.split()
    out: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        # Handle "meno 5" / "minus 5" / "piu 3" / "plus 3"
        if tok in ("meno", "minus") and i + 1 < len(tokens):
            nxt = _WORD_TO_INT.get(tokens[i + 1])
            if nxt is not None:
                out.append(str(-nxt))
                i += 2
                continue
            if re.fullmatch(r"\d+(?:[.,]\d+)?", tokens[i + 1]):
                out.append("-" + tokens[i + 1].replace(",", "."))
                i += 2
                continue
        if tok in ("piu", "plus") and i + 1 < len(tokens):
            nxt = _WORD_TO_INT.get(tokens[i + 1])
            if nxt is not None:
                out.append(f"+{nxt}")
                i += 2
                continue
            if re.fullmatch(r"\d+(?:[.,]\d+)?", tokens[i + 1]):
                out.append("+" + tokens[i + 1].replace(",", "."))
                i += 2
                continue

        # Handle two-word tens + unit like "settanta cinque" or "twenty five"
        if tok in _WORD_TO_INT and _WORD_TO_INT[tok] in (20, 30, 40, 50, 60, 70, 80, 90):
            if i + 1 < len(tokens):
                nxt_val = _WORD_TO_INT.get(tokens[i + 1])
                if nxt_val is not None and 1 <= nxt_val <= 9:
                    out.append(str(_WORD_TO_INT[tok] + nxt_val))
                    i += 2
                    continue

        if tok in _WORD_TO_INT:
            out.append(str(_WORD_TO_INT[tok]))
        else:
            out.append(tok)
        i += 1
    return " ".join(out)


def extract_numbers(text: str) -> list[float]:
    """Extract all signed/unsigned numbers from a command after word conversion."""
    converted = replace_spoken_numbers(text)
    matches = re.findall(r"[+-]?\d+(?:[.,]\d+)?", converted)
    return [float(m.replace(",", ".")) for m in matches]


def fuzzy_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


@dataclass
class RouteMatch:
    kind: str  # "panic" | "wake" | "sleep" | "popup" | "launch_apps" | "program_open" | "program_func" | "target" | "unmatched"
    raw_text: str
    normalized_text: str
    target_id: str = ""
    matched_prefix: str = ""
    remainder: str = ""
    confidence: float = 1.0
    program_id: str = ""
    function_id: str = ""
    params: dict[str, str] = field(default_factory=dict)


class CommandRouter:
    """Routes normalized voice utterances using dynamic user-configured prefixes."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    def update_config(self, config: AppConfig) -> None:
        self._config = config

    def route(self, raw_text: str, is_sleeping: bool = False) -> RouteMatch:
        norm = normalize_text(raw_text)
        if not norm:
            return RouteMatch(kind="unmatched", raw_text=raw_text, normalized_text="")

        # 1. Panic keywords (highest priority, works even in sleep mode if unprefixed allowed)
        if self._config.panic.allow_without_prefix and self._matches_any_phrase(
            norm, self._config.panic.voice_keywords
        ):
            return RouteMatch(
                kind="panic",
                raw_text=raw_text,
                normalized_text=norm,
                target_id="system",
                matched_prefix="",
                remainder=norm,
            )

        # 2. Wake / Sleep mode keywords
        if self._matches_any_phrase(norm, self._config.sleep_wake.wake_keywords):
            return RouteMatch(
                kind="wake",
                raw_text=raw_text,
                normalized_text=norm,
                target_id="system",
                remainder=norm,
            )

        if self._matches_any_phrase(norm, self._config.sleep_wake.sleep_keywords):
            return RouteMatch(
                kind="sleep",
                raw_text=raw_text,
                normalized_text=norm,
                target_id="system",
                remainder=norm,
            )

        # Ignore all target/system execution commands while sleeping
        if is_sleeping:
            return RouteMatch(kind="unmatched", raw_text=raw_text, normalized_text=norm)

        # 3. Dynamic User-Added Programs (Schema 1-2-3: opening prefix + picked/macro functions)
        prog_match = self._match_dynamic_programs(norm, raw_text)
        if prog_match is not None:
            return prog_match

        # 4. Legacy / protocol prefix routing (longest prefix candidates checked first)
        prefix_match = self._match_prefix_routes(norm, raw_text)
        if prefix_match is not None:
            # Check if user spoke a system-prefixed panic keyword
            if (
                prefix_match.target_id == "system"
                and self._matches_any_phrase(
                    prefix_match.remainder, self._config.panic.voice_keywords
                )
            ):
                return RouteMatch(
                    kind="panic",
                    raw_text=raw_text,
                    normalized_text=norm,
                    target_id="system",
                    matched_prefix=prefix_match.matched_prefix,
                    remainder=prefix_match.remainder,
                )
            return prefix_match

        # 4. Optional prefixless popup dismissal & stage app launcher
        if (
            self._config.popup_handler.enabled
            and self._config.popup_handler.allow_without_prefix
            and self._matches_any_phrase(norm, self._config.popup_handler.voice_triggers)
        ):
            return RouteMatch(
                kind="popup",
                raw_text=raw_text,
                normalized_text=norm,
                target_id="system",
                remainder=norm,
            )

        if self._config.stage_launcher.allow_without_prefix:
            if self._matches_any_phrase(
                norm, self._config.stage_launcher.voice_launch_all_triggers
            ) or self._looks_like_app_launch(norm):
                return RouteMatch(
                    kind="launch_apps",
                    raw_text=raw_text,
                    normalized_text=norm,
                    target_id="system",
                    remainder=norm,
                )

        return RouteMatch(kind="unmatched", raw_text=raw_text, normalized_text=norm)

    def _matches_any_phrase(self, norm_text: str, phrases: list[str]) -> bool:
        compact_text = normalize_compact(norm_text)
        for raw_phrase in phrases:
            p = normalize_text(raw_phrase)
            if not p:
                continue
            if norm_text == p or norm_text.startswith(p + " ") or norm_text.endswith(" " + p):
                return True
            if f" {p} " in f" {norm_text} ":
                return True
            p_compact = normalize_compact(p)
            if p_compact and compact_text == p_compact:
                return True
        return False

    def _looks_like_app_launch(self, norm_text: str) -> bool:
        tokens = norm_text.split()
        if len(tokens) < 2:
            return False
        verbs = {normalize_text(v) for v in self._config.stage_launcher.voice_launch_one_verbs if v.strip()}
        if tokens[0] not in verbs:
            return False
        rest = " ".join(tokens[1:])
        for app in self._config.stage_launcher.apps:
            names = [app.name, *app.aliases]
            for name in names:
                n = normalize_text(name)
                if n and (rest == n or n in rest):
                    return True
        for tid, route in self._config.prefix_routes.items():
            if tid == "system" or not route.enabled:
                continue
            for prefix in route.prefixes:
                p = normalize_text(prefix)
                if p and (rest == p or p in rest or normalize_compact(rest) == normalize_compact(p)):
                    return True
        return False

    def _match_leading_phrase_list(
        self,
        norm: str,
        items: list[tuple[str, object]],
        allow_fuzzy: bool = True,
        fuzzy_threshold: float = 0.80,
    ) -> tuple[object, str, str, float] | None:
        """Match longest leading phrase against items=[(phrase, owner), ...]."""
        candidates: list[tuple[int, str, object]] = []
        for phrase, owner in items:
            p_norm = normalize_text(phrase)
            if p_norm:
                candidates.append((len(p_norm), p_norm, owner))
        candidates.sort(key=lambda it: it[0], reverse=True)
        tokens = norm.split()

        for _, p_norm, owner in candidates:
            if norm == p_norm:
                return owner, p_norm, "", 1.0
            if norm.startswith(p_norm + " "):
                return owner, p_norm, norm[len(p_norm) :].strip(), 1.0
            p_compact = normalize_compact(p_norm)
            max_span = min(len(tokens), len(p_norm.split()) + 2, 5)
            for span in range(1, max_span + 1):
                if normalize_compact(" ".join(tokens[:span])) == p_compact:
                    return owner, p_norm, " ".join(tokens[span:]).strip(), 0.98

        if not allow_fuzzy:
            return None
        best = None
        best_score = 0.0
        for _, p_norm, owner in candidates:
            p_compact = normalize_compact(p_norm)
            if len(p_compact) < 3:
                continue
            p_words = len(p_norm.split())
            for span in range(max(1, p_words - 1), min(len(tokens), p_words + 1) + 1):
                head_compact = normalize_compact(" ".join(tokens[:span]))
                score = fuzzy_similarity(head_compact, p_compact)
                if score >= fuzzy_threshold and score > best_score:
                    best_score = score
                    best = (owner, p_norm, " ".join(tokens[span:]).strip(), score)
        return best

    @staticmethod
    def _match_function_template(
        template_raw: str, remainder: str, fuzzy_threshold: float
    ) -> tuple[dict[str, str], float] | None:
        """Match literal phrase or parameterized template like 'chiudi e apri {nome}'."""
        m_param = re.search(r"\{([a-zA-Z0-9_]+)\}", template_raw)
        if not m_param:
            t_norm = normalize_text(template_raw)
            if not t_norm:
                return None
            if remainder == t_norm or normalize_compact(remainder) == normalize_compact(t_norm):
                return {}, 1.0
            score = fuzzy_similarity(normalize_compact(remainder), normalize_compact(t_norm))
            if score >= fuzzy_threshold:
                return {}, score
            return None

        param_name = m_param.group(1)
        before_raw = template_raw[: m_param.start()]
        after_raw = template_raw[m_param.end() :]
        before_norm = normalize_text(before_raw)
        after_norm = normalize_text(after_raw)

        rem_tokens = remainder.split()
        if not rem_tokens:
            return None

        work = remainder
        if after_norm:
            idx = work.rfind(" " + after_norm)
            if idx == -1:
                return None
            work = work[:idx].strip()

        if not before_norm:
            return {param_name: work.strip()}, 0.95

        if work.startswith(before_norm + " "):
            val = work[len(before_norm) :].strip()
            return ({param_name: val}, 1.0) if val else None

        # Token-level fuzzy alignment for minor article drops ("i progetto" vs "il progetto")
        b_tokens = before_norm.split()
        w_tokens = work.split()
        if len(w_tokens) <= max(1, len(b_tokens) - 1):
            return None
        best_split = None
        best_ratio = 0.0
        b_compact = normalize_compact(before_norm)
        for split_idx in range(max(1, len(b_tokens) - 1), min(len(w_tokens), len(b_tokens) + 2)):
            head_compact = normalize_compact(" ".join(w_tokens[:split_idx]))
            ratio = fuzzy_similarity(head_compact, b_compact)
            if ratio >= min(fuzzy_threshold, 0.76) and ratio > best_ratio:
                best_ratio = ratio
                best_split = split_idx
        if best_split is not None:
            val = " ".join(w_tokens[best_split:]).strip()
            if val:
                return {param_name: val}, best_ratio
        return None

    def _match_dynamic_programs(self, norm: str, raw_text: str) -> RouteMatch | None:
        if not self._config.programs:
            return None

        open_items: list[tuple[str, object]] = []
        for prog in self._config.programs:
            if not prog.enabled:
                continue
            for cmd in prog.open_commands:
                for part in cmd.split(","):
                    part_clean = part.strip()
                    if part_clean:
                        open_items.append((part_clean, prog))

        matched = self._match_leading_phrase_list(norm, open_items, allow_fuzzy=True, fuzzy_threshold=0.80)
        if matched is not None:
            prog: ProgramProfile = matched[0]  # type: ignore[assignment]
            matched_prefix = matched[1]
            remainder = matched[2]
            prefix_score = matched[3]
            if prefix_score < prog.fuzzy_threshold and prefix_score < 0.95:
                matched = None

        if matched is not None:
            prog = matched[0]  # type: ignore[assignment]
            matched_prefix = matched[1]
            remainder = matched[2]
            launch_verbs = {"", "apri", "avvia", "lancia", "mostra", "focus", "open", "start"}
            if remainder in launch_verbs:
                return RouteMatch(
                    kind="program_open",
                    raw_text=raw_text,
                    normalized_text=norm,
                    target_id=prog.id,
                    matched_prefix=matched_prefix,
                    remainder=remainder,
                    confidence=matched[3],
                    program_id=prog.id,
                )

            best_fn: ProgramFunction | None = None
            best_params: dict[str, str] = {}
            best_score = 0.0
            for fn in prog.functions:
                for tmpl in fn.commands:
                    res = self._match_function_template(
                        tmpl, remainder, prog.fuzzy_threshold
                    )
                    if res is not None and res[1] > best_score:
                        best_score = res[1]
                        best_fn = fn
                        best_params = res[0]
            if best_fn is not None:
                return RouteMatch(
                    kind="program_func",
                    raw_text=raw_text,
                    normalized_text=norm,
                    target_id=prog.id,
                    matched_prefix=matched_prefix,
                    remainder=remainder,
                    confidence=best_score,
                    program_id=prog.id,
                    function_id=best_fn.id,
                    params=best_params,
                )

        # Also allow "apri <open_command>" without prefix if stage_launcher.allow_without_prefix
        tokens = norm.split()
        if len(tokens) >= 2 and tokens[0] in {"apri", "avvia", "lancia"}:
            rest = " ".join(tokens[1:])
            hit = self._match_leading_phrase_list(rest, open_items, allow_fuzzy=True, fuzzy_threshold=0.82)
            if hit is not None and hit[2] == "":
                prog = hit[0]  # type: ignore[assignment]
                return RouteMatch(
                    kind="program_open",
                    raw_text=raw_text,
                    normalized_text=norm,
                    target_id=prog.id,
                    matched_prefix=hit[1],
                    remainder=tokens[0],
                    confidence=hit[3],
                    program_id=prog.id,
                )

        # Allow unprefixed functions explicitly flagged allow_without_prefix
        for prog in self._config.programs:
            if not prog.enabled:
                continue
            for fn in prog.functions:
                if not fn.allow_without_prefix:
                    continue
                for tmpl in fn.commands:
                    res = self._match_function_template(tmpl, norm, prog.fuzzy_threshold)
                    if res is not None:
                        return RouteMatch(
                            kind="program_func",
                            raw_text=raw_text,
                            normalized_text=norm,
                            target_id=prog.id,
                            matched_prefix="",
                            remainder=norm,
                            confidence=res[1],
                            program_id=prog.id,
                            function_id=fn.id,
                            params=res[0],
                        )
        return None

    def _match_prefix_routes(self, norm: str, raw_text: str) -> RouteMatch | None:
        candidates: list[tuple[int, str, PrefixRouteConfig]] = []
        for route in self._config.prefix_routes.values():
            if not route.enabled:
                continue
            for prefix in route.prefixes:
                p_norm = normalize_text(prefix)
                if p_norm:
                    candidates.append((len(p_norm), p_norm, route))

        # Sort longest first so multi-word prefixes beat shorter overlapping prefixes
        candidates.sort(key=lambda item: item[0], reverse=True)
        tokens = norm.split()

        # Pass 1: exact / compact prefix match at start of utterance
        for _, p_norm, route in candidates:
            if norm == p_norm:
                return RouteMatch(
                    kind="target",
                    raw_text=raw_text,
                    normalized_text=norm,
                    target_id=route.target_id,
                    matched_prefix=p_norm,
                    remainder="",
                    confidence=1.0,
                )
            if norm.startswith(p_norm + " "):
                remainder = norm[len(p_norm) :].strip()
                return RouteMatch(
                    kind="target",
                    raw_text=raw_text,
                    normalized_text=norm,
                    target_id=route.target_id,
                    matched_prefix=p_norm,
                    remainder=remainder,
                    confidence=1.0,
                )

            # Check compact match across 1..3 leading tokens (handles "ueh beri" vs "uehberi")
            p_compact = normalize_compact(p_norm)
            max_span = min(len(tokens), len(p_norm.split()) + 2, 4)
            for span in range(1, max_span + 1):
                head_compact = normalize_compact(" ".join(tokens[:span]))
                if head_compact == p_compact:
                    remainder = " ".join(tokens[span:]).strip()
                    return RouteMatch(
                        kind="target",
                        raw_text=raw_text,
                        normalized_text=norm,
                        target_id=route.target_id,
                        matched_prefix=p_norm,
                        remainder=remainder,
                        confidence=0.98,
                    )

        # Pass 2: fuzzy prefix match at start of utterance
        best_match: RouteMatch | None = None
        best_score = 0.0
        for _, p_norm, route in candidates:
            if not route.fuzzy_matching:
                continue
            p_compact = normalize_compact(p_norm)
            if len(p_compact) < 3:
                continue
            p_words = len(p_norm.split())
            for span in range(max(1, p_words - 1), min(len(tokens), p_words + 1) + 1):
                head_compact = normalize_compact(" ".join(tokens[:span]))
                score = fuzzy_similarity(head_compact, p_compact)
                if score >= route.fuzzy_threshold and score > best_score:
                    best_score = score
                    best_match = RouteMatch(
                        kind="target",
                        raw_text=raw_text,
                        normalized_text=norm,
                        target_id=route.target_id,
                        matched_prefix=p_norm,
                        remainder=" ".join(tokens[span:]).strip(),
                        confidence=score,
                    )
        return best_match
