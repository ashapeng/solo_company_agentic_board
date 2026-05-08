"""Chair intake tests."""
from __future__ import annotations

from server.board.deliberation import intake


def test_routing_decision_dataclass_shape():
    rd = intake.RoutingDecision(
        interpreted_query="Q",
        decision_type="strategic", complexity="medium", importance="notable",
        rationale="why",
        members=[intake.MemberAssignment(
            member_id="strategist", mode="standard",
            focus="market", priority=90,
        )],
        script="live_research",
        deep_research_dossier=False,
    )
    assert rd.script == "live_research"
    assert rd.members[0].member_id == "strategist"


def test_default_routing_returns_valid_decision():
    rd = intake.DEFAULT_ROUTING(query="anything")
    assert rd.script == "live_research"
    assert rd.members
    assert all(m.mode in ("fast", "standard", "deep") for m in rd.members)


def test_parse_routing_decision_json_valid():
    raw = """
    {
      "interpreted_query": "Should we enter the X market?",
      "decision_type": "strategic",
      "complexity": "high",
      "importance": "critical",
      "rationale": "Market entry decision needs deep evidence.",
      "members": [
        {"member_id": "strategist", "mode": "deep", "focus": "TAM/SAM", "priority": 90},
        {"member_id": "researcher", "mode": "deep", "focus": "personas", "priority": 80}
      ],
      "script": "live_research",
      "deep_research_dossier": false
    }
    """
    rd = intake.parse_routing_decision(raw)
    assert rd.decision_type == "strategic"
    assert len(rd.members) == 2
    assert rd.members[0].mode == "deep"


def test_parse_routing_decision_malformed_returns_none():
    assert intake.parse_routing_decision("{not json") is None
    assert intake.parse_routing_decision("") is None
    assert intake.parse_routing_decision('{"missing": "fields"}') is None


import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from server.board import llm, tools
from server.board.deliberation import intake as intake_mod
from server.board.deliberation.orchestrator import ToolBudget


async def test_run_chair_intake_clear_query_routes_directly(monkeypatch, tmp_path):
    """A clear query produces a RoutingDecision without ask_user calls."""
    routing_json = json.dumps({
        "interpreted_query": "Should we enter market X?",
        "decision_type": "strategic", "complexity": "high",
        "importance": "critical", "rationale": "Critical market decision.",
        "members": [
            {"member_id": "strategist", "mode": "deep",
             "focus": "TAM", "priority": 90},
        ],
        "script": "live_research", "deep_research_dossier": False,
    })
    fake_response = llm.LLMResponse(
        content=routing_json, model="kimi/kimi-k2.6", input_tokens=10,
        output_tokens=20, latency_seconds=0.1, finish_reason="stop",
        tool_calls=[],
    )

    # Stub the protocol read
    proto = tmp_path / "chair_intake.md"
    proto.write_text("Chair intake test prompt")
    monkeypatch.setattr(intake_mod, "_PROTOCOL_PATH", str(proto))

    with patch("server.board.deliberation.intake.query_llm",
               AsyncMock(return_value=fake_response)):
        rd = await intake_mod.run_chair_intake(
            raw_query="Should we enter market X?",
            user_overrides=intake_mod.ChairOverrides(),
            session=SimpleNamespace(),
            on_event=lambda e: None,
            chair_model="kimi/kimi-k2.6",
        )
    assert rd is not None
    assert rd.decision_type == "strategic"
    assert rd.members[0].mode == "deep"


async def test_run_chair_intake_malformed_falls_back_to_default(monkeypatch, tmp_path):
    fake_response = llm.LLMResponse(
        content="this is not json at all",
        model="kimi/kimi-k2.6", input_tokens=10, output_tokens=20,
        latency_seconds=0.1, finish_reason="stop", tool_calls=[],
    )
    proto = tmp_path / "chair_intake.md"
    proto.write_text("Chair intake test prompt")
    monkeypatch.setattr(intake_mod, "_PROTOCOL_PATH", str(proto))
    with patch("server.board.deliberation.intake.query_llm",
               AsyncMock(return_value=fake_response)):
        rd = await intake_mod.run_chair_intake(
            raw_query="Q",
            user_overrides=intake_mod.ChairOverrides(),
            session=SimpleNamespace(),
            on_event=lambda e: None,
            chair_model="kimi/kimi-k2.6",
        )
    assert rd.script == "live_research"
    assert any(m.member_id == "strategist" for m in rd.members)


async def test_run_chair_intake_skip_intake_uses_default_routing(monkeypatch, tmp_path):
    """When ChairOverrides.intake=False, skip intake and use DEFAULT_ROUTING."""
    proto = tmp_path / "chair_intake.md"
    proto.write_text("test")
    monkeypatch.setattr(intake_mod, "_PROTOCOL_PATH", str(proto))
    overrides = intake_mod.ChairOverrides(intake=False)
    # Confirm query_llm is NOT called when intake=False
    fake_query = AsyncMock()
    with patch("server.board.deliberation.intake.query_llm", fake_query):
        rd = await intake_mod.run_chair_intake(
            raw_query="Q",
            user_overrides=overrides,
            session=SimpleNamespace(),
            on_event=lambda e: None,
            chair_model="kimi/kimi-k2.6",
        )
    assert fake_query.call_count == 0
    assert rd.script == "live_research"


async def test_run_chair_intake_depth_override_applied(monkeypatch, tmp_path):
    """ChairOverrides.depth overrides the chair's mode for all members."""
    routing_json = json.dumps({
        "interpreted_query": "Q",
        "decision_type": "strategic", "complexity": "low",
        "importance": "routine", "rationale": "ok",
        "members": [
            {"member_id": "strategist", "mode": "fast",
             "focus": "x", "priority": 90},
            {"member_id": "researcher", "mode": "fast",
             "focus": "y", "priority": 80},
        ],
        "script": "live_research", "deep_research_dossier": False,
    })
    fake_response = llm.LLMResponse(
        content=routing_json, model="kimi/kimi-k2.6", input_tokens=10,
        output_tokens=20, latency_seconds=0.1, finish_reason="stop",
        tool_calls=[],
    )
    proto = tmp_path / "chair_intake.md"
    proto.write_text("test")
    monkeypatch.setattr(intake_mod, "_PROTOCOL_PATH", str(proto))
    with patch("server.board.deliberation.intake.query_llm",
               AsyncMock(return_value=fake_response)):
        rd = await intake_mod.run_chair_intake(
            raw_query="Q",
            user_overrides=intake_mod.ChairOverrides(depth="deep"),
            session=SimpleNamespace(),
            on_event=lambda e: None,
            chair_model="kimi/kimi-k2.6",
        )
    # All members should now be 'deep' even though chair routed 'fast'
    assert all(m.mode == "deep" for m in rd.members)
