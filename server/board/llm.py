"""LLM client: routes to native provider SDKs or OpenRouter (opt-in).

Public surface is `query_llm()` and the `LLMResponse` / `LLMProviderError`
types. Routing is decided by the model id's prefix; see `_PROVIDERS`.
Handlers are added one per provider in subsequent tasks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import httpx

logger = logging.getLogger(__name__)

# Per-handler retry defaults
PRIMARY_MAX_RETRIES = 3
PRIMARY_BACKOFF_SECONDS = [1, 2, 4]
FALLBACK_MAX_RETRIES = 2
FALLBACK_BACKOFF_SECONDS = [1, 2]


@dataclass
class ToolCall:
    """A single tool/function invocation requested by the model."""
    id: str
    name: str
    arguments: dict[str, Any]


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
    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning_content: str | None = None


@dataclass
class LLMStreamChunk:
    """One streamed text delta or final metadata marker from an LLM call."""
    delta: str = ""
    content: str = ""
    done: bool = False
    model: str | None = None
    input_tokens: int = -1
    output_tokens: int = -1
    latency_seconds: float = 0.0
    finish_reason: str | None = None
    response_id: str | None = None
    simulated_stream: bool = False


class LLMProviderError(Exception):
    """Retryable error raised by provider handlers (timeout, 5xx, 429).

    Auth/4xx errors should NOT be wrapped — they raise immediately so callers
    fail fast. Only transient/recoverable failures become LLMProviderError so
    the fallback chain can react to them.
    """


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _full_messages(messages: list[dict[str, Any]], system: str | None) -> list[dict[str, Any]]:
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


def _read_optional_int_env(name: str, *, allow_negative: bool = False) -> int | None:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return None
    try:
        parsed = int(value)
    except ValueError as e:
        raise RuntimeError(f"{name} must be an integer.") from e
    if not allow_negative and parsed < 0:
        raise RuntimeError(f"{name} must be a non-negative integer.")
    return parsed


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


def _openai_shape_reasoning_content(response: Any) -> str | None:
    """Extract reasoning_content from a response (Kimi/DeepSeek thinking mode)."""
    choices = _get_attr_or_item(response, "choices") or []
    if not choices:
        return None
    msg = _get_attr_or_item(choices[0], "message", {}) or {}
    rc = _get_attr_or_item(msg, "reasoning_content", None)
    return str(rc) if rc else None


def _openai_shape_tool_calls(response: Any) -> list[ToolCall]:
    """Parse tool_calls out of an OpenAI-shape chat completion response."""
    choices = _get_attr_or_item(response, "choices") or []
    if not choices:
        return []
    msg = _get_attr_or_item(choices[0], "message", {}) or {}
    raw_calls = _get_attr_or_item(msg, "tool_calls", None) or []
    out: list[ToolCall] = []
    for raw in raw_calls:
        fn = _get_attr_or_item(raw, "function", {}) or {}
        name = _get_attr_or_item(fn, "name", "") or ""
        args_str = _get_attr_or_item(fn, "arguments", "") or ""
        try:
            args = json.loads(args_str) if isinstance(args_str, str) else (args_str or {})
        except json.JSONDecodeError:
            args = {"_raw": args_str}
        out.append(ToolCall(
            id=str(_get_attr_or_item(raw, "id", "") or ""),
            name=name,
            arguments=args,
        ))
    return out


def _gemini_text_part(genai_types: Any, text: str) -> Any:
    """Build a Gemini text part using the google-genai keyword-only API."""
    return genai_types.Part.from_text(text=text)


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
    messages: list[dict[str, Any]],
    *,
    system: str | None,
    temperature: float,
    max_tokens: int,
    timeout: float,
    max_retries: int,
    backoff_seconds: list[int],
    tools: list[dict] | None = None,
    tool_choice: str = "auto",
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
    # v4-pro defaults to high reasoning effort and silently ignores temperature.
    # deepseek-reasoner is the v3-era thinking alias — same behavior.
    if provider_model not in {"deepseek-reasoner", "deepseek-v4-pro"}:
        kwargs["temperature"] = temperature

    # reasoning_effort is a v4-only knob; older models 400 if it's sent.
    if provider_model.startswith("deepseek-v4-"):
        effort = os.getenv("DEEPSEEK_REASONING_EFFORT")
        if effort:
            if effort not in {"low", "medium", "high", "max"}:
                raise RuntimeError(
                    "DEEPSEEK_REASONING_EFFORT must be one of low|medium|high|max."
                )
            kwargs["reasoning_effort"] = effort

    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice

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
                tool_calls=_openai_shape_tool_calls(response),
                reasoning_content=_openai_shape_reasoning_content(response),
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
    messages: list[dict[str, Any]],
    *,
    system: str | None,
    temperature: float,
    max_tokens: int,
    timeout: float,
    max_retries: int,
    backoff_seconds: list[int],
    tools: list[dict] | None = None,
    tool_choice: str = "auto",
) -> LLMResponse:
    """Send a request to Moonshot/Kimi via the OpenAI-compatible endpoint."""
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("openai is not installed. Run `uv add openai`.") from e

    api_key = _read_required_env("MOONSHOT_API_KEY", "Kimi/Moonshot")
    base_url = os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1")
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
    elif provider_model.startswith(("kimi-k2.5", "kimi-k2.6")):
        pass  # K2.5/K2.6: provider enforces fixed sampling; do not pass temperature
    else:
        kwargs["temperature"] = temperature

    thinking = _env_bool("KIMI_THINKING")
    if thinking is not None:
        kwargs["extra_body"] = {"thinking": {"type": "enabled" if thinking else "disabled"}}

    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice

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
                tool_calls=_openai_shape_tool_calls(response),
                reasoning_content=_openai_shape_reasoning_content(response),
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
# DashScope region → native API base URL mapping
#
# Source: https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-dashscope
#
# The native DashScope SDK uses /api/v1 (NOT /compatible-mode/v1, which is
# the OpenAI-compat path). Values of None mean "use the SDK's built-in CN
# default — do not override base_http_api_url".
# ---------------------------------------------------------------------------

QWEN_NATIVE_BASE_URLS: dict[str, str | None] = {
    "international": "https://dashscope-intl.aliyuncs.com/api/v1",
    "singapore": "https://dashscope-intl.aliyuncs.com/api/v1",
    "us": "https://dashscope-us.aliyuncs.com/api/v1",
    "global": "https://dashscope-us.aliyuncs.com/api/v1",
    "cn": None,      # SDK default; no override needed
    "china": None,
    "beijing": None,
}


# ---------------------------------------------------------------------------
# DashScope response helpers (Qwen native SDK)
# ---------------------------------------------------------------------------

def _dashscope_response_content(response: Any) -> str:
    output = _get_attr_or_item(response, "output", {}) or {}
    choices = _get_attr_or_item(output, "choices", []) or []
    if not choices:
        return ""
    msg = _get_attr_or_item(choices[0], "message", {}) or {}
    return _get_attr_or_item(msg, "content", "") or ""


def _dashscope_response_finish_reason(response: Any) -> str | None:
    output = _get_attr_or_item(response, "output", {}) or {}
    choices = _get_attr_or_item(output, "choices", []) or []
    if not choices:
        return None
    return _get_attr_or_item(choices[0], "finish_reason", None)


def _dashscope_response_id(response: Any) -> str | None:
    value = _get_attr_or_item(response, "request_id", None)
    return str(value) if value else None


def _dashscope_response_usage(response: Any) -> tuple[int, int]:
    usage = _get_attr_or_item(response, "usage", {}) or {}
    return (
        int(_get_attr_or_item(usage, "input_tokens", -1) or -1),
        int(_get_attr_or_item(usage, "output_tokens", -1) or -1),
    )


async def _send_qwen(
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
    """Send a request to Alibaba DashScope via the native dashscope SDK."""
    try:
        from dashscope import Generation
    except ImportError as e:
        raise RuntimeError("dashscope is not installed. Run `uv add dashscope`.") from e

    api_key = _read_required_env("DASHSCOPE_API_KEY", "Qwen/DashScope")
    _, provider_model = _split_model_id(model)
    full_messages = _full_messages(messages, system)

    kwargs: dict[str, Any] = {
        "api_key": api_key,
        "model": provider_model,
        "messages": full_messages,
        "result_format": "message",
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    explicit_base_url = os.getenv("DASHSCOPE_BASE_URL")
    if explicit_base_url:
        # Explicit URL override wins over region setting.
        kwargs["base_http_api_url"] = explicit_base_url
    else:
        region = (os.getenv("DASHSCOPE_REGION") or "cn").strip().lower()
        if region not in QWEN_NATIVE_BASE_URLS:
            valid = sorted(QWEN_NATIVE_BASE_URLS)
            raise RuntimeError(
                f"DASHSCOPE_REGION={region!r} is not a recognised region. "
                f"Valid options: {valid}. "
                "Set DASHSCOPE_BASE_URL to override with an explicit URL."
            )
        resolved_url = QWEN_NATIVE_BASE_URLS[region]
        if resolved_url is not None:
            kwargs["base_http_api_url"] = resolved_url
        # If resolved_url is None, omit the kwarg — let the SDK use its default.

    qwen_thinking = _env_bool("QWEN_THINKING")
    if qwen_thinking is not None:
        kwargs["enable_thinking"] = qwen_thinking
    qwen_budget = _read_optional_int_env("QWEN_THINKING_BUDGET")
    if qwen_budget is not None:
        kwargs["thinking_budget"] = qwen_budget
    qwen_preserve = _env_bool("QWEN_PRESERVE_THINKING")
    if qwen_preserve is not None:
        # qwen3.6-* uses preserve_thinking for multi-turn agentic flows.
        # Older models silently ignore it; safe to pass when explicitly set.
        kwargs["preserve_thinking"] = qwen_preserve

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        t0 = time.monotonic()
        try:
            response = await asyncio.to_thread(Generation.call, **kwargs)
            latency = round(time.monotonic() - t0, 3)
            status = _get_attr_or_item(response, "status_code", 200)
            if isinstance(status, int) and status >= 400:
                # DashScope returns errors as response objects, not exceptions.
                raise LLMProviderError(
                    f"DashScope returned status {status}: "
                    f"{_get_attr_or_item(response, 'message', '')}"
                )
            input_tokens, output_tokens = _dashscope_response_usage(response)
            return LLMResponse(
                content=_dashscope_response_content(response),
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_seconds=latency,
                finish_reason=_dashscope_response_finish_reason(response),
                response_id=_dashscope_response_id(response),
            )
        except Exception as e:  # noqa: BLE001
            # Qwen carve-out: LLMProviderError is intentional here — we raise
            # it ourselves above for DashScope's status_code>=400 error-as-
            # response pattern, and want it to participate in retries.
            if not _is_retryable(e) and not isinstance(e, LLMProviderError):
                raise
            last_exc = e
            if attempt < max_retries - 1:
                backoff = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                logger.warning("Qwen call failed (attempt %d/%d): %s; retrying in %ds",
                               attempt + 1, max_retries, e, backoff)
                await asyncio.sleep(backoff)
            else:
                logger.error("Qwen call exhausted retries: %s", e)
    raise LLMProviderError(f"qwen exhausted retries: {last_exc!r}") from last_exc


_GEMINI_ROLE_MAP = {"assistant": "model", "system": "user", "user": "user"}


async def _send_gemini(
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
    """Send a request to Google Gemini via the google-genai SDK."""
    try:
        from google import genai
        from google.genai import types as genai_types
    except ImportError as e:
        raise RuntimeError(
            "google-genai is not installed. Run `uv add google-genai`."
        ) from e

    # Auth: GEMINI_API_KEY (or GOOGLE_API_KEY as fallback). The SDK itself
    # respects either, but we read explicitly so we can fail with a clear msg.
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY (or GOOGLE_API_KEY) not set. Required for Gemini calls."
        )

    _, provider_model = _split_model_id(model)

    # Convert messages → list[Content]; system goes into config.system_instruction
    contents = []
    for msg in messages:
        role = _GEMINI_ROLE_MAP.get(msg.get("role", "user"), "user")
        contents.append(genai_types.Content(
            role=role,
            parts=[_gemini_text_part(genai_types, msg.get("content", ""))],
        ))

    config_kwargs: dict[str, Any] = {
        "system_instruction": system,
        "temperature": temperature,
        "max_output_tokens": max_tokens,
    }

    if provider_model.startswith("gemini-2.5"):
        budget = _read_optional_int_env("GEMINI_THINKING_BUDGET", allow_negative=True)
        if budget is not None:
            # 0 disables; -1 = dynamic; 0..32k = explicit cap.
            config_kwargs["thinking_config"] = genai_types.ThinkingConfig(
                thinking_budget=budget
            )
    elif provider_model.startswith("gemini-3"):
        level = os.getenv("GEMINI_THINKING_LEVEL")
        if level:
            if level not in {"minimal", "low", "medium", "high"}:
                raise RuntimeError(
                    "GEMINI_THINKING_LEVEL must be one of minimal|low|medium|high."
                )
            config_kwargs["thinking_config"] = genai_types.ThinkingConfig(
                thinking_level=level
            )

    config = genai_types.GenerateContentConfig(**config_kwargs)

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        t0 = time.monotonic()
        try:
            client = genai.Client(api_key=api_key)
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=provider_model,
                contents=contents,
                config=config,
            )
            latency = round(time.monotonic() - t0, 3)
            usage = _get_attr_or_item(response, "usage_metadata", None)
            input_tokens = int(_get_attr_or_item(usage, "prompt_token_count", -1) or -1) if usage else -1
            output_tokens = int(_get_attr_or_item(usage, "candidates_token_count", -1) or -1) if usage else -1
            candidates = _get_attr_or_item(response, "candidates", []) or []
            # finish_reason: handle enum (.value preferred), str, or None
            finish_reason = None
            if candidates:
                raw_reason = _get_attr_or_item(candidates[0], "finish_reason", None)
                if raw_reason is None:
                    finish_reason = None
                else:
                    # Enum members typically expose .value; fall back to .name, then str()
                    value = getattr(raw_reason, "value", None)
                    if isinstance(value, str):
                        finish_reason = value
                    else:
                        name = getattr(raw_reason, "name", None)
                        finish_reason = name if isinstance(name, str) else str(raw_reason)

            return LLMResponse(
                content=_get_attr_or_item(response, "text", "") or "",
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_seconds=latency,
                finish_reason=finish_reason,
                response_id=_get_attr_or_item(response, "response_id", None),
            )
        except Exception as e:  # noqa: BLE001
            if not _is_retryable(e):
                raise
            last_exc = e
            if attempt < max_retries - 1:
                backoff = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                logger.warning("Gemini call failed (attempt %d/%d): %s; retrying in %ds",
                               attempt + 1, max_retries, e, backoff)
                await asyncio.sleep(backoff)
            else:
                logger.error("Gemini call exhausted retries: %s", e)
    raise LLMProviderError(f"gemini exhausted retries: {last_exc!r}") from last_exc


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


async def _send_openrouter(
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
    """Send a request to OpenRouter via httpx (escape hatch).

    The model id must have the 'openrouter:' prefix; the suffix is sent
    verbatim as the OpenRouter model id (e.g. 'anthropic/claude-opus-4').
    """
    api_key = (os.getenv("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY not set. Required for openrouter:<model> calls. "
            "Get a key from https://openrouter.ai/keys"
        )
    if "..." in api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY still contains the placeholder. "
            "Replace with a real key from https://openrouter.ai/keys"
        )

    _, provider_model = _split_model_id(model)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/ashapeng/agentic-board",
        "X-Title": "Agentic Board",
    }
    payload = {
        "model": provider_model,
        "messages": _full_messages(messages, system),
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(OPENROUTER_URL, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
            latency = round(time.monotonic() - t0, 3)
            usage = data.get("usage", {}) or {}
            return LLMResponse(
                content=data["choices"][0]["message"]["content"],
                model=model,
                input_tokens=usage.get("prompt_tokens", -1),
                output_tokens=usage.get("completion_tokens", -1),
                latency_seconds=latency,
                finish_reason=data["choices"][0].get("finish_reason"),
                response_id=data.get("id"),
            )
        except Exception as e:  # noqa: BLE001
            if not _is_retryable(e):
                raise
            last_exc = e
            if attempt < max_retries - 1:
                backoff = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                logger.warning("OpenRouter call failed (attempt %d/%d): %s; retrying in %ds",
                               attempt + 1, max_retries, e, backoff)
                await asyncio.sleep(backoff)
            else:
                logger.error("OpenRouter call exhausted retries: %s", e)
    raise LLMProviderError(f"openrouter exhausted retries: {last_exc!r}") from last_exc


# ---------------------------------------------------------------------------
# Provider dispatch table
#
# Each entry: prefix -> async handler with signature
#     async def handler(model, messages, *, system, temperature, max_tokens,
#                       timeout, max_retries, backoff_seconds) -> LLMResponse
# ---------------------------------------------------------------------------

# Providers whose handlers accept the `tools=` / `tool_choice=` kwargs.
# Phase 1: Kimi + DeepSeek. Other providers will be wired in Phase 2.
TOOL_SUPPORTING_PREFIXES: set[str] = {"kimi", "moonshot", "deepseek"}

HandlerType = Callable[..., Awaitable[LLMResponse]]
_PROVIDERS: dict[str, HandlerType] = {
    "glm": _send_zai,
    "zai": _send_zai,
    "deepseek": _send_deepseek,
    "kimi": _send_kimi,
    "moonshot": _send_kimi,
    "qwen": _send_qwen,
    "gemini": _send_gemini,
    "openrouter": _send_openrouter,
}


# ---------------------------------------------------------------------------
# Free-first fallback chain
# ---------------------------------------------------------------------------

FREE_FALLBACKS: list[str] = [
    "gemini/gemini-2.5-flash",   # AI Studio free tier
    "glm/glm-4.5-flash",         # Z.AI free
    "qwen/qwen-flash",           # DashScope free quota (international region only)
]
PAID_LAST_RESORT = "deepseek/deepseek-chat"

_FREE_QWEN_REGIONS = {"international", "singapore"}

# Required env var per fallback model. None = handler reads env lazily and
# missing key is its own error; we only pre-skip when we KNOW it would fail.
_FALLBACK_KEY_ENVS: dict[str, list[str]] = {
    "gemini/gemini-2.5-flash": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    "glm/glm-4.5-flash": ["ZAI_API_KEY"],
    "qwen/qwen-flash": ["DASHSCOPE_API_KEY"],
    "deepseek/deepseek-chat": ["DEEPSEEK_API_KEY"],
}


def _has_any_env(names: list[str]) -> bool:
    return any(os.getenv(n) for n in names)


def _qwen_region_is_free() -> bool:
    region = (os.getenv("DASHSCOPE_REGION") or "cn").strip().lower()
    return region in _FREE_QWEN_REGIONS


def _fallback_eligible(fallback_model: str, primary_prefix: str) -> bool:
    """Return True if this fallback model should be attempted."""
    fb_prefix, _ = _split_model_id(fallback_model)
    if fb_prefix == primary_prefix:
        return False
    keys = _FALLBACK_KEY_ENVS.get(fallback_model, [])
    if keys and not _has_any_env(keys):
        return False
    if fallback_model == "qwen/qwen-flash" and not _qwen_region_is_free():
        return False
    return True


async def _dispatch_to_handler(
    prefix: str,
    model: str,
    messages: list[dict[str, str]],
    *,
    system: str | None,
    temperature: float,
    max_tokens: int,
    timeout: float,
    max_retries: int,
    backoff_seconds: list[int],
    tools: list[dict] | None = None,
    tool_choice: str = "auto",
) -> LLMResponse:
    """Dispatch a single call to the registered handler. Raises if no handler."""
    handler = _PROVIDERS.get(prefix)
    if handler is None:
        raise RuntimeError(
            f"unknown provider prefix: {prefix!r} for model {model!r}. "
            f"Known prefixes: {sorted(_PROVIDERS)}"
        )
    handler_kwargs = dict(
        system=system,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
    )
    if tools is not None and prefix in TOOL_SUPPORTING_PREFIXES:
        handler_kwargs["tools"] = tools
        handler_kwargs["tool_choice"] = tool_choice
    return await handler(model, messages, **handler_kwargs)


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------

async def query_llm(
    model: str,
    messages: list[dict[str, Any]],
    *,
    system: str | None = None,
    tools: list[dict] | None = None,
    tool_choice: str = "auto",
    temperature: float = 0.7,
    max_tokens: int = 8192,        # was 4096 — reasoning models need headroom
    timeout: float = 240.0,        # was 120.0 — deep reasoning takes 60-90s
    fallback: bool = True,
) -> LLMResponse:
    """Route a chat-completion request and apply the free-first fallback chain.

    See spec at docs/superpowers/specs/2026-04-25-llm-providers-refactor-design.md
    for the chain rules. The free-first chain walks
    [gemini-2.5-flash, glm-4.5-flash, qwen-flash] (skipping entries whose key
    isn't set, or that share the failed primary's provider, or — for qwen —
    when DASHSCOPE_REGION isn't a free-quota region), then escalates to
    `deepseek/deepseek-chat` as the paid last resort.

    Only `LLMProviderError` from a handler triggers the fallback chain; other
    exceptions propagate immediately.
    """
    primary_prefix, _ = _split_model_id(model)

    # Primary call — full retry budget
    primary_exc: LLMProviderError | None = None
    try:
        return await _dispatch_to_handler(
            primary_prefix, model, messages,
            system=system, temperature=temperature, max_tokens=max_tokens,
            timeout=timeout,
            max_retries=PRIMARY_MAX_RETRIES,
            backoff_seconds=PRIMARY_BACKOFF_SECONDS,
            tools=tools, tool_choice=tool_choice,
        )
    except LLMProviderError as e:
        primary_exc = e

    if not fallback:
        raise primary_exc

    # Free-first fallback chain
    last_fallback_exc: Exception | None = None
    for fb_model in FREE_FALLBACKS:
        if not _fallback_eligible(fb_model, primary_prefix):
            continue
        fb_prefix, _ = _split_model_id(fb_model)
        try:
            logger.warning("Primary %s failed; trying free fallback %s",
                           model, fb_model)
            return await _dispatch_to_handler(
                fb_prefix, fb_model, messages,
                system=system, temperature=temperature, max_tokens=max_tokens,
                timeout=timeout,
                max_retries=FALLBACK_MAX_RETRIES,
                backoff_seconds=FALLBACK_BACKOFF_SECONDS,
                tools=tools, tool_choice=tool_choice,
            )
        except LLMProviderError as e:
            last_fallback_exc = e
            continue

    # Paid last resort
    if _fallback_eligible(PAID_LAST_RESORT, primary_prefix):
        try:
            logger.warning("Free fallbacks exhausted for %s; trying paid %s",
                           model, PAID_LAST_RESORT)
            paid_prefix, _ = _split_model_id(PAID_LAST_RESORT)
            return await _dispatch_to_handler(
                paid_prefix, PAID_LAST_RESORT, messages,
                system=system, temperature=temperature, max_tokens=max_tokens,
                timeout=timeout,
                max_retries=FALLBACK_MAX_RETRIES,
                backoff_seconds=FALLBACK_BACKOFF_SECONDS,
                tools=tools, tool_choice=tool_choice,
            )
        except LLMProviderError as e:
            last_fallback_exc = e

    # Re-raise primary, chained from last fallback (if any distinct fallback failed)
    if last_fallback_exc is not None and last_fallback_exc is not primary_exc:
        raise primary_exc from last_fallback_exc
    raise primary_exc


async def _stream_deepseek(
    model: str,
    messages: list[dict[str, str]],
    *,
    system: str | None,
    temperature: float,
    max_tokens: int,
    timeout: float,
    fallback: bool,
) -> AsyncIterator[LLMStreamChunk]:
    del fallback
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("openai is not installed. Run `uv add openai`.") from e

    api_key = _read_required_env("DEEPSEEK_API_KEY", "DeepSeek")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    _, provider_model = _split_model_id(model)
    kwargs: dict[str, Any] = {
        "model": provider_model,
        "messages": _full_messages(messages, system),
        "max_tokens": max_tokens,
        "stream": True,
    }
    if provider_model not in {"deepseek-reasoner", "deepseek-v4-pro"}:
        kwargs["temperature"] = temperature
    if provider_model.startswith("deepseek-v4-"):
        effort = os.getenv("DEEPSEEK_REASONING_EFFORT")
        if effort:
            if effort not in {"low", "medium", "high", "max"}:
                raise RuntimeError(
                    "DEEPSEEK_REASONING_EFFORT must be one of low|medium|high|max."
                )
            kwargs["reasoning_effort"] = effort

    async for chunk in _stream_openai_compatible(
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        kwargs=kwargs,
    ):
        yield chunk


async def _stream_kimi(
    model: str,
    messages: list[dict[str, str]],
    *,
    system: str | None,
    temperature: float,
    max_tokens: int,
    timeout: float,
    fallback: bool,
) -> AsyncIterator[LLMStreamChunk]:
    del fallback
    try:
        from openai import OpenAI
    except ImportError as e:
        raise RuntimeError("openai is not installed. Run `uv add openai`.") from e

    api_key = _read_required_env("MOONSHOT_API_KEY", "Kimi/Moonshot")
    base_url = os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1")
    _, provider_model = _split_model_id(model)
    kwargs: dict[str, Any] = {
        "model": provider_model,
        "messages": _full_messages(messages, system),
        "max_tokens": max_tokens,
        "stream": True,
    }
    if provider_model.startswith("kimi-k2-thinking"):
        kwargs["temperature"] = 1.0
    elif provider_model.startswith(("kimi-k2.5", "kimi-k2.6")):
        pass
    else:
        kwargs["temperature"] = temperature

    thinking = _env_bool("KIMI_THINKING")
    if thinking is not None:
        kwargs["extra_body"] = {"thinking": {"type": "enabled" if thinking else "disabled"}}

    async for chunk in _stream_openai_compatible(
        model=model,
        api_key=api_key,
        base_url=base_url,
        timeout=timeout,
        kwargs=kwargs,
    ):
        yield chunk


async def _stream_openai_compatible(
    *,
    model: str,
    api_key: str,
    base_url: str,
    timeout: float,
    kwargs: dict[str, Any],
) -> AsyncIterator[LLMStreamChunk]:
    from openai import OpenAI

    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[Any] = asyncio.Queue()

    def worker() -> None:
        content = ""
        finish_reason = None
        response_id = None
        t0 = time.monotonic()
        try:
            client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
            stream = client.chat.completions.create(**kwargs)
            for raw_chunk in stream:
                response_id = _openai_shape_response_id(raw_chunk) or response_id
                delta, chunk_finish = _openai_stream_delta(raw_chunk)
                finish_reason = chunk_finish or finish_reason
                if not delta:
                    continue
                content += delta
                loop.call_soon_threadsafe(
                    queue.put_nowait,
                    LLMStreamChunk(
                        delta=delta,
                        content=content,
                        model=model,
                        response_id=response_id,
                        simulated_stream=False,
                    ),
                )
            loop.call_soon_threadsafe(
                queue.put_nowait,
                LLMStreamChunk(
                    content=content,
                    done=True,
                    model=model,
                    input_tokens=-1,
                    output_tokens=-1,
                    latency_seconds=round(time.monotonic() - t0, 3),
                    finish_reason=finish_reason,
                    response_id=response_id,
                    simulated_stream=False,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            loop.call_soon_threadsafe(queue.put_nowait, exc)

    task = asyncio.create_task(asyncio.to_thread(worker))
    try:
        while True:
            item = await queue.get()
            if isinstance(item, Exception):
                raise item
            yield item
            if item.done:
                break
    finally:
        await task


def _openai_stream_delta(chunk: Any) -> tuple[str, str | None]:
    choices = _get_attr_or_item(chunk, "choices") or []
    if not choices:
        return "", None
    choice = choices[0]
    delta_obj = _get_attr_or_item(choice, "delta", {}) or {}
    delta = _get_attr_or_item(delta_obj, "content", "") or ""
    finish_reason = _get_attr_or_item(choice, "finish_reason", None)
    return str(delta), finish_reason


_STREAM_HANDLERS: dict[str, Callable[..., AsyncIterator[LLMStreamChunk]]] = {
    "deepseek": _stream_deepseek,
    "kimi": _stream_kimi,
}


async def query_llm_stream(
    model: str,
    messages: list[dict[str, str]],
    *,
    system: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 8192,
    timeout: float = 240.0,
    fallback: bool = True,
) -> AsyncIterator[LLMStreamChunk]:
    """Stream an LLM response.

    Provider-native streaming is intentionally isolated behind this public
    surface. The first implementation keeps all existing provider handlers
    compatible by falling back to a simulated token stream from `query_llm()`;
    callers still receive incremental deltas and a final metadata chunk.
    """
    primary_prefix, _ = _split_model_id(model)
    stream_handler = _STREAM_HANDLERS.get(primary_prefix)
    if stream_handler:
        try:
            async for chunk in stream_handler(
                model,
                messages,
                system=system,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                fallback=fallback,
            ):
                yield chunk
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Native stream for %s failed; falling back to simulated stream: %s",
                model,
                exc,
            )

    response = await query_llm(
        model,
        messages,
        system=system,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        fallback=fallback,
    )

    content = response.content or ""
    cumulative = ""
    for delta in _simulated_stream_deltas(content):
        cumulative += delta
        yield LLMStreamChunk(
            delta=delta,
            content=cumulative,
            model=response.model,
            simulated_stream=True,
        )
        await asyncio.sleep(0)

    yield LLMStreamChunk(
        content=content,
        done=True,
        model=response.model,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        latency_seconds=response.latency_seconds,
        finish_reason=response.finish_reason,
        response_id=response.response_id,
        simulated_stream=True,
    )


def _simulated_stream_deltas(content: str, *, target_chars: int = 48) -> list[str]:
    """Split completed content into small stable deltas for stream consumers."""
    if not content:
        return []
    return [
        content[index:index + target_chars]
        for index in range(0, len(content), target_chars)
    ]
