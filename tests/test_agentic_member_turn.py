"""Tests for agentic_member_turn and ToolBudget."""
from __future__ import annotations

import pytest

from server.board.deliberation import orchestrator


def test_tool_budget_default_fast():
    b = orchestrator.ToolBudget.for_mode("fast")
    assert b.tool_calls_max == 0
    assert b.web_search_max == 0
    assert b.open_browser_max == 0
    assert b.ask_user_max == 0


def test_tool_budget_default_standard():
    b = orchestrator.ToolBudget.for_mode("standard", member_role="member")
    assert b.tool_calls_max == 3
    assert b.web_search_max == 3
    assert b.open_browser_max == 1
    assert b.ask_user_max == 0  # members in standard get no ask_user


def test_tool_budget_default_deep_member():
    b = orchestrator.ToolBudget.for_mode("deep", member_role="member")
    assert b.tool_calls_max == 8
    assert b.web_search_max == 6
    assert b.open_browser_max == 3
    assert b.ask_user_max == 1


def test_tool_budget_default_deep_chair():
    b = orchestrator.ToolBudget.for_mode("deep", member_role="chair")
    assert b.ask_user_max == 3


def test_tool_budget_can_call_and_spend():
    b = orchestrator.ToolBudget.for_mode("standard", member_role="member")
    assert b.can_call("web_search")
    b.spend("web_search", 1.0)
    assert b.tool_calls_used == 1
    assert b.sub_used.get("web_search", 0) == 1


def test_tool_budget_exhausted_when_total_reached():
    b = orchestrator.ToolBudget.for_mode("standard", member_role="member")
    for _ in range(3):
        b.spend("web_search", 1.0)
    assert b.exhausted()


def test_tool_budget_sub_cap_exhausts_for_that_tool_only():
    b = orchestrator.ToolBudget.for_mode("standard", member_role="member")
    b.spend("open_browser", 3.0)
    assert not b.can_call("open_browser")  # sub-cap of 1
    assert b.can_call("web_search")          # other tool still ok


from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from server.board.config import BoardMember
from server.board import llm, tools
from server.board.deliberation.orchestrator import (
    ToolBudget, agentic_member_turn,
)


def _make_member(member_id="strategist"):
    return BoardMember(
        id=member_id, title="Test", role="role",
        expertise=[], system_prompt="You are a tester.",
    )


async def test_agentic_turn_returns_content_when_no_tool_calls(monkeypatch):
    """If LLM returns content with no tool_calls, loop terminates immediately."""
    fake_response = llm.LLMResponse(
        content="Final analysis.",
        model="kimi/kimi-k2.6",
        input_tokens=10, output_tokens=5, latency_seconds=0.1,
        finish_reason="stop", tool_calls=[],
    )
    events: list = []
    with patch("server.board.deliberation.orchestrator.query_llm",
               AsyncMock(return_value=fake_response)):
        result = await agentic_member_turn(
            member=_make_member(),
            model="kimi/kimi-k2.6",
            system_prompt="You are a tester.",
            initial_user_message="Analyze X.",
            tools=[tools.TOOLS["web_search"]],
            budget=ToolBudget.for_mode("standard"),
            session=SimpleNamespace(),
            stage=1,
            on_event=events.append,
        )
    assert result.content == "Final analysis."
    assert result.tool_calls_made == 0
    assert not result.aborted


async def test_agentic_turn_executes_one_tool_call_then_returns(monkeypatch):
    call_responses = iter([
        llm.LLMResponse(
            content="", model="m", input_tokens=1, output_tokens=1,
            latency_seconds=0.1, finish_reason="tool_calls",
            tool_calls=[llm.ToolCall(
                id="tc_1", name="web_search",
                arguments={"query": "x"})],
        ),
        llm.LLMResponse(
            content="Done with results.", model="m",
            input_tokens=1, output_tokens=1, latency_seconds=0.1,
            finish_reason="stop", tool_calls=[],
        ),
    ])
    fake_query_llm = AsyncMock(side_effect=lambda *a, **kw: next(call_responses))
    fake_tool_result = tools.ToolResult(
        content_for_model="search results: X is 1", summary="ok", cost_units=1.0,
    )

    with patch("server.board.deliberation.orchestrator.query_llm", fake_query_llm), \
         patch("server.board.deliberation.orchestrator.execute_tool",
                AsyncMock(return_value=fake_tool_result)):
        result = await agentic_member_turn(
            member=_make_member(),
            model="kimi/kimi-k2.6",
            system_prompt="You are a tester.",
            initial_user_message="Analyze X.",
            tools=[tools.TOOLS["web_search"]],
            budget=ToolBudget.for_mode("standard"),
            session=SimpleNamespace(),
            stage=1,
            on_event=lambda e: None,
        )
    assert result.content == "Done with results."
    assert result.tool_calls_made == 1
    assert fake_query_llm.call_count == 2
