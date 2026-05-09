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
    """Phase 2: chairperson/secretary must run mode=fast even if chair routes 'deep'."""
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
            {"member_id": "chairperson", "mode": "deep",
             "focus": "x", "priority": 100},
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
            for member_id in ["strategist", "chairperson", "architect", "builder", "product"]:
                if "User query:" in content:
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
    # - chairperson should be forced to fast (not in UPGRADED_MEMBERS)
    assert result.routing.members[0].mode == "deep", "strategist should remain in deep mode"
    assert any(m.member_id == "chairperson" and m.mode == "fast"
               for m in result.routing.members)


async def test_live_research_processes_followup(monkeypatch, tmp_path):
    """A queued follow-up triggers re-invocation of the target member."""
    from server.board.deliberation.followup import FollowupBuffer, Followup

    proto = tmp_path / "chair_intake.md"
    proto.write_text("test")
    monkeypatch.setattr(intake_mod, "_PROTOCOL_PATH", str(proto))

    routing_json = json.dumps({
        "interpreted_query": "Q",
        "decision_type": "strategic", "complexity": "low",
        "importance": "routine", "rationale": "ok",
        "members": [{"member_id": "strategist", "mode": "fast",
                     "focus": "x", "priority": 90}],
        "script": "live_research", "deep_research_dossier": False,
    })
    intake_resp = llm.LLMResponse(
        content=routing_json, model="m", input_tokens=1, output_tokens=1,
        latency_seconds=0.1, finish_reason="stop", tool_calls=[],
    )
    member_resp = llm.LLMResponse(
        content="initial analysis", model="m",
        input_tokens=1, output_tokens=1, latency_seconds=0.1,
        finish_reason="stop", tool_calls=[],
    )
    revised_resp = llm.LLMResponse(
        content="revised analysis with follow-up", model="m",
        input_tokens=1, output_tokens=1, latency_seconds=0.1,
        finish_reason="stop", tool_calls=[],
    )
    brief_resp = llm.LLMResponse(
        content="brief v1", model="m", input_tokens=1, output_tokens=1,
        latency_seconds=0.1, finish_reason="stop", tool_calls=[],
    )
    brief_resp_v2 = llm.LLMResponse(
        content="brief v2 incorporating follow-up", model="m",
        input_tokens=1, output_tokens=1, latency_seconds=0.1,
        finish_reason="stop", tool_calls=[],
    )

    call_count = {"intake": 0, "member": 0, "brief": 0}
    async def fake_query(model, messages, **kw):
        # Detect intake by checking message content: intake sends the chair
        # protocol prompt which always references "routing" or "JSON" in the
        # user message, not a "User query:" structured member turn.
        user_content = " ".join(
            m.get("content", "") for m in messages if m.get("role") == "user"
        )
        sys_prompt = kw.get("system", "")
        # Secretary brief: system prompt contains "Board Secretary" or "Sources"
        if "Board Secretary" in sys_prompt or "Sources" in sys_prompt:
            call_count["brief"] += 1
            return brief_resp_v2 if call_count["brief"] >= 2 else brief_resp
        # Intake: the ask_user tool is present AND no "Continue your earlier" in user msg
        tools_kw = kw.get("tools") or []
        names = {t.get("function", {}).get("name") for t in tools_kw if isinstance(t, dict)}
        if "ask_user_clarifying_question" in names and "Continue your earlier" not in user_content:
            call_count["intake"] += 1
            return intake_resp
        # Member/revision call
        call_count["member"] += 1
        if call_count["member"] >= 2:  # second member call = revision
            return revised_resp
        return member_resp

    buf = FollowupBuffer()
    await buf.add(Followup(target="strategist",
                            text="search more on X", raw="strategist: search more on X"))

    with patch("server.board.deliberation.intake.query_llm",
               AsyncMock(side_effect=fake_query)), \
         patch("server.board.deliberation.orchestrator.query_llm",
                AsyncMock(side_effect=fake_query)), \
         patch("server.board.deliberation.live.query_llm",
                AsyncMock(side_effect=fake_query)):
        result = await live.run_live_research(
            query="Q", user_overrides=intake_mod.ChairOverrides(),
            followup_buffer=buf,
        )

    # The strategist's content should be the revised version
    assert result.member_responses["strategist"].content == "revised analysis with follow-up"
    # The secretary brief should be the v2
    assert "v2" in result.secretary_brief


async def test_secretary_brief_includes_sources_in_system_prompt(monkeypatch, tmp_path):
    """The secretary system prompt must mention the Sources section so the
    LLM produces it when members cite sources."""
    proto = tmp_path / "chair_intake.md"
    proto.write_text("test")
    monkeypatch.setattr(intake_mod, "_PROTOCOL_PATH", str(proto))

    routing_json = json.dumps({
        "interpreted_query": "Q",
        "decision_type": "strategic", "complexity": "low",
        "importance": "routine", "rationale": "ok",
        "members": [{"member_id": "strategist", "mode": "fast",
                     "focus": "x", "priority": 90}],
        "script": "live_research", "deep_research_dossier": False,
    })
    intake_resp = llm.LLMResponse(
        content=routing_json, model="m", input_tokens=1, output_tokens=1,
        latency_seconds=0.1, finish_reason="stop", tool_calls=[],
    )
    member_resp = llm.LLMResponse(
        content="my analysis", model="m", input_tokens=1, output_tokens=1,
        latency_seconds=0.1, finish_reason="stop", tool_calls=[],
    )
    brief_resp = llm.LLMResponse(
        content="brief", model="m", input_tokens=1, output_tokens=1,
        latency_seconds=0.1, finish_reason="stop", tool_calls=[],
    )

    captured_systems: list[str] = []
    async def fake_query(model, messages, **kw):
        if kw.get("tools"):
            return intake_resp if any(
                t.get("function", {}).get("name") == "ask_user_clarifying_question"
                for t in kw["tools"] if isinstance(t, dict)
            ) else member_resp
        # Capture system prompts on no-tool calls (member fast + secretary)
        sys_prompt = kw.get("system", "")
        captured_systems.append(sys_prompt or "")
        return brief_resp

    with patch("server.board.deliberation.intake.query_llm",
               AsyncMock(side_effect=fake_query)), \
         patch("server.board.deliberation.orchestrator.query_llm",
                AsyncMock(side_effect=fake_query)), \
         patch("server.board.deliberation.live.query_llm",
                AsyncMock(side_effect=fake_query)):
        await live.run_live_research(
            query="Q", user_overrides=intake_mod.ChairOverrides())

    # The secretary system prompt should mention Sources
    assert any("Sources" in s and "[source:" in s for s in captured_systems), \
        f"No system prompt mentions Sources extraction. Got: {captured_systems}"
