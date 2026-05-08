"""Tool-calling support in the llm.py public surface."""
from __future__ import annotations

import inspect

from server.board import llm


def test_llm_response_has_tool_calls_field():
    resp = llm.LLMResponse(
        content="x", model="m", input_tokens=1, output_tokens=1, latency_seconds=0.1
    )
    assert resp.tool_calls == []


def test_query_llm_accepts_tools_and_tool_choice():
    sig = inspect.signature(llm.query_llm)
    assert "tools" in sig.parameters
    assert "tool_choice" in sig.parameters
    assert sig.parameters["tools"].default is None
    assert sig.parameters["tool_choice"].default == "auto"


def test_tool_call_dataclass_shape():
    tc = llm.ToolCall(id="tc_1", name="web_search", arguments={"q": "x"})
    assert tc.id == "tc_1"
    assert tc.name == "web_search"
    assert tc.arguments == {"q": "x"}
