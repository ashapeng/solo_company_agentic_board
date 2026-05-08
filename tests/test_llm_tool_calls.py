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


import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def _fake_oai_tool_response(tool_calls=None, content="ok"):
    """Fake OpenAI-shape response with optional tool_calls."""
    msg_kwargs = {"content": content}
    if tool_calls:
        msg_kwargs["tool_calls"] = tool_calls
    return SimpleNamespace(
        id="resp-1",
        choices=[SimpleNamespace(
            message=SimpleNamespace(**msg_kwargs),
            finish_reason="tool_calls" if tool_calls else "stop",
        )],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )


class _FakeOpenAIWithTools:
    last_create: dict | None = None

    def __init__(self, **kwargs):
        self.chat = SimpleNamespace(completions=SimpleNamespace(
            create=lambda **kw: (type(self)._record(kw), self._response_for(kw))[1]
        ))

    @classmethod
    def _record(cls, kw):
        cls.last_create = kw

    def _response_for(self, kw):
        if kw.get("tools"):
            tc = SimpleNamespace(
                id="tc_001",
                type="function",
                function=SimpleNamespace(
                    name="web_search",
                    arguments=json.dumps({"query": "test"}),
                ),
            )
            return _fake_oai_tool_response(tool_calls=[tc])
        return _fake_oai_tool_response(content="plain response")


async def test_kimi_passes_tools_and_parses_tool_calls(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "test-key")
    _FakeOpenAIWithTools.last_create = None
    fake_openai = SimpleNamespace(OpenAI=_FakeOpenAIWithTools)
    tools_schema = [{
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search",
            "parameters": {"type": "object",
                            "properties": {"query": {"type": "string"}}},
        },
    }]
    with patch.dict("sys.modules", {"openai": fake_openai}):
        resp = await llm.query_llm(
            "kimi/kimi-k2.6",
            [{"role": "user", "content": "find X"}],
            tools=tools_schema,
            tool_choice="auto",
        )
    assert _FakeOpenAIWithTools.last_create["tools"] == tools_schema
    assert _FakeOpenAIWithTools.last_create["tool_choice"] == "auto"
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].id == "tc_001"
    assert resp.tool_calls[0].name == "web_search"
    assert resp.tool_calls[0].arguments == {"query": "test"}


async def test_kimi_no_tools_does_not_pass_kwarg(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "test-key")
    _FakeOpenAIWithTools.last_create = None
    fake_openai = SimpleNamespace(OpenAI=_FakeOpenAIWithTools)
    with patch.dict("sys.modules", {"openai": fake_openai}):
        await llm.query_llm("kimi/kimi-k2.6", [{"role": "user", "content": "hi"}])
    assert "tools" not in _FakeOpenAIWithTools.last_create
    assert "tool_choice" not in _FakeOpenAIWithTools.last_create
