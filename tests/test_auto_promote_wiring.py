"""Orchestrator wiring tests for P5b auto-promote-to-live."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from server.board.deliberation.orchestrator import BoardSession, MemberResponse


# ─── T6: BoardSession.disagreement_score + auto_promoted_rebuttals ──────────


def test_board_session_disagreement_score_defaults_zero():
    s = BoardSession(session_id="t", user_query="x")
    assert s.disagreement_score == 0


def test_board_session_auto_promoted_rebuttals_defaults_empty():
    s = BoardSession(session_id="t", user_query="x")
    assert s.auto_promoted_rebuttals == []


def test_board_session_to_dict_includes_new_fields():
    s = BoardSession(
        session_id="t", user_query="x",
        disagreement_score=7,
        auto_promoted_rebuttals=[
            {"pair_member_ids": ["strategist", "product"],
             "disagreement_score": 7,
             "topic": "market sizing",
             "severity": "load_bearing",
             "transcript": [{"role": "chair", "content": "open"}],
             "summary": "REBUTTAL OUTCOME — ...",
             "resolution": "PARTIAL",
             "summarizer_model": "qwen/qwen3.6-plus",
             "tokens_in": 500,
             "tokens_out": 200,
             "cost_usd": 0.0,
             "started_at": "2026-05-17T00:00:00+00:00",
             "elapsed_seconds": 12.3,
             "closed_early": False},
        ],
    )
    d = s.to_dict()
    assert d["disagreement_score"] == 7
    assert len(d["auto_promoted_rebuttals"]) == 1
    assert d["auto_promoted_rebuttals"][0]["resolution"] == "PARTIAL"
    assert d["auto_promoted_rebuttals"][0]["transcript"] == [
        {"role": "chair", "content": "open"}
    ]


# ─── T7: stage3() rebuttal_outcomes prepend ─────────────────────────────────


@pytest.mark.asyncio
async def test_stage3_prepends_rebuttal_outcomes_block_when_non_empty():
    """When stage3() receives rebuttal_outcomes, the formatted block must
    appear in the prompt that goes to query_llm BEFORE the existing
    format_stage3() output."""
    from server.board import llm
    from server.board.deliberation.orchestrator import BoardOrchestrator

    captured_messages: list = []

    async def _capture_query(*a, **kw):
        # Capture the messages arg (positional 1 or kwarg) for inspection.
        msgs = kw.get("messages") if "messages" in kw else (a[1] if len(a) > 1 else [])
        captured_messages.extend(msgs)
        return llm.LLMResponse(
            content="synth", model="m", input_tokens=1, output_tokens=1,
            latency_seconds=0.01, finish_reason="stop", tool_calls=[],
        )

    orch = BoardOrchestrator()
    # Patch model attrs to avoid env dependencies.
    orch.chairman_model = "m"

    s1 = [MemberResponse(member_id="strategist", stage=1, content="S1A",
                          model="m", elapsed_seconds=0.01)]
    s2 = [MemberResponse(member_id="strategist", stage=2, content="S2A",
                          model="m", elapsed_seconds=0.01)]

    rebuttals = [
        {"summary": "REBUTTAL OUTCOME — t1\nResolution: PARTIAL\n...", "topic": "t1"},
    ]

    with patch("server.board.deliberation.orchestrator.query_llm",
               AsyncMock(side_effect=_capture_query)):
        await orch.stage3(
            "user q", s1, s2,
            sotb="(no warnings)",
            rebuttal_outcomes=rebuttals,
        )

    assert captured_messages, "stage3 didn't call query_llm"
    user_msg = captured_messages[0]["content"]
    # Rebuttal block must appear (spec §9.2.6 header is the load-bearing marker).
    assert "REBUTTAL OUTCOME (auto-promoted" in user_msg
    assert "REBUTTAL OUTCOME — t1" in user_msg


@pytest.mark.asyncio
async def test_stage3_no_block_when_rebuttal_outcomes_empty_or_none():
    """Default behaviour unchanged when rebuttal_outcomes=None or [].
    The spec §9.2.6 marker must NOT appear."""
    from server.board import llm
    from server.board.deliberation.orchestrator import BoardOrchestrator

    captured: list = []

    async def _capture(*a, **kw):
        msgs = kw.get("messages") if "messages" in kw else (a[1] if len(a) > 1 else [])
        captured.extend(msgs)
        return llm.LLMResponse(
            content="synth", model="m", input_tokens=1, output_tokens=1,
            latency_seconds=0.01, finish_reason="stop", tool_calls=[],
        )

    orch = BoardOrchestrator()
    orch.chairman_model = "m"

    s1 = [MemberResponse(member_id="strategist", stage=1, content="S1",
                          model="m", elapsed_seconds=0.01)]
    s2 = [MemberResponse(member_id="strategist", stage=2, content="S2",
                          model="m", elapsed_seconds=0.01)]

    with patch("server.board.deliberation.orchestrator.query_llm",
               AsyncMock(side_effect=_capture)):
        await orch.stage3("user q", s1, s2, sotb="(no warnings)")  # default kwargs
        await orch.stage3("user q", s1, s2, sotb="(no warnings)",
                           rebuttal_outcomes=[])

    for msg in captured:
        assert "REBUTTAL OUTCOME (auto-promoted" not in msg["content"]
