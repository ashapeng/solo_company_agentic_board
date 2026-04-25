# LLM Providers Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace OpenRouter-as-default in `server/board/llm.py` with five first-class native providers (Qwen, DeepSeek, Moonshot/Kimi, Z.AI/GLM, Gemini); make OpenRouter opt-in via `openrouter:` prefix; reshape fallback to walk free-tier models first with one paid last resort.

**Architecture:** Single-file router (`server/board/llm.py`) keeps `query_llm()` as the public entry. Each provider gets its own `_send_<name>` handler, dispatched via a `_PROVIDERS` prefix table. Native SDKs for Gemini (`google-genai`), Z.AI (`zai-sdk`), Qwen (`dashscope`); OpenAI-compatible SDK (`openai`) for DeepSeek and Kimi; `httpx` for OpenRouter escape hatch. Fallback walks `[gemini-2.5-flash, glm-4.5-flash, qwen-flash]` (free) then `deepseek-chat` (paid) — skipping entries when key missing or same-provider as the failed primary.

**Tech Stack:** Python 3.11+, `uv` package manager, `pytest` (mixed unittest/pytest in this repo), `httpx`, `openai`, `dashscope`, `zai-sdk`, `google-genai`.

**Reference spec:** `docs/superpowers/specs/2026-04-25-llm-providers-refactor-design.md`

---

## File Structure

**Modify:**
- `server/board/llm.py` — full rewrite (router + 6 handlers + free-first fallback)
- `server/board/metrics.py:20-40` — add native-prefix pricing rows
- `server/harness/config_provider.py:9-17` — docstring tweak (add gemini example)
- `pyproject.toml` — add `google-genai>=1.0,<2.0`
- `.env.example` — add `GEMINI_API_KEY`, document Qwen region, update Moonshot URL

**Create:**
- `tests/test_llm_routing.py` — prefix dispatch unit tests
- `tests/test_llm_fallback.py` — free-first chain behavior
- `tests/test_llm_gemini.py` — handler unit tests
- `tests/test_llm_zai.py`
- `tests/test_llm_qwen.py`
- `tests/test_llm_deepseek.py`
- `tests/test_llm_kimi.py`
- `tests/test_llm_openrouter.py`
- `tests/test_llm_live_smoke.py` — opt-in live tests (skipped by default)

**Audit (no expected changes):**
- `server/members/*.md` — verify any `model_override` values use a known prefix
- `server/harness/replay.py` — confirm monkey-patch still hits `query_llm`

---

## Task 1: Add `google-genai` dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the dependency to `pyproject.toml`**

Open `pyproject.toml`. In the `[project] dependencies = [...]` block, add the `google-genai` line so the block becomes:

```toml
dependencies = [
    "httpx>=0.27",
    "fastapi>=0.115",
    "uvicorn>=0.34",
    "python-dotenv>=1.0",
    "rich>=13.9",
    "pydantic>=2.10",
    "pyyaml>=6.0",
    "openai>=1.0",
    "dashscope>=1.20",
    "zai-sdk>=0.2.2",
    "google-genai>=1.0,<2.0",
]
```

- [ ] **Step 2: Sync the lockfile**

Run:

```bash
uv sync
```

Expected: `uv` resolves and installs `google-genai`. No errors.

- [ ] **Step 3: Verify import works**

Run:

```bash
uv run python -c "from google import genai; print(genai.__name__)"
```

Expected output: `google.genai`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add google-genai for native Gemini support"
```

---

## Task 2: Rewrite `llm.py` skeleton — router, error type, empty `_PROVIDERS`

This is the foundational rewrite. The new `query_llm` dispatches via `_PROVIDERS` table (initially empty); unknown prefixes raise `RuntimeError`. Old code (`_send_native_request`, `_send_llm_request`, `_send_zai_request_sync`, `_send_openai_compatible_request_sync`, `FALLBACK_MODELS`, `NATIVE_PROVIDER_PREFIXES`) is deleted. Handlers come in subsequent tasks.

**Files:**
- Modify: `server/board/llm.py` (full rewrite to skeleton)
- Create: `tests/test_llm_routing.py`

- [ ] **Step 1: Write failing routing tests**

Create `tests/test_llm_routing.py` with the full content:

```python
"""Routing-layer unit tests for query_llm prefix dispatch."""
from __future__ import annotations

import pytest

from server.board import llm


@pytest.mark.asyncio
async def test_query_llm_unknown_prefix_raises():
    with pytest.raises(RuntimeError, match="unknown provider prefix"):
        await llm.query_llm("totallymadeup/foo", [{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_query_llm_bare_id_no_prefix_raises():
    """Bare 'provider/model' with no recognized native prefix must error
    rather than silently route to OpenRouter (the old default)."""
    with pytest.raises(RuntimeError, match="unknown provider prefix"):
        await llm.query_llm("anthropic/claude-opus-4", [{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
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
```

- [ ] **Step 2: Install pytest-asyncio if missing**

Check whether `pytest-asyncio` is already a dev dep:

```bash
grep -E "pytest-asyncio|anyio" pyproject.toml || echo "missing"
```

If it prints `missing`, add it as a dev dependency:

```bash
uv add --dev pytest-asyncio
```

Then add this `[tool.pytest.ini_options]` block at the bottom of `pyproject.toml` if it doesn't already exist:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

If a `[tool.pytest.ini_options]` block already exists, just add `asyncio_mode = "auto"` to it (don't duplicate).

- [ ] **Step 3: Run the failing tests**

Run:

```bash
uv run pytest tests/test_llm_routing.py -v
```

Expected: all tests fail (the new module shape doesn't exist yet — `_PROVIDERS` missing, `LLMProviderError` missing, unknown prefixes don't raise the expected message).

- [ ] **Step 4: Rewrite `server/board/llm.py` to the new skeleton**

Replace the **entire contents** of `server/board/llm.py` with:

```python
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
```

- [ ] **Step 5: Run the routing tests — verify pass**

Run:

```bash
uv run pytest tests/test_llm_routing.py -v
```

Expected: all 5 tests pass.

- [ ] **Step 6: Run the existing test suite — confirm scope of breakage**

Run:

```bash
uv run pytest tests/ -x --ignore=tests/test_llm_routing.py 2>&1 | tail -40
```

Expected: failures in tests that import or call into `query_llm` for live provider calls (these will resolve as Tasks 3-8 add handlers). Note any test names that fail so they can be re-checked at Task 15.

- [ ] **Step 7: Commit**

```bash
git add server/board/llm.py tests/test_llm_routing.py pyproject.toml uv.lock
git commit -m "refactor(llm): scaffold prefix-routed handler table

Replace OpenRouter-as-default with a dispatch table; unknown prefix raises.
LLMProviderError introduced for retryable failures. Per-provider handlers
land in follow-up tasks; fallback chain in Task 9."
```

---

## Task 3: Implement `_send_zai` handler

Re-add Z.AI/GLM via `zai-sdk`, async-wrapping the sync client. Mostly carries forward the existing logic.

**Files:**
- Modify: `server/board/llm.py`
- Create: `tests/test_llm_zai.py`

- [ ] **Step 1: Write failing handler tests**

Create `tests/test_llm_zai.py`:

```python
"""Unit tests for the Z.AI / GLM handler."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from server.board import llm


def _fake_zai_response():
    return SimpleNamespace(
        id="resp-zai-1",
        choices=[SimpleNamespace(
            message=SimpleNamespace(content="hello from zai"),
            finish_reason="stop",
        )],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=4),
    )


class _FakeCompletions:
    def __init__(self):
        self.create = MagicMock(return_value=_fake_zai_response())


class _FakeChat:
    def __init__(self):
        self.completions = _FakeCompletions()


class _FakeZaiClient:
    last_init_kwargs = None
    last_create_kwargs = None

    def __init__(self, **kwargs):
        type(self).last_init_kwargs = kwargs
        self.chat = _FakeChat()


@pytest.mark.asyncio
async def test_zai_routes_via_prefix(monkeypatch):
    monkeypatch.setenv("ZAI_API_KEY", "zai-test")

    fake_module = SimpleNamespace(ZaiClient=_FakeZaiClient)
    with patch.dict("sys.modules", {"zai": fake_module}):
        resp = await llm.query_llm(
            "glm/glm-4.6",
            [{"role": "user", "content": "hi"}],
            system="be terse",
            temperature=0.5,
            max_tokens=256,
        )

    assert resp.content == "hello from zai"
    assert resp.model == "glm/glm-4.6"  # original id, not provider-local
    assert resp.input_tokens == 11
    assert resp.output_tokens == 4
    assert resp.finish_reason == "stop"

    create_kwargs = _FakeZaiClient.last_create_kwargs = (
        _FakeZaiClient.__dict__.get("last_create_kwargs")
    )
    # The handler stores .last_create_kwargs on the instance via the chat client


@pytest.mark.asyncio
async def test_zai_thinking_passthrough(monkeypatch):
    monkeypatch.setenv("ZAI_API_KEY", "zai-test")
    monkeypatch.setenv("ZAI_THINKING", "enabled")

    captured = {}

    class _Cli:
        def __init__(self, **kwargs):
            captured["init"] = kwargs
            self.chat = SimpleNamespace(completions=SimpleNamespace(
                create=lambda **kw: (captured.setdefault("create", kw), _fake_zai_response())[1]
            ))

    fake_module = SimpleNamespace(ZaiClient=_Cli)
    with patch.dict("sys.modules", {"zai": fake_module}):
        await llm.query_llm("zai/glm-4.5-air", [{"role": "user", "content": "hi"}])

    assert captured["create"]["thinking"] == {"type": "enabled"}


@pytest.mark.asyncio
async def test_zai_missing_key_raises(monkeypatch):
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    fake_module = SimpleNamespace(ZaiClient=_FakeZaiClient)
    with patch.dict("sys.modules", {"zai": fake_module}):
        with pytest.raises(RuntimeError, match="ZAI_API_KEY"):
            await llm.query_llm("glm/glm-4.6", [{"role": "user", "content": "hi"}])
```

- [ ] **Step 2: Run tests, verify failure**

Run:

```bash
uv run pytest tests/test_llm_zai.py -v
```

Expected: tests fail because `glm/` prefix isn't registered yet (`unknown provider prefix: 'glm'`).

- [ ] **Step 3: Add `_send_zai` handler to `llm.py`**

Append the following code to `server/board/llm.py` **before** the `_PROVIDERS: dict[str, HandlerType] = {}` line (or replace that line as shown below):

```python
import asyncio
import time
from typing import Any


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
            last_exc = e
            if attempt < max_retries - 1:
                backoff = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                logger.warning("Z.AI call failed (attempt %d/%d): %s; retrying in %ds",
                               attempt + 1, max_retries, e, backoff)
                await asyncio.sleep(backoff)
            else:
                logger.error("Z.AI call exhausted retries: %s", e)
    raise LLMProviderError(f"zai exhausted retries: {last_exc!r}") from last_exc
```

Then update the `_PROVIDERS` dict to register both prefixes:

```python
_PROVIDERS: dict[str, HandlerType] = {
    "glm": _send_zai,
    "zai": _send_zai,
}
```

- [ ] **Step 4: Run handler tests — verify pass**

Run:

```bash
uv run pytest tests/test_llm_zai.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Run routing tests — confirm still green**

Run:

```bash
uv run pytest tests/test_llm_routing.py tests/test_llm_zai.py -v
```

Expected: all 8 tests pass.

- [ ] **Step 6: Commit**

```bash
git add server/board/llm.py tests/test_llm_zai.py
git commit -m "feat(llm): add native Z.AI/GLM handler via zai-sdk"
```

---

## Task 4: Implement `_send_deepseek` handler

DeepSeek via OpenAI SDK at `https://api.deepseek.com/v1`. Skips `temperature` for `deepseek-reasoner`.

**Files:**
- Modify: `server/board/llm.py`
- Create: `tests/test_llm_deepseek.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_llm_deepseek.py`:

```python
"""Unit tests for the DeepSeek handler."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from server.board import llm


def _fake_oai_response():
    return SimpleNamespace(
        id="resp-ds-1",
        choices=[SimpleNamespace(
            message=SimpleNamespace(content="ok"),
            finish_reason="stop",
        )],
        usage=SimpleNamespace(prompt_tokens=7, completion_tokens=2),
    )


class _FakeOpenAI:
    last_init: dict | None = None
    last_create: dict | None = None

    def __init__(self, **kwargs):
        type(self).last_init = kwargs
        self.chat = SimpleNamespace(completions=SimpleNamespace(
            create=lambda **kw: (type(self)._record_create(kw), _fake_oai_response())[1]
        ))

    @classmethod
    def _record_create(cls, kw):
        cls.last_create = kw


@pytest.mark.asyncio
async def test_deepseek_chat_passes_temperature(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")

    fake_openai = SimpleNamespace(OpenAI=_FakeOpenAI)
    with patch.dict("sys.modules", {"openai": fake_openai}):
        resp = await llm.query_llm(
            "deepseek/deepseek-chat",
            [{"role": "user", "content": "hi"}],
            temperature=0.4,
            max_tokens=128,
        )
    assert resp.content == "ok"
    assert _FakeOpenAI.last_init["base_url"] == "https://api.deepseek.com/v1"
    assert _FakeOpenAI.last_create["model"] == "deepseek-chat"
    assert _FakeOpenAI.last_create["temperature"] == 0.4


@pytest.mark.asyncio
async def test_deepseek_reasoner_omits_temperature(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")
    fake_openai = SimpleNamespace(OpenAI=_FakeOpenAI)
    with patch.dict("sys.modules", {"openai": fake_openai}):
        await llm.query_llm(
            "deepseek/deepseek-reasoner",
            [{"role": "user", "content": "hi"}],
            temperature=0.7,
        )
    assert "temperature" not in _FakeOpenAI.last_create


@pytest.mark.asyncio
async def test_deepseek_missing_key_raises(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    fake_openai = SimpleNamespace(OpenAI=_FakeOpenAI)
    with patch.dict("sys.modules", {"openai": fake_openai}):
        with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
            await llm.query_llm("deepseek/deepseek-chat", [{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_deepseek_base_url_override(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "ds-test")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://example.test/v1")
    fake_openai = SimpleNamespace(OpenAI=_FakeOpenAI)
    with patch.dict("sys.modules", {"openai": fake_openai}):
        await llm.query_llm("deepseek/deepseek-chat", [{"role": "user", "content": "hi"}])
    assert _FakeOpenAI.last_init["base_url"] == "https://example.test/v1"
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/test_llm_deepseek.py -v
```

Expected: failures with `unknown provider prefix: 'deepseek'`.

- [ ] **Step 3: Add `_send_deepseek` to `llm.py`**

Append after the `_send_zai` definition:

```python
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
            last_exc = e
            if attempt < max_retries - 1:
                backoff = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                logger.warning("DeepSeek call failed (attempt %d/%d): %s; retrying in %ds",
                               attempt + 1, max_retries, e, backoff)
                await asyncio.sleep(backoff)
            else:
                logger.error("DeepSeek call exhausted retries: %s", e)
    raise LLMProviderError(f"deepseek exhausted retries: {last_exc!r}") from last_exc
```

Update `_PROVIDERS` to add the entry:

```python
_PROVIDERS: dict[str, HandlerType] = {
    "glm": _send_zai,
    "zai": _send_zai,
    "deepseek": _send_deepseek,
}
```

- [ ] **Step 4: Run, verify pass**

```bash
uv run pytest tests/test_llm_deepseek.py tests/test_llm_routing.py tests/test_llm_zai.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add server/board/llm.py tests/test_llm_deepseek.py
git commit -m "feat(llm): add native DeepSeek handler via openai SDK"
```

---

## Task 5: Implement `_send_kimi` handler

Kimi via OpenAI SDK at `https://api.moonshot.ai/v1` (note `.ai`, not `.cn`). Preserves K2.5 / K2-thinking temperature rules.

**Files:**
- Modify: `server/board/llm.py`
- Create: `tests/test_llm_kimi.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_llm_kimi.py`:

```python
"""Unit tests for the Kimi/Moonshot handler."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from server.board import llm


def _fake_oai_response():
    return SimpleNamespace(
        id="resp-kimi-1",
        choices=[SimpleNamespace(
            message=SimpleNamespace(content="ok"),
            finish_reason="stop",
        )],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=2),
    )


class _FakeOpenAI:
    last_init: dict | None = None
    last_create: dict | None = None

    def __init__(self, **kwargs):
        type(self).last_init = kwargs
        self.chat = SimpleNamespace(completions=SimpleNamespace(
            create=lambda **kw: (type(self)._record(kw), _fake_oai_response())[1]
        ))

    @classmethod
    def _record(cls, kw):
        cls.last_create = kw


@pytest.mark.asyncio
async def test_kimi_default_base_url_is_dot_ai(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "kimi-test")
    monkeypatch.delenv("MOONSHOT_BASE_URL", raising=False)
    with patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=_FakeOpenAI)}):
        await llm.query_llm("kimi/kimi-k2.6", [{"role": "user", "content": "hi"}])
    assert _FakeOpenAI.last_init["base_url"] == "https://api.moonshot.ai/v1"


@pytest.mark.asyncio
async def test_kimi_k2_5_omits_temperature(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "kimi-test")
    with patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=_FakeOpenAI)}):
        await llm.query_llm(
            "kimi/kimi-k2.5",
            [{"role": "user", "content": "hi"}],
            temperature=0.7,
        )
    assert "temperature" not in _FakeOpenAI.last_create


@pytest.mark.asyncio
async def test_kimi_k2_thinking_forces_one(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "kimi-test")
    with patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=_FakeOpenAI)}):
        await llm.query_llm(
            "kimi/kimi-k2-thinking-preview",
            [{"role": "user", "content": "hi"}],
            temperature=0.3,
        )
    assert _FakeOpenAI.last_create["temperature"] == 1.0


@pytest.mark.asyncio
async def test_kimi_other_model_passes_temperature(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "kimi-test")
    with patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=_FakeOpenAI)}):
        await llm.query_llm(
            "kimi/kimi-k2.6",
            [{"role": "user", "content": "hi"}],
            temperature=0.5,
        )
    assert _FakeOpenAI.last_create["temperature"] == 0.5


@pytest.mark.asyncio
async def test_kimi_thinking_env(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "kimi-test")
    monkeypatch.setenv("KIMI_THINKING", "enabled")
    with patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=_FakeOpenAI)}):
        await llm.query_llm("kimi/kimi-k2.6", [{"role": "user", "content": "hi"}])
    assert _FakeOpenAI.last_create["extra_body"] == {"thinking": {"type": "enabled"}}


@pytest.mark.asyncio
async def test_moonshot_prefix_alias(monkeypatch):
    """The 'moonshot/' prefix routes to the same handler."""
    monkeypatch.setenv("MOONSHOT_API_KEY", "kimi-test")
    with patch.dict("sys.modules", {"openai": SimpleNamespace(OpenAI=_FakeOpenAI)}):
        resp = await llm.query_llm("moonshot/kimi-k2.6", [{"role": "user", "content": "hi"}])
    assert resp.content == "ok"
    assert _FakeOpenAI.last_create["model"] == "kimi-k2.6"
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/test_llm_kimi.py -v
```

Expected: failures with `unknown provider prefix: 'kimi'` / `'moonshot'`.

- [ ] **Step 3: Add `_send_kimi` to `llm.py`**

Append after `_send_deepseek`:

```python
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
            last_exc = e
            if attempt < max_retries - 1:
                backoff = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                logger.warning("Kimi call failed (attempt %d/%d): %s; retrying in %ds",
                               attempt + 1, max_retries, e, backoff)
                await asyncio.sleep(backoff)
            else:
                logger.error("Kimi call exhausted retries: %s", e)
    raise LLMProviderError(f"kimi exhausted retries: {last_exc!r}") from last_exc
```

Update `_PROVIDERS`:

```python
_PROVIDERS: dict[str, HandlerType] = {
    "glm": _send_zai,
    "zai": _send_zai,
    "deepseek": _send_deepseek,
    "kimi": _send_kimi,
    "moonshot": _send_kimi,
}
```

- [ ] **Step 4: Run, verify pass**

```bash
uv run pytest tests/test_llm_kimi.py -v
```

Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add server/board/llm.py tests/test_llm_kimi.py
git commit -m "feat(llm): add native Kimi/Moonshot handler with .ai base URL"
```

---

## Task 6: Implement `_send_qwen` handler (native dashscope)

Native `dashscope` SDK (replaces the previous OpenAI-compatible Qwen path).

**Files:**
- Modify: `server/board/llm.py`
- Create: `tests/test_llm_qwen.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_llm_qwen.py`:

```python
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_qwen_missing_key_raises(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    fake_module = SimpleNamespace(Generation=_FakeGeneration)
    with patch.dict("sys.modules", {"dashscope": fake_module}):
        with pytest.raises(RuntimeError, match="DASHSCOPE_API_KEY"):
            await llm.query_llm("qwen/qwen-flash", [{"role": "user", "content": "hi"}])
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/test_llm_qwen.py -v
```

Expected: failures (`unknown provider prefix: 'qwen'`).

- [ ] **Step 3: Add `_send_qwen` to `llm.py`**

Append after `_send_kimi`:

```python
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
    base_url = os.getenv("DASHSCOPE_BASE_URL")
    if base_url:
        kwargs["base_http_api_url"] = base_url

    qwen_thinking = _env_bool("QWEN_THINKING")
    if qwen_thinking is not None:
        kwargs["enable_thinking"] = qwen_thinking
    qwen_budget = _read_optional_int_env("QWEN_THINKING_BUDGET")
    if qwen_budget is not None:
        kwargs["thinking_budget"] = qwen_budget

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        t0 = time.monotonic()
        try:
            response = await asyncio.to_thread(Generation.call, **kwargs)
            latency = round(time.monotonic() - t0, 3)
            status = _get_attr_or_item(response, "status_code", 200)
            if status >= 400:
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
            last_exc = e
            if attempt < max_retries - 1:
                backoff = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                logger.warning("Qwen call failed (attempt %d/%d): %s; retrying in %ds",
                               attempt + 1, max_retries, e, backoff)
                await asyncio.sleep(backoff)
            else:
                logger.error("Qwen call exhausted retries: %s", e)
    raise LLMProviderError(f"qwen exhausted retries: {last_exc!r}") from last_exc
```

Update `_PROVIDERS`:

```python
_PROVIDERS: dict[str, HandlerType] = {
    "glm": _send_zai,
    "zai": _send_zai,
    "deepseek": _send_deepseek,
    "kimi": _send_kimi,
    "moonshot": _send_kimi,
    "qwen": _send_qwen,
}
```

- [ ] **Step 4: Run, verify pass**

```bash
uv run pytest tests/test_llm_qwen.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add server/board/llm.py tests/test_llm_qwen.py
git commit -m "feat(llm): add native Qwen handler via dashscope SDK"
```

---

## Task 7: Implement `_send_gemini` handler

Gemini via `google-genai`. System prompt routes to `config.system_instruction`. Roles map: `assistant → "model"`, others → `"user"`.

**Files:**
- Modify: `server/board/llm.py`
- Create: `tests/test_llm_gemini.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_llm_gemini.py`:

```python
"""Unit tests for the Gemini handler."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from server.board import llm


class _FakeContent:
    def __init__(self, *, role, parts):
        self.role = role
        self.parts = parts


class _FakePart:
    def __init__(self, *, text):
        self.text = text


class _FakeGenerateContentConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


_FAKE_TYPES = SimpleNamespace(
    Content=lambda role, parts: _FakeContent(role=role, parts=parts),
    Part=SimpleNamespace(from_text=lambda text: _FakePart(text=text)),
    GenerateContentConfig=_FakeGenerateContentConfig,
)


def _fake_gemini_response():
    return SimpleNamespace(
        text="hello from gemini",
        candidates=[SimpleNamespace(finish_reason="STOP")],
        usage_metadata=SimpleNamespace(
            prompt_token_count=12,
            candidates_token_count=5,
        ),
    )


class _FakeModels:
    last_kwargs: dict | None = None

    def generate_content(self, **kwargs):
        type(self).last_kwargs = kwargs
        return _fake_gemini_response()


class _FakeClient:
    last_init_kwargs: dict | None = None

    def __init__(self, **kwargs):
        type(self).last_init_kwargs = kwargs
        self.models = _FakeModels()


@pytest.mark.asyncio
async def test_gemini_basic(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gem-test")
    fake_genai = SimpleNamespace(Client=_FakeClient, types=_FAKE_TYPES)
    fake_google = SimpleNamespace(genai=fake_genai)
    with patch.dict("sys.modules", {
        "google": fake_google,
        "google.genai": fake_genai,
    }):
        resp = await llm.query_llm(
            "gemini/gemini-2.5-flash",
            [{"role": "user", "content": "hi"}],
            system="be terse",
            temperature=0.6,
            max_tokens=200,
        )
    assert resp.content == "hello from gemini"
    assert resp.input_tokens == 12
    assert resp.output_tokens == 5
    kw = _FakeModels.last_kwargs
    assert kw["model"] == "gemini-2.5-flash"
    # System routes to config, not into contents
    assert isinstance(kw["config"], _FakeGenerateContentConfig)
    assert kw["config"].kwargs["system_instruction"] == "be terse"
    assert kw["config"].kwargs["temperature"] == 0.6
    assert kw["config"].kwargs["max_output_tokens"] == 200
    # contents has only the user message (no system entry)
    contents = kw["contents"]
    assert len(contents) == 1
    assert contents[0].role == "user"


@pytest.mark.asyncio
async def test_gemini_assistant_role_maps_to_model(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gem-test")
    fake_genai = SimpleNamespace(Client=_FakeClient, types=_FAKE_TYPES)
    fake_google = SimpleNamespace(genai=fake_genai)
    with patch.dict("sys.modules", {
        "google": fake_google,
        "google.genai": fake_genai,
    }):
        await llm.query_llm(
            "gemini/gemini-2.5-flash",
            [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "second"},
                {"role": "user", "content": "third"},
            ],
        )
    contents = _FakeModels.last_kwargs["contents"]
    assert [c.role for c in contents] == ["user", "model", "user"]


@pytest.mark.asyncio
async def test_gemini_uses_google_api_key_fallback(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "gkey")
    fake_genai = SimpleNamespace(Client=_FakeClient, types=_FAKE_TYPES)
    fake_google = SimpleNamespace(genai=fake_genai)
    with patch.dict("sys.modules", {
        "google": fake_google,
        "google.genai": fake_genai,
    }):
        await llm.query_llm("gemini/gemini-2.5-flash", [{"role": "user", "content": "hi"}])
    # Should not have raised
    assert _FakeClient.last_init_kwargs is not None


@pytest.mark.asyncio
async def test_gemini_missing_both_keys_raises(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    fake_genai = SimpleNamespace(Client=_FakeClient, types=_FAKE_TYPES)
    fake_google = SimpleNamespace(genai=fake_genai)
    with patch.dict("sys.modules", {
        "google": fake_google,
        "google.genai": fake_genai,
    }):
        with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
            await llm.query_llm("gemini/gemini-2.5-flash", [{"role": "user", "content": "hi"}])
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/test_llm_gemini.py -v
```

Expected: failures (`unknown provider prefix: 'gemini'`).

- [ ] **Step 3: Add `_send_gemini` to `llm.py`**

Append after `_send_qwen`:

```python
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
            parts=[genai_types.Part.from_text(msg.get("content", ""))],
        ))

    config = genai_types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        max_output_tokens=max_tokens,
    )

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
            finish_reason = (
                str(_get_attr_or_item(candidates[0], "finish_reason", None))
                if candidates else None
            )
            return LLMResponse(
                content=_get_attr_or_item(response, "text", "") or "",
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_seconds=latency,
                finish_reason=finish_reason,
                response_id=None,  # google-genai doesn't surface a request id
            )
        except Exception as e:  # noqa: BLE001
            last_exc = e
            if attempt < max_retries - 1:
                backoff = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                logger.warning("Gemini call failed (attempt %d/%d): %s; retrying in %ds",
                               attempt + 1, max_retries, e, backoff)
                await asyncio.sleep(backoff)
            else:
                logger.error("Gemini call exhausted retries: %s", e)
    raise LLMProviderError(f"gemini exhausted retries: {last_exc!r}") from last_exc
```

Update `_PROVIDERS`:

```python
_PROVIDERS: dict[str, HandlerType] = {
    "glm": _send_zai,
    "zai": _send_zai,
    "deepseek": _send_deepseek,
    "kimi": _send_kimi,
    "moonshot": _send_kimi,
    "qwen": _send_qwen,
    "gemini": _send_gemini,
}
```

- [ ] **Step 4: Run, verify pass**

```bash
uv run pytest tests/test_llm_gemini.py -v
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add server/board/llm.py tests/test_llm_gemini.py
git commit -m "feat(llm): add native Gemini handler via google-genai"
```

---

## Task 8: Implement `_send_openrouter` escape hatch

`openrouter:<id>` prefix dispatches to a thin `httpx` POST. Anything without the prefix never reaches OpenRouter.

**Files:**
- Modify: `server/board/llm.py`
- Create: `tests/test_llm_openrouter.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_llm_openrouter.py`:

```python
"""Unit tests for the OpenRouter escape-hatch handler."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from server.board import llm


def _fake_openrouter_payload():
    return {
        "id": "or-1",
        "choices": [{
            "message": {"content": "ok"},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 4, "completion_tokens": 1},
    }


@pytest.mark.asyncio
async def test_openrouter_strips_prefix_and_posts(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-test")

    captured = {}

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            captured["init"] = (args, kwargs)
        async def __aenter__(self):
            return self
        async def __aexit__(self, *exc):
            return False
        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            resp.json = MagicMock(return_value=_fake_openrouter_payload())
            return resp

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)

    resp = await llm.query_llm(
        "openrouter:anthropic/claude-opus-4",
        [{"role": "user", "content": "hi"}],
        temperature=0.4,
        max_tokens=100,
    )

    assert resp.content == "ok"
    assert resp.model == "openrouter:anthropic/claude-opus-4"
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    # Prefix stripped before being passed in payload
    assert captured["json"]["model"] == "anthropic/claude-opus-4"
    assert captured["headers"]["Authorization"] == "Bearer or-test"


@pytest.mark.asyncio
async def test_openrouter_missing_key_raises(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENROUTER_API_KEY"):
        await llm.query_llm(
            "openrouter:anthropic/claude-opus-4",
            [{"role": "user", "content": "hi"}],
        )


@pytest.mark.asyncio
async def test_openrouter_non_prefixed_does_not_route_here():
    """A bare provider/model id (no 'openrouter:' prefix) must NOT hit OpenRouter."""
    with pytest.raises(RuntimeError, match="unknown provider prefix"):
        await llm.query_llm(
            "anthropic/claude-opus-4",
            [{"role": "user", "content": "hi"}],
        )
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/test_llm_openrouter.py -v
```

Expected: failures.

- [ ] **Step 3: Add `_send_openrouter` to `llm.py`**

Add an `import httpx` near the top of the file (after `import logging`). Then append after `_send_gemini`:

```python
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
        except (httpx.TimeoutException, httpx.HTTPStatusError) as e:
            last_exc = e
            if attempt < max_retries - 1:
                backoff = backoff_seconds[min(attempt, len(backoff_seconds) - 1)]
                logger.warning("OpenRouter call failed (attempt %d/%d): %s; retrying in %ds",
                               attempt + 1, max_retries, e, backoff)
                await asyncio.sleep(backoff)
            else:
                logger.error("OpenRouter call exhausted retries: %s", e)
    raise LLMProviderError(f"openrouter exhausted retries: {last_exc!r}") from last_exc
```

Update `_PROVIDERS`:

```python
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
```

- [ ] **Step 4: Run, verify pass**

```bash
uv run pytest tests/test_llm_openrouter.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add server/board/llm.py tests/test_llm_openrouter.py
git commit -m "feat(llm): add OpenRouter as opt-in escape hatch via openrouter: prefix"
```

---

## Task 9: Free-first fallback chain

Wrap `query_llm`'s primary call so that on `LLMProviderError`, we walk
`[gemini-2.5-flash → glm-4.5-flash → qwen-flash]` (free) and finally
`deepseek-chat` (paid), skipping entries whose key/region/same-provider rules block them.

**Files:**
- Modify: `server/board/llm.py`
- Create: `tests/test_llm_fallback.py`

- [ ] **Step 1: Write failing fallback tests**

Create `tests/test_llm_fallback.py`:

```python
"""Free-first fallback chain behavior."""
from __future__ import annotations

from unittest.mock import AsyncMock

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


@pytest.mark.asyncio
async def test_chain_walks_in_order_until_success(monkeypatch):
    """gemini fails → glm succeeds. Order: gemini, glm. qwen never called."""
    _all_free_keys(monkeypatch)

    calls: list[str] = []

    async def fake_dispatch(prefix, model, **kwargs):
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


@pytest.mark.asyncio
async def test_skip_when_key_missing(monkeypatch):
    """No GEMINI_API_KEY → gemini fallback skipped, glm tried first."""
    _all_free_keys(monkeypatch)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    calls: list[str] = []

    async def fake_dispatch(prefix, model, **kwargs):
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


@pytest.mark.asyncio
async def test_skip_qwen_when_region_not_free(monkeypatch):
    _all_free_keys(monkeypatch)
    monkeypatch.setenv("DASHSCOPE_REGION", "cn")

    calls: list[str] = []

    async def fake_dispatch(prefix, model, **kwargs):
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


@pytest.mark.asyncio
async def test_skip_same_provider_as_primary(monkeypatch):
    """qwen/qwen-max failure must NOT fall back to qwen/qwen-flash."""
    _all_free_keys(monkeypatch)

    calls: list[str] = []

    async def fake_dispatch(prefix, model, **kwargs):
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


@pytest.mark.asyncio
async def test_fallback_false_skips_chain(monkeypatch):
    _all_free_keys(monkeypatch)

    async def fake_dispatch(prefix, model, **kwargs):
        raise llm.LLMProviderError("primary failed")

    monkeypatch.setattr(llm, "_dispatch_to_handler", fake_dispatch)

    with pytest.raises(llm.LLMProviderError, match="primary failed"):
        await llm.query_llm(
            "kimi/kimi-k2.5",
            [{"role": "user", "content": "hi"}],
            fallback=False,
        )


@pytest.mark.asyncio
async def test_all_fail_raises_primary_chained(monkeypatch):
    _all_free_keys(monkeypatch)

    async def fake_dispatch(prefix, model, **kwargs):
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


@pytest.mark.asyncio
async def test_response_model_reflects_substitution(monkeypatch):
    _all_free_keys(monkeypatch)

    async def fake_dispatch(prefix, model, **kwargs):
        if model == "kimi/kimi-k2.5":
            raise llm.LLMProviderError("primary failed")
        if model == "gemini/gemini-2.5-flash":
            return _success_response(model)
        raise AssertionError(f"unexpected dispatch to {model}")

    monkeypatch.setattr(llm, "_dispatch_to_handler", fake_dispatch)

    resp = await llm.query_llm("kimi/kimi-k2.5", [{"role": "user", "content": "hi"}])
    assert resp.model == "gemini/gemini-2.5-flash"
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/test_llm_fallback.py -v
```

Expected: failures (`_dispatch_to_handler` doesn't exist; `query_llm` has no fallback chain).

- [ ] **Step 3: Refactor `query_llm` to introduce `_dispatch_to_handler` + chain**

Replace the current `query_llm` body in `server/board/llm.py` with the following (and add the constants and helpers shown):

```python
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
) -> LLMResponse:
    """Dispatch a single call to the registered handler. Raises if no handler."""
    handler = _PROVIDERS.get(prefix)
    if handler is None:
        raise RuntimeError(
            f"unknown provider prefix: {prefix!r} for model {model!r}. "
            f"Known prefixes: {sorted(_PROVIDERS)}"
        )
    return await handler(
        model,
        messages,
        system=system,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        max_retries=max_retries,
        backoff_seconds=backoff_seconds,
    )


# ---------------------------------------------------------------------------
# Public entry — replaces the skeleton from Task 2
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
    """Route a chat-completion request and apply the free-first fallback chain.

    See spec at docs/superpowers/specs/2026-04-25-llm-providers-refactor-design.md
    for the chain rules.
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
        )
    except LLMProviderError as e:
        primary_exc = e

    if not fallback:
        raise primary_exc

    # Free-first fallback chain
    last_fallback_exc: Exception | None = primary_exc
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
            )
        except LLMProviderError as e:
            last_fallback_exc = e

    # Re-raise primary, chained from last fallback
    raise primary_exc from last_fallback_exc
```

- [ ] **Step 4: Run, verify pass**

```bash
uv run pytest tests/test_llm_fallback.py -v
```

Expected: 7 tests pass.

- [ ] **Step 5: Run all `test_llm_*` together**

```bash
uv run pytest tests/test_llm_routing.py tests/test_llm_zai.py tests/test_llm_deepseek.py tests/test_llm_kimi.py tests/test_llm_qwen.py tests/test_llm_gemini.py tests/test_llm_openrouter.py tests/test_llm_fallback.py -v
```

Expected: all tests pass (~30+ tests).

- [ ] **Step 6: Commit**

```bash
git add server/board/llm.py tests/test_llm_fallback.py
git commit -m "feat(llm): free-first fallback chain (gemini-flash → glm-flash → qwen-flash → deepseek)"
```

---

## Task 10: Update `metrics.py` cost rates

Add native-prefix entries to `COST_RATES` (existing dict; do not rename). Free models get `(0.0, 0.0)`. Existing OpenRouter-keyed rows (`google/gemini-2.5-pro`, `anthropic/...`, `openai/...`, `x-ai/...`) stay so `openrouter:<id>` lookups still resolve. Update `_estimate_cost` to strip the `openrouter:` prefix before lookup.

Note: `deepseek/deepseek-chat` and `kimi/kimi-k2.5` are **already** in `COST_RATES` (`server/board/metrics.py:28-29`). Do not duplicate.

**Files:**
- Modify: `server/board/metrics.py:22-46`
- Create: `tests/test_llm_metrics_pricing.py`

- [ ] **Step 1: Write failing pricing tests**

Create `tests/test_llm_metrics_pricing.py`:

```python
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
```

- [ ] **Step 2: Run, verify failure**

```bash
uv run pytest tests/test_llm_metrics_pricing.py -v
```

Expected: failures — `KeyError` on the new native-prefix rows; openrouter prefix not stripped.

- [ ] **Step 3: Add new rows to `COST_RATES` in `server/board/metrics.py`**

Open `server/board/metrics.py`. Replace the existing `COST_RATES` dict (currently `server/board/metrics.py:22-30`) with the expanded version below. The pre-existing rows are preserved; new native-prefix rows are added.

```python
# Cost rates per 1M tokens: {model_prefix: (input_rate, output_rate)}
COST_RATES: dict[str, tuple[float, float]] = {
    # OpenRouter-keyed (used when model id starts with 'openrouter:')
    "anthropic/claude-opus-4": (15.0, 75.0),
    "anthropic/claude-sonnet-4": (3.0, 15.0),
    "openai/gpt-4.1": (2.0, 8.0),
    "google/gemini-2.5-pro": (1.25, 10.0),
    "x-ai/grok-3": (3.0, 15.0),

    # Native-prefix rows (USD per 1M tokens, input / output)
    "gemini/gemini-2.5-flash":    (0.0, 0.0),    # AI Studio free tier
    "gemini/gemini-2.5-pro":      (1.25, 10.0),  # paid AI Studio
    "glm/glm-4.5-flash":          (0.0, 0.0),    # Z.AI free
    "glm/glm-4.6":                (0.6, 2.2),    # Z.AI paid (approximate)
    "qwen/qwen-flash":            (0.0, 0.0),    # DashScope free quota (Singapore)
    "qwen/qwen-turbo":            (0.05, 0.20),
    "qwen/qwen-plus":             (0.4, 1.2),
    "qwen/qwen-max":              (1.6, 6.4),
    "deepseek/deepseek-chat":     (0.27, 1.10),
    "deepseek/deepseek-reasoner": (0.55, 2.19),
    "kimi/kimi-k2.5":             (0.60, 2.50),
    "kimi/kimi-k2.6":             (0.60, 2.50),
}
```

- [ ] **Step 4: Update `_estimate_cost` to strip `openrouter:` prefix**

In `server/board/metrics.py`, replace the existing `_estimate_cost` function (currently `server/board/metrics.py:36-46`) with:

```python
def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD for a single call.

    Tokens set to -1 (unknown) are treated as 0 for cost estimation. The
    'openrouter:' prefix is stripped before lookup so 'openrouter:google/...'
    resolves to the same row as the underlying OpenRouter model id.
    """
    key = model.split(":", 1)[1] if model.startswith("openrouter:") else model
    input_rate, output_rate = COST_RATES.get(key, _DEFAULT_RATE)

    in_tok = max(input_tokens, 0)
    out_tok = max(output_tokens, 0)

    return (in_tok * input_rate / 1_000_000) + (out_tok * output_rate / 1_000_000)
```

- [ ] **Step 5: Run, verify pass**

```bash
uv run pytest tests/test_llm_metrics_pricing.py -v
```

Expected: 4 tests pass (parametrized produces more individual cases).

- [ ] **Step 6: Commit**

```bash
git add server/board/metrics.py tests/test_llm_metrics_pricing.py
git commit -m "feat(metrics): add native-prefix cost rates; strip openrouter: in lookup"
```

---

## Task 11: Update `config_provider.py` docstring

Pure docstring update — `provider_of()` already returns `"gemini"` for `gemini/<model>` because the function is prefix-generic.

**Files:**
- Modify: `server/harness/config_provider.py`

- [ ] **Step 1: Update the docstring**

Open `server/harness/config_provider.py`. In the `provider_of()` docstring (lines 8-17), add a `gemini/...` example. Replace the docstring's `Examples:` block so it reads:

```python
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
```

- [ ] **Step 2: Verify with a quick smoke**

```bash
uv run python -c "from server.harness.config_provider import provider_of; print(provider_of('gemini/gemini-2.5-flash'))"
```

Expected output: `gemini`

- [ ] **Step 3: Commit**

```bash
git add server/harness/config_provider.py
git commit -m "docs(harness): note gemini prefix in provider_of() examples"
```

---

## Task 12: Update `.env.example`

Add `GEMINI_API_KEY`, document Qwen region requirement, update Moonshot URL example, add `gemini/` prefix line.

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Read current `.env.example`**

Open `.env.example` to confirm the current content (already viewed during brainstorming).

- [ ] **Step 2: Apply the following edits**

Replace the entire current content of `.env.example` with:

```bash
# Native provider SDK keys used by the default model configuration.
DEEPSEEK_API_KEY=...
MOONSHOT_API_KEY=...
GEMINI_API_KEY=...
# (Set GOOGLE_API_KEY instead of GEMINI_API_KEY if you prefer; if both are
# set, GOOGLE_API_KEY wins per google-genai SDK conventions.)

# Optional API hardening for non-local deployments.
# Remote access stays disabled unless AGENTIC_BOARD_ALLOW_REMOTE=1.
# If remote access is enabled, every non-local request must send:
# Authorization: Bearer <AGENTIC_BOARD_REMOTE_TOKEN>
# AGENTIC_BOARD_ALLOW_REMOTE=0
# AGENTIC_BOARD_REMOTE_TOKEN=your-long-random-token
# AGENTIC_BOARD_WEB_SEARCH_RATE_LIMIT=20
# AGENTIC_BOARD_WEB_SEARCH_RATE_WINDOW_SECONDS=60

# Optional: override default models (see board/config.py)
# CHAIRMAN_MODEL=kimi/kimi-k2.5
# COUNCIL_MODELS=deepseek/deepseek-chat,kimi/kimi-k2.5
# CLASSIFIER_MODEL=deepseek/deepseek-chat
# VERIFICATION_MODEL=kimi/kimi-k2.5

# Use model prefixes to route natively:
# - gemini/gemini-2.5-flash      -> google-genai SDK (free tier)
# - glm/glm-4.6 or zai/glm-4.6   -> Z.AI SDK
# - qwen/qwen-flash              -> DashScope native SDK
# - deepseek/deepseek-chat       -> DeepSeek via OpenAI SDK (api.deepseek.com/v1)
# - kimi/kimi-k2.5 (or moonshot/) -> Moonshot via OpenAI SDK (api.moonshot.ai/v1)
# ZAI_API_KEY=...
# DASHSCOPE_API_KEY=...
# Set DASHSCOPE_REGION=international (or singapore) to access Qwen's free
# 1M-in/1M-out quota. Default 'cn' has NO free quota.
# DASHSCOPE_REGION=international

# Optional base-URL overrides:
# DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
# MOONSHOT_BASE_URL=https://api.moonshot.ai/v1
# DASHSCOPE_BASE_URL=

# Optional thinking-mode toggles:
# ZAI_THINKING=enabled
# QWEN_THINKING=true
# QWEN_THINKING_BUDGET=512
# KIMI_THINKING=enabled

# Optional OpenRouter escape hatch. ONLY used when a model id starts with
# 'openrouter:' — never the implicit default. Example:
#   CHAIRMAN_MODEL=openrouter:anthropic/claude-opus-4
# OPENROUTER_API_KEY=your-openrouter-api-key

# AGENTIC_BOARD_ALLOW_SAME_VERIFIER=1
# AGENTIC_BOARD_SHADOW_DISABLED=1

# AGENTIC_BOARD_DRIFT_SCORE_DELTA=-0.5
# AGENTIC_BOARD_DRIFT_JS=0.3
```

- [ ] **Step 3: Commit**

```bash
git add .env.example
git commit -m "docs(env): add GEMINI_API_KEY; document Qwen free-region; update Moonshot URL"
```

---

## Task 13: Audit member files for `model_override` values

Verify any hardcoded model overrides in `server/members/*.md` use a known native prefix or `openrouter:` form.

**Files:**
- Audit / possibly modify: `server/members/*.md`

- [ ] **Step 1: Grep for `model_override`**

Run:

```bash
grep -rn 'model_override' /home/apeng/projects/solo_company_agentic_board/server/members/ 2>/dev/null
```

If no output: nothing to do. Skip to Step 3.

- [ ] **Step 2: Verify each value uses a known prefix**

For each match, confirm the value starts with one of:
- `gemini/`, `glm/`, `zai/`, `qwen/`, `deepseek/`, `kimi/`, `moonshot/`, `openrouter:`

If any value uses a bare `provider/model` id like `google/gemini-2.5-pro` or `anthropic/claude-opus-4` (which *would* have routed to OpenRouter under the old default), prefix it with `openrouter:` (e.g. `openrouter:google/gemini-2.5-pro`). This preserves intended behavior; the new dispatcher refuses bare ids.

Edit each affected member file's frontmatter to update the value.

- [ ] **Step 3: Run the existing roster/loader tests to confirm no regression**

```bash
uv run pytest tests/test_roster_routing.py tests/test_member_intake_frontmatter_contract.py -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit (only if files changed)**

If Step 2 modified any member files:

```bash
git add server/members/
git commit -m "fix(members): prefix bare OpenRouter model ids with openrouter:"
```

If no changes were needed, just skip.

---

## Task 14: Live smoke test scaffold

A single opt-in test per provider that hits the real API. Skipped by default; run with `pytest -m live` after keys are set.

**Files:**
- Create: `tests/test_llm_live_smoke.py`

- [ ] **Step 1: Register the `live` marker**

Open `pyproject.toml`. In the `[tool.pytest.ini_options]` block (added in Task 2), add a `markers` entry. The block should look like:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = [
    "live: opt-in tests that hit real provider APIs (skipped by default)",
]
```

- [ ] **Step 2: Create the live smoke file**

Create `tests/test_llm_live_smoke.py`:

```python
"""Live smoke tests — opt-in only.

Run with:
    uv run pytest -m live tests/test_llm_live_smoke.py -v

Each test is skipped if its required env var is unset.
"""
from __future__ import annotations

import os

import pytest

from server.board import llm

pytestmark = pytest.mark.live


PING = [{"role": "user", "content": "Say 'pong' and nothing else."}]


@pytest.mark.skipif(not os.getenv("GEMINI_API_KEY") and not os.getenv("GOOGLE_API_KEY"),
                    reason="GEMINI_API_KEY / GOOGLE_API_KEY not set")
@pytest.mark.asyncio
async def test_live_gemini():
    resp = await llm.query_llm(
        "gemini/gemini-2.5-flash",
        PING,
        max_tokens=8,
        fallback=False,
    )
    assert resp.content
    assert resp.input_tokens >= 0


@pytest.mark.skipif(not os.getenv("ZAI_API_KEY"), reason="ZAI_API_KEY not set")
@pytest.mark.asyncio
async def test_live_zai():
    resp = await llm.query_llm("glm/glm-4.5-flash", PING, max_tokens=8, fallback=False)
    assert resp.content


@pytest.mark.skipif(not os.getenv("DASHSCOPE_API_KEY"), reason="DASHSCOPE_API_KEY not set")
@pytest.mark.asyncio
async def test_live_qwen():
    resp = await llm.query_llm("qwen/qwen-flash", PING, max_tokens=8, fallback=False)
    assert resp.content


@pytest.mark.skipif(not os.getenv("DEEPSEEK_API_KEY"), reason="DEEPSEEK_API_KEY not set")
@pytest.mark.asyncio
async def test_live_deepseek():
    resp = await llm.query_llm("deepseek/deepseek-chat", PING, max_tokens=8, fallback=False)
    assert resp.content


@pytest.mark.skipif(not os.getenv("MOONSHOT_API_KEY"), reason="MOONSHOT_API_KEY not set")
@pytest.mark.asyncio
async def test_live_kimi():
    resp = await llm.query_llm("kimi/kimi-k2.5", PING, max_tokens=8, fallback=False)
    assert resp.content


@pytest.mark.skipif(not os.getenv("OPENROUTER_API_KEY"), reason="OPENROUTER_API_KEY not set")
@pytest.mark.asyncio
async def test_live_openrouter():
    resp = await llm.query_llm(
        "openrouter:anthropic/claude-haiku-4-5",
        PING,
        max_tokens=8,
        fallback=False,
    )
    assert resp.content
```

- [ ] **Step 3: Confirm default run skips live tests**

```bash
uv run pytest tests/test_llm_live_smoke.py --collect-only -q
```

Expected: tests are collected but **skipped** (output shows `s` markers, no failures, no real network calls).

- [ ] **Step 4: Commit**

```bash
git add tests/test_llm_live_smoke.py pyproject.toml
git commit -m "test(llm): add opt-in live smoke tests gated by pytest -m live"
```

---

## Task 15: Final integration — full suite, lint, manual sanity

**Files:**
- Verify only; no code changes expected unless failures surface.

- [ ] **Step 1: Run the full unit test suite**

```bash
uv run pytest tests/ -v --ignore=tests/test_llm_live_smoke.py 2>&1 | tail -80
```

Expected: all tests pass. If any prior test (e.g. `test_replay_contract.py`, `test_board_contract.py`) was hardcoding bare OpenRouter ids (`google/gemini-2.5-pro` etc.), it will now fail with `unknown provider prefix`. Fix each by:
- prefixing with `openrouter:` if the test intended OpenRouter, OR
- swapping to a native id (`gemini/gemini-2.5-flash`) if the test was just using "some model".

Commit the fix as: `git commit -m "test: prefix legacy bare model ids for new dispatcher"`.

- [ ] **Step 2: Boot the API once and confirm `/members` works**

```bash
uv run uvicorn server.api:app --port 8765 &
sleep 3
curl -s http://localhost:8765/members | head -c 200
kill %1 2>/dev/null
```

Expected: JSON output starting with `[{"id":...}]`. No exception in the server log about `_assert_verifier_decoupled` or unknown prefixes.

- [ ] **Step 3: One CLI deliberation with budget mode**

Only run this if at least `DEEPSEEK_API_KEY` and `MOONSHOT_API_KEY` are set in `.env`:

```bash
uv run python -m server.cli --budget --members strategist "Should we ship a free tier?"
```

Expected: a deliberation completes, a budget summary prints, no errors.

- [ ] **Step 4: Verify no leftover references to deleted symbols**

```bash
grep -rn "_send_native_request\|_send_llm_request\|FALLBACK_MODELS\|NATIVE_PROVIDER_PREFIXES\|_send_zai_request_sync\|_send_openai_compatible_request_sync" /home/apeng/projects/solo_company_agentic_board/server /home/apeng/projects/solo_company_agentic_board/tests 2>/dev/null
```

Expected: empty output (all the old symbols are gone).

- [ ] **Step 5: Final commit (if any fixes were applied during steps 1-4)**

If steps 1-4 introduced fixes:

```bash
git add -A
git commit -m "chore(llm): final integration fixes after providers refactor"
```

If no fixes were needed, no commit.

- [ ] **Step 6: Summary log**

Print a short summary of what landed:

```bash
git log --oneline 16b0b36..HEAD 2>/dev/null || git log --oneline -20
```

(Replace `16b0b36` with the actual commit hash before the refactor began if known. Otherwise just `-20`.)

---

## Done

The board now talks natively to Gemini, Z.AI/GLM, Qwen, DeepSeek, and Kimi via each provider's official API. OpenRouter is opt-in via `openrouter:` prefix. When a primary model fails, free-tier models are tried first (`gemini-2.5-flash`, `glm-4.5-flash`, `qwen-flash`), with `deepseek-chat` as the paid last resort. All provider keys are read lazily — missing keys for unused providers don't block startup.
