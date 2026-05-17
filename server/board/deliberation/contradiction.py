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

import asyncio
import logging
import re
from dataclasses import dataclass
from itertools import combinations as _combinations
from typing import Any

from server.board.llm import query_llm

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


# ─── LLM judge (per candidate pair) ─────────────────────────────────────────


CONTRADICTION_JUDGE_PROMPT = """Two board members made claims about the same topic. Are they contradictory?

MEMBER A's claim:
{claim_a_text}
Evidence cited: {claim_a_refs}

MEMBER B's claim:
{claim_b_text}
Evidence cited: {claim_b_refs}

Verdict rules:
  CONTRADICTORY  - A and B cannot both be true
  CONSISTENT     - A and B can both be true (different aspects, compatible numbers)
  UNRELATED      - A and B are about different things; no contradiction

If CONTRADICTORY, also rate severity:
  load_bearing - if either claim is central to a recommendation
  material     - meaningful disagreement
  minor        - phrasing difference, not substantive

Respond exactly:
VERDICT: <CONTRADICTORY|CONSISTENT|UNRELATED>
SEVERITY: <load_bearing|material|minor|none>
TOPIC: <short topic phrase>"""


_VERDICT_RE = re.compile(r"VERDICT:\s*(CONTRADICTORY|CONSISTENT|UNRELATED)", re.IGNORECASE)
_SEVERITY_RE = re.compile(r"SEVERITY:\s*(load_bearing|material|minor|none)", re.IGNORECASE)
_TOPIC_RE = re.compile(r"TOPIC:\s*(.+)", re.IGNORECASE)


def _parse_judge_response(raw: str) -> tuple[str, str, str]:
    """Return (verdict, severity, topic). Defaults to CONSISTENT/none/'' when
    the model didn't follow the format — never raises."""
    if not raw:
        return ("CONSISTENT", "none", "")
    m_v = _VERDICT_RE.search(raw)
    verdict = m_v.group(1).upper() if m_v else "CONSISTENT"
    m_s = _SEVERITY_RE.search(raw)
    severity = m_s.group(1).lower() if m_s else "none"
    m_t = _TOPIC_RE.search(raw)
    topic = m_t.group(1).strip() if m_t else ""
    return (verdict, severity, topic)


async def _judge_pair(claim_a: dict, claim_b: dict, *, model: str) -> dict[str, str]:
    """Run the blinded judge LLM on one candidate pair. Returns
    {verdict, severity, topic}. Errors are downgraded to CONSISTENT so a
    flaky judge can't manufacture noise."""
    def _join_refs(refs: Any) -> str:
        return ", ".join(str(r) for r in (refs or ["[UNVERIFIED]"]))

    prompt = CONTRADICTION_JUDGE_PROMPT.format(
        claim_a_text=str(claim_a.get("text", "")),
        claim_a_refs=_join_refs(claim_a.get("evidence_refs")),
        claim_b_text=str(claim_b.get("text", "")),
        claim_b_refs=_join_refs(claim_b.get("evidence_refs")),
    )
    try:
        resp = await query_llm(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=200,
            timeout=120.0,
            fallback=True,
        )
        verdict, severity, topic = _parse_judge_response(resp.content or "")
    except Exception as e:
        logger.warning("contradiction judge failed for one pair: %s", e)
        verdict, severity, topic = ("CONSISTENT", "none", "")
    return {"verdict": verdict, "severity": severity, "topic": topic}


# ─── Orchestrator ───────────────────────────────────────────────────────────


async def detect_contradictions(
    atomized_claims: dict[str, list[dict]],
    *,
    judge_model: str,
    max_pairs: int = 12,
) -> list[ContradictionFinding]:
    """Find cross-member contradictions per spec §6.2.

    Two-step:
      1. Cluster all cross-member load-bearing claim pairs by topic overlap
         (entity match or numeric ±20%). Same-member pairs and qualitative
         claims are excluded. Pairs are deterministically ordered.
      2. If clustering yields more than `max_pairs` candidates, keep the
         top-N by `_score_pair_overlap` (more shared signal wins).
      3. Run the LLM judge on each candidate in parallel. Only
         `CONTRADICTORY` verdicts become ContradictionFindings.

    Returns the findings in input order. Never raises on judge failure — a
    flaky pair is dropped silently (logged at WARNING by `_judge_pair`).
    """
    # Flatten (member_id, claim) so we can iterate combinations cleanly.
    flat: list[tuple[str, dict]] = []
    for member_id, claims in (atomized_claims or {}).items():
        for c in claims or []:
            flat.append((str(member_id), c))

    candidates: list[tuple[dict, dict]] = []
    for (m_a, c_a), (m_b, c_b) in _combinations(flat, 2):
        if m_a == m_b:
            continue
        if not _topics_overlap(c_a, c_b):
            continue
        candidates.append((c_a, c_b))

    if len(candidates) > max_pairs:
        candidates.sort(key=lambda pair: _score_pair_overlap(*pair), reverse=True)
        candidates = candidates[:max_pairs]

    if not candidates:
        return []

    async def _judge(pair: tuple[dict, dict]) -> tuple[tuple[dict, dict], dict[str, str]]:
        verdict = await _judge_pair(pair[0], pair[1], model=judge_model)
        return pair, verdict

    results = await asyncio.gather(
        *[_judge(pair) for pair in candidates],
        return_exceptions=True,
    )

    findings: list[ContradictionFinding] = []
    for item in results:
        if isinstance(item, Exception):
            logger.warning("contradiction judge raised: %s", item)
            continue
        (claim_a, claim_b), verdict = item
        if verdict["verdict"] != "CONTRADICTORY":
            continue
        findings.append(ContradictionFinding(
            topic=verdict["topic"] or "(no topic)",
            claim_a=claim_a,
            claim_b=claim_b,
            severity=verdict["severity"] or "minor",
        ))
    return findings
