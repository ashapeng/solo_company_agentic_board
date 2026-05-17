"""Blinded verifier protocol tests."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from server.board.deliberation.atomizer import AtomizedClaim
from server.board.deliberation.verification import (
    BlindedVerificationResult,
    verify_synthesis,
)
from server.board.llm import LLMResponse


def _llm(text: str) -> LLMResponse:
    return LLMResponse(
        content=text, model="qwen/qwen3.6-max-preview",
        input_tokens=10, output_tokens=20, latency_seconds=0.1,
    )


class _FakeSession:
    def __init__(self):
        self.evidence_packets: dict[str, str] = {}


@pytest.mark.asyncio
async def test_blinded_verifier_passes_when_all_cited_claims_supported():
    synthesis = "EV growth was 19% in Q4 2025 per Reuters."
    cited_claim = AtomizedClaim(
        id="c1", kind="numeric", text="EV growth was 19% in Q4 2025",
        evidence_refs=["https://reuters.com/ev"],
        member_id="chairperson", confidence=0.9,
    )

    with patch(
        "server.board.deliberation.verification.atomize",
        new=AsyncMock(return_value=[cited_claim]),
    ), patch(
        "server.board.deliberation.verification.resolve_evidence",
        new=AsyncMock(return_value={"https://reuters.com/ev": "Q4 2025 EV growth was 19% YoY"}),
    ), patch(
        "server.board.deliberation.verification.query_llm",
        new=AsyncMock(return_value=_llm("VERDICT: SUPPORTED\nRATIONALE: source confirms 19%")),
    ):
        result = await verify_synthesis(
            synthesis=synthesis, stage2_compacted="", user_query="ev growth?",
            session=_FakeSession(),
        )

    assert isinstance(result, BlindedVerificationResult)
    assert result.passed is True
    assert result.supported_count == 1
    assert result.contradicted_count == 0
    assert result.unverified_count == 0
    assert result.per_claim[0]["verdict"] == "SUPPORTED"
    assert result.per_claim[0]["claim_text"] == "EV growth was 19% in Q4 2025"


@pytest.mark.asyncio
async def test_blinded_verifier_fails_when_claim_contradicted():
    cited = AtomizedClaim(
        id="c1", kind="numeric", text="X grew 50%",
        evidence_refs=["https://src"], member_id="chairperson", confidence=0.8,
    )
    with patch(
        "server.board.deliberation.verification.atomize",
        new=AsyncMock(return_value=[cited]),
    ), patch(
        "server.board.deliberation.verification.resolve_evidence",
        new=AsyncMock(return_value={"https://src": "X grew only 10%"}),
    ), patch(
        "server.board.deliberation.verification.query_llm",
        new=AsyncMock(return_value=_llm("VERDICT: CONTRADICTED\nRATIONALE: source says 10% not 50%")),
    ):
        result = await verify_synthesis(
            synthesis="X grew 50%", stage2_compacted="", user_query="?",
            session=_FakeSession(),
        )

    assert result.passed is False
    assert result.contradicted_count == 1
    assert result.supported_count == 0
    # Deficiency must surface the verdict label + claim text so the eval
    # checker's `deficiency_contains` keyword match works.
    assert any("CONTRADICTED" in d for d in result.deficiencies)
    assert any("X grew 50%" in d for d in result.deficiencies)


@pytest.mark.asyncio
async def test_blinded_verifier_fails_with_unverified_when_off_topic_evidence():
    cited = AtomizedClaim(
        id="c1", kind="numeric", text="A is 100",
        evidence_refs=["https://src"], member_id="chairperson", confidence=0.5,
    )
    with patch(
        "server.board.deliberation.verification.atomize",
        new=AsyncMock(return_value=[cited]),
    ), patch(
        "server.board.deliberation.verification.resolve_evidence",
        new=AsyncMock(return_value={"https://src": "completely unrelated text"}),
    ), patch(
        "server.board.deliberation.verification.query_llm",
        new=AsyncMock(return_value=_llm("VERDICT: UNVERIFIED\nRATIONALE: source is off-topic")),
    ):
        result = await verify_synthesis(
            synthesis="A is 100", stage2_compacted="", user_query="?",
            session=_FakeSession(),
        )

    assert result.passed is False
    assert result.unverified_count == 1
    assert any("UNVERIFIED" in d for d in result.deficiencies)


@pytest.mark.asyncio
async def test_blinded_verifier_filters_to_load_bearing_cited_claims():
    """Qualitative or [UNVERIFIED] claims are not blinded-verified per spec §5.2.1 step 2."""
    qual = AtomizedClaim(
        id="q1", kind="qualitative", text="This is risky",
        evidence_refs=["https://src"], member_id="chairperson", confidence=1.0,
    )
    uncited = AtomizedClaim(
        id="u1", kind="numeric", text="growth is 30%",
        evidence_refs=["[UNVERIFIED]"], member_id="chairperson", confidence=0.6,
    )
    cited = AtomizedClaim(
        id="c1", kind="numeric", text="revenue is $10M",
        evidence_refs=["https://src"], member_id="chairperson", confidence=0.9,
    )
    with patch(
        "server.board.deliberation.verification.atomize",
        new=AsyncMock(return_value=[qual, uncited, cited]),
    ), patch(
        "server.board.deliberation.verification.resolve_evidence",
        new=AsyncMock(return_value={"https://src": "revenue is $10M confirmed"}),
    ), patch(
        "server.board.deliberation.verification.query_llm",
        new=AsyncMock(return_value=_llm("VERDICT: SUPPORTED\nRATIONALE: confirmed")),
    ) as mock_llm:
        result = await verify_synthesis(
            synthesis="any text", stage2_compacted="", user_query="?",
            session=_FakeSession(),
        )

    # Only the load-bearing cited claim (revenue) went through the per-claim LLM.
    assert mock_llm.await_count == 1
    assert result.supported_count == 1
    # Uncited load-bearing claim surfaces as a deficiency without LLM call
    assert any("uncited" in d.lower() or "no citation" in d.lower() for d in result.deficiencies)


@pytest.mark.asyncio
async def test_blinded_verifier_falls_back_to_checklist_when_no_cited_claims(monkeypatch):
    """If atomizer returns only [UNVERIFIED] claims AND no load-bearing cited claims,
    the verifier falls back to the legacy 6-point checklist."""
    qual = AtomizedClaim(
        id="q1", kind="qualitative", text="just opinions here",
        evidence_refs=["[UNVERIFIED]"], member_id="chairperson", confidence=1.0,
    )
    checklist_response = '{"score": 8, "deficiencies": [], "suggestions": []}'

    with patch(
        "server.board.deliberation.verification.atomize",
        new=AsyncMock(return_value=[qual]),
    ), patch(
        "server.board.deliberation.verification.query_llm",
        new=AsyncMock(return_value=_llm(checklist_response)),
    ) as mock_llm:
        result = await verify_synthesis(
            synthesis="just opinions here", stage2_compacted="", user_query="?",
            session=_FakeSession(),
        )

    # The legacy checklist ran (one LLM call), per-claim path did not
    assert mock_llm.await_count == 1
    assert result.score == 8
    assert result.passed is True
    # per_claim list is empty when we fell back
    assert result.per_claim == []


@pytest.mark.asyncio
async def test_blinded_verifier_unparseable_verdict_recorded_as_unverified():
    cited = AtomizedClaim(
        id="c1", kind="numeric", text="X is 5",
        evidence_refs=["https://src"], member_id="chairperson", confidence=0.5,
    )
    with patch(
        "server.board.deliberation.verification.atomize",
        new=AsyncMock(return_value=[cited]),
    ), patch(
        "server.board.deliberation.verification.resolve_evidence",
        new=AsyncMock(return_value={"https://src": "something"}),
    ), patch(
        "server.board.deliberation.verification.query_llm",
        new=AsyncMock(return_value=_llm("garbage with no verdict line")),
    ):
        result = await verify_synthesis(
            synthesis="X is 5", stage2_compacted="", user_query="?",
            session=_FakeSession(),
        )
    assert result.unverified_count == 1
    assert result.per_claim[0]["verdict"] == "UNVERIFIED"


from server.board.deliberation.verification import (
    build_revision_prompt,
)


def test_build_revision_prompt_per_claim_format():
    """When per_claim results are present, the revision prompt names each
    failing claim with its verdict, rationale, and evidence."""
    result = BlindedVerificationResult(
        score=3, passed=False,
        deficiencies=[], suggestions=[],
        per_claim=[
            {"claim_id": "a", "claim_text": "EV grew 30%",
             "verdict": "CONTRADICTED",
             "rationale": "source says 19%", "evidence_refs": ["https://reuters.com/x"]},
            {"claim_id": "b", "claim_text": "Mistral MAU is 5M",
             "verdict": "UNVERIFIED",
             "rationale": "source off-topic", "evidence_refs": ["https://blog.example/y"]},
            {"claim_id": "c", "claim_text": "Y is true",
             "verdict": "SUPPORTED",
             "rationale": "confirmed", "evidence_refs": ["https://wsj.com/z"]},
        ],
        supported_count=1, contradicted_count=1, unverified_count=1,
    )

    prompt = build_revision_prompt(result)

    assert "claim-by-claim" in prompt
    assert "CONTRADICTED" in prompt
    assert "EV grew 30%" in prompt
    assert "UNVERIFIED" in prompt
    assert "Mistral MAU is 5M" in prompt
    # The SUPPORTED claim must NOT appear (only failures)
    assert "Y is true" not in prompt
    assert "Do not rephrase" in prompt


def test_build_revision_prompt_legacy_fallback_format():
    """For a non-blinded VerificationResult (checklist fallback), the legacy
    format is used."""
    from server.board.deliberation.verification import VerificationResult
    result = VerificationResult(
        score=4, passed=False,
        deficiencies=["needs more evidence", "executive summary missing"],
    )
    prompt = build_revision_prompt(result)
    assert "scored 4/10" in prompt
    assert "needs more evidence" in prompt
    assert "executive summary missing" in prompt
