"""Unit tests for the Gemini handler."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from server.board import llm


class _FakeContent:
    def __init__(self, *, role, parts):
        self.role = role
        self.parts = parts


class _FakePart:
    def __init__(self, *, text):
        self.text = text


class _FakeGenerateContentConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


_FAKE_TYPES = SimpleNamespace(
    Content=lambda role, parts: _FakeContent(role=role, parts=parts),
    Part=SimpleNamespace(from_text=lambda text: _FakePart(text=text)),
    GenerateContentConfig=_FakeGenerateContentConfig,
)


def _fake_gemini_response():
    return SimpleNamespace(
        text="hello from gemini",
        candidates=[SimpleNamespace(finish_reason="STOP")],
        usage_metadata=SimpleNamespace(
            prompt_token_count=12,
            candidates_token_count=5,
        ),
    )


class _FakeModels:
    last_kwargs: dict | None = None

    def generate_content(self, **kwargs):
        type(self).last_kwargs = kwargs
        return _fake_gemini_response()


class _FakeClient:
    last_init_kwargs: dict | None = None

    def __init__(self, **kwargs):
        type(self).last_init_kwargs = kwargs
        self.models = _FakeModels()


async def test_gemini_basic(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gem-test")
    fake_genai = SimpleNamespace(Client=_FakeClient, types=_FAKE_TYPES)
    fake_google = SimpleNamespace(genai=fake_genai)
    with patch.dict("sys.modules", {
        "google": fake_google,
        "google.genai": fake_genai,
    }):
        resp = await llm.query_llm(
            "gemini/gemini-2.5-flash",
            [{"role": "user", "content": "hi"}],
            system="be terse",
            temperature=0.6,
            max_tokens=200,
        )
    assert resp.content == "hello from gemini"
    assert resp.input_tokens == 12
    assert resp.output_tokens == 5
    kw = _FakeModels.last_kwargs
    assert kw["model"] == "gemini-2.5-flash"
    # System routes to config, not into contents
    assert isinstance(kw["config"], _FakeGenerateContentConfig)
    assert kw["config"].kwargs["system_instruction"] == "be terse"
    assert kw["config"].kwargs["temperature"] == 0.6
    assert kw["config"].kwargs["max_output_tokens"] == 200
    # contents has only the user message (no system entry)
    contents = kw["contents"]
    assert len(contents) == 1
    assert contents[0].role == "user"


async def test_gemini_assistant_role_maps_to_model(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gem-test")
    fake_genai = SimpleNamespace(Client=_FakeClient, types=_FAKE_TYPES)
    fake_google = SimpleNamespace(genai=fake_genai)
    with patch.dict("sys.modules", {
        "google": fake_google,
        "google.genai": fake_genai,
    }):
        await llm.query_llm(
            "gemini/gemini-2.5-flash",
            [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "second"},
                {"role": "user", "content": "third"},
            ],
        )
    contents = _FakeModels.last_kwargs["contents"]
    assert [c.role for c in contents] == ["user", "model", "user"]


async def test_gemini_uses_google_api_key_fallback(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "gkey")
    fake_genai = SimpleNamespace(Client=_FakeClient, types=_FAKE_TYPES)
    fake_google = SimpleNamespace(genai=fake_genai)
    with patch.dict("sys.modules", {
        "google": fake_google,
        "google.genai": fake_genai,
    }):
        await llm.query_llm("gemini/gemini-2.5-flash", [{"role": "user", "content": "hi"}])
    # Should not have raised
    assert _FakeClient.last_init_kwargs is not None


async def test_gemini_missing_both_keys_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    fake_genai = SimpleNamespace(Client=_FakeClient, types=_FAKE_TYPES)
    fake_google = SimpleNamespace(genai=fake_genai)
    with patch.dict("sys.modules", {
        "google": fake_google,
        "google.genai": fake_genai,
    }):
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            await llm.query_llm("gemini/gemini-2.5-flash", [{"role": "user", "content": "hi"}])
