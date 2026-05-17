"""Unit tests for the DeepSeek handler."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from server.board import llm


def _fake_oai_response():
    return SimpleNamespace(
        id="resp-ds-1",
        choices=[SimpleNamespace(
            message=SimpleNamespace(content="ok"),
            finish_reason="stop",
        )],
        usage=SimpleNamespace(prompt_tokens=7, completion_tokens=2),
    )


class _FakeOpenAI:
    last_init: dict | None = None
    last_create: dict | None = None

    def __init__(self, **kwargs):
        type(self).last_init = kwargs
        self.chat = SimpleNamespace(completions=SimpleNamespace(
            create=lambda **kw: (type(self)._record_create(kw), _fake_oai_response())[1]
        ))

    @classmethod
    def _record_create(cls, kw):
        cls.last_create = kw


async def test_deepseek_chat_passes_temperature(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")

    fake_openai = SimpleNamespace(OpenAI=_FakeOpenAI)
    with patch.dict("sys.modules", {"openai": fake_openai}):
        resp = await llm.query_llm(
            "deepseek/deepseek-chat",
            [{"role": "user", "content": "hi"}],
            temperature=0.4,
            max_tokens=128,
        )
    assert resp.content == "ok"
    assert _FakeOpenAI.last_init["base_url"] == "https://api.deepseek.com/v1"
    assert _FakeOpenAI.last_create["model"] == "deepseek-chat"
    assert _FakeOpenAI.last_create["temperature"] == 0.4


async def test_deepseek_reasoner_omits_temperature(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")
    fake_openai = SimpleNamespace(OpenAI=_FakeOpenAI)
    with patch.dict("sys.modules", {"openai": fake_openai}):
        await llm.query_llm(
            "deepseek/deepseek-reasoner",
            [{"role": "user", "content": "hi"}],
            temperature=0.7,
        )
    assert "temperature" not in _FakeOpenAI.last_create


async def test_deepseek_missing_key_raises(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    fake_openai = SimpleNamespace(OpenAI=_FakeOpenAI)
    with patch.dict("sys.modules", {"openai": fake_openai}):
        with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
            await llm.query_llm("deepseek/deepseek-chat", [{"role": "user", "content": "hi"}])


async def test_deepseek_base_url_override(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://example.test/v1")
    fake_openai = SimpleNamespace(OpenAI=_FakeOpenAI)
    with patch.dict("sys.modules", {"openai": fake_openai}):
        await llm.query_llm("deepseek/deepseek-chat", [{"role": "user", "content": "hi"}])
    assert _FakeOpenAI.last_init["base_url"] == "https://example.test/v1"


async def test_deepseek_fails_fast_on_auth_error(monkeypatch):
    """Auth errors must NOT trigger the retry loop."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")

    call_count = {"n": 0}

    class _AuthError(Exception):
        status_code = 401

    def _create(**kw):
        call_count["n"] += 1
        raise _AuthError("Unauthorized")

    class _Cli:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=_create))

    fake_openai = SimpleNamespace(OpenAI=_Cli)
    with patch.dict("sys.modules", {"openai": fake_openai}):
        with pytest.raises(_AuthError):
            await llm.query_llm("deepseek/deepseek-chat", [{"role": "user", "content": "hi"}])
    assert call_count["n"] == 1


async def test_deepseek_v4_pro_omits_temperature(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")
    fake_openai = SimpleNamespace(OpenAI=_FakeOpenAI)
    with patch.dict("sys.modules", {"openai": fake_openai}):
        await llm.query_llm(
            "deepseek/deepseek-v4-pro",
            [{"role": "user", "content": "hi"}],
            temperature=0.7,
        )
    assert "temperature" not in _FakeOpenAI.last_create


async def test_deepseek_v4_flash_passes_temperature(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")
    # conftest.py loads .env, which may set DEEPSEEK_REASONING_EFFORT=low for
    # the production board. This test asserts the kwarg is absent when no
    # effort is requested, so isolate it from the ambient env.
    monkeypatch.delenv("DEEPSEEK_REASONING_EFFORT", raising=False)
    fake_openai = SimpleNamespace(OpenAI=_FakeOpenAI)
    with patch.dict("sys.modules", {"openai": fake_openai}):
        await llm.query_llm(
            "deepseek/deepseek-v4-flash",
            [{"role": "user", "content": "hi"}],
            temperature=0.4,
        )
    assert _FakeOpenAI.last_create["temperature"] == 0.4
    assert "reasoning_effort" not in _FakeOpenAI.last_create


async def test_deepseek_v4_reasoning_effort_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")
    monkeypatch.setenv("DEEPSEEK_REASONING_EFFORT", "high")
    fake_openai = SimpleNamespace(OpenAI=_FakeOpenAI)
    with patch.dict("sys.modules", {"openai": fake_openai}):
        await llm.query_llm(
            "deepseek/deepseek-v4-flash",
            [{"role": "user", "content": "hi"}],
        )
    assert _FakeOpenAI.last_create["reasoning_effort"] == "high"


async def test_deepseek_reasoning_effort_invalid_raises(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")
    monkeypatch.setenv("DEEPSEEK_REASONING_EFFORT", "extreme")
    fake_openai = SimpleNamespace(OpenAI=_FakeOpenAI)
    with patch.dict("sys.modules", {"openai": fake_openai}):
        with pytest.raises(RuntimeError, match="DEEPSEEK_REASONING_EFFORT"):
            await llm.query_llm(
                "deepseek/deepseek-v4-flash",
                [{"role": "user", "content": "hi"}],
            )


async def test_deepseek_reasoning_effort_ignored_for_chat(monkeypatch):
    """Effort env must NOT be sent for non-v4 models — guards against silent
    400s on the legacy deepseek-chat endpoint."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")
    monkeypatch.setenv("DEEPSEEK_REASONING_EFFORT", "high")
    fake_openai = SimpleNamespace(OpenAI=_FakeOpenAI)
    with patch.dict("sys.modules", {"openai": fake_openai}):
        await llm.query_llm(
            "deepseek/deepseek-chat",
            [{"role": "user", "content": "hi"}],
        )
    assert "reasoning_effort" not in _FakeOpenAI.last_create
