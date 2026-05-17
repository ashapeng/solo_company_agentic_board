"""Cross-member contradiction detector tests (spec §6)."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from server.board.deliberation.contradiction import (
    CONTRADICTION_JUDGE_PROMPT,
    ContradictionFinding,
    _extract_entities,
    _extract_numbers,
    _judge_pair,
    _parse_judge_response,
    _score_pair_overlap,
    _topics_overlap,
    detect_contradictions,
)
from server.board.llm import LLMResponse


def _llm(text: str) -> LLMResponse:
    return LLMResponse(
        content=text, model="qwen/qwen3.6-max-preview",
        input_tokens=10, output_tokens=20, latency_seconds=0.1,
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


def test_judge_prompt_includes_required_substrings():
    """The verbatim prompt from spec §6.3 must include all rule keywords so
    downstream models behave consistently."""
    assert "CONTRADICTORY" in CONTRADICTION_JUDGE_PROMPT
    assert "CONSISTENT" in CONTRADICTION_JUDGE_PROMPT
    assert "UNRELATED" in CONTRADICTION_JUDGE_PROMPT
    assert "load_bearing" in CONTRADICTION_JUDGE_PROMPT
    assert "VERDICT:" in CONTRADICTION_JUDGE_PROMPT
    assert "TOPIC:" in CONTRADICTION_JUDGE_PROMPT


def test_parse_judge_response_extracts_three_fields():
    raw = "VERDICT: CONTRADICTORY\nSEVERITY: material\nTOPIC: EV battery growth"
    verdict, severity, topic = _parse_judge_response(raw)
    assert verdict == "CONTRADICTORY"
    assert severity == "material"
    assert topic == "EV battery growth"


def test_parse_judge_response_defaults_to_consistent_on_unparseable():
    """Safe default — unparseable output is treated as not-a-contradiction,
    so the finding list never contains noise."""
    verdict, severity, topic = _parse_judge_response("garbage with no verdict line")
    assert verdict == "CONSISTENT"
    assert severity == "none"
    assert topic == ""


def test_parse_judge_response_lowercases_severity_and_uppercases_verdict():
    """Tolerate model case variation."""
    raw = "verdict: contradictory\nseverity: LOAD_BEARING\ntopic: x"
    verdict, severity, topic = _parse_judge_response(raw)
    assert verdict == "CONTRADICTORY"
    assert severity == "load_bearing"


@pytest.mark.asyncio
async def test_judge_pair_returns_verdict_dict():
    a = _claim("strategist", "EV growth was 19%")
    b = _claim("critic", "EV growth was 10%")
    response = "VERDICT: CONTRADICTORY\nSEVERITY: material\nTOPIC: EV growth"
    with patch(
        "server.board.deliberation.contradiction.query_llm",
        new=AsyncMock(return_value=_llm(response)),
    ):
        result = await _judge_pair(a, b, model="qwen/qwen3.6-max-preview")
    assert result["verdict"] == "CONTRADICTORY"
    assert result["severity"] == "material"
    assert result["topic"] == "EV growth"


@pytest.mark.asyncio
async def test_judge_pair_falls_back_to_consistent_on_llm_failure():
    """A flaky judge call must not block detection — treat as not-contradicted."""
    a = _claim("a", "X")
    b = _claim("b", "Y")
    with patch(
        "server.board.deliberation.contradiction.query_llm",
        new=AsyncMock(side_effect=RuntimeError("provider down")),
    ):
        result = await _judge_pair(a, b, model="qwen/qwen3.6-max-preview")
    assert result["verdict"] == "CONSISTENT"
    assert result["severity"] == "none"
    assert result["topic"] == ""


@pytest.mark.asyncio
async def test_detect_contradictions_returns_only_contradictory_verdicts():
    # Numbers within ±20% so topic-overlap fires (the heuristic from Task 2);
    # judge mock then returns CONTRADICTORY to exercise the finding-emit path.
    atomized = {
        "strategist": [_claim("strategist", "EV growth was 19%")],
        "critic":     [_claim("critic",     "EV growth was 16%")],
    }
    judge_response = "VERDICT: CONTRADICTORY\nSEVERITY: material\nTOPIC: EV growth"
    with patch(
        "server.board.deliberation.contradiction.query_llm",
        new=AsyncMock(return_value=_llm(judge_response)),
    ):
        findings = await detect_contradictions(
            atomized, judge_model="qwen/qwen3.6-max-preview", max_pairs=12,
        )
    assert len(findings) == 1
    assert findings[0].severity == "material"
    assert findings[0].topic == "EV growth"


@pytest.mark.asyncio
async def test_detect_contradictions_drops_consistent_verdicts():
    """Judge says CONSISTENT → no finding emitted."""
    atomized = {
        "a": [_claim("a", "CATL has 30% share")],
        "b": [_claim("b", "CATL has 32% share")],
    }
    with patch(
        "server.board.deliberation.contradiction.query_llm",
        new=AsyncMock(return_value=_llm("VERDICT: CONSISTENT\nSEVERITY: none\nTOPIC: CATL")),
    ):
        findings = await detect_contradictions(
            atomized, judge_model="qwen/qwen3.6-max-preview", max_pairs=12,
        )
    assert findings == []


@pytest.mark.asyncio
async def test_detect_contradictions_skips_same_member_pairs():
    """Two claims from the SAME member cannot contradict each other in this
    context — judge should not be called."""
    atomized = {
        "strategist": [
            _claim("strategist", "CATL grew 12%"),
            _claim("strategist", "CATL grew 24%"),  # internally inconsistent — ignored
        ],
    }
    judge_mock = AsyncMock()
    with patch(
        "server.board.deliberation.contradiction.query_llm", new=judge_mock,
    ):
        findings = await detect_contradictions(atomized, judge_model="m", max_pairs=12)
    assert findings == []
    judge_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_detect_contradictions_skips_non_overlapping_pairs():
    """Topic-clustering rules out unrelated claims — judge not called."""
    atomized = {
        "a": [_claim("a", "Mistral is in Paris", kind="named_entity")],
        "b": [_claim("b", "Tesla shipped 1.8M units", kind="numeric")],
    }
    judge_mock = AsyncMock()
    with patch(
        "server.board.deliberation.contradiction.query_llm", new=judge_mock,
    ):
        findings = await detect_contradictions(atomized, judge_model="m", max_pairs=12)
    assert findings == []
    judge_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_detect_contradictions_caps_at_max_pairs():
    """When candidate pairs exceed max_pairs, only top-N by overlap score
    get judged. Confirm the judge was called exactly max_pairs times."""
    # Build 5 members × 1 claim each, all overlapping on the same entity.
    # That yields C(5,2) = 10 candidate pairs. Cap at 3.
    atomized = {
        f"m{i}": [_claim(f"m{i}", f"CATL has {10 + i}% share")]
        for i in range(5)
    }
    judge_mock = AsyncMock(return_value=_llm("VERDICT: CONSISTENT\nSEVERITY: none\nTOPIC: CATL"))
    with patch(
        "server.board.deliberation.contradiction.query_llm", new=judge_mock,
    ):
        findings = await detect_contradictions(atomized, judge_model="m", max_pairs=3)
    assert judge_mock.await_count == 3
    assert findings == []  # all said CONSISTENT
