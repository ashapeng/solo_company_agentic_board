"""Cross-member contradiction detector tests (spec §6)."""
from __future__ import annotations

import pytest

from server.board.deliberation.contradiction import (
    ContradictionFinding,
    _extract_entities,
    _extract_numbers,
    _score_pair_overlap,
    _topics_overlap,
)


def _claim(member_id: str, text: str, kind: str = "numeric",
           refs: list[str] | None = None) -> dict:
    return {
        "id": f"id-{member_id}-{text[:6]}",
        "kind": kind,
        "text": text,
        "evidence_refs": refs or ["[UNVERIFIED]"],
        "member_id": member_id,
        "confidence": 0.8,
    }


def test_contradiction_finding_to_dict_roundtrip():
    a = _claim("strategist", "EV growth was 19%")
    b = _claim("critic", "EV growth was 10%")
    finding = ContradictionFinding(
        topic="EV growth", claim_a=a, claim_b=b, severity="material",
    )
    d = finding.to_dict()
    assert d["topic"] == "EV growth"
    assert d["severity"] == "material"
    assert d["claim_a"]["member_id"] == "strategist"
    assert d["claim_b"]["text"] == "EV growth was 10%"


def test_extract_numbers_pulls_percentages_dollars_and_plain_counts():
    assert 19.0 in _extract_numbers("EV growth was 19% in Q4")
    assert 5_000_000.0 in _extract_numbers("Mistral MAU is 5M")
    assert 50_000.0 in _extract_numbers("revenue was $50K")
    # Years and dates should NOT count as quantities — too noisy
    nums = _extract_numbers("2026 forecast")
    assert 2026.0 not in nums


def test_extract_entities_normalizes_case_and_filters_stopwords():
    entities = _extract_entities("CATL gained share over BYD in 2026")
    assert "catl" in entities
    assert "byd" in entities
    # Stopwords / verbs / common nouns aren't entities
    assert "gained" not in entities
    assert "share" not in entities
    assert "the" not in entities


def test_topics_overlap_same_named_entity():
    a = _claim("strategist", "CATL gained 12% share", kind="named_entity")
    b = _claim("critic", "CATL led the market", kind="named_entity")
    assert _topics_overlap(a, b) is True


def test_topics_overlap_numeric_within_20_pct():
    a = _claim("strategist", "EV growth was 19% YoY", kind="numeric")
    b = _claim("critic", "EV growth was 22% YoY", kind="numeric")  # within ±20%
    assert _topics_overlap(a, b) is True


def test_topics_overlap_numeric_too_far_apart():
    a = _claim("strategist", "growth was 5%", kind="numeric")
    b = _claim("critic", "growth was 35%", kind="numeric")
    # 35 vs 5 is way outside ±20%
    assert _topics_overlap(a, b) is False


def test_topics_overlap_excludes_qualitative_kinds():
    """Qualitative claims are NEVER candidates (spec §6.2 — too noisy)."""
    a = _claim("strategist", "the market is risky", kind="qualitative")
    b = _claim("critic", "the market is safe", kind="qualitative")
    assert _topics_overlap(a, b) is False


def test_topics_overlap_excludes_unrelated_named_entities():
    a = _claim("strategist", "OpenAI raised funding", kind="named_entity")
    b = _claim("critic", "Anthropic hired engineers", kind="named_entity")
    assert _topics_overlap(a, b) is False


def test_score_pair_overlap_orders_pairs_by_evidence_density():
    """Pairs sharing more entities/numbers score higher — used to pick top-N."""
    weak = (
        _claim("a", "CATL gained share"),
        _claim("b", "CATL did well"),
    )
    strong = (
        _claim("a", "CATL grew 19% in Q4 2025"),
        _claim("b", "CATL grew 22% in Q4 2025"),
    )
    assert _score_pair_overlap(*strong) > _score_pair_overlap(*weak)
