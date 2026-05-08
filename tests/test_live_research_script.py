"""Live `live_research` script integration tests."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from server.board import llm
from server.board.deliberation import live, intake as intake_mod


async def test_live_research_runs_intake_then_first_round(monkeypatch, tmp_path):
    """Smoke: live_research script invokes chair intake, then runs assigned members."""
    proto = tmp_path / "chair_intake.md"
    proto.write_text("test")
    monkeypatch.setattr(intake_mod, "_PROTOCOL_PATH", str(proto))

    routing_json = json.dumps({
        "interpreted_query": "Q",
        "decision_type": "strategic", "complexity": "medium",
        "importance": "notable", "rationale": "ok",
        "members": [
            {"member_id": "strategist", "mode": "standard",
             "focus": "x", "priority": 90},
            {"member_id": "researcher", "mode": "standard",
             "focus": "y", "priority": 80},
        ],
        "script": "live_research", "deep_research_dossier": False,
    })
    intake_resp = llm.LLMResponse(
        content=routing_json, model="m", input_tokens=1, output_tokens=1,
        latency_seconds=0.1, finish_reason="stop", tool_calls=[],
    )
    member_resp = llm.LLMResponse(
        content="strategist analysis here", model="m",
        input_tokens=1, output_tokens=1, latency_seconds=0.1,
        finish_reason="stop", tool_calls=[],
    )
    brief_resp = llm.LLMResponse(
        content="## Agreements\n- ok", model="m",
        input_tokens=1, output_tokens=1, latency_seconds=0.1,
        finish_reason="stop", tool_calls=[],
    )

    call_log: list[tuple[str, ...]] = []
    async def fake_query(model, messages, **kw):
        # Detect intake by tools list including ask_user
        tools_kw = kw.get("tools") or []
        names = {t.get("function", {}).get("name") for t in tools_kw if isinstance(t, dict)}
        if "ask_user_clarifying_question" in names:
            call_log.append(("intake",))
            return intake_resp
        # Detect secretary brief by absence of tools
        if not tools_kw:
            # Could be a member in fast mode OR the secretary brief
            # We use a counter: secretary fires last
            call_log.append(("notool", model))
            # Return brief or member based on call order
            if len([c for c in call_log if c[0] == "notool"]) >= 3:
                return brief_resp
            return member_resp
        call_log.append(("member", model))
        return member_resp

    with patch("server.board.deliberation.intake.query_llm",
               AsyncMock(side_effect=fake_query)), \
         patch("server.board.deliberation.orchestrator.query_llm",
                AsyncMock(side_effect=fake_query)), \
         patch("server.board.deliberation.live.query_llm",
                AsyncMock(side_effect=fake_query), create=True):
        result = await live.run_live_research(
            query="Q",
            user_overrides=intake_mod.ChairOverrides(),
        )
    assert "strategist" in result.member_responses
    assert "researcher" in result.member_responses
    # intake fired first
    assert call_log[0] == ("intake",)


async def test_live_research_forces_non_upgraded_members_to_fast(monkeypatch, tmp_path):
    """Phase 1: critic/architect/etc. must run mode=fast even if chair routes 'deep'."""
    proto = tmp_path / "chair_intake.md"
    proto.write_text("test")
    monkeypatch.setattr(intake_mod, "_PROTOCOL_PATH", str(proto))

    routing_json = json.dumps({
        "interpreted_query": "Q",
        "decision_type": "strategic", "complexity": "high",
        "importance": "critical", "rationale": "deep all",
        "members": [
            {"member_id": "strategist", "mode": "deep",
             "focus": "x", "priority": 90},
            {"member_id": "critic",     "mode": "deep",
             "focus": "x", "priority": 75},
        ],
        "script": "live_research", "deep_research_dossier": False,
    })
    intake_resp = llm.LLMResponse(
        content=routing_json, model="m", input_tokens=1, output_tokens=1,
        latency_seconds=0.1, finish_reason="stop", tool_calls=[],
    )
    member_resp = llm.LLMResponse(
        content="x analysis", model="m", input_tokens=1, output_tokens=1,
        latency_seconds=0.1, finish_reason="stop", tool_calls=[],
    )
    brief_resp = llm.LLMResponse(
        content="brief", model="m", input_tokens=1, output_tokens=1,
        latency_seconds=0.1, finish_reason="stop", tool_calls=[],
    )

    captured_by_member: dict[str, list | None] = {}
    async def fake_query(model, messages, **kw):
        tools_kw = kw.get("tools") or None
        names = set()
        if tools_kw:
            names = {t.get("function", {}).get("name") for t in tools_kw if isinstance(t, dict)}
        if "ask_user_clarifying_question" in names:
            return intake_resp
        # Extract which member this is for (if in the user message)
        for msg in messages:
            content = msg.get("content", "")
            for member_id in ["strategist", "critic", "architect", "builder", "product"]:
                if f"User query:" in content:
                    # This is a member turn; capture which one + tools status
                    if member_id not in captured_by_member:
                        captured_by_member[member_id] = tools_kw
                    break
        return member_resp if tools_kw else member_resp if len(captured_by_member) <= 2 else brief_resp

    with patch("server.board.deliberation.intake.query_llm",
               AsyncMock(side_effect=fake_query)), \
         patch("server.board.deliberation.orchestrator.query_llm",
                AsyncMock(side_effect=fake_query)), \
         patch("server.board.deliberation.live.query_llm",
                AsyncMock(side_effect=fake_query)):
        result = await live.run_live_research(
            query="Q", user_overrides=intake_mod.ChairOverrides())
    # Verify final routing reflects the override:
    # - strategist should keep deep (upgraded)
    # - critic should be forced to fast (not upgraded)
    assert result.routing.members[0].mode == "deep", "strategist should remain in deep mode"
    critic_member = [m for m in result.routing.members if m.member_id == "critic"]
    assert len(critic_member) == 1, "critic should be in routing"
    assert critic_member[0].mode == "fast", f"critic should be forced to fast, got {critic_member[0].mode}"
