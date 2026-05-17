"""Integration: orchestrator runs the contradiction detector after Stage 1."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from server.board.deliberation.contradiction import ContradictionFinding
from server.board.deliberation.orchestrator import BoardOrchestrator, MemberResponse


def _resp(member_id: str, content: str = "x") -> MemberResponse:
    return MemberResponse(
        member_id=member_id, stage=1, content=content,
        model="test-model", elapsed_seconds=0.1,
    )


def _claim(member_id: str, text: str) -> dict:
    return {
        "id": f"id-{member_id}-{text[:6]}", "kind": "numeric", "text": text,
        "evidence_refs": ["[UNVERIFIED]"], "member_id": member_id, "confidence": 0.8,
    }


@pytest.mark.asyncio
async def test_contradiction_detector_runs_and_results_land_on_session():
    """When verify=True and atomized_claims has ≥2 members, detector runs
    and findings are stored on session.contradictions as dicts."""
    orchestrator = BoardOrchestrator()
    finding = ContradictionFinding(
        topic="EV growth",
        claim_a=_claim("strategist", "EV growth was 19%"),
        claim_b=_claim("critic", "EV growth was 10%"),
        severity="material",
    )

    async def _atomize_for(text, *, member_id, **_kw):
        from server.board.deliberation.atomizer import AtomizedClaim
        return [AtomizedClaim(
            id=f"id-{member_id}", kind="numeric", text=f"{member_id} text",
            evidence_refs=["[UNVERIFIED]"], member_id=member_id, confidence=0.8,
        )]

    with (
        patch.object(orchestrator, "stage1", new=AsyncMock(return_value=[
            _resp("strategist"), _resp("critic"),
        ])),
        patch.object(orchestrator, "stage2", new=AsyncMock(return_value=[])),
        patch.object(orchestrator, "stage3", new=AsyncMock(return_value=_resp("chairperson"))),
        patch.object(orchestrator, "stage4_secretary_brief", new=AsyncMock(return_value=None)),
        patch("server.board.deliberation.orchestrator.atomize", new=AsyncMock(side_effect=_atomize_for)),
        patch("server.board.deliberation.orchestrator.detect_contradictions",
              new=AsyncMock(return_value=[finding])),
        patch("server.board.deliberation.verification.verify_synthesis", new=AsyncMock()),
        patch("server.board.deliberation.orchestrator.BoardSession.save",
              return_value=Path("data/sessions/x.json")),
        patch("server.board.deliberation.orchestrator._record_to_ledger"),
        patch("server.board.deliberation.orchestrator.record_delegation_plan"),
    ):
        session = await orchestrator.deliberate(
            "Should we pivot?", skip_classify=True, verify=True,
            session_id="board_p2",
        )

    assert len(session.contradictions) == 1
    assert session.contradictions[0]["topic"] == "EV growth"
    assert session.contradictions[0]["severity"] == "material"
    assert session.contradictions[0]["claim_a"]["member_id"] == "strategist"


@pytest.mark.asyncio
async def test_contradiction_detector_skipped_when_verify_false():
    orchestrator = BoardOrchestrator()
    detector_mock = AsyncMock()

    with (
        patch.object(orchestrator, "stage1", new=AsyncMock(return_value=[
            _resp("strategist"), _resp("critic"),
        ])),
        patch.object(orchestrator, "stage2", new=AsyncMock(return_value=[])),
        patch.object(orchestrator, "stage3", new=AsyncMock(return_value=_resp("chairperson"))),
        patch.object(orchestrator, "stage4_secretary_brief", new=AsyncMock(return_value=None)),
        patch("server.board.deliberation.orchestrator.atomize", new=AsyncMock()),
        patch("server.board.deliberation.orchestrator.detect_contradictions", new=detector_mock),
        patch("server.board.deliberation.orchestrator.BoardSession.save",
              return_value=Path("data/sessions/x.json")),
        patch("server.board.deliberation.orchestrator._record_to_ledger"),
        patch("server.board.deliberation.orchestrator.record_delegation_plan"),
    ):
        session = await orchestrator.deliberate(
            "x", skip_classify=True, verify=False, session_id="board_no_p2",
        )

    assert session.contradictions == []
    detector_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_contradiction_detector_skipped_when_only_one_member_responded():
    """Detector needs ≥2 members to compare claims. With only one, skip."""
    orchestrator = BoardOrchestrator()
    detector_mock = AsyncMock()

    with (
        patch.object(orchestrator, "stage1", new=AsyncMock(return_value=[_resp("strategist")])),
        patch.object(orchestrator, "stage2", new=AsyncMock(return_value=[])),
        patch.object(orchestrator, "stage3", new=AsyncMock(return_value=_resp("chairperson"))),
        patch.object(orchestrator, "stage4_secretary_brief", new=AsyncMock(return_value=None)),
        patch("server.board.deliberation.orchestrator.atomize",
              new=AsyncMock(return_value=[])),
        patch("server.board.deliberation.orchestrator.detect_contradictions", new=detector_mock),
        patch("server.board.deliberation.verification.verify_synthesis", new=AsyncMock()),
        patch("server.board.deliberation.orchestrator.BoardSession.save",
              return_value=Path("data/sessions/x.json")),
        patch("server.board.deliberation.orchestrator._record_to_ledger"),
        patch("server.board.deliberation.orchestrator.record_delegation_plan"),
    ):
        session = await orchestrator.deliberate(
            "x", skip_classify=True, verify=True, session_id="board_solo",
        )

    assert session.contradictions == []
    detector_mock.assert_not_awaited()


def test_board_session_to_dict_includes_contradictions():
    """to_dict() includes contradictions so they persist in saved sessions."""
    from server.board.deliberation.orchestrator import BoardSession
    session = BoardSession(
        session_id="x", user_query="?",
        contradictions=[{
            "topic": "EV growth",
            "claim_a": {"member_id": "strategist", "text": "19%"},
            "claim_b": {"member_id": "critic", "text": "10%"},
            "severity": "material",
        }],
    )
    d = session.to_dict()
    assert "contradictions" in d
    assert d["contradictions"][0]["topic"] == "EV growth"
