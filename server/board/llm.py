"""LLM client: routes to native provider SDKs or OpenRouter (opt-in).

Public surface is `query_llm()` and the `LLMResponse` / `LLMProviderError`
types. Routing is decided by the model id's prefix; see `_PROVIDERS`.
Handlers are added one per provider in subsequent tasks.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

# Per-handler retry defaults
PRIMARY_MAX_RETRIES = 3
PRIMARY_BACKOFF_SECONDS = [1, 2, 4]
FALLBACK_MAX_RETRIES = 2
FALLBACK_BACKOFF_SECONDS = [1, 2]


@dataclass
class LLMResponse:
    """Structured response from an LLM call."""
    content: str
    model: str
    input_tokens: int       # -1 if missing from response
    output_tokens: int      # -1 if missing from response
    latency_seconds: float
    finish_reason: str | None = None
    response_id: str | None = None


class LLMProviderError(Exception):
    """Retryable error raised by provider handlers (timeout, 5xx, 429).

    Auth/4xx errors should NOT be wrapped — they raise immediately so callers
    fail fast. Only transient/recoverable failures become LLMProviderError so
    the fallback chain can react to them.
    """


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _full_messages(messages: list[dict[str, str]], system: str | None) -> list[dict[str, str]]:
    """Build message list with optional system message prepended."""
    if system is None:
        return list(messages)
    return [{"role": "system", "content": system}] + list(messages)


def _split_model_id(model: str) -> tuple[str, str]:
    """Return (prefix, provider_local_model). For ``openrouter:<id>`` the
    prefix is ``openrouter`` and the second element is the rest verbatim."""
    if model.startswith("openrouter:"):
        return "openrouter", model.split(":", 1)[1]
    if "/" in model:
        prefix, _, remainder = model.partition("/")
        return prefix, remainder or model
    return model, model


def _read_required_env(name: str, provider_label: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"{name} not set. Required for native {provider_label} calls."
        )
    return value


# ---------------------------------------------------------------------------
# Provider dispatch table
#
# Each entry: prefix -> async handler with signature
#     async def handler(model, messages, *, system, temperature, max_tokens,
#                       timeout, max_retries, backoff_seconds) -> LLMResponse
#
# Handlers are added one per provider in tasks 3-8.
# ---------------------------------------------------------------------------

HandlerType = Callable[..., Awaitable[LLMResponse]]
_PROVIDERS: dict[str, HandlerType] = {}


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

async def query_llm(
    model: str,
    messages: list[dict[str, str]],
    *,
    system: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout: float = 120.0,
    fallback: bool = True,
) -> LLMResponse:
    """Route a chat-completion request to the configured provider.

    Returns an LLMResponse. The free-first fallback chain (see Task 9) is
    skipped when fallback=False or when no handler is registered for the
    primary's prefix.
    """
    prefix, _ = _split_model_id(model)
    handler = _PROVIDERS.get(prefix)
    if handler is None:
        raise RuntimeError(
            f"unknown provider prefix: {prefix!r} for model {model!r}. "
            f"Known prefixes: {sorted(_PROVIDERS) or '(none registered yet)'}"
        )
    return await handler(
        model,
        messages,
        system=system,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        max_retries=PRIMARY_MAX_RETRIES,
        backoff_seconds=PRIMARY_BACKOFF_SECONDS,
    )
