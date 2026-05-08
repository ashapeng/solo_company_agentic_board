"""Tool registry contract tests."""
from __future__ import annotations

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
    assert call_kwargs["query"] == "agency tooling 2026"
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
