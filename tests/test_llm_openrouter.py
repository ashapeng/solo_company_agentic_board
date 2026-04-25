"""Unit tests for the OpenRouter escape-hatch handler."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from server.board import llm


def _fake_openrouter_payload():
    return {
        "id": "or-1",
        "choices": [{
            "message": {"content": "ok"},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 4, "completion_tokens": 1},
    }


async def test_openrouter_strips_prefix_and_posts(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")

    captured = {}

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            captured["init"] = (args, kwargs)
        async def __aenter__(self):
            return self
        async def __aexit__(self, *exc):
            return False
        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json = MagicMock(return_value=_fake_openrouter_payload())
            return resp

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    resp = await llm.query_llm(
        "openrouter:anthropic/claude-opus-4",
        [{"role": "user", "content": "hi"}],
        temperature=0.4,
        max_tokens=100,
    )

    assert resp.content == "ok"
    assert resp.model == "openrouter:anthropic/claude-opus-4"
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    # Prefix stripped before being passed in payload
    assert captured["json"]["model"] == "anthropic/claude-opus-4"
    assert captured["headers"]["Authorization"] == "Bearer or-test"


async def test_openrouter_missing_key_raises(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        await llm.query_llm(
            "openrouter:anthropic/claude-opus-4",
            [{"role": "user", "content": "hi"}],
        )


async def test_openrouter_non_prefixed_does_not_route_here():
    """A bare provider/model id (no 'openrouter:' prefix) must NOT hit OpenRouter."""
    with pytest.raises(RuntimeError, match="unknown provider prefix"):
        await llm.query_llm(
            "anthropic/claude-opus-4",
            [{"role": "user", "content": "hi"}],
        )
