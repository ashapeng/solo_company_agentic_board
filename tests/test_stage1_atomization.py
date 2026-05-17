"""Stage 1 per-member atomization tests (spec §5.1.1).

Atomization runs after Stage 1 completes (parallel member calls), BEFORE Stage 2
starts compaction. Each member's response is atomized independently; results
land in session.atomized_claims, keyed by member_id. Atomization is gated on
verify=True (HEAVY tier, P1 convention). Failure is non-fatal — a single
member's atomizer error is logged but the pipeline continues.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from server.board.deliberation.atomizer import AtomizedClaim
from server.board.deliberation.orchestrator import BoardOrchestrator, MemberResponse


def _resp(member_id: str, content: str = "x") -> MemberResponse:
    return MemberResponse(
        member_id=member_id, stage=1, content=content,
        model="test-model", elapsed_seconds=0.1,
    )


def _claim(member_id: str, text: str, kind: str = "numeric") -> AtomizedClaim:
    return AtomizedClaim(
        id=f"id-{member_id}-{text[:8]}",
        kind=kind,
        text=text,
        evidence_refs=["[UNVERIFIED]"],
        member_id=member_id,
        confidence=0.8,
    )


@pytest.mark.asyncio
async def test_stage1_atomization_populates_session_when_verify_true():
    """When verify=True, each member's Stage 1 response is atomized and stored
    on session.atomized_claims keyed by member_id."""
    orchestrator = BoardOrchestrator()

    def _atomize_for(text, *, member_id, **_kw):
        # Return one synthetic claim per member so the test can verify the keying.
        return [_claim(member_id, f"{member_id} growth was 19%")]

    with (
        patch.object(orchestrator, "stage1", new=AsyncMock(return_value=[
            _resp("strategist", "EV growth was 19% [https://reuters.com/x]"),
            _resp("product", "MVP scoped for Q2 [https://example.com/y]"),
        ])),
        patch.object(orchestrator, "stage2", new=AsyncMock(return_value=[])),
        patch.object(orchestrator, "stage3", new=AsyncMock(return_value=_resp("chairperson", "synth"))),
        patch.object(orchestrator, "stage4_secretary_brief", new=AsyncMock(return_value=None)),
        patch("server.board.deliberation.orchestrator.atomize", new=AsyncMock(side_effect=_atomize_for)),
        patch("server.board.deliberation.verification.verify_synthesis", new=AsyncMock()),
        patch("server.board.deliberation.orchestrator.BoardSession.save", return_value=Path("data/sessions/x.json")),
        patch("server.board.deliberation.orchestrator._record_to_ledger"),
        patch("server.board.deliberation.orchestrator.record_delegation_plan"),
    ):
        session = await orchestrator.deliberate(
            "Should we pivot?",
            skip_classify=True,
            verify=True,
            session_id="board_atomize",
        )

    assert "strategist" in session.atomized_claims
    assert "product" in session.atomized_claims
    assert len(session.atomized_claims["strategist"]) == 1
    assert session.atomized_claims["strategist"][0]["member_id"] == "strategist"
    assert "strategist growth was 19%" in session.atomized_claims["strategist"][0]["text"]


@pytest.mark.asyncio
async def test_stage1_atomization_skipped_when_verify_false():
    """verify=False → no atomization, session.atomized_claims stays empty."""
    orchestrator = BoardOrchestrator()

    atomize_mock = AsyncMock()

    with (
        patch.object(orchestrator, "stage1", new=AsyncMock(return_value=[
            _resp("strategist"), _resp("product"),
        ])),
        patch.object(orchestrator, "stage2", new=AsyncMock(return_value=[])),
        patch.object(orchestrator, "stage3", new=AsyncMock(return_value=_resp("chairperson"))),
        patch.object(orchestrator, "stage4_secretary_brief", new=AsyncMock(return_value=None)),
        patch("server.board.deliberation.orchestrator.atomize", new=atomize_mock),
        patch("server.board.deliberation.orchestrator.BoardSession.save", return_value=Path("data/sessions/x.json")),
        patch("server.board.deliberation.orchestrator._record_to_ledger"),
        patch("server.board.deliberation.orchestrator.record_delegation_plan"),
    ):
        session = await orchestrator.deliberate(
            "Should we pivot?",
            skip_classify=True,
            verify=False,
            session_id="board_atomize_off",
        )

    assert session.atomized_claims == {}
    atomize_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_stage1_atomization_failure_non_fatal():
    """If atomize() raises for one member, the pipeline continues and that
    member's slot is simply omitted from session.atomized_claims."""
    orchestrator = BoardOrchestrator()

    async def _atomize_failing(text, *, member_id, **_kw):
        if member_id == "product":
            raise RuntimeError("atomizer provider down")
        return [_claim(member_id, "some claim")]

    with (
        patch.object(orchestrator, "stage1", new=AsyncMock(return_value=[
            _resp("strategist"), _resp("product"), _resp("critic"),
        ])),
        patch.object(orchestrator, "stage2", new=AsyncMock(return_value=[])),
        patch.object(orchestrator, "stage3", new=AsyncMock(return_value=_resp("chairperson"))),
        patch.object(orchestrator, "stage4_secretary_brief", new=AsyncMock(return_value=None)),
        patch("server.board.deliberation.orchestrator.atomize", new=AsyncMock(side_effect=_atomize_failing)),
        patch("server.board.deliberation.verification.verify_synthesis", new=AsyncMock()),
        patch("server.board.deliberation.orchestrator.BoardSession.save", return_value=Path("data/sessions/x.json")),
        patch("server.board.deliberation.orchestrator._record_to_ledger"),
        patch("server.board.deliberation.orchestrator.record_delegation_plan"),
    ):
        session = await orchestrator.deliberate(
            "Should we pivot?",
            skip_classify=True,
            verify=True,
            session_id="board_atomize_partial",
        )

    # Non-failing members landed; the failing one is omitted.
    assert "strategist" in session.atomized_claims
    assert "critic" in session.atomized_claims
    assert "product" not in session.atomized_claims


def test_board_session_to_dict_includes_atomized_claims():
    """session.to_dict() must include atomized_claims so they're persisted."""
    from server.board.deliberation.orchestrator import BoardSession
    session = BoardSession(
        session_id="x", user_query="?",
        atomized_claims={
            "strategist": [{"id": "abc", "kind": "numeric", "text": "X is 5",
                            "evidence_refs": ["https://src"], "member_id": "strategist",
                            "confidence": 0.9}],
        },
    )
    d = session.to_dict()
    assert "atomized_claims" in d
    assert d["atomized_claims"]["strategist"][0]["text"] == "X is 5"
