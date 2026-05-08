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
