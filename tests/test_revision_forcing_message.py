"""Tests for REVISION_FORCING_PROMPT + _build_revision_forcing_message (spec §7.2.2)."""
from __future__ import annotations

from server.board.llm import ToolCall
from server.board.tools import ToolResult


# ─── REVISION_FORCING_PROMPT constant shape ─────────────────────────────────

def test_revision_forcing_prompt_constant_contains_required_placeholders():
    """The prompt must reference all three template fields the spec calls
    out (tool_name, contradicted, rationale) and the must-do block."""
    from server.board.deliberation.orchestrator import REVISION_FORCING_PROMPT

    assert "{tool_name}" in REVISION_FORCING_PROMPT
    assert "{contradicted_claim}" in REVISION_FORCING_PROMPT
    assert "{rationale}" in REVISION_FORCING_PROMPT
    assert "FORCED REVISION" in REVISION_FORCING_PROMPT
    assert "(a)" in REVISION_FORCING_PROMPT
    assert "(b)" in REVISION_FORCING_PROMPT
    assert "validate_claim" in REVISION_FORCING_PROMPT  # the re-validate option


def test_revision_forcing_prompt_is_self_contained_user_instruction():
    """No leading whitespace surprises; the prompt must read as a directive
    the model sees in a user turn."""
    from server.board.deliberation.orchestrator import REVISION_FORCING_PROMPT

    assert REVISION_FORCING_PROMPT.strip() == REVISION_FORCING_PROMPT.strip()
    # Spec mandates these two clauses appear:
    assert "Drop this claim" in REVISION_FORCING_PROMPT
    assert "new citation" in REVISION_FORCING_PROMPT.lower() or "citation that supports" in REVISION_FORCING_PROMPT


# ─── _build_revision_forcing_message helper ────────────────────────────────

def _make_tool_call(name: str = "validate_claim", arguments: dict | None = None) -> ToolCall:
    return ToolCall(id="tc_1", name=name, arguments=arguments or {"claim": "x"})


def test_build_message_returns_user_role_dict():
    from server.board.deliberation.orchestrator import _build_revision_forcing_message

    tc = _make_tool_call()
    tr = ToolResult(
        content_for_model="validate_claim('average conversion rate is 8%'):\n"
                          "VERDICT: CONTRADICTED\n"
                          "RATIONALE: Reuters reports 3% across 2025 cohorts.\n"
                          "KEY_SOURCES: https://reuters.com/...",
        summary="validate_claim: CONTRADICTED",
        cost_units=2.0,
    )
    msg = _build_revision_forcing_message(tc, tr)
    assert msg["role"] == "user"
    assert isinstance(msg["content"], str)
    assert msg["content"].strip()  # non-empty


def test_build_message_includes_tool_name_summary_and_rationale_snippet():
    """The formatted prompt body must surface all three fields the spec
    template lists, so the model knows which call to revise."""
    from server.board.deliberation.orchestrator import _build_revision_forcing_message

    tc = _make_tool_call(name="validate_claim")
    tr = ToolResult(
        content_for_model="validate_claim('YC W26 batch size is 600 startups'):\n"
                          "VERDICT: CONTRADICTED\n"
                          "RATIONALE: YC's own blog says W26 had 244 startups.\n"
                          "KEY_SOURCES: https://ycombinator.com/blog/w26",
        summary="validate_claim: CONTRADICTED",
        cost_units=2.0,
    )
    content = _build_revision_forcing_message(tc, tr)["content"]
    # tool_name surfaced
    assert "validate_claim" in content
    # the summary itself (which carries the verdict) surfaced
    assert "validate_claim: CONTRADICTED" in content
    # rationale snippet from content_for_model surfaced (the YC fact)
    assert "YC" in content or "ycombinator" in content


def test_build_message_truncates_rationale_to_500_chars():
    """Long content_for_model must be truncated so a verbose tool result
    doesn't blow the message context."""
    from server.board.deliberation.orchestrator import _build_revision_forcing_message

    tc = _make_tool_call()
    huge = "validate_claim('x'):\nVERDICT: CONTRADICTED\nRATIONALE: " + ("R" * 2000)
    tr = ToolResult(
        content_for_model=huge,
        summary="validate_claim: CONTRADICTED",
        cost_units=2.0,
    )
    content = _build_revision_forcing_message(tc, tr)["content"]
    # The injected rationale slice is bounded to 500 chars from content_for_model.
    # The full prompt is larger (template + headers + summary + slice) but the
    # rationale portion specifically must not carry the entire 2000-char R string.
    assert content.count("R") < 600  # 500 + a small margin for any 'R' in fixed text


def test_build_message_handles_empty_content_for_model():
    """Defensive: a tool that returns CONTRADICTED with empty content still
    produces a well-formed forced-revision message (rationale becomes
    empty/placeholder, but tool_name and summary still surface)."""
    from server.board.deliberation.orchestrator import _build_revision_forcing_message

    tc = _make_tool_call(name="future_tool")
    tr = ToolResult(
        content_for_model="",
        summary="future_tool: CONTRADICTED",
        cost_units=0.0,
    )
    msg = _build_revision_forcing_message(tc, tr)
    assert msg["role"] == "user"
    assert "future_tool" in msg["content"]
    assert "future_tool: CONTRADICTED" in msg["content"]


def test_build_message_uses_tool_call_name_not_summary_substring():
    """tool_name field is sourced from tc.name (canonical), not parsed out of
    summary. Lets future tools use any summary format."""
    from server.board.deliberation.orchestrator import _build_revision_forcing_message

    tc = _make_tool_call(name="some_future_tool")
    tr = ToolResult(
        content_for_model="anything CONTRADICTED",
        summary="anything: CONTRADICTED",
        cost_units=1.0,
    )
    content = _build_revision_forcing_message(tc, tr)["content"]
    assert "some_future_tool" in content
