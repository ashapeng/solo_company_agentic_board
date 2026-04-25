"""Cost-rate coverage for native-prefix model ids and openrouter: stripping."""
from __future__ import annotations

import pytest

from server.board import metrics


@pytest.mark.parametrize("model", [
    "gemini/gemini-2.5-flash",
    "glm/glm-4.5-flash",
    "qwen/qwen-flash",
])
def test_free_models_priced_zero(model):
    in_rate, out_rate = metrics.COST_RATES[model]
    assert in_rate == 0.0
    assert out_rate == 0.0


@pytest.mark.parametrize("model", [
    "gemini/gemini-2.5-pro",
    "qwen/qwen-max",
    "qwen/qwen-plus",
    "deepseek/deepseek-chat",   # pre-existing
    "kimi/kimi-k2.5",           # pre-existing
])
def test_paid_models_have_nonzero_rates(model):
    in_rate, out_rate = metrics.COST_RATES[model]
    assert in_rate > 0.0
    assert out_rate > 0.0


def test_estimate_cost_strips_openrouter_prefix():
    """openrouter:google/gemini-2.5-pro must resolve to the same row as
    'google/gemini-2.5-pro' (the OpenRouter id), not the default rate."""
    bare = metrics._estimate_cost("google/gemini-2.5-pro", 1_000_000, 1_000_000)
    prefixed = metrics._estimate_cost("openrouter:google/gemini-2.5-pro",
                                      1_000_000, 1_000_000)
    assert prefixed == bare
    assert prefixed > 0.0


def test_estimate_cost_free_model_is_zero():
    cost = metrics._estimate_cost("gemini/gemini-2.5-flash", 1_000_000, 1_000_000)
    assert cost == 0.0
