"""Auto-Promote-to-Live (spec §9.2): rebuttal sub-pipeline.

When Stage 2 produces a high disagreement score and the HEAVY-tier gate is on,
this module orchestrates a chair-moderated live rebuttal between the most
contentious member pair(s), then summarizes each rebuttal into a REBUTTAL
OUTCOME block the chair reads during Stage 3 synthesis.

Public surface used by the orchestrator (`deliberate()`):
  - compute_disagreement(stage2_responses) -> int                              # implemented
  - pick_top_pairs(stage2_responses, *, contradictions, max_pairs) -> list     # planned (T3)
  - summarize_rebuttal(*, transcript, topic, ..., model) -> tuple              # planned (T4)
  - format_rebuttal_outcomes_block(rebuttals) -> str                            # planned (T4)
  - run_live_rebuttal(*, ...) -> dict                                          # planned (T5)

Behind a dark-launch flag (`hardening.auto_promote_enabled: False`) so the
cheap orchestration ships immediately and the expensive live-rebuttal loop
stays off until calibration data exists. The disagreement score is computed
and persisted on the session unconditionally — telemetry for tuning the
threshold later.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from server.board.deliberation.orchestrator import MemberResponse

logger = logging.getLogger(__name__)


# ─── §9.2.2 disagreement score ───────────────────────────────────────────────


def compute_disagreement(stage2_responses: "Sequence[MemberResponse]") -> int:
    """Spec §9.2.2 formula. Counts ``[Challenge]`` markers per response and
    adds 1 per response containing ``"Changed because"`` (presence, not count).

    Pure function — no LLM call. Safe to invoke regardless of the dark-launch
    flag; the orchestrator always persists the result on
    ``session.disagreement_score`` for tuning telemetry.
    """
    score = 0
    for r in stage2_responses or []:
        text = (getattr(r, "content", "") or "")
        score += text.count("[Challenge]")
        if "Changed because" in text:
            score += 1
    return score


# ─── §9.2 pair picker (primary + spec §9.2.7 fallback) ──────────────────────


_SEVERITY_RANK = {"load_bearing": 3, "material": 2, "minor": 1}


def _challenge_count(text: str) -> int:
    return (text or "").count("[Challenge]")


def _challenge_counts_by_member(
    stage2_responses: "Sequence[MemberResponse]",
) -> dict[str, int]:
    """Return {member_id: count} for every member with at least one response.
    Multiple responses from the same member sum together (defensive — Stage 2
    is typically one-per-member, but the function does not assume it)."""
    counts: dict[str, int] = {}
    for r in stage2_responses or []:
        mid = getattr(r, "member_id", None)
        if not mid:
            continue
        counts[mid] = counts.get(mid, 0) + _challenge_count(getattr(r, "content", ""))
    return counts


def _first_challenge_line(text: str) -> str:
    """Return the first ``[Challenge] ...`` line from a Stage 2 response,
    truncated to 300 chars. Empty string when no such line exists."""
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped.startswith("[Challenge]"):
            return stripped[:300]
    return ""


def pick_top_pairs(
    stage2_responses: "Sequence[MemberResponse]",
    *,
    contradictions: list[dict] | None = None,
    max_pairs: int = 2,
) -> list[dict]:
    """Return a ranked, deduped, capped list of (member_a, member_b) pairs
    to auto-promote into live rebuttals.

    Primary path (``contradictions`` non-empty): rank by severity, tiebreak by
    combined ``[Challenge]`` count for the two members, dedupe by unordered
    member-id pair, slice to ``max_pairs``.

    Fallback path (``contradictions`` empty AND some ``[Challenge]`` markers
    exist): pick the two most-challenged members; topic = first
    ``[Challenge] ...`` line from the most-challenged member. Returns at most
    1 pair (the spec describes a single fallback pair). Returns ``[]`` when
    both signals are absent.

    Pure function — no LLM call. Each returned dict has keys
    ``pair_member_ids``, ``topic``, ``severity`` (or ``None`` in fallback),
    ``score`` (combined ``[Challenge]`` count).
    """
    challenge_counts = _challenge_counts_by_member(stage2_responses)

    if contradictions:
        # ── Primary path
        seen: set[frozenset] = set()
        # Stable sort: severity desc, then combined score desc.
        candidates: list[tuple[int, int, dict]] = []
        for c in contradictions:
            a_id = (c.get("claim_a") or {}).get("member_id", "")
            b_id = (c.get("claim_b") or {}).get("member_id", "")
            if not a_id or not b_id or a_id == b_id:
                continue
            sev = c.get("severity", "minor")
            sev_rank = _SEVERITY_RANK.get(sev, 0)
            score = challenge_counts.get(a_id, 0) + challenge_counts.get(b_id, 0)
            candidates.append((sev_rank, score, c))
        # Sort: severity desc, score desc. Stable so the original order
        # breaks ties beyond that.
        candidates.sort(key=lambda t: (-t[0], -t[1]))
        out: list[dict] = []
        for _sev_rank, score, c in candidates:
            a_id = (c.get("claim_a") or {}).get("member_id", "")
            b_id = (c.get("claim_b") or {}).get("member_id", "")
            key = frozenset({a_id, b_id})
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "pair_member_ids": [a_id, b_id],
                "topic": str(c.get("topic", ""))[:300],
                "severity": c.get("severity"),
                "score": int(score),
            })
            if len(out) >= max_pairs:
                break
        return out

    # ── Fallback path (spec §9.2.7 dependency note)
    # Need at least 2 members and at least one [Challenge] marker total.
    if sum(challenge_counts.values()) == 0:
        return []
    if len(challenge_counts) < 2:
        return []
    # Top-2 by count; break ties alphabetically for determinism.
    by_count = sorted(
        challenge_counts.items(),
        key=lambda kv: (-kv[1], kv[0]),
    )
    a_id, a_count = by_count[0]
    b_id, b_count = by_count[1]
    # Topic = first [Challenge] line from the most-challenged member.
    topic_source = next(
        (getattr(r, "content", "") for r in stage2_responses
         if getattr(r, "member_id", None) == a_id),
        "",
    )
    topic = _first_challenge_line(topic_source)
    return [{
        "pair_member_ids": [a_id, b_id],
        "topic": topic or "(no specific topic — fallback path)",
        "severity": None,
        "score": int(a_count + b_count),
    }]
