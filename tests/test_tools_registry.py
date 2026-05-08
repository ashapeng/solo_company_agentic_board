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
