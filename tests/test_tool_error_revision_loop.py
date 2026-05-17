"""End-to-end integration tests for the P3b tool-error revision loop.

Asserts the full happy path through agentic_member_turn:
  1. Model emits validate_claim tool call
  2. Fake tool returns CONTRADICTED ToolResult
  3. Next model invocation sees the forced revision user turn in messages
  4. Model produces a corrected output that drops the contradicted claim
  5. Multiple CONTRADICTEDs each consume one slot up to the cap
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from server.board import llm, tools
from server.board.config import BoardMember
from server.board.deliberation.orchestrator import (
    REVISION_FORCING_PROMPT,
    ToolBudget,
    agentic_member_turn,
)


def _member(member_id: str = "strategist") -> BoardMember:
    return BoardMember(
        id=member_id, title="Test", role="role",
        expertise=[], system_prompt="You are a tester.",
    )


def _budget(max_calls: int = 4) -> ToolBudget:
    return ToolBudget(
        tool_calls_max=max_calls, wall_seconds_max=300, per_call_timeout=240.0,
        open_browser_max=0, web_search_max=0, fetch_url_max=0, ask_user_max=0,
    )


async def test_full_flow_validate_claim_contradicted_then_drop():
    """End-to-end: validate_claim returns CONTRADICTED; member sees forced
    revision turn on the next call; member drops the claim."""
    tc1 = llm.LLMResponse(
        content="", model="m", input_tokens=1, output_tokens=1, latency_seconds=0.1,
        finish_reason="tool_calls",
        tool_calls=[llm.ToolCall(
            id="tc_1", name="validate_claim",
            arguments={"claim": "Mistral was founded in 2021"},
        )],
    )
    final = llm.LLMResponse(
        content=(
            "I drop the Mistral 2021 founding claim — the forced revision "
            "showed contradicting evidence and I have no new citation to "
            "support it. Mistral's founding year is [UNVERIFIED] in this analysis."
        ),
        model="m", input_tokens=1, output_tokens=1, latency_seconds=0.1,
        finish_reason="stop", tool_calls=[],
    )
    captured_messages: list[list] = []
    responses = iter([tc1, final])

    async def _spy(*args, **kwargs):
        captured_messages.append(list(args[1]) if len(args) > 1 else list(kwargs.get("messages", [])))
        return next(responses)

    contra = tools.ToolResult(
        content_for_model=(
            "validate_claim('Mistral was founded in 2021'):\n"
            "VERDICT: CONTRADICTED\n"
            "RATIONALE: Multiple sources confirm Mistral AI was founded in April 2023.\n"
            "KEY_SOURCES: https://en.wikipedia.org/wiki/Mistral_AI, https://reuters.com/..."
        ),
        summary="validate_claim: CONTRADICTED",
        cost_units=2.0,
    )

    with patch("server.board.deliberation.orchestrator.query_llm",
               AsyncMock(side_effect=_spy)), \
         patch("server.board.deliberation.orchestrator.execute_tool",
                AsyncMock(return_value=contra)):
        result = await agentic_member_turn(
            member=_member(), model="m",
            system_prompt="You are a tester.",
            initial_user_message="Analyze Mistral's market position.",
            tools=[tools.TOOLS["validate_claim"]],
            budget=_budget(max_calls=2),
            session=SimpleNamespace(), stage=1, on_event=lambda e: None,
        )

    assert "drop the Mistral 2021" in result.content
    assert "[UNVERIFIED]" in result.content

    second_call = captured_messages[1]
    forced = [m for m in second_call
              if m.get("role") == "user" and "FORCED REVISION" in (m.get("content") or "")]
    assert len(forced) == 1
    body = forced[0]["content"]
    assert "validate_claim" in body
    assert "validate_claim: CONTRADICTED" in body
    assert "Mistral AI was founded in April 2023" in body
    assert "(a) Drop this claim" in body
    assert "(b) Provide a new citation" in body


async def test_two_contradicteds_each_consume_one_slot():
    """Two distinct CONTRADICTED returns within one member turn each fire
    their own forced revision under cap=2."""
    tc_call = lambda i, claim: llm.LLMResponse(
        content="", model="m", input_tokens=1, output_tokens=1, latency_seconds=0.1,
        finish_reason="tool_calls",
        tool_calls=[llm.ToolCall(
            id=f"tc_{i}", name="validate_claim", arguments={"claim": claim},
        )],
    )
    final = llm.LLMResponse(
        content="Both claims dropped after revisions.", model="m",
        input_tokens=1, output_tokens=1, latency_seconds=0.1,
        finish_reason="stop", tool_calls=[],
    )
    captured_messages: list[list] = []
    responses = iter([
        tc_call(1, "claim A"),
        tc_call(2, "claim B"),
        final,
    ])

    async def _spy(*args, **kwargs):
        captured_messages.append(list(args[1]) if len(args) > 1 else list(kwargs.get("messages", [])))
        return next(responses)

    contra = tools.ToolResult(
        content_for_model="validate_claim('x'): VERDICT: CONTRADICTED\nRATIONALE: nope.",
        summary="validate_claim: CONTRADICTED",
        cost_units=2.0,
    )

    with patch("server.board.deliberation.orchestrator.query_llm",
               AsyncMock(side_effect=_spy)), \
         patch("server.board.deliberation.orchestrator.execute_tool",
                AsyncMock(return_value=contra)):
        await agentic_member_turn(
            member=_member(), model="m",
            system_prompt="You are a tester.",
            initial_user_message="Analyze X.",
            tools=[tools.TOOLS["validate_claim"]],
            budget=_budget(max_calls=3),
            session=SimpleNamespace(), stage=1, on_event=lambda e: None,
        )

    final_msgs = captured_messages[-1]
    forced = [m for m in final_msgs
              if m.get("role") == "user" and "FORCED REVISION" in (m.get("content") or "")]
    assert len(forced) == 2


async def test_forced_revision_uses_constant_template_verbatim():
    """The injected message body must derive from REVISION_FORCING_PROMPT
    (spec §7.2.2). Catches regressions if someone refactors and rewrites
    the prompt inline."""
    tc = llm.LLMResponse(
        content="", model="m", input_tokens=1, output_tokens=1, latency_seconds=0.1,
        finish_reason="tool_calls",
        tool_calls=[llm.ToolCall(id="tc_1", name="validate_claim",
                                  arguments={"claim": "x"})],
    )
    final = llm.LLMResponse(
        content="Done.", model="m", input_tokens=1, output_tokens=1,
        latency_seconds=0.1, finish_reason="stop", tool_calls=[],
    )
    captured_messages: list[list] = []
    responses = iter([tc, final])

    async def _spy(*args, **kwargs):
        captured_messages.append(list(args[1]) if len(args) > 1 else list(kwargs.get("messages", [])))
        return next(responses)

    contra = tools.ToolResult(
        content_for_model="validate_claim('x'): VERDICT: CONTRADICTED",
        summary="validate_claim: CONTRADICTED",
        cost_units=2.0,
    )

    with patch("server.board.deliberation.orchestrator.query_llm",
               AsyncMock(side_effect=_spy)), \
         patch("server.board.deliberation.orchestrator.execute_tool",
                AsyncMock(return_value=contra)):
        await agentic_member_turn(
            member=_member(), model="m",
            system_prompt="x", initial_user_message="x",
            tools=[tools.TOOLS["validate_claim"]],
            budget=_budget(max_calls=2),
            session=SimpleNamespace(), stage=1, on_event=lambda e: None,
        )

    forced = [m for m in captured_messages[1]
              if m.get("role") == "user" and "FORCED REVISION" in (m.get("content") or "")]
    assert len(forced) == 1
    body = forced[0]["content"]
    assert "Do not re-assert the contradicted claim without new evidence." in body
    assert "  Tool:" in body
    assert "  Contradicted:" in body
    assert "  Rationale:" in body
