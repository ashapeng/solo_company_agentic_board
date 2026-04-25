"""LLM client: routes to native provider SDKs or OpenRouter (opt-in).

Public surface is `query_llm()` and the `LLMResponse` / `LLMProviderError`
types. Routing is decided by the model id's prefix; see `_PROVIDERS`.
Handlers are added one per provider in subsequent tasks.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

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


def _env_bool(name: str) -> bool | None:
    value = os.getenv(name)
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"enabled", "true", "1", "yes", "on"}:
        return True
    if normalized in {"disabled", "false", "0", "no", "off"}:
        return False
    raise RuntimeError(f"{name} must be one of enabled/disabled, true/false, 1/0.")


# ---------------------------------------------------------------------------
# OpenAI-shape response helpers (shared by zai, deepseek, kimi, …)
# ---------------------------------------------------------------------------

def _get_attr_or_item(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _openai_shape_content(response: Any) -> str:
    choices = _get_attr_or_item(response, "choices") or []
    if not choices:
        return ""
    msg = _get_attr_or_item(choices[0], "message", {})
    return _get_attr_or_item(msg, "content", "") or ""


def _openai_shape_finish_reason(response: Any) -> str | None:
    choices = _get_attr_or_item(response, "choices") or []
    if not choices:
        return None
    return _get_attr_or_item(choices[0], "finish_reason", None)


def _openai_shape_response_id(response: Any) -> str | None:
    value = _get_attr_or_item(response, "id", None)
    return str(value) if value else None


def _openai_shape_usage(response: Any) -> tuple[int, int]:
    usage = _get_attr_or_item(response, "usage", {}) or {}
    input_tokens = (
        _get_attr_or_item(usage, "prompt_tokens", None)
        or _get_attr_or_item(usage, "input_tokens", None)
        or -1
    )
    output_tokens = (
        _get_attr_or_item(usage, "completion_tokens", None)
        or _get_attr_or_item(usage, "output_tokens", None)
        or -1
    )
    return int(input_tokens), int(output_tokens)


def _is_retryable(exc: Exception) -> bool:
    """Return True if an exception represents a transient/retryable failure.

    Retryable: timeouts, connection errors, HTTP 5xx, HTTP 429.
    NON-retryable: HTTP 4xx (auth, bad request, not found, etc.) — fail fast.
    Raised before reaching the retry loop so callers see the original error.
    """
    if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
        return True
    name = type(exc).__name__
    # Common transient exception names across SDKs (httpx, openai, google-genai, zai)
    if any(token in name for token in (
        "Timeout", "ConnectError", "ConnectionError",
        "RateLimit", "InternalServer", "ServiceUnavailable",
        "BadGateway", "GatewayTimeout",
    )):
        return True
    # Look for HTTP status (httpx.HTTPStatusError, openai.APIStatusError, etc.)
    status = getattr(exc, "status_code", None)
    if status is None:
        response = getattr(exc, "response", None)
        if response is not None:
            status = getattr(response, "status_code", None)
    if isinstance(status, int):
        if status == 429 or status >= 500:
            return True
        # 4xx other than 429 are non-retryable
        return False
    # Unknown shape — be conservative: do NOT retry. Auth errors with
    # idiosyncratic exception names will fail fast instead of waiting out
    # the backoff schedule.
    return False


# ---------------------------------------------------------------------------
# Provider handlers
# ---------------------------------------------------------------------------

async def _send_zai(
    model: str,
    messages: list[dict[str, str]],
    *,
    system: str | None,
    temperature: float,
    max_tokens: int,
    timeout: float,
    max_retries: int,
    backoff_seconds: list[int],
) -> LLMResponse:
    """Send a request to Z.AI via zai-sdk."""
    try:
        from zai import ZaiClient
    except ImportError as e:
        raise RuntimeError("zai-sdk is not installed. Run `uv add zai-sdk`.") from e

    api_key = _read_required_env("ZAI_API_KEY", "Z.AI/GLM")
    _, provider_model = _split_model_id(model)
    full_messages = _full_messages(messages, system)

    kwargs: dict[str, Any] = {
        "model": provider_model,
        "messages": full_messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    thinking = os.getenv("ZAI_THINKING")
    if thinking in {"enabled", "disabled"}:
        kwargs["thinking"] = {"type": thinking}

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        t0 = time.monotonic()
        try:
            client = ZaiClient(api_key=api_key, timeout=timeout)
            response = await asyncio.to_thread(
                client.chat.completions.create, **kwargs
            )
            latency = round(time.monotonic() - t0, 3)
            input_tokens, output_tokens = _openai_shape_usage(response)
            return LLMResponse(
                content=_openai_shape_content(response),
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_seconds=latency,
                finish_reason=_openai_shape_finish_reason(response),
                response_id=_openai_shape_response_id(response),
            )
        except Exception as e:  # noqa: BLE001 — broad catch for retry policy
            if not _is_retryable(e):
                raise
            last_exc = e
            if attempt < max_retries - 1:
                backoff = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                logger.warning("Z.AI call failed (attempt %d/%d): %s; retrying in %ds",
                               attempt + 1, max_retries, e, backoff)
                await asyncio.sleep(backoff)
            else:
                logger.error("Z.AI call exhausted retries: %s", e)
    raise LLMProviderError(f"zai exhausted retries: {last_exc!r}") from last_exc


async def _send_deepseek(
    model: str,
    messages: list[dict[str, str]],
    *,
    system: str | None,
    temperature: float,
    max_tokens: int,
    timeout: float,
    max_retries: int,
    backoff_seconds: list[int],
) -> LLMResponse:
    """Send a request to DeepSeek via the OpenAI-compatible endpoint."""
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("openai is not installed. Run `uv add openai`.") from e

    api_key = _read_required_env("DEEPSEEK_API_KEY", "DeepSeek")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    _, provider_model = _split_model_id(model)
    full_messages = _full_messages(messages, system)

    kwargs: dict[str, Any] = {
        "model": provider_model,
        "messages": full_messages,
        "max_tokens": max_tokens,
    }
    if provider_model != "deepseek-reasoner":
        kwargs["temperature"] = temperature

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        t0 = time.monotonic()
        try:
            client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
            response = await asyncio.to_thread(client.chat.completions.create, **kwargs)
            latency = round(time.monotonic() - t0, 3)
            input_tokens, output_tokens = _openai_shape_usage(response)
            return LLMResponse(
                content=_openai_shape_content(response),
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_seconds=latency,
                finish_reason=_openai_shape_finish_reason(response),
                response_id=_openai_shape_response_id(response),
            )
        except Exception as e:  # noqa: BLE001
            if not _is_retryable(e):
                raise
            last_exc = e
            if attempt < max_retries - 1:
                backoff = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                logger.warning("DeepSeek call failed (attempt %d/%d): %s; retrying in %ds",
                               attempt + 1, max_retries, e, backoff)
                await asyncio.sleep(backoff)
            else:
                logger.error("DeepSeek call exhausted retries: %s", e)
    raise LLMProviderError(f"deepseek exhausted retries: {last_exc!r}") from last_exc


async def _send_kimi(
    model: str,
    messages: list[dict[str, str]],
    *,
    system: str | None,
    temperature: float,
    max_tokens: int,
    timeout: float,
    max_retries: int,
    backoff_seconds: list[int],
) -> LLMResponse:
    """Send a request to Moonshot/Kimi via the OpenAI-compatible endpoint."""
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("openai is not installed. Run `uv add openai`.") from e

    api_key = _read_required_env("MOONSHOT_API_KEY", "Kimi/Moonshot")
    base_url = os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1")
    _, provider_model = _split_model_id(model)
    full_messages = _full_messages(messages, system)

    kwargs: dict[str, Any] = {
        "model": provider_model,
        "messages": full_messages,
        "max_tokens": max_tokens,
    }
    # Per-model temperature rules
    if provider_model.startswith("kimi-k2-thinking"):
        kwargs["temperature"] = 1.0
    elif provider_model.startswith("kimi-k2.5"):
        pass  # provider enforces fixed sampling; do not pass temperature
    else:
        kwargs["temperature"] = temperature

    thinking = _env_bool("KIMI_THINKING")
    if thinking is not None:
        kwargs["extra_body"] = {"thinking": {"type": "enabled" if thinking else "disabled"}}

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        t0 = time.monotonic()
        try:
            client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
            response = await asyncio.to_thread(client.chat.completions.create, **kwargs)
            latency = round(time.monotonic() - t0, 3)
            input_tokens, output_tokens = _openai_shape_usage(response)
            return LLMResponse(
                content=_openai_shape_content(response),
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_seconds=latency,
                finish_reason=_openai_shape_finish_reason(response),
                response_id=_openai_shape_response_id(response),
            )
        except Exception as e:  # noqa: BLE001
            if not _is_retryable(e):
                raise
            last_exc = e
            if attempt < max_retries - 1:
                backoff = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                logger.warning("Kimi call failed (attempt %d/%d): %s; retrying in %ds",
                               attempt + 1, max_retries, e, backoff)
                await asyncio.sleep(backoff)
            else:
                logger.error("Kimi call exhausted retries: %s", e)
    raise LLMProviderError(f"kimi exhausted retries: {last_exc!r}") from last_exc


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
_PROVIDERS: dict[str, HandlerType] = {
    "glm": _send_zai,
    "zai": _send_zai,
    "deepseek": _send_deepseek,
    "kimi": _send_kimi,
    "moonshot": _send_kimi,
}


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
