"""Unit tests for the Qwen / DashScope native handler."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from server.board import llm


def _fake_dashscope_response():
    """Shape returned by dashscope.Generation.call with result_format='message'."""
    return SimpleNamespace(
        request_id="req-qwen-1",
        status_code=200,
        output=SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content="qwen ok"),
                finish_reason="stop",
            )],
        ),
        usage=SimpleNamespace(input_tokens=9, output_tokens=3),
    )


class _FakeGeneration:
    last_call_kwargs: dict | None = None

    @classmethod
    def call(cls, **kwargs):
        cls.last_call_kwargs = kwargs
        return _fake_dashscope_response()


async def test_qwen_native_call_shape(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "qwen-test")
    fake_module = SimpleNamespace(Generation=_FakeGeneration)
    with patch.dict("sys.modules", {"dashscope": fake_module}):
        resp = await llm.query_llm(
            "qwen/qwen-flash",
            [{"role": "user", "content": "hi"}],
            system="be terse",
            temperature=0.3,
            max_tokens=128,
        )
    kw = _FakeGeneration.last_call_kwargs
    assert kw["api_key"] == "qwen-test"
    assert kw["model"] == "qwen-flash"
    assert kw["result_format"] == "message"
    assert kw["temperature"] == 0.3
    assert kw["max_tokens"] == 128
    # System message prepended
    assert kw["messages"][0] == {"role": "system", "content": "be terse"}
    assert kw["messages"][1] == {"role": "user", "content": "hi"}
    assert resp.content == "qwen ok"
    assert resp.input_tokens == 9
    assert resp.output_tokens == 3


async def test_qwen_thinking_envs(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "qwen-test")
    monkeypatch.setenv("QWEN_THINKING", "true")
    monkeypatch.setenv("QWEN_THINKING_BUDGET", "256")
    fake_module = SimpleNamespace(Generation=_FakeGeneration)
    with patch.dict("sys.modules", {"dashscope": fake_module}):
        await llm.query_llm("qwen/qwen-plus", [{"role": "user", "content": "hi"}])
    kw = _FakeGeneration.last_call_kwargs
    assert kw["enable_thinking"] is True
    assert kw["thinking_budget"] == 256


async def test_qwen_missing_key_raises(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    fake_module = SimpleNamespace(Generation=_FakeGeneration)
    with patch.dict("sys.modules", {"dashscope": fake_module}):
        with pytest.raises(RuntimeError, match="DASHSCOPE_API_KEY"):
            await llm.query_llm("qwen/qwen-flash", [{"role": "user", "content": "hi"}])


async def test_qwen_error_status_raises_provider_error(monkeypatch):
    """A non-200 status_code from DashScope should raise LLMProviderError
    (after retry exhaustion) rather than returning a malformed response."""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "qwen-test")

    error_response = SimpleNamespace(
        request_id="req-bad",
        status_code=500,
        message="Internal server error",
    )

    class _FailGeneration:
        @classmethod
        def call(cls, **kwargs):
            return error_response

    # Patch sleep so the retry loop doesn't actually wait.
    async def _instant_sleep(_):
        return None
    monkeypatch.setattr("server.board.llm.asyncio.sleep", _instant_sleep)

    fake_module = SimpleNamespace(Generation=_FailGeneration)
    with patch.dict("sys.modules", {"dashscope": fake_module}):
        with pytest.raises(llm.LLMProviderError):
            await llm.query_llm(
                "qwen/qwen-flash",
                [{"role": "user", "content": "hi"}],
                fallback=False,  # isolate handler behavior; don't invoke the fallback chain
            )


async def test_qwen_region_international_routes_to_intl_endpoint(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "qwen-test")
    monkeypatch.setenv("DASHSCOPE_REGION", "international")
    monkeypatch.delenv("DASHSCOPE_BASE_URL", raising=False)
    fake_module = SimpleNamespace(Generation=_FakeGeneration)
    with patch.dict("sys.modules", {"dashscope": fake_module}):
        await llm.query_llm("qwen/qwen-flash", [{"role": "user", "content": "hi"}])
    kw = _FakeGeneration.last_call_kwargs
    assert kw["base_http_api_url"] == "https://dashscope-intl.aliyuncs.com/api/v1"


async def test_qwen_region_cn_uses_sdk_default(monkeypatch):
    """Region 'cn' (default) should NOT pass base_http_api_url — let the SDK
    use its built-in CN endpoint."""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "qwen-test")
    monkeypatch.setenv("DASHSCOPE_REGION", "cn")
    monkeypatch.delenv("DASHSCOPE_BASE_URL", raising=False)
    fake_module = SimpleNamespace(Generation=_FakeGeneration)
    with patch.dict("sys.modules", {"dashscope": fake_module}):
        await llm.query_llm("qwen/qwen-flash", [{"role": "user", "content": "hi"}])
    kw = _FakeGeneration.last_call_kwargs
    assert "base_http_api_url" not in kw


async def test_qwen_explicit_base_url_overrides_region(monkeypatch):
    """DASHSCOPE_BASE_URL should win over DASHSCOPE_REGION."""
    monkeypatch.setenv("DASHSCOPE_API_KEY", "qwen-test")
    monkeypatch.setenv("DASHSCOPE_REGION", "international")
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://custom.example.com/api")
    fake_module = SimpleNamespace(Generation=_FakeGeneration)
    with patch.dict("sys.modules", {"dashscope": fake_module}):
        await llm.query_llm("qwen/qwen-flash", [{"role": "user", "content": "hi"}])
    kw = _FakeGeneration.last_call_kwargs
    assert kw["base_http_api_url"] == "https://custom.example.com/api"


async def test_qwen_unknown_region_raises(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "qwen-test")
    monkeypatch.setenv("DASHSCOPE_REGION", "atlantis")
    monkeypatch.delenv("DASHSCOPE_BASE_URL", raising=False)
    fake_module = SimpleNamespace(Generation=_FakeGeneration)
    with patch.dict("sys.modules", {"dashscope": fake_module}):
        with pytest.raises(RuntimeError, match="DASHSCOPE_REGION"):
            await llm.query_llm("qwen/qwen-flash", [{"role": "user", "content": "hi"}])


async def test_qwen_preserve_thinking_env(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "qwen-test")
    monkeypatch.setenv("QWEN_PRESERVE_THINKING", "true")
    monkeypatch.delenv("DASHSCOPE_REGION", raising=False)
    monkeypatch.delenv("DASHSCOPE_BASE_URL", raising=False)
    fake_module = SimpleNamespace(Generation=_FakeGeneration)
    with patch.dict("sys.modules", {"dashscope": fake_module}):
        await llm.query_llm(
            "qwen/qwen3.6-max-preview",
            [{"role": "user", "content": "hi"}],
        )
    kw = _FakeGeneration.last_call_kwargs
    assert kw["preserve_thinking"] is True


async def test_qwen_preserve_thinking_omitted_when_unset(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "qwen-test")
    monkeypatch.delenv("QWEN_PRESERVE_THINKING", raising=False)
    monkeypatch.delenv("DASHSCOPE_REGION", raising=False)
    monkeypatch.delenv("DASHSCOPE_BASE_URL", raising=False)
    fake_module = SimpleNamespace(Generation=_FakeGeneration)
    with patch.dict("sys.modules", {"dashscope": fake_module}):
        await llm.query_llm(
            "qwen/qwen3.6-max-preview",
            [{"role": "user", "content": "hi"}],
        )
    kw = _FakeGeneration.last_call_kwargs
    assert "preserve_thinking" not in kw


async def test_qwen_preserve_thinking_false(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "qwen-test")
    monkeypatch.setenv("QWEN_PRESERVE_THINKING", "false")
    monkeypatch.delenv("DASHSCOPE_REGION", raising=False)
    monkeypatch.delenv("DASHSCOPE_BASE_URL", raising=False)
    fake_module = SimpleNamespace(Generation=_FakeGeneration)
    with patch.dict("sys.modules", {"dashscope": fake_module}):
        await llm.query_llm(
            "qwen/qwen3.6-max-preview",
            [{"role": "user", "content": "hi"}],
        )
    kw = _FakeGeneration.last_call_kwargs
    assert kw["preserve_thinking"] is False
