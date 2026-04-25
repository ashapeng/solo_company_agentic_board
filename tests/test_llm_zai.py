"""Unit tests for the Z.AI / GLM handler."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from server.board import llm


def _fake_zai_response():
    return SimpleNamespace(
        id="resp-zai-1",
        choices=[SimpleNamespace(
            message=SimpleNamespace(content="hello from zai"),
            finish_reason="stop",
        )],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=4),
    )


class _FakeCompletions:
    def __init__(self):
        self.create = MagicMock(return_value=_fake_zai_response())


class _FakeChat:
    def __init__(self):
        self.completions = _FakeCompletions()


class _FakeZaiClient:
    last_init_kwargs = None
    last_create_kwargs = None

    def __init__(self, **kwargs):
        type(self).last_init_kwargs = kwargs
        self.chat = _FakeChat()


async def test_zai_routes_via_prefix(monkeypatch):
    monkeypatch.setenv("ZAI_API_KEY", "zai-test")

    fake_module = SimpleNamespace(ZaiClient=_FakeZaiClient)
    with patch.dict("sys.modules", {"zai": fake_module}):
        resp = await llm.query_llm(
            "glm/glm-4.6",
            [{"role": "user", "content": "hi"}],
            system="be terse",
            temperature=0.5,
            max_tokens=256,
        )

    assert resp.content == "hello from zai"
    assert resp.model == "glm/glm-4.6"  # original id, not provider-local
    assert resp.input_tokens == 11
    assert resp.output_tokens == 4
    assert resp.finish_reason == "stop"


async def test_zai_thinking_passthrough(monkeypatch):
    monkeypatch.setenv("ZAI_API_KEY", "zai-test")
    monkeypatch.setenv("ZAI_THINKING", "enabled")

    captured = {}

    class _Cli:
        def __init__(self, **kwargs):
            captured["init"] = kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(
                create=lambda **kw: (captured.setdefault("create", kw), _fake_zai_response())[1]
            ))

    fake_module = SimpleNamespace(ZaiClient=_Cli)
    with patch.dict("sys.modules", {"zai": fake_module}):
        await llm.query_llm("zai/glm-4.5-air", [{"role": "user", "content": "hi"}])

    assert captured["create"]["thinking"] == {"type": "enabled"}


async def test_zai_missing_key_raises(monkeypatch):
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    fake_module = SimpleNamespace(ZaiClient=_FakeZaiClient)
    with patch.dict("sys.modules", {"zai": fake_module}):
        with pytest.raises(RuntimeError, match="ZAI_API_KEY"):
            await llm.query_llm("glm/glm-4.6", [{"role": "user", "content": "hi"}])


async def test_zai_fails_fast_on_auth_error(monkeypatch):
    """Auth errors (401/403) must NOT trigger the retry loop."""
    monkeypatch.setenv("ZAI_API_KEY", "zai-test")

    call_count = {"n": 0}

    class _AuthError(Exception):
        status_code = 401

    class _Cli:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(
                create=lambda **kw: (call_count.update(n=call_count["n"] + 1), _raise_auth())[1]
            ))

    def _raise_auth():
        raise _AuthError("Unauthorized")

    fake_module = SimpleNamespace(ZaiClient=_Cli)
    with patch.dict("sys.modules", {"zai": fake_module}):
        with pytest.raises(_AuthError):
            await llm.query_llm("glm/glm-4.6", [{"role": "user", "content": "hi"}])

    # Auth error must not trigger retries — exactly one call attempt
    assert call_count["n"] == 1


async def test_zai_retries_on_5xx(monkeypatch):
    """5xx errors are retryable and trigger backoff retries."""
    monkeypatch.setenv("ZAI_API_KEY", "zai-test")

    call_count = {"n": 0}

    class _ServerError(Exception):
        status_code = 503

    def _create_attempt(**kw):
        call_count["n"] += 1
        if call_count["n"] < 3:
            raise _ServerError("Service Unavailable")
        return _fake_zai_response()

    class _Cli:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=_create_attempt))

    # Patch sleep to avoid real backoff delays in tests
    async def _instant_sleep(_):
        return None

    monkeypatch.setattr("server.board.llm.asyncio.sleep", _instant_sleep)

    fake_module = SimpleNamespace(ZaiClient=_Cli)
    with patch.dict("sys.modules", {"zai": fake_module}):
        resp = await llm.query_llm("glm/glm-4.6", [{"role": "user", "content": "hi"}])

    assert resp.content == "hello from zai"
    assert call_count["n"] == 3  # 2 failures, then success on attempt 3
