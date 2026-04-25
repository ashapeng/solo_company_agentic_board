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


@pytest.mark.parametrize("model,in_rate,out_rate", [
    ("kimi/kimi-k2.6",                       0.95, 4.00),
    ("deepseek/deepseek-v4-flash",           0.14, 0.28),
    ("deepseek/deepseek-v4-pro",             0.435, 0.87),
    ("glm/glm-5.1",                          1.40, 4.40),
    ("glm/glm-5",                            0.50, 2.08),
    ("glm/glm-4.7-flash",                    0.0, 0.0),
    ("qwen/qwen3.6-max-preview",             1.30, 7.80),
    ("qwen/qwen3.6-plus",                    0.325, 1.95),
    ("qwen/qwen3-max",                       0.78, 3.90),
    ("qwen/qwen3.5-plus",                    0.26, 1.56),
    ("gemini/gemini-3-pro-preview",          3.00, 15.00),
    ("gemini/gemini-3-flash-preview",        0.25, 0.80),
    ("gemini/gemini-3-flash-lite-preview",   0.25, 1.50),
])
def test_reasoning_models_have_expected_rates(model, in_rate, out_rate):
    actual_in, actual_out = metrics.COST_RATES[model]
    assert actual_in == in_rate
    assert actual_out == out_rate


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
