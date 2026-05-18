"""Auto-Promote-to-Live tests (spec §9.2 + design-choices supplement)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from server.board.deliberation.orchestrator import MemberResponse


def _resp(member_id: str, text: str, stage: int = 2) -> MemberResponse:
    return MemberResponse(
        member_id=member_id, stage=stage, content=text,
        model="m", elapsed_seconds=0.1,
    )


# ─── T2: compute_disagreement (spec §9.2.2) ─────────────────────────────────


def test_compute_disagreement_zero_when_no_responses():
    from server.board.deliberation.auto_promote import compute_disagreement
    assert compute_disagreement([]) == 0


def test_compute_disagreement_counts_challenge_markers():
    from server.board.deliberation.auto_promote import compute_disagreement
    responses = [
        _resp("strategist", "Some text. [Challenge] Foo. [Challenge] Bar."),
        _resp("product", "Plain text without challenges."),
    ]
    assert compute_disagreement(responses) == 2


def test_compute_disagreement_adds_one_per_response_with_changed_because():
    """Spec §9.2.2 literal: presence check, not count."""
    from server.board.deliberation.auto_promote import compute_disagreement
    responses = [
        _resp("strategist", "Changed because of new evidence. Changed because of X."),
        _resp("product", "Plain."),
    ]
    # First response: 0 [Challenge] + 1 "Changed because" presence = 1
    # Second response: 0 + 0 = 0
    assert compute_disagreement(responses) == 1


def test_compute_disagreement_combines_both_signals():
    from server.board.deliberation.auto_promote import compute_disagreement
    responses = [
        _resp("strategist", "[Challenge] Foo. [Challenge] Bar. Changed because new data."),
        _resp("product", "[Challenge] Baz."),
        _resp("critic", "Plain."),
    ]
    # strategist: 2 + 1 = 3
    # product:    1 + 0 = 1
    # critic:     0 + 0 = 0
    assert compute_disagreement(responses) == 4


def test_compute_disagreement_handles_none_content():
    """Defensive: a member response with content=None should not crash."""
    from server.board.deliberation.auto_promote import compute_disagreement
    r = _resp("strategist", "")  # the dataclass requires str; use empty
    r.content = None  # simulate post-load corruption
    assert compute_disagreement([r]) == 0


# ─── T3: pick_top_pairs ──────────────────────────────────────────────────────


def _claim(member_id: str, text: str) -> dict:
    """Minimal claim dict shape (matches AtomizedClaim.to_dict() subset
    actually used by pick_top_pairs)."""
    return {"member_id": member_id, "text": text, "evidence_refs": []}


def test_pick_top_pairs_returns_empty_when_no_signal():
    """No contradictions and no [Challenge] markers → no pairs to fire."""
    from server.board.deliberation.auto_promote import pick_top_pairs
    responses = [_resp("strategist", "plain"), _resp("product", "plain")]
    assert pick_top_pairs(responses, contradictions=[], max_pairs=2) == []


def test_pick_top_pairs_primary_path_uses_contradictions_severity():
    """When contradictions present, rank by severity (load_bearing > material)."""
    from server.board.deliberation.auto_promote import pick_top_pairs
    responses = [
        _resp("strategist", "[Challenge] product is wrong"),
        _resp("product", "no concession"),
        _resp("critic", "[Challenge] minor stuff"),
    ]
    contradictions = [
        {"topic": "topic-minor",
         "claim_a": _claim("strategist", "ttm rev = $50M"),
         "claim_b": _claim("critic",     "ttm rev = $80M"),
         "severity": "minor"},
        {"topic": "topic-load-bearing",
         "claim_a": _claim("strategist", "market growth 20% YoY"),
         "claim_b": _claim("product",    "market growth 10% YoY"),
         "severity": "load_bearing"},
    ]
    pairs = pick_top_pairs(responses, contradictions=contradictions, max_pairs=2)
    # load_bearing ranks first
    assert pairs[0]["severity"] == "load_bearing"
    assert set(pairs[0]["pair_member_ids"]) == {"strategist", "product"}
    assert pairs[0]["topic"] == "topic-load-bearing"
    # minor second
    assert pairs[1]["severity"] == "minor"
    assert set(pairs[1]["pair_member_ids"]) == {"strategist", "critic"}


def test_pick_top_pairs_dedupes_same_pair_across_contradictions():
    """Two contradictions on the same member pair → one slot, highest severity."""
    from server.board.deliberation.auto_promote import pick_top_pairs
    responses = [_resp("strategist", ""), _resp("product", "")]
    contradictions = [
        {"topic": "t1",
         "claim_a": _claim("strategist", "a1"), "claim_b": _claim("product", "b1"),
         "severity": "minor"},
        {"topic": "t2",
         "claim_a": _claim("strategist", "a2"), "claim_b": _claim("product", "b2"),
         "severity": "load_bearing"},  # same pair, higher severity
    ]
    pairs = pick_top_pairs(responses, contradictions=contradictions, max_pairs=2)
    assert len(pairs) == 1
    assert pairs[0]["severity"] == "load_bearing"
    assert pairs[0]["topic"] == "t2"


def test_pick_top_pairs_caps_at_max_pairs():
    """More candidate pairs than max_pairs → slice to max_pairs after rank."""
    from server.board.deliberation.auto_promote import pick_top_pairs
    responses = [
        _resp("strategist", ""), _resp("product", ""),
        _resp("critic", ""), _resp("architect", ""),
    ]
    contradictions = [
        {"topic": f"t{i}", "claim_a": _claim(a, "x"), "claim_b": _claim(b, "y"),
         "severity": "material"}
        for i, (a, b) in enumerate([
            ("strategist", "product"),
            ("strategist", "critic"),
            ("product", "architect"),
            ("critic", "architect"),
        ])
    ]
    pairs = pick_top_pairs(responses, contradictions=contradictions, max_pairs=2)
    assert len(pairs) == 2  # cap applied


def test_pick_top_pairs_fallback_when_no_contradictions():
    """Spec §9.2.7: contradictions empty, [Challenge] count > 0 → pick top-2
    most-challenged members; topic = first [Challenge] line."""
    from server.board.deliberation.auto_promote import pick_top_pairs
    responses = [
        _resp("strategist", "[Challenge] product is wrong\nmore\n[Challenge] product underweights X"),  # 2
        _resp("product", "[Challenge] strategist over-claims"),                # 1
        _resp("critic", "plain"),                                              # 0
    ]
    pairs = pick_top_pairs(responses, contradictions=[], max_pairs=2)
    assert len(pairs) == 1  # fallback returns at most one pair
    # strategist is most-challenged, product second
    assert set(pairs[0]["pair_member_ids"]) == {"strategist", "product"}
    assert pairs[0]["severity"] is None  # fallback has no severity
    # Topic = first [Challenge] line from the most-challenged member.
    assert "product is wrong" in pairs[0]["topic"]


def test_pick_top_pairs_fallback_returns_empty_when_no_challenge_signal():
    """If both lists are empty signal-wise, return empty (no fire)."""
    from server.board.deliberation.auto_promote import pick_top_pairs
    responses = [_resp("strategist", "plain"), _resp("product", "plain")]
    assert pick_top_pairs(responses, contradictions=[], max_pairs=2) == []


def test_pick_top_pairs_score_is_combined_challenge_count():
    """Pair score = sum of [Challenge] counts for both members across their
    Stage 2 responses. Used as a tiebreaker within a single severity tier."""
    from server.board.deliberation.auto_promote import pick_top_pairs
    responses = [
        _resp("strategist", "[Challenge] x [Challenge] y"),   # 2
        _resp("product", "[Challenge] z"),                    # 1
        _resp("critic", ""),                                  # 0
        _resp("architect", "[Challenge] a [Challenge] b [Challenge] c"),  # 3
    ]
    contradictions = [
        # both pairs are material — score breaks the tie. critic+architect (3)
        # should rank above strategist+product (3) by member_id alpha tiebreak
        # below; assert the higher-score pair wins.
        {"topic": "t-low",  "claim_a": _claim("strategist", "x"), "claim_b": _claim("critic", "y"),
         "severity": "material"},
        {"topic": "t-high", "claim_a": _claim("architect", "x"), "claim_b": _claim("product", "y"),
         "severity": "material"},
    ]
    pairs = pick_top_pairs(responses, contradictions=contradictions, max_pairs=2)
    # First entry should be the (architect, product) pair (combined score 3+1 = 4).
    assert pairs[0]["topic"] == "t-high"
    assert pairs[0]["score"] == 4
