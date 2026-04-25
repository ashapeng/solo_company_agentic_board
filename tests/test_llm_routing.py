"""Routing-layer unit tests for query_llm prefix dispatch."""
from __future__ import annotations

import pytest

from server.board import llm


async def test_query_llm_unknown_prefix_raises():
    with pytest.raises(RuntimeError, match="unknown provider prefix"):
        await llm.query_llm("totallymadeup/foo", [{"role": "user", "content": "hi"}])


async def test_query_llm_bare_id_no_prefix_raises():
    """Bare 'provider/model' with no recognized native prefix must error
    rather than silently route to OpenRouter (the old default)."""
    with pytest.raises(RuntimeError, match="unknown provider prefix"):
        await llm.query_llm("anthropic/claude-opus-4", [{"role": "user", "content": "hi"}])


async def test_llm_provider_error_is_exposed():
    """LLMProviderError must be importable for fallback chain consumers."""
    assert hasattr(llm, "LLMProviderError")
    assert issubclass(llm.LLMProviderError, Exception)


def test_providers_table_present():
    """The _PROVIDERS dispatch table must exist as a dict."""
    assert isinstance(llm._PROVIDERS, dict)


def test_llm_response_dataclass_unchanged():
    """LLMResponse keeps its existing field set so callers don't break."""
    fields = {f for f in llm.LLMResponse.__dataclass_fields__}
    assert fields == {
        "content", "model", "input_tokens", "output_tokens",
        "latency_seconds", "finish_reason", "response_id",
    }
