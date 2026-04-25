# server/harness/config_provider.py
"""Infer provider tag from a board model_id."""

from __future__ import annotations


def provider_of(model_id: str) -> str:
    """Return the provider prefix for a model_id.

    Examples:
        'kimi/kimi-k2.5'                                -> 'kimi'
        'deepseek/deepseek-chat'                        -> 'deepseek'
        'glm/glm-4.6'                                   -> 'glm'
        'zai/...'                                       -> 'zai'
        'qwen/...'                                      -> 'qwen'
        'gemini/gemini-2.5-flash'                       -> 'gemini'
        'openrouter:anthropic/claude-3.5-sonnet'        -> 'openrouter'
    """
    if not model_id:
        return "unknown"
    if ":" in model_id:
        return model_id.split(":", 1)[0].strip().lower() or "unknown"
    if "/" in model_id:
        return model_id.split("/", 1)[0].strip().lower() or "unknown"
    return model_id.strip().lower() or "unknown"
