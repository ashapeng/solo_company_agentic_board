"""Cross-member contradiction detector (spec §6).

After Stage 1 atomization, each cross-member pair of load-bearing claims is
first clustered by deterministic topic overlap (entity match or numeric
proximity), then verified by an LLM judge. Only CONTRADICTORY verdicts are
returned as ContradictionFinding entries.

The module has two halves:
- Pure functions (this file's first half): no LLM calls — entity/number
  extraction, topic overlap, pair scoring. Used by detect_contradictions to
  bound LLM cost.
- LLM-using code (Tasks 3+4 below): the judge prompt and the orchestrator.

Qualitative claims are excluded from contradiction detection entirely
(spec §6.2 — too noisy).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


_LOAD_BEARING_KINDS: set[str] = {"numeric", "named_entity", "comparative"}
_NUMERIC_PROXIMITY_PCT: float = 20.0   # ±20% counts as "same quantity" (spec §6.2)
_MIN_ENTITY_LEN: int = 3               # filter out 1-2 char tokens

# Stop-words to keep out of entity extraction. Lower-cased.
_ENTITY_STOPWORDS: set[str] = {
    "the", "and", "for", "with", "from", "into", "over", "under", "about",
    "this", "that", "these", "those", "share", "shares", "market", "growth",
    "year", "years", "rate", "rates", "data", "report", "reports",
    "company", "companies", "product", "products", "user", "users",
    "gained", "gains", "lost", "lose", "led", "lead", "rose", "rise",
    "fell", "fall", "had", "have", "will", "are", "was", "were", "been",
    "more", "most", "less", "least", "many", "much", "some", "all", "any",
    "their", "they", "them", "than", "then", "also", "between", "among",
    "did", "does", "doing", "done", "could", "should", "would", "may",
    "might", "must", "can",
}


@dataclass
class ContradictionFinding:
    """One verified cross-member contradiction (spec §3.5).

    Carries the two AtomizedClaim dicts directly so callers don't need to
    re-resolve member_id → claim. severity is the LLM judge's rating.
    """
    topic: str
    claim_a: dict
    claim_b: dict
    severity: str  # "minor" | "material" | "load_bearing"

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "claim_a": dict(self.claim_a),
            "claim_b": dict(self.claim_b),
            "severity": self.severity,
        }


# ─── Topic clustering (pure, deterministic) ─────────────────────────────────

_NUM_RE = re.compile(r"\$?(\d+(?:\.\d+)?)\s*([KMBTkmbt%]?)")
_UNIT_MULTIPLIERS = {"": 1, "k": 1_000, "m": 1_000_000, "b": 1_000_000_000, "t": 1_000_000_000_000}


def _extract_numbers(text: str) -> list[float]:
    """Pull quantities out of a claim. Year-like 4-digit standalone numbers
    are excluded (too noisy)."""
    out: list[float] = []
    for match in _NUM_RE.finditer(text or ""):
        raw, unit = match.group(1), (match.group(2) or "").lower()
        try:
            value = float(raw)
        except ValueError:
            continue
        if unit == "%":
            out.append(value)
            continue
        if unit == "" and 1900 <= value <= 2100 and "." not in raw:
            continue
        out.append(value * _UNIT_MULTIPLIERS.get(unit, 1))
    return out


_ENTITY_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]+")


def _extract_entities(text: str) -> set[str]:
    """Lowercased token set with stopwords + short tokens removed."""
    raw_tokens = _ENTITY_RE.findall(text or "")
    out: set[str] = set()
    for tok in raw_tokens:
        norm = tok.lower()
        if len(norm) < _MIN_ENTITY_LEN:
            continue
        if norm in _ENTITY_STOPWORDS:
            continue
        out.add(norm)
    return out


def _within_proximity(a: float, b: float, pct: float) -> bool:
    """True if a and b are within ±pct% of each other. Handles zeros safely."""
    if a == 0 and b == 0:
        return True
    larger = max(abs(a), abs(b))
    if larger == 0:
        return True
    return (abs(a - b) / larger) * 100.0 <= pct


def _topics_overlap(claim_a: dict, claim_b: dict) -> bool:
    """Spec §6.2 topic-overlap heuristic. Returns False for qualitative claims
    and for any pair without an entity/quantity bridge."""
    kind_a = claim_a.get("kind", "qualitative")
    kind_b = claim_b.get("kind", "qualitative")
    if kind_a not in _LOAD_BEARING_KINDS or kind_b not in _LOAD_BEARING_KINDS:
        return False

    text_a = str(claim_a.get("text", ""))
    text_b = str(claim_b.get("text", ""))

    entities_a = _extract_entities(text_a)
    entities_b = _extract_entities(text_b)
    if entities_a & entities_b:
        return True

    nums_a = _extract_numbers(text_a)
    nums_b = _extract_numbers(text_b)
    for na in nums_a:
        for nb in nums_b:
            if _within_proximity(na, nb, _NUMERIC_PROXIMITY_PCT):
                return True
    return False


def _score_pair_overlap(claim_a: dict, claim_b: dict) -> float:
    """Higher score → stronger candidate (more shared signal). Used to pick
    top-N when the candidate set exceeds max_pairs."""
    text_a = str(claim_a.get("text", ""))
    text_b = str(claim_b.get("text", ""))
    entities_shared = len(_extract_entities(text_a) & _extract_entities(text_b))
    numeric_hits = 0
    for na in _extract_numbers(text_a):
        for nb in _extract_numbers(text_b):
            if _within_proximity(na, nb, _NUMERIC_PROXIMITY_PCT):
                numeric_hits += 1
    # Weight: each shared entity = 2pts; each numeric overlap = 1pt.
    return float(entities_shared * 2 + numeric_hits)
