"""Free-first fallback chain behavior."""
from __future__ import annotations

import pytest

from server.board import llm


def _all_free_keys(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("ZAI_API_KEY", "z")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "q")
    monkeypatch.setenv("DASHSCOPE_REGION", "international")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d")
    monkeypatch.setenv("MOONSHOT_API_KEY", "k")


def _success_response(model: str) -> llm.LLMResponse:
    return llm.LLMResponse(
        content="ok", model=model,
        input_tokens=1, output_tokens=1, latency_seconds=0.0,
    )


async def test_chain_walks_in_order_until_success(monkeypatch):
    """gemini fails → glm succeeds. Order: gemini, glm. qwen never called."""
    _all_free_keys(monkeypatch)

    calls: list[str] = []

    async def fake_dispatch(prefix, model, messages, **kwargs):
        calls.append(model)
        if model == "kimi/kimi-k2.5":
            raise llm.LLMProviderError("primary failed")
        if model == "gemini/gemini-2.5-flash":
            raise llm.LLMProviderError("free 1 failed")
        if model == "glm/glm-4.5-flash":
            return _success_response(model)
        raise AssertionError(f"unexpected dispatch to {model}")

    monkeypatch.setattr(llm, "_dispatch_to_handler", fake_dispatch)

    resp = await llm.query_llm("kimi/kimi-k2.5", [{"role": "user", "content": "hi"}])
    assert resp.model == "glm/glm-4.5-flash"
    assert calls == ["kimi/kimi-k2.5", "gemini/gemini-2.5-flash", "glm/glm-4.5-flash"]


async def test_skip_when_key_missing(monkeypatch):
    """No GEMINI_API_KEY → gemini fallback skipped, glm tried first."""
    _all_free_keys(monkeypatch)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    calls: list[str] = []

    async def fake_dispatch(prefix, model, messages, **kwargs):
        calls.append(model)
        if model == "kimi/kimi-k2.5":
            raise llm.LLMProviderError("primary failed")
        if model == "glm/glm-4.5-flash":
            return _success_response(model)
        raise AssertionError(f"unexpected dispatch to {model}")

    monkeypatch.setattr(llm, "_dispatch_to_handler", fake_dispatch)

    resp = await llm.query_llm("kimi/kimi-k2.5", [{"role": "user", "content": "hi"}])
    assert resp.model == "glm/glm-4.5-flash"
    assert "gemini/gemini-2.5-flash" not in calls


async def test_skip_qwen_when_region_not_free(monkeypatch):
    _all_free_keys(monkeypatch)
    monkeypatch.setenv("DASHSCOPE_REGION", "cn")

    calls: list[str] = []

    async def fake_dispatch(prefix, model, messages, **kwargs):
        calls.append(model)
        if model == "kimi/kimi-k2.5":
            raise llm.LLMProviderError("primary failed")
        if model in ("gemini/gemini-2.5-flash", "glm/glm-4.5-flash"):
            raise llm.LLMProviderError("free fallback failed")
        if model == "deepseek/deepseek-chat":
            return _success_response(model)
        raise AssertionError(f"unexpected dispatch to {model}")

    monkeypatch.setattr(llm, "_dispatch_to_handler", fake_dispatch)

    resp = await llm.query_llm("kimi/kimi-k2.5", [{"role": "user", "content": "hi"}])
    assert "qwen/qwen-flash" not in calls
    assert resp.model == "deepseek/deepseek-chat"


async def test_skip_same_provider_as_primary(monkeypatch):
    """qwen/qwen-max failure must NOT fall back to qwen/qwen-flash."""
    _all_free_keys(monkeypatch)

    calls: list[str] = []

    async def fake_dispatch(prefix, model, messages, **kwargs):
        calls.append(model)
        if model == "qwen/qwen-max":
            raise llm.LLMProviderError("primary failed")
        if model == "gemini/gemini-2.5-flash":
            return _success_response(model)
        raise AssertionError(f"unexpected dispatch to {model}")

    monkeypatch.setattr(llm, "_dispatch_to_handler", fake_dispatch)

    resp = await llm.query_llm("qwen/qwen-max", [{"role": "user", "content": "hi"}])
    assert "qwen/qwen-flash" not in calls
    assert resp.model == "gemini/gemini-2.5-flash"


async def test_fallback_false_skips_chain(monkeypatch):
    _all_free_keys(monkeypatch)

    async def fake_dispatch(prefix, model, messages, **kwargs):
        raise llm.LLMProviderError("primary failed")

    monkeypatch.setattr(llm, "_dispatch_to_handler", fake_dispatch)

    with pytest.raises(llm.LLMProviderError, match="primary failed"):
        await llm.query_llm(
            "kimi/kimi-k2.5",
            [{"role": "user", "content": "hi"}],
            fallback=False,
        )


async def test_all_fail_raises_primary_chained(monkeypatch):
    _all_free_keys(monkeypatch)

    async def fake_dispatch(prefix, model, messages, **kwargs):
        raise llm.LLMProviderError(f"{model} failed")

    monkeypatch.setattr(llm, "_dispatch_to_handler", fake_dispatch)

    with pytest.raises(llm.LLMProviderError) as excinfo:
        await llm.query_llm("kimi/kimi-k2.5", [{"role": "user", "content": "hi"}])
    # The primary's message must be in the final raised chain
    assert "kimi/kimi-k2.5 failed" in str(excinfo.value) or any(
        "kimi/kimi-k2.5 failed" in str(e)
        for e in [excinfo.value.__cause__, excinfo.value.__context__]
        if e is not None
    )


async def test_response_model_reflects_substitution(monkeypatch):
    _all_free_keys(monkeypatch)

    async def fake_dispatch(prefix, model, messages, **kwargs):
        if model == "kimi/kimi-k2.5":
            raise llm.LLMProviderError("primary failed")
        if model == "gemini/gemini-2.5-flash":
            return _success_response(model)
        raise AssertionError(f"unexpected dispatch to {model}")

    monkeypatch.setattr(llm, "_dispatch_to_handler", fake_dispatch)

    resp = await llm.query_llm("kimi/kimi-k2.5", [{"role": "user", "content": "hi"}])
    assert resp.model == "gemini/gemini-2.5-flash"
