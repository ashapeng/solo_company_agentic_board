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


async def test_agentic_turn_force_finishes_on_budget_exhaustion(monkeypatch):
    """When budget is exhausted mid-loop, the loop forces a final analysis."""
    tool_call_resp = llm.LLMResponse(
        content="", model="m", input_tokens=1, output_tokens=1, latency_seconds=0.1,
        finish_reason="tool_calls",
        tool_calls=[llm.ToolCall(id="tc", name="web_search",
                                  arguments={"query": "x"})],
    )
    final_resp = llm.LLMResponse(
        content="Forced final: budget spent, [UNRESOLVED] remains.",
        model="m", input_tokens=1, output_tokens=1, latency_seconds=0.1,
        finish_reason="stop", tool_calls=[],
    )

    captured_kwargs: list[dict] = []

    async def _spy_query(*args, **kwargs):
        captured_kwargs.append(kwargs)
        # First call: tool_call response. Second call: final.
        if len(captured_kwargs) == 1:
            return tool_call_resp
        return final_resp

    fake_tool_result = tools.ToolResult(
        content_for_model="ok", summary="ok", cost_units=1.0,
    )
    budget = ToolBudget(
        tool_calls_max=1, wall_seconds_max=300, per_call_timeout=240.0,
        open_browser_max=1, web_search_max=1, fetch_url_max=1, ask_user_max=0,
    )
    with patch("server.board.deliberation.orchestrator.query_llm",
               AsyncMock(side_effect=_spy_query)), \
         patch("server.board.deliberation.orchestrator.execute_tool",
                AsyncMock(return_value=fake_tool_result)):
        result = await agentic_member_turn(
            member=_make_member(), model="m",
            system_prompt="x", initial_user_message="x",
            tools=[tools.TOOLS["web_search"]],
            budget=budget,
            session=SimpleNamespace(), stage=1, on_event=lambda e: None,
        )
    assert "Forced final" in result.content
    # Second call must have tool_choice="none" and tools=None
    assert captured_kwargs[-1].get("tool_choice") == "none"
    assert captured_kwargs[-1].get("tools") is None


async def test_force_finish_appends_final_analysis_instruction(monkeypatch):
    """When budget is exhausted, the loop appends an explicit instruction
    telling the model to write final analysis (not emit tool markup)."""
    tool_call_resp = llm.LLMResponse(
        content="", model="m", input_tokens=1, output_tokens=1, latency_seconds=0.1,
        finish_reason="tool_calls",
        tool_calls=[llm.ToolCall(id="tc", name="web_search",
                                  arguments={"query": "x"})],
    )
    final_resp = llm.LLMResponse(
        content="Real final analysis.", model="m",
        input_tokens=1, output_tokens=1, latency_seconds=0.1,
        finish_reason="stop", tool_calls=[],
    )

    captured_messages: list[list] = []
    responses = iter([tool_call_resp, final_resp])

    async def _spy_query(*args, **kwargs):
        captured_messages.append(list(args[1]) if len(args) > 1 else list(kwargs.get("messages", [])))
        return next(responses)

    fake_tool_result = tools.ToolResult(
        content_for_model="ok", summary="ok", cost_units=1.0,
    )
    budget = ToolBudget(
        tool_calls_max=1, wall_seconds_max=300, per_call_timeout=240.0,
        open_browser_max=1, web_search_max=1, fetch_url_max=1, ask_user_max=0,
    )
    with patch("server.board.deliberation.orchestrator.query_llm",
               AsyncMock(side_effect=_spy_query)), \
         patch("server.board.deliberation.orchestrator.execute_tool",
                AsyncMock(return_value=fake_tool_result)):
        result = await agentic_member_turn(
            member=_make_member(), model="m",
            system_prompt="x", initial_user_message="x",
            tools=[tools.TOOLS["web_search"]],
            budget=budget,
            session=SimpleNamespace(), stage=1, on_event=lambda e: None,
        )
    assert result.content == "Real final analysis."
    # The SECOND call's messages must include the final-analysis instruction.
    second_call_msgs = captured_messages[1]
    final_instruction_msgs = [
        m for m in second_call_msgs
        if m.get("role") == "user" and "FINAL ANALYSIS" in (m.get("content") or "")
    ]
    assert len(final_instruction_msgs) == 1
    assert "no XML" in final_instruction_msgs[0]["content"].lower() or \
           "no xml" in final_instruction_msgs[0]["content"].lower() or \
           "DSML" in final_instruction_msgs[0]["content"]


# --- P3b: forced-revision loop on CONTRADICTED tool results -----------------


async def test_contradicted_tool_result_injects_forced_revision_turn(monkeypatch):
    """When validate_claim returns CONTRADICTED, the next LLM call must see
    the forced revision turn in its messages (spec section 7.2.1)."""
    tool_call_resp = llm.LLMResponse(
        content="", model="m", input_tokens=1, output_tokens=1, latency_seconds=0.1,
        finish_reason="tool_calls",
        tool_calls=[llm.ToolCall(id="tc_1", name="validate_claim",
                                  arguments={"claim": "YC W26 had 600 startups"})],
    )
    final_resp = llm.LLMResponse(
        content="I drop the YC 600 claim; insufficient evidence.",
        model="m", input_tokens=1, output_tokens=1, latency_seconds=0.1,
        finish_reason="stop", tool_calls=[],
    )
    captured_messages: list[list] = []
    responses = iter([tool_call_resp, final_resp])

    async def _spy_query(*args, **kwargs):
        captured_messages.append(list(args[1]) if len(args) > 1 else list(kwargs.get("messages", [])))
        return next(responses)

    fake_tool_result = tools.ToolResult(
        content_for_model="validate_claim('YC W26 had 600 startups'):\n"
                          "VERDICT: CONTRADICTED\nRATIONALE: YC blog says 244.",
        summary="validate_claim: CONTRADICTED",
        cost_units=2.0,
    )

    with patch("server.board.deliberation.orchestrator.query_llm",
               AsyncMock(side_effect=_spy_query)), \
         patch("server.board.deliberation.orchestrator.execute_tool",
                AsyncMock(return_value=fake_tool_result)):
        result = await agentic_member_turn(
            member=_make_member(), model="m",
            system_prompt="x", initial_user_message="x",
            tools=[tools.TOOLS["validate_claim"]],
            budget=ToolBudget.for_mode("standard"),
            session=SimpleNamespace(), stage=1, on_event=lambda e: None,
        )

    assert "drop the YC 600 claim" in result.content
    # The SECOND call's messages must include the FORCED REVISION user turn.
    second_call_msgs = captured_messages[1]
    forced_turns = [
        m for m in second_call_msgs
        if m.get("role") == "user" and "FORCED REVISION" in (m.get("content") or "")
    ]
    assert len(forced_turns) == 1
    # Body must surface the tool name, summary, and rationale snippet.
    body = forced_turns[0]["content"]
    assert "validate_claim" in body
    assert "validate_claim: CONTRADICTED" in body
    assert "YC blog says 244" in body
    # Ordering contract: the tool result must land BEFORE its forced-revision
    # turn so the model first sees the verdict, then the directive.
    tool_msgs = [m for m in second_call_msgs if m.get("role") == "tool"]
    assert tool_msgs, "expected the tool result to be in the second call's messages"
    assert second_call_msgs.index(forced_turns[0]) > second_call_msgs.index(tool_msgs[-1])


async def test_supported_tool_result_does_not_inject_forced_revision(monkeypatch):
    """A SUPPORTED verdict must NOT inject a forced revision turn --
    otherwise the loop would over-fire on every validate_claim call."""
    tool_call_resp = llm.LLMResponse(
        content="", model="m", input_tokens=1, output_tokens=1, latency_seconds=0.1,
        finish_reason="tool_calls",
        tool_calls=[llm.ToolCall(id="tc_1", name="validate_claim",
                                  arguments={"claim": "x"})],
    )
    final_resp = llm.LLMResponse(
        content="Claim is supported; carrying on.",
        model="m", input_tokens=1, output_tokens=1, latency_seconds=0.1,
        finish_reason="stop", tool_calls=[],
    )
    captured_messages: list[list] = []
    responses = iter([tool_call_resp, final_resp])

    async def _spy_query(*args, **kwargs):
        captured_messages.append(list(args[1]) if len(args) > 1 else list(kwargs.get("messages", [])))
        return next(responses)

    fake_tool_result = tools.ToolResult(
        content_for_model="validate_claim('x'): VERDICT: SUPPORTED",
        summary="validate_claim: SUPPORTED",
        cost_units=2.0,
    )

    with patch("server.board.deliberation.orchestrator.query_llm",
               AsyncMock(side_effect=_spy_query)), \
         patch("server.board.deliberation.orchestrator.execute_tool",
                AsyncMock(return_value=fake_tool_result)):
        await agentic_member_turn(
            member=_make_member(), model="m",
            system_prompt="x", initial_user_message="x",
            tools=[tools.TOOLS["validate_claim"]],
            budget=ToolBudget.for_mode("standard"),
            session=SimpleNamespace(), stage=1, on_event=lambda e: None,
        )

    second_call_msgs = captured_messages[1]
    forced_turns = [
        m for m in second_call_msgs
        if m.get("role") == "user" and "FORCED REVISION" in (m.get("content") or "")
    ]
    assert len(forced_turns) == 0


async def test_forced_revision_cap_enforced(monkeypatch, caplog):
    """After `max_forced_revisions_per_member` CONTRADICTEDs in a single
    member turn, further CONTRADICTEDs do NOT inject another forced turn --
    instead a logger.warning is emitted (spec section 7.2.3 + Refinement R5)."""
    import logging
    from server.harness.config import HarnessConfig, get_config

    # Issue: 3 tool calls all returning CONTRADICTED, with cap=2 -> only 2 forced turns.
    tc_resp = lambda i: llm.LLMResponse(
        content="", model="m", input_tokens=1, output_tokens=1, latency_seconds=0.1,
        finish_reason="tool_calls",
        tool_calls=[llm.ToolCall(id=f"tc_{i}", name="validate_claim",
                                  arguments={"claim": f"claim {i}"})],
    )
    final = llm.LLMResponse(
        content="Final.", model="m", input_tokens=1, output_tokens=1,
        latency_seconds=0.1, finish_reason="stop", tool_calls=[],
    )
    captured_messages: list[list] = []
    responses = iter([tc_resp(1), tc_resp(2), tc_resp(3), final])

    async def _spy_query(*args, **kwargs):
        captured_messages.append(list(args[1]) if len(args) > 1 else list(kwargs.get("messages", [])))
        return next(responses)

    contra_result = tools.ToolResult(
        content_for_model="validate_claim('x'): VERDICT: CONTRADICTED\nRATIONALE: bad.",
        summary="validate_claim: CONTRADICTED",
        cost_units=2.0,
    )

    # Force cap = 2 (matches default but pin explicitly so the test is robust
    # to future default changes).
    fake_cfg = HarnessConfig()
    fake_cfg.hardening = dict(fake_cfg.hardening)
    fake_cfg.hardening["max_forced_revisions_per_member"] = 2

    # Budget allows 4 tool calls so the cap (not the budget) is the gating
    # factor for forced-revision injection.
    budget = ToolBudget(
        tool_calls_max=4, wall_seconds_max=300, per_call_timeout=240.0,
        open_browser_max=0, web_search_max=0, fetch_url_max=0, ask_user_max=0,
    )

    get_config.cache_clear()
    caplog.set_level(logging.WARNING, logger="server.board.deliberation.orchestrator")
    try:
        with patch("server.harness.config.load_config", return_value=fake_cfg), \
             patch("server.board.deliberation.orchestrator.query_llm",
                   AsyncMock(side_effect=_spy_query)), \
             patch("server.board.deliberation.orchestrator.execute_tool",
                   AsyncMock(return_value=contra_result)):
            await agentic_member_turn(
                member=_make_member(), model="m",
                system_prompt="x", initial_user_message="x",
                tools=[tools.TOOLS["validate_claim"]],
                budget=budget,
                session=SimpleNamespace(), stage=1, on_event=lambda e: None,
            )
    finally:
        get_config.cache_clear()

    # Count FORCED REVISION turns that landed in the FINAL LLM call's messages.
    final_call_msgs = captured_messages[-1]
    forced_turns = [
        m for m in final_call_msgs
        if m.get("role") == "user" and "FORCED REVISION" in (m.get("content") or "")
    ]
    assert len(forced_turns) == 2, (
        f"expected exactly 2 forced revisions under cap=2, got {len(forced_turns)}"
    )
    # The 3rd CONTRADICTED must have emitted a stuck-member warning.
    stuck_warnings = [
        rec for rec in caplog.records
        if rec.levelno == logging.WARNING and "stuck" in rec.getMessage().lower()
    ]
    assert len(stuck_warnings) >= 1, (
        f"expected at least one stuck-member warning; got records: "
        f"{[r.getMessage() for r in caplog.records]}"
    )


async def test_forced_revision_cap_configurable(monkeypatch):
    """When the cap is set to 1, only the first CONTRADICTED triggers a
    forced revision; the second is logged but not injected."""
    from server.harness.config import HarnessConfig, get_config

    tc_resp = lambda i: llm.LLMResponse(
        content="", model="m", input_tokens=1, output_tokens=1, latency_seconds=0.1,
        finish_reason="tool_calls",
        tool_calls=[llm.ToolCall(id=f"tc_{i}", name="validate_claim",
                                  arguments={"claim": f"c{i}"})],
    )
    final = llm.LLMResponse(
        content="Final.", model="m", input_tokens=1, output_tokens=1,
        latency_seconds=0.1, finish_reason="stop", tool_calls=[],
    )
    captured_messages: list[list] = []
    responses = iter([tc_resp(1), tc_resp(2), final])

    async def _spy_query(*args, **kwargs):
        captured_messages.append(list(args[1]) if len(args) > 1 else list(kwargs.get("messages", [])))
        return next(responses)

    contra_result = tools.ToolResult(
        content_for_model="validate_claim('x'): VERDICT: CONTRADICTED",
        summary="validate_claim: CONTRADICTED",
        cost_units=2.0,
    )

    fake_cfg = HarnessConfig()
    fake_cfg.hardening = dict(fake_cfg.hardening)
    fake_cfg.hardening["max_forced_revisions_per_member"] = 1

    budget = ToolBudget(
        tool_calls_max=3, wall_seconds_max=300, per_call_timeout=240.0,
        open_browser_max=0, web_search_max=0, fetch_url_max=0, ask_user_max=0,
    )

    get_config.cache_clear()
    try:
        with patch("server.harness.config.load_config", return_value=fake_cfg), \
             patch("server.board.deliberation.orchestrator.query_llm",
                   AsyncMock(side_effect=_spy_query)), \
             patch("server.board.deliberation.orchestrator.execute_tool",
                   AsyncMock(return_value=contra_result)):
            await agentic_member_turn(
                member=_make_member(), model="m",
                system_prompt="x", initial_user_message="x",
                tools=[tools.TOOLS["validate_claim"]],
                budget=budget,
                session=SimpleNamespace(), stage=1, on_event=lambda e: None,
            )
    finally:
        get_config.cache_clear()

    final_call_msgs = captured_messages[-1]
    forced_turns = [
        m for m in final_call_msgs
        if m.get("role") == "user" and "FORCED REVISION" in (m.get("content") or "")
    ]
    assert len(forced_turns) == 1


# ─── Tool-call persistence helpers ──────────────────────────────────────────

from server.board.deliberation.orchestrator import _parse_tool_verdict


def test_parse_tool_verdict_supported():
    content = "validate_claim('x'):\nVERDICT: SUPPORTED\nRATIONALE: confirmed."
    assert _parse_tool_verdict("validate_claim", content) == "SUPPORTED"


def test_parse_tool_verdict_contradicted():
    content = "validate_claim('x'):\nVERDICT: CONTRADICTED\nRATIONALE: refuted."
    assert _parse_tool_verdict("validate_claim", content) == "CONTRADICTED"


def test_parse_tool_verdict_unverified():
    content = "validate_claim('x'):\nVERDICT: UNVERIFIED\nRATIONALE: thin."
    assert _parse_tool_verdict("validate_claim", content) == "UNVERIFIED"


def test_parse_tool_verdict_returns_literal_judge_verdict_even_when_downgrade_appended():
    """The P3a downgrade appends `[SOURCE-AUTHORITY DOWNGRADE]` to the body.
    The verdict line itself still says SUPPORTED (the judge's word). The
    canonical post-downgrade verdict lives on ToolResult.summary; the record
    builder (`_make_tool_call_record`) reads both and prefers the summary."""
    content = (
        "validate_claim('x'):\nVERDICT: SUPPORTED\nRATIONALE: ok\n"
        "\n[SOURCE-AUTHORITY DOWNGRADE] insufficient source authority. "
        "Verdict downgraded to UNVERIFIED."
    )
    assert _parse_tool_verdict("validate_claim", content) == "SUPPORTED"


def test_parse_tool_verdict_returns_none_when_no_verdict_line():
    """No 'VERDICT:' substring → None (caller stores None on the record)."""
    assert _parse_tool_verdict("validate_claim", "some other text") is None
    assert _parse_tool_verdict("validate_claim", "") is None


def test_parse_tool_verdict_returns_none_for_non_validate_claim_tool():
    """web_search, fetch_url, etc. don't emit verdicts. Parser returns None."""
    assert _parse_tool_verdict("web_search", "VERDICT: SUPPORTED") is None
    assert _parse_tool_verdict("fetch_url", "VERDICT: CONTRADICTED") is None
    assert _parse_tool_verdict("open_browser", "anything") is None
    assert _parse_tool_verdict("ask_user_clarifying_question", "anything") is None


def test_parse_tool_verdict_is_case_insensitive():
    """Mirror _handle_validate_claim's convention (which also .upper()s before
    substring match) so the persisted record's verdict never disagrees with
    the tool's own parsing path."""
    assert _parse_tool_verdict("validate_claim", "verdict: supported") == "SUPPORTED"
    assert _parse_tool_verdict("validate_claim", "Verdict: ContraDicted") == "CONTRADICTED"


from server.board.deliberation.orchestrator import _make_tool_call_record


def test_make_tool_call_record_full_shape_for_validate_claim():
    """The record shape pins the contract for downstream consumers
    (evals/signals.py reads these keys by name)."""
    member = _make_member("strategist")
    tc = llm.ToolCall(
        id="tc_42",
        name="validate_claim",
        arguments={"claim": "average AI demo→paid conversion is 8%"},
    )
    result = tools.ToolResult(
        content_for_model=(
            "validate_claim('average AI demo→paid conversion is 8%'):\n"
            "VERDICT: UNVERIFIED\nRATIONALE: thin sources."
        ),
        summary="validate_claim: UNVERIFIED",
        cost_units=2.0,
    )
    rec = _make_tool_call_record(member, stage=1, tool_call=tc,
                                  tool_result=result, elapsed_seconds=1.42)
    assert rec["member_id"] == "strategist"
    assert rec["stage"] == 1
    assert rec["tool_name"] == "validate_claim"
    assert rec["tool_call_id"] == "tc_42"
    assert rec["arguments"] == {"claim": "average AI demo→paid conversion is 8%"}
    assert rec["summary"] == "validate_claim: UNVERIFIED"
    assert rec["content_for_model"].startswith("validate_claim(")
    assert rec["verdict"] == "UNVERIFIED"
    assert rec["error"] is None
    assert rec["elapsed_seconds"] == 1.42
    assert "T" in rec["timestamp"]
    assert rec["timestamp"].endswith("+00:00")


def test_make_tool_call_record_uses_summary_verdict_when_downgrade_present():
    """When P3a downgrades SUPPORTED → UNVERIFIED, the body keeps the
    judge's literal 'VERDICT: SUPPORTED' line but the summary reflects the
    canonical post-downgrade verdict. The record's `verdict` field MUST
    match the summary (downstream consumer reads this as the verdict)."""
    member = _make_member()
    tc = llm.ToolCall(id="tc", name="validate_claim",
                      arguments={"claim": "trap claim"})
    result = tools.ToolResult(
        content_for_model=(
            "validate_claim('trap claim'):\nVERDICT: SUPPORTED\nRATIONALE: ok\n"
            "\n[SOURCE-AUTHORITY DOWNGRADE] insufficient source authority. "
            "Verdict downgraded to UNVERIFIED."
        ),
        summary="validate_claim: UNVERIFIED",
        cost_units=2.0,
    )
    rec = _make_tool_call_record(member, stage=1, tool_call=tc,
                                  tool_result=result, elapsed_seconds=0.5)
    assert rec["verdict"] == "UNVERIFIED"


def test_make_tool_call_record_verdict_none_for_non_validate_claim():
    member = _make_member()
    tc = llm.ToolCall(id="tc", name="web_search",
                      arguments={"query": "x"})
    result = tools.ToolResult(
        content_for_model="web_search('x') results:\n1. Foo\n2. Bar",
        summary="web_search 'x' → 2 results",
        cost_units=1.0,
    )
    rec = _make_tool_call_record(member, stage=2, tool_call=tc,
                                  tool_result=result, elapsed_seconds=0.3)
    assert rec["tool_name"] == "web_search"
    assert rec["verdict"] is None
    assert rec["arguments"] == {"query": "x"}


def test_make_tool_call_record_propagates_error_field():
    """When the tool returned an error, the record's error field carries it."""
    member = _make_member()
    tc = llm.ToolCall(id="tc", name="fetch_url",
                      arguments={"url": "https://blocked.example/x"})
    result = tools.ToolResult(
        content_for_model="fetch_url: blocked URL",
        summary="fetch_url blocked",
        cost_units=0.0,
        error="blocked URL (SSRF guard)",
    )
    rec = _make_tool_call_record(member, stage=1, tool_call=tc,
                                  tool_result=result, elapsed_seconds=0.01)
    assert rec["error"] == "blocked URL (SSRF guard)"


# --- agentic_member_turn → session.tool_call_results persistence -------------


async def test_agentic_turn_persists_tool_call_to_session(monkeypatch):
    """When session has tool_call_results, every tool call is appended."""
    from server.board.deliberation.orchestrator import BoardSession

    call_responses = iter([
        llm.LLMResponse(
            content="", model="m", input_tokens=1, output_tokens=1,
            latency_seconds=0.1, finish_reason="tool_calls",
            tool_calls=[llm.ToolCall(
                id="tc_v", name="validate_claim",
                arguments={"claim": "the conversion rate for AI demos is 8%"})],
        ),
        llm.LLMResponse(
            content="Wrapped up.", model="m",
            input_tokens=1, output_tokens=1, latency_seconds=0.1,
            finish_reason="stop", tool_calls=[],
        ),
    ])
    fake_query_llm = AsyncMock(side_effect=lambda *a, **kw: next(call_responses))
    # Simulate the post-P3a downgrade: judge said SUPPORTED, summary says
    # UNVERIFIED, body carries the [SOURCE-AUTHORITY DOWNGRADE] note.
    fake_tool_result = tools.ToolResult(
        content_for_model=(
            "validate_claim('the conversion rate for AI demos is 8%'):\n"
            "VERDICT: SUPPORTED\nRATIONALE: blogs say so.\n"
            "\n[SOURCE-AUTHORITY DOWNGRADE] insufficient source authority — "
            "found 3 unknown; need ≥1 academic OR ≥2 major_news OR ≥3 established_blog. "
            "Verdict downgraded to UNVERIFIED."
        ),
        summary="validate_claim: UNVERIFIED",
        cost_units=2.0,
    )

    session = BoardSession(session_id="board_test", user_query="x")

    with patch("server.board.deliberation.orchestrator.query_llm", fake_query_llm), \
         patch("server.board.deliberation.orchestrator.execute_tool",
                AsyncMock(return_value=fake_tool_result)):
        await agentic_member_turn(
            member=_make_member("strategist"),
            model="kimi/kimi-k2.6",
            system_prompt="x",
            initial_user_message="Analyze AI demo conversion.",
            tools=[tools.TOOLS["validate_claim"]],
            budget=ToolBudget.for_mode("standard"),
            session=session,
            stage=1,
            on_event=lambda e: None,
        )

    assert len(session.tool_call_results) == 1
    rec = session.tool_call_results[0]
    assert rec["member_id"] == "strategist"
    assert rec["stage"] == 1
    assert rec["tool_name"] == "validate_claim"
    assert rec["tool_call_id"] == "tc_v"
    assert rec["arguments"] == {"claim": "the conversion rate for AI demos is 8%"}
    # Canonical post-downgrade verdict from summary, not the judge's literal line.
    assert rec["verdict"] == "UNVERIFIED"
    assert rec["error"] is None


async def test_agentic_turn_does_not_crash_when_session_lacks_field(monkeypatch):
    """Back-compat: SimpleNamespace session (used by every other test in
    this file) has no tool_call_results attribute. The hook must guard
    with hasattr and skip silently."""
    fake_response = llm.LLMResponse(
        content="", model="m", input_tokens=1, output_tokens=1,
        latency_seconds=0.1, finish_reason="tool_calls",
        tool_calls=[llm.ToolCall(id="tc", name="web_search",
                                  arguments={"query": "x"})],
    )
    final_response = llm.LLMResponse(
        content="Done.", model="m", input_tokens=1, output_tokens=1,
        latency_seconds=0.1, finish_reason="stop", tool_calls=[],
    )
    fake_query_llm = AsyncMock(side_effect=[fake_response, final_response])
    fake_tool_result = tools.ToolResult(
        content_for_model="ok", summary="ok", cost_units=1.0,
    )
    bare_session = SimpleNamespace()  # NO tool_call_results attr
    with patch("server.board.deliberation.orchestrator.query_llm", fake_query_llm), \
         patch("server.board.deliberation.orchestrator.execute_tool",
                AsyncMock(return_value=fake_tool_result)):
        result = await agentic_member_turn(
            member=_make_member(),
            model="m",
            system_prompt="x",
            initial_user_message="x",
            tools=[tools.TOOLS["web_search"]],
            budget=ToolBudget.for_mode("standard"),
            session=bare_session,
            stage=1,
            on_event=lambda e: None,
        )
    # Loop completed normally.
    assert result.content == "Done."
    # Session was never mutated with a new attribute.
    assert not hasattr(bare_session, "tool_call_results")


async def test_agentic_turn_persists_multiple_tool_calls_in_order(monkeypatch):
    """Multiple tool calls across multiple LLM turns each get one record,
    preserved in call order."""
    from server.board.deliberation.orchestrator import BoardSession

    # Turn 1: one validate_claim. Turn 2: one web_search. Turn 3: final.
    responses = iter([
        llm.LLMResponse(
            content="", model="m", input_tokens=1, output_tokens=1,
            latency_seconds=0.1, finish_reason="tool_calls",
            tool_calls=[llm.ToolCall(id="tc_1", name="validate_claim",
                                      arguments={"claim": "claim A"})],
        ),
        llm.LLMResponse(
            content="", model="m", input_tokens=1, output_tokens=1,
            latency_seconds=0.1, finish_reason="tool_calls",
            tool_calls=[llm.ToolCall(id="tc_2", name="web_search",
                                      arguments={"query": "follow-up"})],
        ),
        llm.LLMResponse(
            content="Final.", model="m", input_tokens=1, output_tokens=1,
            latency_seconds=0.1, finish_reason="stop", tool_calls=[],
        ),
    ])

    tool_results = iter([
        tools.ToolResult(
            content_for_model="validate_claim('claim A'):\nVERDICT: SUPPORTED",
            summary="validate_claim: SUPPORTED", cost_units=2.0,
        ),
        tools.ToolResult(
            content_for_model="web_search('follow-up') results: ...",
            summary="web_search 'follow-up' → 3 results", cost_units=1.0,
        ),
    ])

    session = BoardSession(session_id="board_test", user_query="x")

    async def _spy_query(*a, **kw):
        return next(responses)

    async def _spy_exec(*a, **kw):
        return next(tool_results)

    with patch("server.board.deliberation.orchestrator.query_llm",
               AsyncMock(side_effect=_spy_query)), \
         patch("server.board.deliberation.orchestrator.execute_tool",
                AsyncMock(side_effect=_spy_exec)):
        await agentic_member_turn(
            member=_make_member("product"),
            model="m", system_prompt="x", initial_user_message="x",
            tools=[tools.TOOLS["validate_claim"], tools.TOOLS["web_search"]],
            budget=ToolBudget.for_mode("standard"),
            session=session, stage=2, on_event=lambda e: None,
        )

    assert len(session.tool_call_results) == 2
    assert session.tool_call_results[0]["tool_name"] == "validate_claim"
    assert session.tool_call_results[0]["verdict"] == "SUPPORTED"
    assert session.tool_call_results[1]["tool_name"] == "web_search"
    assert session.tool_call_results[1]["verdict"] is None
    # Both records carry the right stage.
    assert all(r["stage"] == 2 for r in session.tool_call_results)
    assert all(r["member_id"] == "product" for r in session.tool_call_results)


async def test_agentic_turn_persists_each_call_in_parallel_fanout():
    """A single LLMResponse with multiple tool_calls fan out via asyncio.gather;
    each call must produce its own record with its own elapsed_seconds (not
    the gather's wall time)."""
    from server.board.deliberation.orchestrator import BoardSession

    parallel_call = llm.LLMResponse(
        content="", model="m", input_tokens=1, output_tokens=1,
        latency_seconds=0.1, finish_reason="tool_calls",
        tool_calls=[
            llm.ToolCall(id="tc_a", name="validate_claim",
                          arguments={"claim": "claim alpha"}),
            llm.ToolCall(id="tc_b", name="web_search",
                          arguments={"query": "follow-up"}),
        ],
    )
    final = llm.LLMResponse(
        content="Done.", model="m", input_tokens=1, output_tokens=1,
        latency_seconds=0.1, finish_reason="stop", tool_calls=[],
    )
    responses = iter([parallel_call, final])

    async def _query(*a, **kw):
        return next(responses)

    per_tool_results = {
        "validate_claim": tools.ToolResult(
            content_for_model="validate_claim('claim alpha'):\nVERDICT: SUPPORTED",
            summary="validate_claim: SUPPORTED", cost_units=2.0,
        ),
        "web_search": tools.ToolResult(
            content_for_model="web_search('follow-up') results: ...",
            summary="web_search 'follow-up' → 3 results", cost_units=1.0,
        ),
    }

    async def _exec(*, name, **kw):
        return per_tool_results[name]

    session = BoardSession(session_id="board_parallel", user_query="x")

    with patch("server.board.deliberation.orchestrator.query_llm",
               AsyncMock(side_effect=_query)), \
         patch("server.board.deliberation.orchestrator.execute_tool",
                AsyncMock(side_effect=_exec)):
        await agentic_member_turn(
            member=_make_member("strategist"),
            model="m", system_prompt="x", initial_user_message="x",
            tools=[tools.TOOLS["validate_claim"], tools.TOOLS["web_search"]],
            budget=ToolBudget.for_mode("standard"),
            session=session, stage=1, on_event=lambda e: None,
        )

    # Both tool calls within the same LLM turn each landed as their own record.
    assert len(session.tool_call_results) == 2
    names = [r["tool_name"] for r in session.tool_call_results]
    assert set(names) == {"validate_claim", "web_search"}
    # Per-call timing semantics: each record carries its own elapsed_seconds.
    for r in session.tool_call_results:
        assert isinstance(r["elapsed_seconds"], float)
        assert r["elapsed_seconds"] >= 0.0
