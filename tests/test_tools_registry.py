"""Tool registry contract tests."""
from __future__ import annotations

import asyncio
import socket

import pytest

from server.board import tools


def test_tool_dataclass_shape():
    async def _h(**kwargs):
        return tools.ToolResult(content_for_model="x", summary="ok", cost_units=1.0)
    t = tools.Tool(
        name="x",
        description="d",
        parameters={"type": "object", "properties": {}},
        handler=_h,
    )
    assert t.name == "x"
    assert callable(t.handler)


def test_tool_to_openai_schema():
    async def _h(**kwargs):
        return tools.ToolResult(content_for_model="x", summary="ok", cost_units=1.0)
    t = tools.Tool(
        name="web_search",
        description="Search the web.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        handler=_h,
    )
    schema = t.to_openai_schema()
    assert schema == {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }


def test_registry_lookup():
    assert "web_search" in tools.TOOLS
    assert "fetch_url" in tools.TOOLS
    assert "ask_user_clarifying_question" in tools.TOOLS
    assert "open_browser" in tools.TOOLS


async def test_execute_tool_unknown_name():
    result = await tools.execute_tool(
        name="nonexistent_tool", arguments={}, session=None, member_id=None,
    )
    assert result.error is not None
    assert "unknown tool" in result.error.lower()


from unittest.mock import AsyncMock, patch


async def test_web_search_handler_invokes_execution_layer(monkeypatch):
    fake_results = {
        "results": [
            {"title": "X", "url": "https://x.example",
             "snippet": "snip", "retrieved_at": "2026-05-07T10:00:00Z"},
        ],
        "provider": "tavily",
    }
    fake_search = AsyncMock(return_value=fake_results)
    with patch("server.execution.web_search.web_search", fake_search):
        result = await tools.execute_tool(
            name="web_search",
            arguments={"query": "agency tooling 2026", "max_results": 3},
            session=None,
            member_id="strategist",
        )
    assert result.error is None
    assert result.cost_units == 1.0
    assert "X" in result.content_for_model
    assert "https://x.example" in result.content_for_model
    fake_search.assert_called_once()
    call_kwargs = fake_search.call_args.kwargs
    # Query is augmented with strategist's role keywords: "market" and "competition"
    assert "agency tooling 2026" in call_kwargs["query"]
    assert "market" in call_kwargs["query"].lower()
    assert "competition" in call_kwargs["query"].lower()
    assert call_kwargs["max_results"] == 3


async def test_fetch_url_handler_returns_text(monkeypatch):
    class _FakeResp:
        status_code = 200
        text = "<html><body><h1>Hi</h1></body></html>"
        def raise_for_status(self): pass

    class _FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw): return _FakeResp()

    # Patch DNS so test TLD resolves to a public IP (not private)
    async def fake_resolve(host, port, *a, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
    loop = asyncio.get_event_loop()
    monkeypatch.setattr(loop, "getaddrinfo", fake_resolve)

    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: _FakeClient())
    result = await tools.execute_tool(
        name="fetch_url", arguments={"url": "https://example.test"},
        session=None, member_id=None,
    )
    assert result.error is None
    assert "Hi" in result.content_for_model or "<h1>Hi</h1>" in result.content_for_model
    assert result.cost_units == 0.5


async def test_fetch_url_handler_failure_returns_error():
    result = await tools.execute_tool(
        name="fetch_url", arguments={"url": "not-a-url"},
        session=None, member_id=None,
    )
    assert result.error is not None


async def test_ask_user_uses_session_callback():
    captured: dict = {}

    async def fake_ask(question: str, why: str) -> str:
        captured["question"] = question
        captured["why"] = why
        return "user-answer"

    class _FakeSession:
        ask_user = staticmethod(fake_ask)

    result = await tools.execute_tool(
        name="ask_user_clarifying_question",
        arguments={"question": "Which segment?",
                   "why_it_matters": "TAM differs by segment"},
        session=_FakeSession(),
        member_id="strategist",
    )
    assert result.error is None
    assert captured["question"] == "Which segment?"
    assert "user-answer" in result.content_for_model


async def test_ask_user_session_without_callback_returns_no_response():
    class _SessionNoCallback: pass
    result = await tools.execute_tool(
        name="ask_user_clarifying_question",
        arguments={"question": "Q?", "why_it_matters": "Y"},
        session=_SessionNoCallback(), member_id="strategist",
    )
    assert "[NO_USER_RESPONSE]" in result.content_for_model


from types import SimpleNamespace


async def test_validate_claim_supported_verdict(monkeypatch):
    """validate_claim runs a search + judge and returns the verdict."""
    fake_search_results = {
        "results": [
            {"title": "Source A", "url": "https://a.example",
             "snippet": "Tokyo metropolitan area population is 37 million.",
             "retrieved_at": "2026-05-07"},
            {"title": "Source B", "url": "https://b.example",
             "snippet": "Tokyo has 37M people in greater area.",
             "retrieved_at": "2026-05-07"},
        ],
    }
    fake_search = AsyncMock(return_value=fake_search_results)

    fake_judge_response = SimpleNamespace(
        content=("VERDICT: SUPPORTED\n"
                  "RATIONALE: Multiple sources confirm 37 million.\n"
                  "KEY_SOURCES: https://a.example, https://b.example"),
        model="gemini/gemini-2.5-flash",
        input_tokens=20, output_tokens=10, latency_seconds=0.2,
        finish_reason="stop", tool_calls=[], reasoning_content=None,
    )
    fake_query = AsyncMock(return_value=fake_judge_response)

    with patch("server.execution.web_search.web_search", fake_search), \
         patch("server.board.tools.query_llm", fake_query):
        result = await tools.execute_tool(
            name="validate_claim",
            arguments={"claim": "Tokyo population is 37 million"},
            session=None, member_id="strategist",
        )

    assert result.error is None
    assert "SUPPORTED" in result.summary or "SUPPORTED" in result.content_for_model
    assert "https://a.example" in result.content_for_model
    fake_search.assert_called_once()
    fake_query.assert_called_once()


async def test_validate_claim_no_search_results():
    """When web_search returns nothing, validate_claim short-circuits gracefully."""
    fake_search = AsyncMock(return_value={"results": []})
    with patch("server.execution.web_search.web_search", fake_search):
        result = await tools.execute_tool(
            name="validate_claim",
            arguments={"claim": "Some unverifiable claim"},
            session=None, member_id="strategist",
        )
    assert result.error is None
    assert "no" in result.summary.lower() or "unverified" in result.summary.lower()


async def test_validate_claim_unknown_verdict_falls_back_to_unverified(monkeypatch):
    """If the judge response doesn't contain a recognizable verdict word,
    treat it as UNVERIFIED (don't crash)."""
    fake_search_results = {
        "results": [{"title": "X", "url": "https://x", "snippet": "data",
                     "retrieved_at": "2026-05-07"}],
    }
    fake_search = AsyncMock(return_value=fake_search_results)
    fake_judge = AsyncMock(return_value=SimpleNamespace(
        content="some unparsable response",
        model="m", input_tokens=1, output_tokens=1, latency_seconds=0.1,
        finish_reason="stop", tool_calls=[], reasoning_content=None,
    ))

    with patch("server.execution.web_search.web_search", fake_search), \
         patch("server.board.tools.query_llm", fake_judge):
        result = await tools.execute_tool(
            name="validate_claim",
            arguments={"claim": "X"},
            session=None, member_id="strategist",
        )
    assert result.error is None
    assert "UNVERIFIED" in result.summary


async def test_web_search_augments_query_with_role_keywords(monkeypatch):
    """When member_id matches a known role, the query is augmented with role keywords."""
    captured_calls: list[dict] = []
    fake_results = {"results": [
        {"title": "X", "url": "https://x.example", "snippet": "snip",
         "retrieved_at": "2026-05-07"},
    ]}

    async def fake_ws(*args, **kwargs):
        captured_calls.append(kwargs)
        return fake_results

    with patch("server.execution.web_search.web_search", fake_ws):
        await tools.execute_tool(
            name="web_search",
            arguments={"query": "agency campaign briefs"},
            session=None,
            member_id="strategist",
        )
    # Strategist's role keywords: ["market", "competition", "industry trend", "strategy"]
    # Helper takes the first 2.
    assert "market" in captured_calls[0]["query"].lower()
    assert "competition" in captured_calls[0]["query"].lower()
    # Original query is preserved
    assert "agency campaign briefs" in captured_calls[0]["query"]


async def test_web_search_no_augmentation_when_member_unknown(monkeypatch):
    """An unknown member_id passes the query through unchanged."""
    captured_calls: list[dict] = []
    fake_results = {"results": []}

    async def fake_ws(*args, **kwargs):
        captured_calls.append(kwargs)
        return fake_results

    with patch("server.execution.web_search.web_search", fake_ws):
        await tools.execute_tool(
            name="web_search",
            arguments={"query": "raw query"},
            session=None,
            member_id="unknown_member",
        )
    # Falls back to using member_role as the only keyword; here member_role is "".
    # Since the helper appends a single empty token, the query may have a
    # trailing space. Accept either exact "raw query" or "raw query " (one trailing).
    sent_query = captured_calls[0]["query"].strip()
    assert sent_query == "raw query"


async def test_web_search_no_augmentation_when_member_id_none(monkeypatch):
    """When member_id is None, query passes through unchanged."""
    captured_calls: list[dict] = []
    fake_results = {"results": []}

    async def fake_ws(*args, **kwargs):
        captured_calls.append(kwargs)
        return fake_results

    with patch("server.execution.web_search.web_search", fake_ws):
        await tools.execute_tool(
            name="web_search",
            arguments={"query": "untargeted query"},
            session=None,
            member_id=None,
        )
    assert captured_calls[0]["query"].strip() == "untargeted query"


async def test_validate_claim_evidence_wrapped_in_evidence_tags(monkeypatch):
    """The judge prompt must wrap evidence in <evidence> tags with an
    untrusted-content instruction to prevent prompt injection."""
    fake_results = {"results": [
        {"title": "X", "url": "https://x", "snippet": "Tokyo population is 37M",
         "retrieved_at": "2026-05-07"},
    ]}
    fake_search = AsyncMock(return_value=fake_results)

    captured_prompts: list[str] = []

    async def fake_judge(model, messages, **kwargs):
        captured_prompts.append(messages[0]["content"])
        return SimpleNamespace(
            content="VERDICT: SUPPORTED\nRATIONALE: yes\nKEY_SOURCES: https://x",
            model=model, input_tokens=1, output_tokens=1, latency_seconds=0.1,
            finish_reason="stop", tool_calls=[], reasoning_content=None,
        )

    with patch("server.execution.web_search.web_search", fake_search), \
         patch("server.board.tools.query_llm", fake_judge):
        await tools.execute_tool(
            name="validate_claim", arguments={"claim": "Tokyo is 37M"},
            session=None, member_id="strategist",
        )
    assert captured_prompts, "judge LLM was not called"
    prompt = captured_prompts[0]
    assert "<evidence>" in prompt and "</evidence>" in prompt
    assert "untrusted" in prompt.lower() or "ignore" in prompt.lower()


# ── ToolResult.triggers_revision (P3b spec §7.2.1) ──────────────────────────

def test_tool_result_triggers_revision_on_validate_claim_contradicted():
    """The canonical case: validate_claim with verdict CONTRADICTED."""
    from server.board.tools import ToolResult
    r = ToolResult(
        content_for_model="validate_claim('x'): VERDICT: CONTRADICTED…",
        summary="validate_claim: CONTRADICTED",
        cost_units=2.0,
    )
    assert r.triggers_revision is True


def test_tool_result_triggers_revision_substring_match_is_tool_agnostic():
    """Trigger fires for ANY tool whose summary contains the literal 'CONTRADICTED'.
    Documents the contract for future tool authors (spec §7.2.1)."""
    from server.board.tools import ToolResult
    r = ToolResult(
        content_for_model="future_tool result body",
        summary="future_tool: CONTRADICTED (2/3 sources)",
        cost_units=1.0,
    )
    assert r.triggers_revision is True


def test_tool_result_does_not_trigger_on_supported_or_unverified():
    from server.board.tools import ToolResult
    for summary in (
        "validate_claim: SUPPORTED",
        "validate_claim: UNVERIFIED",
        "validate_claim: UNVERIFIED (no search results)",
        "web_search 'x' → 5 results",
        "fetched https://example.com (1234 chars)",
        "",
    ):
        r = ToolResult(content_for_model="", summary=summary, cost_units=0.0)
        assert r.triggers_revision is False, f"unexpected trigger on summary={summary!r}"


def test_tool_result_triggers_revision_is_case_sensitive():
    """Lowercase 'contradicted' does NOT trigger. Pin the contract — future
    tools must emit the exact token to opt in."""
    from server.board.tools import ToolResult
    r = ToolResult(
        content_for_model="x",
        summary="validate_claim: contradicted",
        cost_units=0.0,
    )
    assert r.triggers_revision is False


def test_tool_result_triggers_revision_ignores_content_for_model():
    """Only `summary` is inspected. `content_for_model` containing the word
    doesn't trip the trigger — otherwise a SUPPORTED verdict that quoted
    CONTRADICTED in its rationale would falsely fire."""
    from server.board.tools import ToolResult
    r = ToolResult(
        content_for_model="The evidence does not say CONTRADICTED anywhere relevant.",
        summary="validate_claim: SUPPORTED",
        cost_units=2.0,
    )
    assert r.triggers_revision is False


def test_expand_peer_registered_with_spec_schema():
    """Spec §9.1: TOOLS["expand_peer"] with the exact schema."""
    assert "expand_peer" in tools.TOOLS
    t = tools.TOOLS["expand_peer"]
    assert t.name == "expand_peer"
    # Description includes the cap reminder so the model self-rations.
    assert "1 call per stage" in t.description.lower() \
        or "capped" in t.description.lower()
    # Parameters: member_letter (string, required), no others.
    params = t.parameters
    assert params["type"] == "object"
    assert "member_letter" in params["properties"]
    assert params["properties"]["member_letter"]["type"] == "string"
    assert params["required"] == ["member_letter"]
    # Handler is async + bound.
    import inspect
    assert inspect.iscoroutinefunction(t.handler)


async def test_expand_peer_via_execute_tool_routes_to_handler():
    """End-to-end: execute_tool('expand_peer', ...) dispatches to the handler."""
    from server.board.deliberation.orchestrator import BoardSession, MemberResponse

    session = BoardSession(
        session_id="t", user_query="x",
        stage1_responses=[
            MemberResponse(member_id="strategist", stage=1,
                            content="STRAT FULL.", model="m",
                            elapsed_seconds=0.1),
        ],
        stage2_anonymization_map={"A": "strategist"},
    )
    result = await tools.execute_tool(
        name="expand_peer",
        arguments={"member_letter": "A"},
        session=session, member_id="critic",
    )
    assert result.error is None
    assert "STRAT FULL." in result.content_for_model
