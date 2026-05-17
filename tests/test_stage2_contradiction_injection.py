"""Stage 2 peer review receives the PEER CONTRADICTIONS DETECTED block."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from server.board.deliberation.contradiction import (
    ContradictionFinding,
    format_contradictions_block,
)
from server.board.deliberation.orchestrator import BoardOrchestrator, MemberResponse
from server.board.deliberation.prompts import format_stage2


def _resp(member_id: str, content: str = "x") -> MemberResponse:
    return MemberResponse(
        member_id=member_id, stage=1, content=content,
        model="test-model", elapsed_seconds=0.1,
    )


def _claim(member_id: str, text: str) -> dict:
    return {
        "id": f"id-{member_id}-{text[:6]}", "kind": "numeric", "text": text,
        "evidence_refs": ["https://example.com"], "member_id": member_id, "confidence": 0.8,
    }


def test_format_contradictions_block_renders_each_finding():
    findings = [
        ContradictionFinding(
            topic="EV growth",
            claim_a=_claim("strategist", "EV growth was 19%"),
            claim_b=_claim("critic", "EV growth was 10%"),
            severity="load_bearing",
        ),
        ContradictionFinding(
            topic="MAU",
            claim_a=_claim("product", "MAU is 5M"),
            claim_b=_claim("researcher", "MAU is 12M"),
            severity="material",
        ),
    ]
    block = format_contradictions_block(findings)
    assert "PEER CONTRADICTIONS DETECTED" in block
    assert "[LOAD-BEARING]" in block
    assert "EV growth" in block
    assert "EV growth was 19%" in block
    assert "EV growth was 10%" in block
    assert "MAU" in block
    assert "[MATERIAL]" in block


def test_format_contradictions_block_returns_empty_string_when_no_findings():
    assert format_contradictions_block([]) == ""


def test_format_stage2_substitutes_peer_contradictions_placeholder():
    rendered = format_stage2(
        role="Critic",
        user_query="Should we pivot?",
        anonymized_responses="### Member A\n## TL;DR\n- something.",
        stage2_behavior="Challenge missing evidence.",
        peer_contradictions="PEER CONTRADICTIONS DETECTED\n\n1. [MATERIAL] Topic: EV growth\n",
    )
    assert "PEER CONTRADICTIONS DETECTED" in rendered
    assert "EV growth" in rendered


def test_format_stage2_with_empty_peer_contradictions_leaves_no_placeholder():
    rendered = format_stage2(
        role="Critic",
        user_query="x",
        anonymized_responses="...",
        stage2_behavior="...",
        peer_contradictions="",
    )
    assert "{{peer_contradictions}}" not in rendered
    assert "PEER CONTRADICTIONS DETECTED" not in rendered


@pytest.mark.asyncio
async def test_stage2_pipes_contradictions_block_into_each_member_prompt():
    """End-to-end: when session.contradictions is populated, stage2() builds
    a non-empty peer_contradictions block and passes it through format_stage2
    for every member."""
    from server.board.config import BoardMember

    def _member(member_id: str) -> BoardMember:
        return BoardMember(
            id=member_id, title=f"{member_id.title()}", role="Test",
            expertise=[], system_prompt=f"{member_id}-sys",
            stage2_behavior="Challenge.",
        )

    orchestrator = BoardOrchestrator(members=[_member("strategist"), _member("critic")])
    # Simulate the contradiction-detected pipeline state.
    contradictions = [{
        "topic": "EV growth",
        "claim_a": _claim("strategist", "EV growth was 19%"),
        "claim_b": _claim("critic", "EV growth was 10%"),
        "severity": "material",
    }]

    captured: list[str] = []
    async def _fake_query(member, prompt, stage):
        captured.append(prompt)
        return MemberResponse(
            member_id=member.id, stage=stage, content="ok",
            model="x", elapsed_seconds=0.1,
        )

    with patch.object(orchestrator, "_query_member", side_effect=_fake_query):
        await orchestrator.stage2(
            "Should we pivot?",
            [_resp("strategist"), _resp("critic")],
            contradictions=contradictions,
        )

    assert len(captured) == 2
    for prompt in captured:
        assert "PEER CONTRADICTIONS DETECTED" in prompt
        assert "EV growth was 19%" in prompt
        assert "EV growth was 10%" in prompt


@pytest.mark.asyncio
async def test_stage2_omits_contradictions_block_when_none():
    """No contradictions → no PEER CONTRADICTIONS block in the prompt."""
    from server.board.config import BoardMember

    def _member(member_id: str) -> BoardMember:
        return BoardMember(
            id=member_id, title=f"{member_id.title()}", role="Test",
            expertise=[], system_prompt=f"{member_id}-sys",
            stage2_behavior="Challenge.",
        )

    orchestrator = BoardOrchestrator(members=[_member("strategist"), _member("critic")])
    captured: list[str] = []
    async def _fake_query(member, prompt, stage):
        captured.append(prompt)
        return MemberResponse(
            member_id=member.id, stage=stage, content="ok",
            model="x", elapsed_seconds=0.1,
        )

    with patch.object(orchestrator, "_query_member", side_effect=_fake_query):
        await orchestrator.stage2(
            "Should we pivot?",
            [_resp("strategist"), _resp("critic")],
            contradictions=[],
        )

    assert len(captured) == 2
    for prompt in captured:
        assert "PEER CONTRADICTIONS DETECTED" not in prompt
