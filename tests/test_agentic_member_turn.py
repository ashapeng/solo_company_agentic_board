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
