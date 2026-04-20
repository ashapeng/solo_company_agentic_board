"""LLM client: sends requests to OpenRouter or native provider SDKs."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Retry configuration
MAX_RETRIES = 3
BACKOFF_SECONDS = [1, 2, 4]

# Fallback retry configuration (fewer attempts for the fallback model)
FALLBACK_MAX_RETRIES = 2
FALLBACK_BACKOFF_SECONDS = [1, 2]

# Model fallback chain: if the primary model fails, try the fallback
FALLBACK_MODELS = {
    "x-ai/grok-3": "openai/gpt-4.1",
    "google/gemini-2.5-pro": "anthropic/claude-sonnet-4",
    "openai/gpt-4.1": "anthropic/claude-sonnet-4",
    "anthropic/claude-sonnet-4": "google/gemini-2.5-pro",
}

# Native provider routing. Existing OpenRouter-style model IDs continue to use
# OpenRouter unless they use one of these explicit native prefixes.
NATIVE_PROVIDER_PREFIXES = {
    "glm": "zai",
    "zai": "zai",
    "qwen": "qwen",
    "deepseek": "deepseek",
    "kimi": "kimi",
    "moonshot": "kimi",
}

QWEN_BASE_URLS = {
    "international": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "singapore": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "global": "https://dashscope-us.aliyuncs.com/compatible-mode/v1",
    "us": "https://dashscope-us.aliyuncs.com/compatible-mode/v1",
    "virginia": "https://dashscope-us.aliyuncs.com/compatible-mode/v1",
    "cn": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "china": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "beijing": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "hongkong": "https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1",
    "hk": "https://cn-hongkong.dashscope.aliyuncs.com/compatible-mode/v1",
}


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


def _full_messages(messages: list[dict[str, str]], system: str | None) -> list[dict[str, str]]:
    """Build message list with optional system message."""
    full_messages = list(messages)
    if system is not None:
        full_messages = [{"role": "system", "content": system}] + full_messages
    return full_messages


def _split_model_id(model: str) -> tuple[str, str]:
    """Return provider/model from a model id such as ``deepseek/deepseek-chat``."""
    provider, _, model_name = model.partition("/")
    return provider, model_name or model


def _native_provider_for_model(model: str) -> tuple[str, str] | None:
    """Return native provider and provider-local model name, if enabled by prefix."""
    if model.startswith("openrouter:"):
        return None
    provider_prefix, provider_model = _split_model_id(model)
    native_provider = NATIVE_PROVIDER_PREFIXES.get(provider_prefix)
    if not native_provider:
        return None
    return native_provider, provider_model


def _openrouter_model_id(model: str) -> str:
    """Strip the force-OpenRouter prefix if present."""
    if model.startswith("openrouter:"):
        return model.split(":", 1)[1]
    return model


def _read_required_env(name: str, provider: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} not set. Required for native {provider} SDK calls.")
    return value


def _read_openrouter_api_key() -> str:
    api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY not set. "
            "Copy .env.example to .env and add your key from https://openrouter.ai/keys"
        )
    if "..." in api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY still contains the placeholder. "
            "Replace it with a real key from https://openrouter.ai/keys"
        )
    return api_key


def _get_attr_or_item(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


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


def _read_optional_int_env(name: str) -> int | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return None
    try:
        parsed = int(value)
    except ValueError as e:
        raise RuntimeError(f"{name} must be an integer.") from e
    if parsed < 0:
        raise RuntimeError(f"{name} must be a non-negative integer.")
    return parsed


def _choice_message_content(response: Any) -> str:
    """Extract assistant message content from OpenAI-like or DashScope-like responses."""
    choices = _get_attr_or_item(response, "choices")
    if not choices:
        output = _get_attr_or_item(response, "output", {})
        choices = _get_attr_or_item(output, "choices", [])
    if not choices:
        return ""

    choice = choices[0]
    message = _get_attr_or_item(choice, "message", {})
    content = _get_attr_or_item(message, "content", "")
    return content or ""


def _choice_finish_reason(response: Any) -> str | None:
    choices = _get_attr_or_item(response, "choices")
    if not choices:
        output = _get_attr_or_item(response, "output", {})
        choices = _get_attr_or_item(output, "choices", [])
    if not choices:
        return None
    return _get_attr_or_item(choices[0], "finish_reason", None)


def _response_id(response: Any) -> str | None:
    value = _get_attr_or_item(response, "id", None)
    return str(value) if value else None


def _usage_tokens(response: Any) -> tuple[int, int]:
    """Extract token counts from OpenAI-like or DashScope-like usage objects."""
    usage = _get_attr_or_item(response, "usage", {})
    if not usage:
        usage = _get_attr_or_item(_get_attr_or_item(response, "output", {}), "usage", {})

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


async def _send_llm_request(
    model: str,
    messages: list[dict[str, str]],
    *,
    system: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout: float = 120.0,
    max_retries: int = MAX_RETRIES,
    backoff_seconds: list[int] | None = None,
) -> LLMResponse:
    """Low-level retry loop for a single model. Raises on exhaustion."""
    if backoff_seconds is None:
        backoff_seconds = BACKOFF_SECONDS

    api_key = _read_openrouter_api_key()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/ashapeng/agentic-board",
        "X-Title": "Agentic Board",
    }

    full_messages = _full_messages(messages, system)

    payload = {
        "model": model,
        "messages": full_messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    last_exception: Exception | None = None

    for attempt in range(max_retries):
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(OPENROUTER_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            latency = round(time.monotonic() - t0, 3)

            # Extract content
            content = data["choices"][0]["message"]["content"]

            # Extract token usage (may be missing)
            usage = data.get("usage", {})
            input_tokens = usage.get("prompt_tokens", -1)
            output_tokens = usage.get("completion_tokens", -1)

            return LLMResponse(
                content=content,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_seconds=latency,
                finish_reason=data["choices"][0].get("finish_reason"),
                response_id=data.get("id"),
            )

        except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
            last_exception = e
            if attempt < max_retries - 1:
                backoff = backoff_seconds[attempt] if attempt < len(backoff_seconds) else backoff_seconds[-1]
                logger.warning(
                    "LLM request failed (attempt %d/%d, model=%s): %s. "
                    "Retrying in %ds...",
                    attempt + 1,
                    max_retries,
                    model,
                    str(e),
                    backoff,
                )
                await asyncio.sleep(backoff)
            else:
                logger.error(
                    "LLM request failed after %d attempts (model=%s): %s",
                    max_retries,
                    model,
                    str(e),
                )

    # All retries exhausted
    raise last_exception  # type: ignore[misc]


async def _send_native_request(
    model: str,
    messages: list[dict[str, str]],
    *,
    system: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout: float = 120.0,
) -> LLMResponse:
    """Send a request through a native provider SDK."""
    resolved = _native_provider_for_model(model)
    if not resolved:
        raise ValueError(f"Model is not configured for native provider routing: {model}")

    provider, provider_model = resolved
    full_messages = _full_messages(messages, system)
    t0 = time.monotonic()

    if provider == "zai":
        response = await asyncio.to_thread(
            _send_zai_request_sync,
            provider_model,
            full_messages,
            temperature,
            max_tokens,
            timeout,
        )
    elif provider in {"qwen", "deepseek", "kimi"}:
        response = await asyncio.to_thread(
            _send_openai_compatible_request_sync,
            provider,
            provider_model,
            full_messages,
            temperature,
            max_tokens,
            timeout,
        )
    else:
        raise ValueError(f"Unsupported native provider: {provider}")

    latency = round(time.monotonic() - t0, 3)
    input_tokens, output_tokens = _usage_tokens(response)
    return LLMResponse(
        content=_choice_message_content(response),
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_seconds=latency,
        finish_reason=_choice_finish_reason(response),
        response_id=_response_id(response),
    )


def _send_zai_request_sync(
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    timeout: float,
) -> Any:
    try:
        from zai import ZaiClient
    except ImportError as e:
        raise RuntimeError("zai-sdk is not installed. Run `uv add zai-sdk`.") from e

    api_key = _read_required_env("ZAI_API_KEY", "Z.AI/GLM")
    client = ZaiClient(api_key=api_key, timeout=timeout)
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    thinking = os.getenv("ZAI_THINKING")
    if thinking in {"enabled", "disabled"}:
        kwargs["thinking"] = {"type": thinking}
    return client.chat.completions.create(**kwargs)


def _send_openai_compatible_request_sync(
    provider: str,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    timeout: float,
) -> Any:
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("openai is not installed. Run `uv add openai`.") from e

    if provider == "deepseek":
        api_key = _read_required_env("DEEPSEEK_API_KEY", "DeepSeek")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if model != "deepseek-reasoner":
            kwargs["temperature"] = temperature
    elif provider == "qwen":
        api_key = _read_required_env("DASHSCOPE_API_KEY", "Qwen/DashScope")
        region = os.getenv("DASHSCOPE_REGION", "cn").lower()
        base_url = os.getenv("DASHSCOPE_BASE_URL") or QWEN_BASE_URLS.get(region)
        if not base_url:
            raise RuntimeError(
                f"Unsupported DASHSCOPE_REGION '{region}'. "
                "Set DASHSCOPE_BASE_URL or use one of: "
                f"{', '.join(sorted(QWEN_BASE_URLS))}."
            )
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        extra_body: dict[str, Any] = {}
        qwen_thinking = _env_bool("QWEN_THINKING")
        if qwen_thinking is not None:
            extra_body["enable_thinking"] = qwen_thinking
        qwen_thinking_budget = _read_optional_int_env("QWEN_THINKING_BUDGET")
        if qwen_thinking_budget is not None:
            extra_body["thinking_budget"] = qwen_thinking_budget
        if extra_body:
            kwargs["extra_body"] = extra_body
    elif provider == "kimi":
        api_key = _read_required_env("MOONSHOT_API_KEY", "Kimi/Moonshot")
        base_url = os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1")
        kwargs = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        # Kimi K2.5 enforces fixed sampling values. Do not pass temperature unless
        # the caller explicitly opts into provider-specific override handling.
        if model.startswith("kimi-k2-thinking"):
            kwargs["temperature"] = 1.0
        elif not model.startswith("kimi-k2.5"):
            kwargs["temperature"] = temperature
        thinking = _env_bool("KIMI_THINKING")
        if thinking is not None:
            thinking_type = "enabled" if thinking else "disabled"
            kwargs["extra_body"] = {"thinking": {"type": thinking_type}}
    else:
        raise ValueError(f"Unsupported OpenAI-compatible native provider: {provider}")

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
    return client.chat.completions.create(**kwargs)


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
    """Send a chat completion request to the configured provider and return an LLMResponse.

    Parameters
    ----------
    model : str
        The model identifier (e.g. ``deepseek/deepseek-chat`` or ``kimi/kimi-k2.5``).
    messages : list[dict]
        Conversation messages (role/content dicts).
    system : str | None
        If provided, prepended as a system message.
    temperature : float
        Sampling temperature.
    max_tokens : int
        Maximum response tokens.
    timeout : float
        HTTP request timeout in seconds.
    fallback : bool
        If True and all retries fail, try the fallback model (if configured).

    Returns
    -------
    LLMResponse
        Structured response with content, token counts, and latency.
        If a fallback model succeeds, ``model`` reflects the actual model used.
    """
    native_provider = _native_provider_for_model(model)
    if native_provider:
        return await _send_native_request(
            model,
            messages,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

    openrouter_model = _openrouter_model_id(model)
    try:
        return await _send_llm_request(
            openrouter_model, messages,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            max_retries=MAX_RETRIES,
            backoff_seconds=BACKOFF_SECONDS,
        )
    except (httpx.TimeoutException, httpx.HTTPStatusError) as primary_err:
        fallback_model = FALLBACK_MODELS.get(openrouter_model) if fallback else None
        if not fallback_model:
            raise

        logger.warning(
            "Primary model %s exhausted retries. Falling back to %s...",
            openrouter_model,
            fallback_model,
        )

        try:
            return await _send_llm_request(
                fallback_model, messages,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                max_retries=FALLBACK_MAX_RETRIES,
                backoff_seconds=FALLBACK_BACKOFF_SECONDS,
            )
        except (httpx.TimeoutException, httpx.HTTPStatusError) as fallback_err:
            logger.error(
                "Fallback model %s also failed: %s. Giving up.",
                fallback_model,
                fallback_err,
            )
            # Raise the fallback error, chained from the primary
            raise fallback_err from primary_err
