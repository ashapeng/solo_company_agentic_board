"""Unit tests for the Kimi/Moonshot handler."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from server.board import llm


def _fake_oai_response():
    return SimpleNamespace(
        id="resp-kimi-1",
        choices=[SimpleNamespace(
            message=SimpleNamespace(content="ok"),
            finish_reason="stop",
        )],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2),
    )


class _FakeOpenAI:
    last_init: dict | None = None
    last_create: dict | None = None

    def __init__(self, **kwargs):
        type(self).last_init = kwargs
        self.chat = SimpleNamespace(completions=SimpleNamespace(
            create=lambda **kw: (type(self)._record(kw), _fake_oai_response())[1]
        ))

    @classmethod
    def _record(cls, kw):
        cls.last_create = kw


async def test_kimi_default_base_url_is_dot_ai(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "kimi-test")
    monkeypatch.delenv("MOONSHOT_BASE_URL", raising=False)
    with patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=_FakeOpenAI)}):
        await llm.query_llm("kimi/kimi-k2.6", [{"role": "user", "content": "hi"}])
    assert _FakeOpenAI.last_init["base_url"] == "https://api.moonshot.ai/v1"


async def test_kimi_k2_5_omits_temperature(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "kimi-test")
    with patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=_FakeOpenAI)}):
        await llm.query_llm(
            "kimi/kimi-k2.5",
            [{"role": "user", "content": "hi"}],
            temperature=0.7,
        )
    assert "temperature" not in _FakeOpenAI.last_create


async def test_kimi_k2_thinking_forces_one(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "kimi-test")
    with patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=_FakeOpenAI)}):
        await llm.query_llm(
            "kimi/kimi-k2-thinking-preview",
            [{"role": "user", "content": "hi"}],
            temperature=0.3,
        )
    assert _FakeOpenAI.last_create["temperature"] == 1.0


async def test_kimi_other_model_passes_temperature(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "kimi-test")
    with patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=_FakeOpenAI)}):
        await llm.query_llm(
            "kimi/kimi-k2.6",
            [{"role": "user", "content": "hi"}],
            temperature=0.5,
        )
    assert _FakeOpenAI.last_create["temperature"] == 0.5


async def test_kimi_thinking_env(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "kimi-test")
    monkeypatch.setenv("KIMI_THINKING", "enabled")
    with patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=_FakeOpenAI)}):
        await llm.query_llm("kimi/kimi-k2.6", [{"role": "user", "content": "hi"}])
    assert _FakeOpenAI.last_create["extra_body"] == {"thinking": {"type": "enabled"}}


async def test_moonshot_prefix_alias(monkeypatch):
    """The 'moonshot/' prefix routes to the same handler."""
    monkeypatch.setenv("MOONSHOT_API_KEY", "kimi-test")
    with patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=_FakeOpenAI)}):
        resp = await llm.query_llm("moonshot/kimi-k2.6", [{"role": "user", "content": "hi"}])
    assert resp.content == "ok"
    assert _FakeOpenAI.last_create["model"] == "kimi-k2.6"
