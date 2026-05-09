# Agentic Research Loop — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the 5–7 day demo slice from `docs/superpowers/specs/2026-05-07-agentic-research-loop-design.md`: a chair intake turn, a tool-use loop for board members, and a `live_research` script in `live.py` that runs Strategist + Researcher with real web search + local Chrome browsing.

**Architecture:** Add `tools=` and `tool_calls` to `server/board/llm.py` for Kimi + DeepSeek. New `server/board/tools.py` registry exposes `web_search`, `fetch_url`, `open_browser`, `ask_user_clarifying_question`. New `agentic_member_turn` in `orchestrator.py` runs a budgeted tool-use loop. New `server/board/deliberation/intake.py` runs a chair intake that emits a structured `RoutingDecision`. `live.py` gains a `script="live_research"` path. Strategist + Researcher prompts get a Research Protocol section; other members keep `mode=fast` (no tools).

**Tech Stack:** Python 3.11, asyncio, pytest + pytest-asyncio, OpenAI Python SDK (Kimi + DeepSeek via OpenAI-compatible endpoints), Playwright (Chromium driving local Chrome), markdownify, httpx.

---

## File structure

### Created

| File | Responsibility |
|---|---|
| `server/board/tools.py` | Tool registry: `Tool`, `ToolCall`, `ToolResult` dataclasses; `TOOLS` dict; `execute_tool` dispatcher; per-tool handlers for web_search/fetch_url/ask_user/open_browser. |
| `server/board/deliberation/intake.py` | `run_chair_intake()` and `RoutingDecision` / `MemberAssignment` dataclasses; intake JSON parsing + `DEFAULT_ROUTING` fallback. |
| `server/protocols/chair_intake.md` | System prompt for the chair intake turn. |
| `scripts/smoke_tool_call.py` | Day 1 smoke: Kimi/DeepSeek emits a `tool_calls` response. |
| `scripts/smoke_tool_loop.py` | Day 2 smoke: Kimi runs a one-tool loop. |
| `scripts/smoke_browser.py` | Day 3 smoke: open Chrome, extract markdown from a JS-heavy page. |
| `tests/test_llm_tool_calls.py` | Unit tests for `tools=` parameter on Kimi + DeepSeek. |
| `tests/test_tools_registry.py` | Unit tests for tool dispatcher and individual handlers (mocked). |
| `tests/test_open_browser.py` | Unit tests for browser tool with Playwright mocked. |
| `tests/test_agentic_member_turn.py` | Tests for the tool-use loop with mocked LLM and tool handlers. |
| `tests/test_intake.py` | Tests for chair intake (clear query, ambiguous query, malformed JSON fallback). |
| `tests/test_live_research_script.py` | Integration test for `script="live_research"`. |
| `docs/agentic-research-demo.md` | One-page demo README. |

### Modified

| File | What changes |
|---|---|
| `server/board/llm.py` | Add `ToolCall` dataclass, `tools=`/`tool_choice=` params on `query_llm()`, tool_calls parsing in `_send_kimi` + `_send_deepseek`, support for `role="tool"` messages. |
| `server/board/deliberation/orchestrator.py` | Add `ToolBudget`, `MemberTurnResult`, `agentic_member_turn()` async function; helpers for budget filtering and force-finish. |
| `server/board/deliberation/live.py` | Add `script` field on `LiveSession`, `live_research` flow that calls intake → first member round → secretary brief; mode override forcing all non-strategist/researcher members to `fast`. |
| `server/cli.py` | Add `--depth fast\|standard\|deep` and `--live-research` flags. |
| `server/members/strategist.md` | Append `## Research Protocol` section. |
| `server/members/researcher.md` | Append `## Research Protocol` section. |
| `pyproject.toml` | Add `playwright>=1.49`, `markdownify>=0.13` to dependencies. |

### Untouched in Phase 1

- Other `server/members/*.md` (5 of 7).
- `server/board/deliberation/classifier.py` (kept as fallback).
- `server/harness/*` (Phase 3 adds tool-call ledger).
- Web UI (Phase 2 adds tool-event rendering).

---

## Day 1 — LLM client tool seam

### Task 1: Add `ToolCall` dataclass and `tools=` parameter signature to `llm.py`

**Files:**
- Modify: `server/board/llm.py:29-53` (LLMResponse dataclass)
- Modify: `server/board/llm.py:871-893` (query_llm signature)
- Test: `tests/test_llm_tool_calls.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/test_llm_tool_calls.py`:

```python
"""Tool-calling support in the llm.py public surface."""
from __future__ import annotations

import inspect

from server.board import llm


def test_llm_response_has_tool_calls_field():
    resp = llm.LLMResponse(
        content="x", model="m", input_tokens=1, output_tokens=1, latency_seconds=0.1
    )
    assert resp.tool_calls == []


def test_query_llm_accepts_tools_and_tool_choice():
    sig = inspect.signature(llm.query_llm)
    assert "tools" in sig.parameters
    assert "tool_choice" in sig.parameters
    assert sig.parameters["tools"].default is None
    assert sig.parameters["tool_choice"].default == "auto"


def test_tool_call_dataclass_shape():
    tc = llm.ToolCall(id="tc_1", name="web_search", arguments={"q": "x"})
    assert tc.id == "tc_1"
    assert tc.name == "web_search"
    assert tc.arguments == {"q": "x"}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_llm_tool_calls.py -v
```
Expected: FAIL with `AttributeError: module 'server.board.llm' has no attribute 'ToolCall'` or similar.

- [ ] **Step 3: Implement `ToolCall` and `tool_calls` field**

In `server/board/llm.py`, after the `LLMStreamChunk` dataclass (around line 53), add:

```python
@dataclass
class ToolCall:
    """A single tool/function invocation requested by the model."""
    id: str
    name: str
    arguments: dict[str, Any]
```

Modify the existing `LLMResponse` dataclass to add `tool_calls`:

```python
@dataclass
class LLMResponse:
    """Structured response from an LLM call."""
    content: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_seconds: float
    finish_reason: str | None = None
    response_id: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
```

Add `from dataclasses import field` to the imports if not already present (it's already used in `LLMStreamChunk`, so verify).

Modify `query_llm` signature to accept `tools` and `tool_choice`:

```python
async def query_llm(
    model: str,
    messages: list[dict[str, Any]],
    *,
    system: str | None = None,
    tools: list[dict] | None = None,
    tool_choice: str = "auto",
    temperature: float = 0.7,
    max_tokens: int = 8192,
    timeout: float = 240.0,
    fallback: bool = True,
) -> LLMResponse:
```

Note: change `messages: list[dict[str, str]]` to `list[dict[str, Any]]` everywhere it appears in the public signature, since tool messages have non-string fields (`tool_calls`, `tool_call_id`).

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_llm_tool_calls.py -v
```
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/board/llm.py tests/test_llm_tool_calls.py
git commit -m "feat(llm): add ToolCall dataclass and tools= parameter scaffolding"
```

---

### Task 2: Wire `tools=` through Kimi handler

**Files:**
- Modify: `server/board/llm.py:346-413` (`_send_kimi`)
- Test: `tests/test_llm_tool_calls.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_llm_tool_calls.py`:

```python
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def _fake_oai_tool_response(tool_calls=None, content="ok"):
    """Fake OpenAI-shape response with optional tool_calls."""
    msg_kwargs = {"content": content}
    if tool_calls:
        msg_kwargs["tool_calls"] = tool_calls
    return SimpleNamespace(
        id="resp-1",
        choices=[SimpleNamespace(
            message=SimpleNamespace(**msg_kwargs),
            finish_reason="tool_calls" if tool_calls else "stop",
        )],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
    )


class _FakeOpenAIWithTools:
    last_create: dict | None = None

    def __init__(self, **kwargs):
        self.chat = SimpleNamespace(completions=SimpleNamespace(
            create=lambda **kw: (type(self)._record(kw), self._response_for(kw))[1]
        ))

    @classmethod
    def _record(cls, kw):
        cls.last_create = kw

    def _response_for(self, kw):
        if kw.get("tools"):
            tc = SimpleNamespace(
                id="tc_001",
                type="function",
                function=SimpleNamespace(
                    name="web_search",
                    arguments=json.dumps({"query": "test"}),
                ),
            )
            return _fake_oai_tool_response(tool_calls=[tc])
        return _fake_oai_tool_response(content="plain response")


async def test_kimi_passes_tools_and_parses_tool_calls(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "test-key")
    _FakeOpenAIWithTools.last_create = None
    fake_openai = SimpleNamespace(OpenAI=_FakeOpenAIWithTools)
    tools_schema = [{
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search",
            "parameters": {"type": "object",
                            "properties": {"query": {"type": "string"}}},
        },
    }]
    with patch.dict("sys.modules", {"openai": fake_openai}):
        resp = await llm.query_llm(
            "kimi/kimi-k2.6",
            [{"role": "user", "content": "find X"}],
            tools=tools_schema,
            tool_choice="auto",
        )
    assert _FakeOpenAIWithTools.last_create["tools"] == tools_schema
    assert _FakeOpenAIWithTools.last_create["tool_choice"] == "auto"
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].id == "tc_001"
    assert resp.tool_calls[0].name == "web_search"
    assert resp.tool_calls[0].arguments == {"query": "test"}


async def test_kimi_no_tools_does_not_pass_kwarg(monkeypatch):
    monkeypatch.setenv("MOONSHOT_API_KEY", "test-key")
    _FakeOpenAIWithTools.last_create = None
    fake_openai = SimpleNamespace(OpenAI=_FakeOpenAIWithTools)
    with patch.dict("sys.modules", {"openai": fake_openai}):
        await llm.query_llm("kimi/kimi-k2.6", [{"role": "user", "content": "hi"}])
    assert "tools" not in _FakeOpenAIWithTools.last_create
    assert "tool_choice" not in _FakeOpenAIWithTools.last_create
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_llm_tool_calls.py -v
```
Expected: 2 new tests FAIL (Kimi handler doesn't pass `tools` yet).

- [ ] **Step 3: Add a helper to parse OpenAI-shape tool_calls**

In `server/board/llm.py`, after `_openai_shape_response_id` (around line 149), add:

```python
def _openai_shape_tool_calls(response: Any) -> list[ToolCall]:
    """Parse tool_calls out of an OpenAI-shape chat completion response."""
    import json
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
```

- [ ] **Step 4: Update `_send_kimi` to forward `tools`/`tool_choice` and parse the response**

In `server/board/llm.py`, modify `_send_kimi` (around line 346):

```python
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
    # ... existing imports/api_key/base_url/full_messages ...
    kwargs: dict[str, Any] = {
        "model": provider_model,
        "messages": full_messages,
        "max_tokens": max_tokens,
    }
    # Per-model temperature rules (keep existing block here)
    if provider_model.startswith("kimi-k2-thinking"):
        kwargs["temperature"] = 1.0
    elif provider_model.startswith(("kimi-k2.5", "kimi-k2.6")):
        pass
    else:
        kwargs["temperature"] = temperature

    thinking = _env_bool("KIMI_THINKING")
    if thinking is not None:
        kwargs["extra_body"] = {"thinking": {"type": "enabled" if thinking else "disabled"}}

    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice

    # ... existing retry loop, but in the success branch return:
    return LLMResponse(
        content=_openai_shape_content(response),
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_seconds=latency,
        finish_reason=_openai_shape_finish_reason(response),
        response_id=_openai_shape_response_id(response),
        tool_calls=_openai_shape_tool_calls(response),
    )
```

- [ ] **Step 5: Update `_dispatch_to_handler` and `query_llm` to pass `tools`/`tool_choice`**

In `server/board/llm.py`, modify `_dispatch_to_handler` (around line 836) to accept and forward the kwargs:

```python
async def _dispatch_to_handler(
    prefix: str,
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
    if tools is not None:
        handler_kwargs["tools"] = tools
        handler_kwargs["tool_choice"] = tool_choice
    return await handler(model, messages, **handler_kwargs)
```

In `query_llm` (around line 871), forward the new params on every dispatch call:

```python
return await _dispatch_to_handler(
    primary_prefix, model, messages,
    system=system, temperature=temperature, max_tokens=max_tokens,
    timeout=timeout,
    max_retries=PRIMARY_MAX_RETRIES,
    backoff_seconds=PRIMARY_BACKOFF_SECONDS,
    tools=tools, tool_choice=tool_choice,
)
```

Apply the same `tools=tools, tool_choice=tool_choice` addition to the two fallback dispatch calls in `query_llm` (free-fallback chain and paid last-resort).

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/test_llm_tool_calls.py tests/test_llm_kimi.py -v
```
Expected: New Kimi tool tests PASS; existing Kimi tests still PASS.

- [ ] **Step 7: Commit**

```bash
git add server/board/llm.py tests/test_llm_tool_calls.py
git commit -m "feat(llm): wire tools= through Kimi handler with tool_calls parsing"
```

---

### Task 3: Wire `tools=` through DeepSeek handler

**Files:**
- Modify: `server/board/llm.py:273-343` (`_send_deepseek`)
- Test: `tests/test_llm_tool_calls.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_llm_tool_calls.py`:

```python
async def test_deepseek_passes_tools_and_parses_tool_calls(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    _FakeOpenAIWithTools.last_create = None
    fake_openai = SimpleNamespace(OpenAI=_FakeOpenAIWithTools)
    tools_schema = [{
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search",
            "parameters": {"type": "object",
                            "properties": {"query": {"type": "string"}}},
        },
    }]
    with patch.dict("sys.modules", {"openai": fake_openai}):
        resp = await llm.query_llm(
            "deepseek/deepseek-chat",
            [{"role": "user", "content": "find X"}],
            tools=tools_schema,
        )
    assert _FakeOpenAIWithTools.last_create["tools"] == tools_schema
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "web_search"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_llm_tool_calls.py::test_deepseek_passes_tools_and_parses_tool_calls -v
```
Expected: FAIL.

- [ ] **Step 3: Update `_send_deepseek`**

In `server/board/llm.py`, modify `_send_deepseek` signature and implementation, mirroring Task 2's Kimi changes:

```python
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
    # ... existing imports/api_key/base_url/full_messages ...
    kwargs: dict[str, Any] = {
        "model": provider_model,
        "messages": full_messages,
        "max_tokens": max_tokens,
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
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice

    # ... in the success branch, return LLMResponse with tool_calls=_openai_shape_tool_calls(response)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_llm_tool_calls.py tests/test_llm_deepseek.py -v
```
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add server/board/llm.py tests/test_llm_tool_calls.py
git commit -m "feat(llm): wire tools= through DeepSeek handler"
```

---

### Task 4: Support `role="tool"` messages and validate `messages` shape

**Files:**
- Modify: `server/board/llm.py:69-73` (`_full_messages`)
- Test: `tests/test_llm_tool_calls.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_llm_tool_calls.py`:

```python
async def test_tool_role_message_passes_through_to_openai_compatible(monkeypatch):
    """role='tool' messages must pass through llm.py to the provider intact."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    _FakeOpenAIWithTools.last_create = None
    fake_openai = SimpleNamespace(OpenAI=_FakeOpenAIWithTools)
    msgs = [
        {"role": "user", "content": "find X"},
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "tc_1", "type": "function",
                          "function": {"name": "web_search",
                                       "arguments": '{"q": "X"}'}}]},
        {"role": "tool", "tool_call_id": "tc_1", "content": "results: 1, 2, 3"},
    ]
    with patch.dict("sys.modules", {"openai": fake_openai}):
        await llm.query_llm("deepseek/deepseek-chat", msgs)
    sent = _FakeOpenAIWithTools.last_create["messages"]
    assert any(m.get("role") == "tool" and m.get("tool_call_id") == "tc_1" for m in sent)
    assert any(m.get("role") == "assistant" and "tool_calls" in m for m in sent)
```

- [ ] **Step 2: Run test to verify it passes (or fails)**

```bash
uv run pytest tests/test_llm_tool_calls.py::test_tool_role_message_passes_through_to_openai_compatible -v
```

It may already pass since `_full_messages` does `list(messages)` without filtering — but we want to verify and lock the behavior with a test. If it passes, skip Step 3 and go to Step 4.

- [ ] **Step 3 (only if Step 2 fails): Verify `_full_messages` is permissive**

`_full_messages` in `server/board/llm.py` is:

```python
def _full_messages(messages: list[dict[str, str]], system: str | None) -> list[dict[str, str]]:
    if system is None:
        return list(messages)
    return [{"role": "system", "content": system}] + list(messages)
```

Update the type hint to `list[dict[str, Any]]`:

```python
def _full_messages(messages: list[dict[str, Any]], system: str | None) -> list[dict[str, Any]]:
    if system is None:
        return list(messages)
    return [{"role": "system", "content": system}] + list(messages)
```

- [ ] **Step 4: Commit**

```bash
git add server/board/llm.py tests/test_llm_tool_calls.py
git commit -m "test(llm): pin role='tool' message passthrough behaviour"
```

---

### Task 5: Day-1 smoke script (live API, opt-in)

**Files:**
- Create: `scripts/smoke_tool_call.py`

- [ ] **Step 1: Write the smoke script**

Create `scripts/smoke_tool_call.py`:

```python
"""Day-1 smoke: confirm Kimi and DeepSeek emit a tool_calls response.

Hits real APIs. Requires MOONSHOT_API_KEY and DEEPSEEK_API_KEY in env.
Run: uv run python scripts/smoke_tool_call.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from server.board import llm


SEARCH_TOOL = [{
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for current information.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
}]


async def smoke_one(model: str) -> bool:
    print(f"\n=== Smoking {model} ===")
    resp = await llm.query_llm(
        model,
        [{"role": "user",
          "content": "Use web_search to find the current population of Tokyo."}],
        tools=SEARCH_TOOL,
        tool_choice="auto",
        max_tokens=512,
        timeout=60.0,
        fallback=False,
    )
    print(f"  finish_reason: {resp.finish_reason}")
    print(f"  content: {(resp.content or '')[:200]!r}")
    print(f"  tool_calls: {[(tc.name, tc.arguments) for tc in resp.tool_calls]}")
    if not resp.tool_calls:
        print("  ✗ no tool_calls — model did not invoke web_search")
        return False
    print(f"  ✓ {len(resp.tool_calls)} tool_call(s)")
    return True


async def main() -> int:
    failures: list[str] = []
    if not os.getenv("MOONSHOT_API_KEY"):
        print("MOONSHOT_API_KEY missing; skipping kimi")
    elif not await smoke_one("kimi/kimi-k2.6"):
        failures.append("kimi")
    if not os.getenv("DEEPSEEK_API_KEY"):
        print("DEEPSEEK_API_KEY missing; skipping deepseek")
    elif not await smoke_one("deepseek/deepseek-v4-pro"):
        failures.append("deepseek")
    if failures:
        print(f"\n✗ smoke failures: {failures}")
        return 1
    print("\n✓ all smokes passed")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 2: Run the smoke script (requires API keys)**

```bash
uv run python scripts/smoke_tool_call.py
```
Expected: both providers return at least one `tool_call`. If a provider doesn't, the script reports it; treat as a Day-1 blocker per spec §7 (Risks).

- [ ] **Step 3: Commit**

```bash
git add scripts/smoke_tool_call.py
git commit -m "feat(scripts): day-1 smoke for tool_calls on Kimi + DeepSeek"
```

---

## Day 2 — Tool registry

### Task 6: `Tool`, `ToolResult` dataclasses and registry skeleton

**Files:**
- Create: `server/board/tools.py`
- Create: `tests/test_tools_registry.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_tools_registry.py`:

```python
"""Tool registry contract tests."""
from __future__ import annotations

import pytest

from server.board import tools


def test_tool_dataclass_shape():
    async def _h(**kwargs):
        return tools.ToolResult(content_for_model="x", summary="ok", cost_units=1.0)
    t = tools.Tool(
        name="x",
        description="d",
        parameters={"type": "object", "properties": {}},
        handler=_h,
    )
    assert t.name == "x"
    assert callable(t.handler)


def test_tool_to_openai_schema():
    async def _h(**kwargs):
        return tools.ToolResult(content_for_model="x", summary="ok", cost_units=1.0)
    t = tools.Tool(
        name="web_search",
        description="Search the web.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        handler=_h,
    )
    schema = t.to_openai_schema()
    assert schema == {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }


def test_registry_lookup():
    assert "web_search" in tools.TOOLS
    assert "fetch_url" in tools.TOOLS
    assert "ask_user_clarifying_question" in tools.TOOLS
    assert "open_browser" in tools.TOOLS


async def test_execute_tool_unknown_name():
    result = await tools.execute_tool(
        name="nonexistent_tool", arguments={}, session=None, member_id=None,
    )
    assert result.error is not None
    assert "unknown tool" in result.error.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_tools_registry.py -v
```
Expected: FAIL — `server.board.tools` does not exist.

- [ ] **Step 3: Create the registry skeleton**

Create `server/board/tools.py`:

```python
"""Tool registry for board members.

A Tool is a (name, description, JSON-schema parameters, async handler) record.
Handlers receive validated kwargs from the LLM's tool_call.arguments and
return a ToolResult. The registry is provider-agnostic; per-provider
schema conversion lives in llm.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

ToolHandler = Callable[..., Awaitable["ToolResult"]]


@dataclass
class ToolResult:
    """Result of executing one tool call."""
    content_for_model: str
    summary: str
    cost_units: float
    artifact_id: str | None = None
    error: str | None = None


@dataclass
class Tool:
    """A registered tool with provider-agnostic schema and async handler."""
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def to_openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# Registry — populated by Tasks 7–10
TOOLS: dict[str, Tool] = {}


async def execute_tool(
    *,
    name: str,
    arguments: dict[str, Any],
    session: Any,
    member_id: str | None,
) -> ToolResult:
    """Look up and invoke a registered tool. Returns a ToolResult with
    `error` set if the tool is unknown or if the handler raises."""
    tool = TOOLS.get(name)
    if tool is None:
        return ToolResult(
            content_for_model=f"Error: unknown tool {name!r}",
            summary=f"unknown tool {name!r}",
            cost_units=0.0,
            error=f"unknown tool: {name!r}",
        )
    try:
        return await tool.handler(
            session=session, member_id=member_id, **arguments,
        )
    except Exception as exc:  # noqa: BLE001 — surface tool errors as ToolResult
        return ToolResult(
            content_for_model=f"Tool {name} failed: {exc}",
            summary=f"{name} error: {exc}",
            cost_units=0.0,
            error=str(exc),
        )
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_tools_registry.py -v
```
Expected: 3 tests PASS, 1 still FAIL (`test_registry_lookup` — handlers not yet registered). That FAIL is expected and lifts in Tasks 7–10.

- [ ] **Step 5: Commit**

```bash
git add server/board/tools.py tests/test_tools_registry.py
git commit -m "feat(tools): tool registry skeleton with Tool/ToolResult"
```

---

### Task 7: `web_search` tool handler

**Files:**
- Modify: `server/board/tools.py`
- Test: `tests/test_tools_registry.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tools_registry.py`:

```python
from unittest.mock import AsyncMock, patch


async def test_web_search_handler_invokes_execution_layer(monkeypatch):
    fake_results = {
        "results": [
            {"title": "X", "url": "https://x.example",
             "snippet": "snip", "retrieved_at": "2026-05-07T10:00:00Z"},
        ],
        "provider": "tavily",
    }
    fake_search = AsyncMock(return_value=fake_results)
    with patch("server.execution.web_search.web_search", fake_search):
        result = await tools.execute_tool(
            name="web_search",
            arguments={"query": "agency tooling 2026", "max_results": 3},
            session=None,
            member_id="strategist",
        )
    assert result.error is None
    assert result.cost_units == 1.0
    assert "X" in result.content_for_model
    assert "https://x.example" in result.content_for_model
    fake_search.assert_called_once()
    call_kwargs = fake_search.call_args.kwargs
    assert call_kwargs["query"] == "agency tooling 2026"
    assert call_kwargs["max_results"] == 3
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_tools_registry.py::test_web_search_handler_invokes_execution_layer -v
```
Expected: FAIL — `web_search` not registered.

- [ ] **Step 3: Add the handler and register**

Append to `server/board/tools.py`:

```python
# ────────────── web_search ──────────────

async def _handle_web_search(
    *,
    query: str,
    max_results: int = 5,
    recency_days: int | None = None,
    session: Any = None,
    member_id: str | None = None,
    **_unused: Any,
) -> ToolResult:
    """Wraps server.execution.web_search.web_search()."""
    from server.execution.web_search import web_search as _ws

    session_id = getattr(session, "session_id", None) if session else None
    raw = await _ws(
        query=query,
        max_results=min(int(max_results or 5), 10),
        session_id=session_id,
    )
    results = raw.get("results", []) if isinstance(raw, dict) else []
    if not results:
        return ToolResult(
            content_for_model=f"web_search('{query}') returned no results.",
            summary=f"web_search '{query}' → 0 results",
            cost_units=1.0,
        )
    lines = [f"web_search('{query}') results:"]
    for i, r in enumerate(results, 1):
        title = r.get("title", "(no title)")
        url = r.get("url", "")
        snippet = (r.get("snippet") or r.get("description") or "")[:300]
        retrieved = r.get("retrieved_at", "")
        lines.append(f"{i}. {title}\n   URL: {url}\n   Snippet: {snippet}"
                     + (f"\n   Retrieved: {retrieved}" if retrieved else ""))
    return ToolResult(
        content_for_model="\n".join(lines),
        summary=f"web_search '{query}' → {len(results)} results",
        cost_units=1.0,
    )


TOOLS["web_search"] = Tool(
    name="web_search",
    description="Search the web for current information. Returns a list of "
                "results with title, snippet, url, retrieved_at. Use when you "
                "need facts you don't have or to verify a claim.",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "the search query"},
            "max_results": {
                "type": "integer", "minimum": 1, "maximum": 10, "default": 5,
            },
            "recency_days": {
                "type": "integer",
                "description": "(optional) only results from last N days",
            },
        },
        "required": ["query"],
    },
    handler=_handle_web_search,
)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_tools_registry.py -v
```
Expected: previous failing tests now PASS.

- [ ] **Step 5: Commit**

```bash
git add server/board/tools.py tests/test_tools_registry.py
git commit -m "feat(tools): web_search handler wrapping execution.web_search"
```

---

### Task 8: `fetch_url` tool handler

**Files:**
- Modify: `server/board/tools.py`
- Test: `tests/test_tools_registry.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tools_registry.py`:

```python
async def test_fetch_url_handler_returns_text(monkeypatch):
    class _FakeResp:
        status_code = 200
        text = "<html><body><h1>Hi</h1></body></html>"
        def raise_for_status(self): pass

    class _FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw): return _FakeResp()

    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: _FakeClient())
    result = await tools.execute_tool(
        name="fetch_url", arguments={"url": "https://example.test"},
        session=None, member_id=None,
    )
    assert result.error is None
    assert "Hi" in result.content_for_model or "<h1>Hi</h1>" in result.content_for_model
    assert result.cost_units == 0.5


async def test_fetch_url_handler_failure_returns_error():
    result = await tools.execute_tool(
        name="fetch_url", arguments={"url": "not-a-url"},
        session=None, member_id=None,
    )
    assert result.error is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_tools_registry.py::test_fetch_url_handler_returns_text -v
```
Expected: FAIL.

- [ ] **Step 3: Add the handler**

Append to `server/board/tools.py`:

```python
# ────────────── fetch_url ──────────────

async def _handle_fetch_url(
    *,
    url: str,
    session: Any = None,
    member_id: str | None = None,
    **_unused: Any,
) -> ToolResult:
    """HTTP GET a URL; return its text (truncated to 12k chars)."""
    import httpx

    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return ToolResult(
            content_for_model=f"fetch_url: invalid URL {url!r}",
            summary="fetch_url invalid URL",
            cost_units=0.0,
            error=f"invalid URL: {url!r}",
        )
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True,
                                  headers={"User-Agent": "AgenticBoard/1.0"}) as c:
        resp = await c.get(url)
        resp.raise_for_status()
    text = resp.text[:12000]
    return ToolResult(
        content_for_model=f"fetch_url('{url}') →\n{text}",
        summary=f"fetched {url} ({len(resp.text)} chars)",
        cost_units=0.5,
    )


TOOLS["fetch_url"] = Tool(
    name="fetch_url",
    description="HTTP GET a URL and return its text. Faster than open_browser "
                "but fails on JS-rendered or anti-bot-protected sites.",
    parameters={
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    },
    handler=_handle_fetch_url,
)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_tools_registry.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/board/tools.py tests/test_tools_registry.py
git commit -m "feat(tools): fetch_url handler with httpx"
```

---

### Task 9: `ask_user_clarifying_question` tool handler

**Files:**
- Modify: `server/board/tools.py`
- Test: `tests/test_tools_registry.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tools_registry.py`:

```python
async def test_ask_user_uses_session_callback():
    captured: dict = {}

    async def fake_ask(question: str, why: str) -> str:
        captured["question"] = question
        captured["why"] = why
        return "user-answer"

    class _FakeSession:
        ask_user = staticmethod(fake_ask)

    result = await tools.execute_tool(
        name="ask_user_clarifying_question",
        arguments={"question": "Which segment?",
                   "why_it_matters": "TAM differs by segment"},
        session=_FakeSession(),
        member_id="strategist",
    )
    assert result.error is None
    assert captured["question"] == "Which segment?"
    assert "user-answer" in result.content_for_model


async def test_ask_user_session_without_callback_returns_no_response():
    class _SessionNoCallback: pass
    result = await tools.execute_tool(
        name="ask_user_clarifying_question",
        arguments={"question": "Q?", "why_it_matters": "Y"},
        session=_SessionNoCallback(), member_id="strategist",
    )
    assert "[NO_USER_RESPONSE]" in result.content_for_model
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_tools_registry.py::test_ask_user_uses_session_callback -v
```
Expected: FAIL — handler not registered.

- [ ] **Step 3: Add the handler**

Append to `server/board/tools.py`:

```python
# ────────────── ask_user_clarifying_question ──────────────

async def _handle_ask_user(
    *,
    question: str,
    why_it_matters: str,
    session: Any = None,
    member_id: str | None = None,
    **_unused: Any,
) -> ToolResult:
    """Pause analysis and ask the user. Session must expose an async
    `ask_user(question, why)` method; otherwise return [NO_USER_RESPONSE]."""
    callback = getattr(session, "ask_user", None) if session else None
    if callback is None:
        return ToolResult(
            content_for_model="[NO_USER_RESPONSE] (session has no ask_user channel)",
            summary="ask_user: no channel",
            cost_units=0.0,
        )
    answer = await callback(question, why_it_matters)
    return ToolResult(
        content_for_model=f"User answered: {answer}",
        summary=f"asked: {question[:60]}",
        cost_units=2.0,
    )


TOOLS["ask_user_clarifying_question"] = Tool(
    name="ask_user_clarifying_question",
    description="Pause analysis and ask the user a clarifying question. "
                "Returns the user's response. Use ONLY when the question is "
                "essential to your analysis and not answerable by web search.",
    parameters={
        "type": "object",
        "properties": {
            "question": {"type": "string"},
            "why_it_matters": {
                "type": "string",
                "description": "one sentence explaining what it changes",
            },
        },
        "required": ["question", "why_it_matters"],
    },
    handler=_handle_ask_user,
)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_tools_registry.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/board/tools.py tests/test_tools_registry.py
git commit -m "feat(tools): ask_user_clarifying_question handler"
```

---

## Day 3 — Browser tool

### Task 10: Add Playwright + markdownify dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add dependencies**

In `pyproject.toml`, append to the `dependencies` list:

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
    "pdfplumber>=0.11.9",
    "playwright>=1.49",
    "markdownify>=0.13",
]
```

- [ ] **Step 2: Install with uv**

```bash
uv sync
uv run playwright install chromium
```
Expected: dependencies install; Playwright downloads its bundled Chromium (we use `channel="chrome"` to drive the user's installed Chrome instead, but the bundle ships defaults Playwright needs).

- [ ] **Step 3: Verify import**

```bash
uv run python -c "import playwright.async_api; import markdownify; print('ok')"
```
Expected: `ok`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add playwright + markdownify dependencies"
```

---

### Task 11: Chrome user-data-dir resolver

**Files:**
- Modify: `server/board/tools.py`
- Create: `tests/test_open_browser.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_open_browser.py`:

```python
"""Tests for the open_browser tool."""
from __future__ import annotations

import sys

import pytest

from server.board import tools


def test_chrome_profile_dir_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("AGENTIC_BOARD_CHROME_USER_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    expected = tmp_path / ".config" / "google-chrome"
    assert tools._resolve_chrome_user_data_dir() == str(expected)


def test_chrome_profile_dir_env_override(monkeypatch):
    monkeypatch.setenv("AGENTIC_BOARD_CHROME_USER_DATA_DIR", "/custom/path")
    assert tools._resolve_chrome_user_data_dir() == "/custom/path"


def test_chrome_profile_dir_macos(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("AGENTIC_BOARD_CHROME_USER_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    expected = tmp_path / "Library" / "Application Support" / "Google" / "Chrome"
    assert tools._resolve_chrome_user_data_dir() == str(expected)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_open_browser.py -v
```
Expected: FAIL — `_resolve_chrome_user_data_dir` not defined.

- [ ] **Step 3: Add resolver**

Append to `server/board/tools.py`:

```python
# ────────────── Chrome / Playwright helpers ──────────────

import os as _os
import sys as _sys
from pathlib import Path as _Path


def _resolve_chrome_user_data_dir() -> str:
    """Return the path to Chrome's user-data dir for the current OS.
    Override with AGENTIC_BOARD_CHROME_USER_DATA_DIR env var."""
    override = _os.getenv("AGENTIC_BOARD_CHROME_USER_DATA_DIR")
    if override:
        return override
    home = _Path(_os.path.expanduser("~"))
    if _sys.platform.startswith("linux"):
        return str(home / ".config" / "google-chrome")
    if _sys.platform == "darwin":
        return str(home / "Library" / "Application Support" / "Google" / "Chrome")
    if _sys.platform.startswith("win"):
        local = _os.getenv("LOCALAPPDATA") or str(home / "AppData" / "Local")
        return str(_Path(local) / "Google" / "Chrome" / "User Data")
    return str(home / ".config" / "google-chrome")
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_open_browser.py -v
```
Expected: 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/board/tools.py tests/test_open_browser.py
git commit -m "feat(tools): Chrome user-data-dir resolver per OS"
```

---

### Task 12: `open_browser` handler with Playwright + Tavily fallback

**Files:**
- Modify: `server/board/tools.py`
- Modify: `tests/test_open_browser.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_open_browser.py`:

```python
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


class _FakePage:
    async def goto(self, url, **kw): pass
    async def wait_for_load_state(self, *a, **kw): pass
    async def content(self):
        return "<html><body><h1>Hello</h1><p>Body</p></body></html>"
    async def close(self): pass


class _FakeContext:
    async def new_page(self): return _FakePage()
    async def close(self): pass


class _FakeBrowserType:
    async def launch_persistent_context(self, **kw):
        return _FakeContext()


class _FakePlaywrightCM:
    chromium = _FakeBrowserType()
    async def __aenter__(self): return self
    async def __aexit__(self, *a): pass


async def test_open_browser_returns_markdown(monkeypatch):
    monkeypatch.setenv("AGENTIC_BOARD_BROWSER", "chrome")
    monkeypatch.setenv("AGENTIC_BOARD_CHROME_USER_DATA_DIR", "/tmp/chrome-test")

    fake_async_pw = SimpleNamespace(
        async_playwright=lambda: _FakePlaywrightCM(),
    )
    with patch.dict(
        "sys.modules",
        {"playwright": SimpleNamespace(async_api=fake_async_pw),
         "playwright.async_api": fake_async_pw},
    ):
        result = await tools.execute_tool(
            name="open_browser",
            arguments={"url": "https://example.test"},
            session=None, member_id="strategist",
        )
    assert result.error is None
    assert result.cost_units == 3.0
    assert "Hello" in result.content_for_model


async def test_open_browser_tavily_fallback(monkeypatch):
    monkeypatch.setenv("AGENTIC_BOARD_BROWSER", "tavily")
    fake_results = {"results": [
        {"title": "Hello", "url": "https://example.test",
         "snippet": "Body content", "retrieved_at": "2026-05-07T10:00:00Z"},
    ]}
    fake_search = AsyncMock(return_value=fake_results)
    with patch("server.execution.web_search.web_search", fake_search):
        result = await tools.execute_tool(
            name="open_browser",
            arguments={"url": "https://example.test"},
            session=None, member_id="strategist",
        )
    assert result.error is None
    assert "Hello" in result.content_for_model


async def test_open_browser_disabled_returns_error(monkeypatch):
    monkeypatch.setenv("AGENTIC_BOARD_BROWSER", "disabled")
    result = await tools.execute_tool(
        name="open_browser", arguments={"url": "https://example.test"},
        session=None, member_id="strategist",
    )
    assert result.error is not None
    assert "disabled" in result.error.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_open_browser.py -v
```
Expected: FAILs.

- [ ] **Step 3: Add the handler**

Append to `server/board/tools.py`:

```python
# ────────────── open_browser ──────────────

import asyncio as _asyncio

_BROWSER_SEMAPHORE = _asyncio.Semaphore(1)
_OPEN_BROWSER_MAX_CHARS = 12000


async def _handle_open_browser(
    *,
    url: str,
    wait_for: str | None = None,
    extract: str = "markdown",
    session: Any = None,
    member_id: str | None = None,
    **_unused: Any,
) -> ToolResult:
    """Open a URL in local Chrome via Playwright; return rendered text.
    Mode controlled by AGENTIC_BOARD_BROWSER env: chrome (default) | tavily | disabled."""
    mode = (_os.getenv("AGENTIC_BOARD_BROWSER") or "chrome").lower()
    if mode == "disabled":
        return ToolResult(
            content_for_model="open_browser disabled (AGENTIC_BOARD_BROWSER=disabled)",
            summary="browser disabled",
            cost_units=0.0,
            error="browser disabled",
        )
    if mode == "tavily":
        return await _open_browser_via_tavily(url=url, member_id=member_id, session=session)
    return await _open_browser_via_playwright(
        url=url, wait_for=wait_for, extract=extract, member_id=member_id,
    )


async def _open_browser_via_tavily(
    *, url: str, member_id: str | None, session: Any,
) -> ToolResult:
    """Fallback when Playwright is unavailable: search the URL and return top snippets."""
    from server.execution.web_search import web_search as _ws
    session_id = getattr(session, "session_id", None) if session else None
    raw = await _ws(query=url, max_results=3, session_id=session_id)
    results = raw.get("results", []) if isinstance(raw, dict) else []
    if not results:
        return ToolResult(
            content_for_model=f"open_browser(fallback) for {url}: no content",
            summary="no fallback content", cost_units=1.0,
        )
    lines = [f"open_browser fallback for {url} (Tavily snippets):"]
    for r in results:
        lines.append(f"- {r.get('title', '')}: {r.get('snippet', '')[:300]}")
    return ToolResult(
        content_for_model="\n".join(lines)[:_OPEN_BROWSER_MAX_CHARS],
        summary=f"opened (fallback) {url}",
        cost_units=1.5,
    )


async def _open_browser_via_playwright(
    *, url: str, wait_for: str | None, extract: str, member_id: str | None,
) -> ToolResult:
    """Drive local Chrome with the user's profile via Playwright."""
    from playwright.async_api import async_playwright
    try:
        from markdownify import markdownify as _md
    except ImportError:
        _md = None

    user_data_dir = _resolve_chrome_user_data_dir()
    headed = _os.getenv("AGENTIC_BOARD_BROWSER_HEADED", "1") != "0"
    async with _BROWSER_SEMAPHORE:
        async with async_playwright() as pw:
            try:
                ctx = await pw.chromium.launch_persistent_context(
                    user_data_dir=user_data_dir,
                    channel="chrome",
                    headless=not headed,
                )
            except Exception as exc:
                return ToolResult(
                    content_for_model=(
                        f"open_browser failed to launch Chrome: {exc}. "
                        "Close any running Chrome with this profile, OR set "
                        "AGENTIC_BOARD_BROWSER=tavily."),
                    summary="chrome launch failed",
                    cost_units=0.0,
                    error=str(exc),
                )
            try:
                page = await ctx.new_page()
                await page.goto(url, timeout=30000)
                await page.wait_for_load_state("networkidle", timeout=20000)
                if wait_for:
                    try:
                        await page.wait_for_selector(wait_for, timeout=15000)
                    except Exception:
                        pass
                html = await page.content()
            finally:
                await ctx.close()

    if extract == "html":
        body = html
    elif extract == "text":
        # naive strip — markdownify gives us cleaner output normally
        import re
        body = re.sub(r"<[^>]+>", "", html)
    else:  # markdown
        body = _md(html, heading_style="ATX") if _md else html
    body = body[:_OPEN_BROWSER_MAX_CHARS]
    return ToolResult(
        content_for_model=f"open_browser('{url}') →\n{body}",
        summary=f"opened {url}",
        cost_units=3.0,
    )


TOOLS["open_browser"] = Tool(
    name="open_browser",
    description="Open a URL in a real Chrome browser session and extract the "
                "rendered page text. Use for sites that block scrapers, JS-rendered "
                "content, or pages needing your logged-in session. Slower (~5–15s). "
                "Use sparingly.",
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "wait_for": {"type": "string",
                          "description": "(optional) CSS selector to wait for"},
            "extract": {"type": "string", "enum": ["text", "markdown", "html"],
                         "default": "markdown"},
        },
        "required": ["url"],
    },
    handler=_handle_open_browser,
)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_open_browser.py -v
```
Expected: 3 new tests PASS, 3 earlier tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add server/board/tools.py tests/test_open_browser.py
git commit -m "feat(tools): open_browser via Playwright with Tavily fallback"
```

---

### Task 13: Day-3 browser smoke script

**Files:**
- Create: `scripts/smoke_browser.py`

- [ ] **Step 1: Write the smoke script**

Create `scripts/smoke_browser.py`:

```python
"""Day-3 smoke: open a JS-heavy page in local Chrome and dump first 500 chars.

Run: uv run python scripts/smoke_browser.py
With Tavily fallback: AGENTIC_BOARD_BROWSER=tavily uv run python scripts/smoke_browser.py
Headless: AGENTIC_BOARD_BROWSER_HEADED=0 uv run python scripts/smoke_browser.py
"""
from __future__ import annotations

import asyncio
import sys

from server.board.tools import execute_tool


async def main() -> int:
    url = "https://news.ycombinator.com/"
    print(f"Opening {url} via open_browser...")
    result = await execute_tool(
        name="open_browser",
        arguments={"url": url, "extract": "markdown"},
        session=None, member_id="smoke",
    )
    if result.error:
        print(f"✗ {result.error}")
        return 1
    print(f"✓ {result.summary}")
    print("---")
    print(result.content_for_model[:500])
    print("---")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 2: Run the smoke script**

```bash
uv run python scripts/smoke_browser.py
```
Expected: Chrome window opens (if `AGENTIC_BOARD_BROWSER_HEADED=1`, the default), page loads, first 500 chars print. If Chrome with the same profile is already running, expect a clear error message and a hint to set `AGENTIC_BOARD_BROWSER=tavily`.

- [ ] **Step 3: Commit**

```bash
git add scripts/smoke_browser.py
git commit -m "feat(scripts): day-3 browser smoke script"
```

---

## Day 4 — Member tool loop

### Task 14: `ToolBudget` and `MemberTurnResult` dataclasses

**Files:**
- Modify: `server/board/deliberation/orchestrator.py`
- Create: `tests/test_agentic_member_turn.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_agentic_member_turn.py`:

```python
"""Tests for agentic_member_turn and ToolBudget."""
from __future__ import annotations

import pytest

from server.board.deliberation import orchestrator


def test_tool_budget_default_fast():
    b = orchestrator.ToolBudget.for_mode("fast")
    assert b.tool_calls_max == 0
    assert b.web_search_max == 0
    assert b.open_browser_max == 0
    assert b.ask_user_max == 0


def test_tool_budget_default_standard():
    b = orchestrator.ToolBudget.for_mode("standard", member_role="member")
    assert b.tool_calls_max == 3
    assert b.web_search_max == 3
    assert b.open_browser_max == 1
    assert b.ask_user_max == 0  # members in standard get no ask_user


def test_tool_budget_default_deep_member():
    b = orchestrator.ToolBudget.for_mode("deep", member_role="member")
    assert b.tool_calls_max == 8
    assert b.web_search_max == 6
    assert b.open_browser_max == 3
    assert b.ask_user_max == 1


def test_tool_budget_default_deep_chair():
    b = orchestrator.ToolBudget.for_mode("deep", member_role="chair")
    assert b.ask_user_max == 3


def test_tool_budget_can_call_and_spend():
    b = orchestrator.ToolBudget.for_mode("standard", member_role="member")
    assert b.can_call("web_search")
    b.spend("web_search", 1.0)
    assert b.tool_calls_used == 1
    assert b.sub_used.get("web_search", 0) == 1


def test_tool_budget_exhausted_when_total_reached():
    b = orchestrator.ToolBudget.for_mode("standard", member_role="member")
    for _ in range(3):
        b.spend("web_search", 1.0)
    assert b.exhausted()


def test_tool_budget_sub_cap_exhausts_for_that_tool_only():
    b = orchestrator.ToolBudget.for_mode("standard", member_role="member")
    b.spend("open_browser", 3.0)
    assert not b.can_call("open_browser")  # sub-cap of 1
    assert b.can_call("web_search")          # other tool still ok
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_agentic_member_turn.py -v
```
Expected: FAIL — classes not defined.

- [ ] **Step 3: Implement `ToolBudget` and `MemberTurnResult`**

In `server/board/deliberation/orchestrator.py`, near the top after existing imports, add:

```python
from dataclasses import dataclass, field


@dataclass
class ToolBudget:
    tool_calls_max: int
    wall_seconds_max: int
    per_call_timeout: float
    open_browser_max: int
    web_search_max: int
    fetch_url_max: int
    ask_user_max: int
    tool_calls_used: int = 0
    wall_seconds_used: float = 0.0
    sub_used: dict[str, int] = field(default_factory=dict)

    SUB_CAPS_BY_TOOL = {
        "web_search": "web_search_max",
        "open_browser": "open_browser_max",
        "fetch_url": "fetch_url_max",
        "ask_user_clarifying_question": "ask_user_max",
    }

    @classmethod
    def for_mode(cls, mode: str, *, member_role: str = "member") -> "ToolBudget":
        if mode == "fast":
            return cls(0, 60, 240.0, 0, 0, 0, 1 if member_role == "chair" else 0)
        if mode == "standard":
            return cls(3, 180, 240.0, 1, 3, 2,
                        2 if member_role == "chair" else 0)
        if mode == "deep":
            return cls(8, 480, 240.0, 3, 6, 4,
                        3 if member_role == "chair" else 1)
        raise ValueError(f"unknown mode {mode!r}; expected fast|standard|deep")

    def can_call(self, name: str) -> bool:
        if self.tool_calls_used >= self.tool_calls_max:
            return False
        cap_attr = self.SUB_CAPS_BY_TOOL.get(name)
        if cap_attr is None:
            return True
        cap = getattr(self, cap_attr)
        return self.sub_used.get(name, 0) < cap

    def spend(self, name: str, cost_units: float) -> None:
        self.tool_calls_used += 1
        self.sub_used[name] = self.sub_used.get(name, 0) + 1

    def exhausted(self) -> bool:
        return self.tool_calls_used >= self.tool_calls_max


@dataclass
class MemberTurnResult:
    content: str
    tool_calls_made: int
    finish_reason: str | None
    aborted: bool = False
    abort_reason: str | None = None
    evidence_packets: list[str] = field(default_factory=list)
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_agentic_member_turn.py -v
```
Expected: 7 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/board/deliberation/orchestrator.py tests/test_agentic_member_turn.py
git commit -m "feat(orchestrator): ToolBudget and MemberTurnResult dataclasses"
```

---

### Task 15: `agentic_member_turn` — single-iteration loop

**Files:**
- Modify: `server/board/deliberation/orchestrator.py`
- Modify: `tests/test_agentic_member_turn.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agentic_member_turn.py`:

```python
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

from server.board.config import BoardMember
from server.board import llm, tools
from server.board.deliberation.orchestrator import (
    ToolBudget, agentic_member_turn,
)


def _make_member(member_id="strategist"):
    return BoardMember(
        id=member_id, title="Test", role="role",
        expertise=[], system_prompt="You are a tester.",
    )


async def test_agentic_turn_returns_content_when_no_tool_calls(monkeypatch):
    """If LLM returns content with no tool_calls, loop terminates immediately."""
    fake_response = llm.LLMResponse(
        content="Final analysis.",
        model="kimi/kimi-k2.6",
        input_tokens=10, output_tokens=5, latency_seconds=0.1,
        finish_reason="stop", tool_calls=[],
    )
    events: list = []
    with patch("server.board.deliberation.orchestrator.query_llm",
               AsyncMock(return_value=fake_response)):
        result = await agentic_member_turn(
            member=_make_member(),
            model="kimi/kimi-k2.6",
            system_prompt="You are a tester.",
            initial_user_message="Analyze X.",
            tools=[tools.TOOLS["web_search"]],
            budget=ToolBudget.for_mode("standard"),
            session=SimpleNamespace(),
            stage=1,
            on_event=events.append,
        )
    assert result.content == "Final analysis."
    assert result.tool_calls_made == 0
    assert not result.aborted


async def test_agentic_turn_executes_one_tool_call_then_returns(monkeypatch):
    call_responses = iter([
        llm.LLMResponse(
            content="", model="m", input_tokens=1, output_tokens=1,
            latency_seconds=0.1, finish_reason="tool_calls",
            tool_calls=[llm.ToolCall(
                id="tc_1", name="web_search",
                arguments={"query": "x"})],
        ),
        llm.LLMResponse(
            content="Done with results.", model="m",
            input_tokens=1, output_tokens=1, latency_seconds=0.1,
            finish_reason="stop", tool_calls=[],
        ),
    ])
    fake_query_llm = AsyncMock(side_effect=lambda *a, **kw: next(call_responses))
    fake_tool_result = tools.ToolResult(
        content_for_model="search results: X is 1", summary="ok", cost_units=1.0,
    )

    with patch("server.board.deliberation.orchestrator.query_llm", fake_query_llm), \
         patch("server.board.deliberation.orchestrator.execute_tool",
                AsyncMock(return_value=fake_tool_result)):
        result = await agentic_member_turn(
            member=_make_member(),
            model="kimi/kimi-k2.6",
            system_prompt="You are a tester.",
            initial_user_message="Analyze X.",
            tools=[tools.TOOLS["web_search"]],
            budget=ToolBudget.for_mode("standard"),
            session=SimpleNamespace(),
            stage=1,
            on_event=lambda e: None,
        )
    assert result.content == "Done with results."
    assert result.tool_calls_made == 1
    assert fake_query_llm.call_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_agentic_member_turn.py -v
```
Expected: FAIL — `agentic_member_turn` not defined.

- [ ] **Step 3: Implement `agentic_member_turn`**

In `server/board/deliberation/orchestrator.py`, near the bottom, after existing helpers but before the existing `_query_member`, add:

```python
import logging as _logging
from typing import Awaitable as _Awaitable, Callable as _Callable

from ..config import BoardMember
from ..llm import LLMResponse, ToolCall, query_llm
from ..tools import Tool, ToolResult, execute_tool

_orch_logger = _logging.getLogger(__name__)


def _budget_filtered_tools(all_tools: list[Tool], budget: ToolBudget) -> list[dict]:
    """Return only the tool schemas the budget still allows."""
    return [t.to_openai_schema() for t in all_tools if budget.can_call(t.name)]


def _tool_call_message(tcs: list[ToolCall]) -> dict:
    return {
        "role": "assistant", "content": "",
        "tool_calls": [
            {"id": tc.id, "type": "function",
             "function": {"name": tc.name,
                          "arguments": __import__("json").dumps(tc.arguments)}}
            for tc in tcs
        ],
    }


async def agentic_member_turn(
    *,
    member: BoardMember,
    model: str,
    system_prompt: str,
    initial_user_message: str,
    tools: list[Tool],
    budget: ToolBudget,
    session: object,
    stage: int,
    on_event: _Callable[[object], None],
) -> MemberTurnResult:
    """Run the model in a tool-use loop bounded by `budget`.
    Loop terminates when:
      - LLM returns content with no tool_calls, OR
      - budget is exhausted (one final tool_choice='none' call to write
        the final analysis), OR
      - a tool raises an unrecoverable error (currently never).
    """
    import asyncio as _aio
    import time as _time

    on_event(SimpleEvent("MemberStart", member.id, stage))
    messages: list[dict] = [{"role": "user", "content": initial_user_message}]
    t_start = _time.monotonic()

    while True:
        wall = _time.monotonic() - t_start
        budget.wall_seconds_used = wall
        budget_tools = _budget_filtered_tools(tools, budget)
        no_more_tools = not budget_tools or budget.exhausted() \
            or wall >= budget.wall_seconds_max

        on_event(SimpleEvent("MemberThinking", member.id))
        response: LLMResponse = await query_llm(
            model, messages,
            system=system_prompt,
            tools=None if no_more_tools else budget_tools,
            tool_choice="none" if no_more_tools else "auto",
            timeout=budget.per_call_timeout,
        )

        if not response.tool_calls:
            on_event(SimpleEvent("MemberComplete", member.id, response.finish_reason))
            return MemberTurnResult(
                content=response.content or "",
                tool_calls_made=budget.tool_calls_used,
                finish_reason=response.finish_reason,
            )

        # Append assistant tool-call message
        messages.append(_tool_call_message(response.tool_calls))

        # Execute tool calls in parallel
        async def _exec(tc: ToolCall) -> tuple[ToolCall, ToolResult]:
            on_event(SimpleEvent("ToolCall", member.id, tc.name, tc.arguments))
            result = await execute_tool(
                name=tc.name, arguments=tc.arguments,
                session=session, member_id=member.id,
            )
            on_event(SimpleEvent("ToolResult", member.id, tc.name,
                                  result.summary, result.cost_units))
            return tc, result

        results = await _aio.gather(*[_exec(tc) for tc in response.tool_calls])
        for tc, result in results:
            messages.append({
                "role": "tool", "tool_call_id": tc.id,
                "content": result.content_for_model[:8000],
            })
            budget.spend(tc.name, result.cost_units)


class SimpleEvent:
    """Lightweight event for the on_event stream during Phase 1.
    Phase 2 replaces this with the proper Event hierarchy in live.py."""
    def __init__(self, kind: str, *args):
        self.kind = kind
        self.args = args
    def __repr__(self):
        return f"Event({self.kind!r}, {self.args!r})"
```

Note the import shadowing: this file already imports `BoardMember` directly via `from ..config import ...`. Verify the existing imports near the top of `orchestrator.py` and avoid duplicates — only add the imports above if they aren't already present. The `import asyncio as _aio` and `import time as _time` inside the function are scoped locally to avoid collision with anything at module scope; these can be hoisted to module scope if `asyncio` and `time` aren't already imported.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_agentic_member_turn.py -v
```
Expected: 2 new tests PASS, plus the 7 from Task 14.

- [ ] **Step 5: Commit**

```bash
git add server/board/deliberation/orchestrator.py tests/test_agentic_member_turn.py
git commit -m "feat(orchestrator): agentic_member_turn tool-use loop"
```

---

### Task 16: Force-finish on budget exhaustion

**Files:**
- Modify: `server/board/deliberation/orchestrator.py`
- Modify: `tests/test_agentic_member_turn.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agentic_member_turn.py`:

```python
async def test_agentic_turn_force_finishes_on_budget_exhaustion(monkeypatch):
    """When budget is exhausted mid-loop, the loop forces a final analysis."""
    # Three responses: tool_call, tool_call, tool_call — but budget is 1 call max.
    tool_call_resp = llm.LLMResponse(
        content="", model="m", input_tokens=1, output_tokens=1, latency_seconds=0.1,
        finish_reason="tool_calls",
        tool_calls=[llm.ToolCall(id="tc", name="web_search",
                                  arguments={"query": "x"})],
    )
    final_resp = llm.LLMResponse(
        content="Forced final: budget spent, [UNRESOLVED] remains.",
        model="m", input_tokens=1, output_tokens=1, latency_seconds=0.1,
        finish_reason="stop", tool_calls=[],
    )
    responses = iter([tool_call_resp, final_resp])
    fake_query_llm = AsyncMock(side_effect=lambda *a, **kw: next(responses))

    captured_kwargs: list[dict] = []
    async def _spy_query(*args, **kwargs):
        captured_kwargs.append(kwargs)
        return next(responses)

    fake_tool_result = tools.ToolResult(
        content_for_model="ok", summary="ok", cost_units=1.0,
    )
    budget = ToolBudget(
        tool_calls_max=1, wall_seconds_max=300, per_call_timeout=240.0,
        open_browser_max=1, web_search_max=1, fetch_url_max=1, ask_user_max=0,
    )
    with patch("server.board.deliberation.orchestrator.query_llm",
               AsyncMock(side_effect=_spy_query)), \
         patch("server.board.deliberation.orchestrator.execute_tool",
                AsyncMock(return_value=fake_tool_result)):
        # reset the iter after monkey-patch wrap
        responses = iter([tool_call_resp, final_resp])
        result = await agentic_member_turn(
            member=_make_member(), model="m",
            system_prompt="x", initial_user_message="x",
            tools=[tools.TOOLS["web_search"]],
            budget=budget,
            session=SimpleNamespace(), stage=1, on_event=lambda e: None,
        )
    assert "Forced final" in result.content
    # Final call must have tool_choice="none"
    assert captured_kwargs[-1].get("tool_choice") == "none"
    assert captured_kwargs[-1].get("tools") is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_agentic_member_turn.py::test_agentic_turn_force_finishes_on_budget_exhaustion -v
```
Expected: PASS — the loop already handles this via the `no_more_tools` check in Task 15. If it fails, debug the budget filtering logic.

- [ ] **Step 3: Commit**

```bash
git add tests/test_agentic_member_turn.py
git commit -m "test(orchestrator): pin force-finish on budget exhaustion"
```

---

### Task 17: Append Research Protocol to strategist + researcher prompts

**Files:**
- Modify: `server/members/strategist.md`
- Modify: `server/members/researcher.md`

- [ ] **Step 1: Append to `server/members/strategist.md`**

Append at the end of `server/members/strategist.md`, after the existing "Open Questions" example:

```markdown

## Research Protocol (Phase 1)

You have tools to gather evidence:
- `web_search(query)` — facts, market data, current events.
- `open_browser(url)` — full page content; use after a search returns
  a promising URL OR for sites that block simple fetches.
- `fetch_url(url)` — plain HTML/JSON; faster than open_browser.
- `ask_user_clarifying_question(question, why_it_matters)` — ONLY when
  the answer materially changes your analysis AND cannot be found by
  search. Available only in deep mode.

Rules:
1. Use tools BEFORE making a load-bearing factual claim. If your
   TAM/SAM numbers depend on a market figure, search for it.
2. Prefer one focused query over many vague ones.
3. Do NOT use ask_user for things you can search for. Burn search
   budget first.
4. After collecting evidence, write your analysis. Cite sources inline
   as `[source: <title>, <url>, retrieved <YYYY-MM-DD>]`.
5. If a load-bearing claim remains [UNVERIFIED] after using your search
   budget, say so explicitly and explain why it matters.

Your tool budget is rendered into the user message at runtime.
```

- [ ] **Step 2: Append the same Research Protocol section to `server/members/researcher.md`**

Same content, appended verbatim (the rules apply identically to the researcher).

- [ ] **Step 3: Verify members still load**

```bash
uv run python -c "from server.board.config import get_board_members; ms = get_board_members(); print([m.id for m in ms])"
```
Expected: list includes strategist and researcher; no exception.

- [ ] **Step 4: Commit**

```bash
git add server/members/strategist.md server/members/researcher.md
git commit -m "docs(members): add Research Protocol to strategist + researcher"
```

---

## Day 5 — Chair intake

### Task 18: `RoutingDecision` dataclass and `chair_intake.md` prompt

**Files:**
- Create: `server/board/deliberation/intake.py`
- Create: `server/protocols/chair_intake.md`
- Create: `tests/test_intake.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_intake.py`:

```python
"""Chair intake tests."""
from __future__ import annotations

from server.board.deliberation import intake


def test_routing_decision_dataclass_shape():
    rd = intake.RoutingDecision(
        interpreted_query="Q",
        decision_type="strategic", complexity="medium", importance="notable",
        rationale="why",
        members=[intake.MemberAssignment(
            member_id="strategist", mode="standard",
            focus="market", priority=90,
        )],
        script="live_research",
        deep_research_dossier=False,
    )
    assert rd.script == "live_research"
    assert rd.members[0].member_id == "strategist"


def test_default_routing_returns_valid_decision():
    rd = intake.DEFAULT_ROUTING(query="anything")
    assert rd.script == "live_research"
    assert rd.members
    assert all(m.mode in ("fast", "standard", "deep") for m in rd.members)


def test_parse_routing_decision_json_valid():
    raw = """
    {
      "interpreted_query": "Should we enter the X market?",
      "decision_type": "strategic",
      "complexity": "high",
      "importance": "critical",
      "rationale": "Market entry decision needs deep evidence.",
      "members": [
        {"member_id": "strategist", "mode": "deep", "focus": "TAM/SAM", "priority": 90},
        {"member_id": "researcher", "mode": "deep", "focus": "personas", "priority": 80}
      ],
      "script": "live_research",
      "deep_research_dossier": false
    }
    """
    rd = intake.parse_routing_decision(raw)
    assert rd.decision_type == "strategic"
    assert len(rd.members) == 2
    assert rd.members[0].mode == "deep"


def test_parse_routing_decision_malformed_returns_none():
    assert intake.parse_routing_decision("{not json") is None
    assert intake.parse_routing_decision("") is None
    assert intake.parse_routing_decision('{"missing": "fields"}') is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_intake.py -v
```
Expected: FAIL — module not present.

- [ ] **Step 3: Create `server/board/deliberation/intake.py`**

```python
"""Chair intake turn: clarify query, emit RoutingDecision."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass
class MemberAssignment:
    member_id: str
    mode: str        # fast|standard|deep
    focus: str
    priority: int


@dataclass
class RoutingDecision:
    interpreted_query: str
    decision_type: str
    complexity: str
    importance: str
    rationale: str
    members: list[MemberAssignment]
    script: str = "live_research"
    deep_research_dossier: bool = False


_DEFAULT_ROSTER = [
    ("strategist", "standard", "market context", 90),
    ("product",    "standard", "product framing", 85),
    ("researcher", "standard", "customer voice",   80),
    ("critic",     "standard", "risk pressure",    75),
    ("architect",  "standard", "technical reality", 65),
    ("builder",    "standard", "build path",       60),
]


def DEFAULT_ROUTING(query: str) -> RoutingDecision:
    """Fallback routing when intake fails or is skipped."""
    return RoutingDecision(
        interpreted_query=query,
        decision_type="full-board",
        complexity="medium",
        importance="notable",
        rationale="Fallback: chair intake unavailable; routing all members in standard mode.",
        members=[
            MemberAssignment(member_id=mid, mode=mode, focus=focus, priority=pri)
            for (mid, mode, focus, pri) in _DEFAULT_ROSTER
        ],
        script="live_research",
        deep_research_dossier=False,
    )


_REQUIRED_TOP_FIELDS = (
    "interpreted_query", "decision_type", "complexity", "importance",
    "rationale", "members",
)


def parse_routing_decision(raw: str) -> RoutingDecision | None:
    """Parse a JSON RoutingDecision; return None on any failure."""
    if not raw:
        return None
    # Tolerate code fences
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("RoutingDecision parse failed: %s", exc)
        return None
    if not isinstance(data, dict):
        return None
    if any(f not in data for f in _REQUIRED_TOP_FIELDS):
        return None
    members_raw = data.get("members") or []
    if not members_raw:
        return None
    try:
        members = [
            MemberAssignment(
                member_id=str(m["member_id"]),
                mode=str(m.get("mode", "standard")),
                focus=str(m.get("focus", "")),
                priority=int(m.get("priority", 50)),
            )
            for m in members_raw
        ]
    except (KeyError, TypeError, ValueError):
        return None
    return RoutingDecision(
        interpreted_query=str(data["interpreted_query"]),
        decision_type=str(data["decision_type"]),
        complexity=str(data["complexity"]),
        importance=str(data["importance"]),
        rationale=str(data["rationale"]),
        members=members,
        script=str(data.get("script", "live_research")),
        deep_research_dossier=bool(data.get("deep_research_dossier", False)),
    )
```

- [ ] **Step 4: Create `server/protocols/chair_intake.md`**

```markdown
# Chair Intake — System Prompt

You are the Chairperson opening a board deliberation.

Your job in this turn is two-fold:
1. **Interpret the query.** Read it carefully. If essential context is
   missing AND not recoverable from a quick web_search, ask the user
   1–3 clarifying questions using ask_user_clarifying_question. Stop
   asking once you have enough to route.
2. **Emit a RoutingDecision.** Decide which members should participate
   and at what depth (fast | standard | deep), then produce a single
   JSON object matching the schema below as your final reply.

## Members available (Phase 1)

- `strategist` — market, competition, evidence
- `product` — product strategy, MVP definition, prioritization
- `researcher` — customer voice, personas, JTBD
- `critic` — assumption stress-test, pre-mortem
- `architect` — technical feasibility
- `builder` — implementation, validation paths

## Mode selection heuristic

- `fast` — query is routine, low-complexity, no research needed.
- `standard` — typical deliberation; members may search.
- `deep` — high-complexity AND/OR critical importance; members have
  larger tool budgets and may ask the user clarifying questions.

## Your tools

- `web_search(query)` — use sparingly to ground unfamiliar terms.
- `ask_user_clarifying_question(question, why_it_matters)` — for the
  intake clarifications. Maximum 3.

## Required final output

Your FINAL reply (after any tool calls) MUST be a single JSON object
with this exact shape, and no other text:

```json
{
  "interpreted_query": "<your restated, disambiguated version>",
  "decision_type": "strategic|product|customer|technical|finance|legal|full-board",
  "complexity": "low|medium|high",
  "importance": "routine|notable|critical",
  "rationale": "<one paragraph: why these members, why this depth>",
  "members": [
    {"member_id": "strategist", "mode": "standard|deep|fast",
     "focus": "<one-line directive>", "priority": 90}
  ],
  "script": "live_research",
  "deep_research_dossier": false
}
```

Do not include markdown code fences in your final reply — emit the raw
JSON object only. The runtime tolerates fences but the cleaner output is
strict JSON.
```

- [ ] **Step 5: Run tests**

```bash
uv run pytest tests/test_intake.py -v
```
Expected: 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add server/board/deliberation/intake.py server/protocols/chair_intake.md tests/test_intake.py
git commit -m "feat(intake): RoutingDecision dataclass + chair intake prompt"
```

---

### Task 19: `run_chair_intake` function

**Files:**
- Modify: `server/board/deliberation/intake.py`
- Modify: `tests/test_intake.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_intake.py`:

```python
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from server.board import llm, tools
from server.board.deliberation import intake as intake_mod
from server.board.deliberation.orchestrator import ToolBudget


async def test_run_chair_intake_clear_query_routes_directly(monkeypatch, tmp_path):
    """A clear query produces a RoutingDecision without ask_user calls."""
    routing_json = json.dumps({
        "interpreted_query": "Should we enter market X?",
        "decision_type": "strategic", "complexity": "high",
        "importance": "critical", "rationale": "Critical market decision.",
        "members": [
            {"member_id": "strategist", "mode": "deep",
             "focus": "TAM", "priority": 90},
        ],
        "script": "live_research", "deep_research_dossier": False,
    })
    fake_response = llm.LLMResponse(
        content=routing_json, model="kimi/kimi-k2.6", input_tokens=10,
        output_tokens=20, latency_seconds=0.1, finish_reason="stop",
        tool_calls=[],
    )

    # Stub the protocol read
    proto = tmp_path / "chair_intake.md"
    proto.write_text("Chair intake test prompt")
    monkeypatch.setattr(intake_mod, "_PROTOCOL_PATH", str(proto))

    with patch("server.board.deliberation.intake.query_llm",
               AsyncMock(return_value=fake_response)):
        rd = await intake_mod.run_chair_intake(
            raw_query="Should we enter market X?",
            user_overrides=intake_mod.ChairOverrides(),
            session=SimpleNamespace(),
            on_event=lambda e: None,
            chair_model="kimi/kimi-k2.6",
        )
    assert rd is not None
    assert rd.decision_type == "strategic"
    assert rd.members[0].mode == "deep"


async def test_run_chair_intake_malformed_falls_back_to_default(monkeypatch, tmp_path):
    fake_response = llm.LLMResponse(
        content="this is not json at all",
        model="kimi/kimi-k2.6", input_tokens=10, output_tokens=20,
        latency_seconds=0.1, finish_reason="stop", tool_calls=[],
    )
    proto = tmp_path / "chair_intake.md"
    proto.write_text("Chair intake test prompt")
    monkeypatch.setattr(intake_mod, "_PROTOCOL_PATH", str(proto))
    with patch("server.board.deliberation.intake.query_llm",
               AsyncMock(return_value=fake_response)):
        rd = await intake_mod.run_chair_intake(
            raw_query="Q",
            user_overrides=intake_mod.ChairOverrides(),
            session=SimpleNamespace(),
            on_event=lambda e: None,
            chair_model="kimi/kimi-k2.6",
        )
    assert rd.script == "live_research"
    assert any(m.member_id == "strategist" for m in rd.members)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_intake.py::test_run_chair_intake_clear_query_routes_directly -v
```
Expected: FAIL.

- [ ] **Step 3: Implement `run_chair_intake` and `ChairOverrides`**

Append to `server/board/deliberation/intake.py`:

```python
import os
from pathlib import Path

from ..config import get_chairman_model
from ..llm import query_llm
from ..tools import TOOLS, Tool


_PROTOCOL_PATH = str(
    Path(__file__).parent.parent.parent / "protocols" / "chair_intake.md"
)

_INTAKE_TOOLS = ["web_search", "ask_user_clarifying_question"]
_MAX_INTAKE_LOOP_ITERS = 6  # safety cap


@dataclass
class ChairOverrides:
    """User-provided overrides applied after the chair's routing decision."""
    depth: str | None = None              # forces all members to this mode
    members_filter: list[str] | None = None  # restricts roster
    intake: bool = True                    # if False, skip chair, use DEFAULT_ROUTING


def _read_intake_prompt() -> str:
    return Path(_PROTOCOL_PATH).read_text(encoding="utf-8")


def _apply_overrides(rd: RoutingDecision, ovr: ChairOverrides) -> RoutingDecision:
    members = rd.members
    if ovr.members_filter:
        members = [m for m in members if m.member_id in ovr.members_filter]
        if not members:
            members = rd.members  # don't end up empty
    if ovr.depth in ("fast", "standard", "deep"):
        members = [
            MemberAssignment(member_id=m.member_id, mode=ovr.depth,
                             focus=m.focus, priority=m.priority)
            for m in members
        ]
    return RoutingDecision(
        interpreted_query=rd.interpreted_query,
        decision_type=rd.decision_type,
        complexity=rd.complexity,
        importance=rd.importance,
        rationale=rd.rationale,
        members=members,
        script=rd.script,
        deep_research_dossier=rd.deep_research_dossier,
    )


async def run_chair_intake(
    *,
    raw_query: str,
    user_overrides: ChairOverrides,
    session: object,
    on_event: Callable[[object], None],
    chair_model: str | None = None,
) -> RoutingDecision:
    """Run the chair intake. Always returns a RoutingDecision (falls back
    to DEFAULT_ROUTING on any failure)."""
    if not user_overrides.intake:
        rd = DEFAULT_ROUTING(raw_query)
        return _apply_overrides(rd, user_overrides)

    chair_model = chair_model or get_chairman_model()
    intake_tools = [TOOLS[name] for name in _INTAKE_TOOLS if name in TOOLS]
    tool_schemas = [t.to_openai_schema() for t in intake_tools]
    system_prompt = _read_intake_prompt()
    messages: list[dict] = [{"role": "user",
                              "content": f"User query: {raw_query}"}]

    last_content = ""
    for _ in range(_MAX_INTAKE_LOOP_ITERS):
        response = await query_llm(
            chair_model, messages,
            system=system_prompt,
            tools=tool_schemas,
            tool_choice="auto",
            max_tokens=2000,
            timeout=120.0,
        )
        last_content = response.content or last_content
        if not response.tool_calls:
            break
        messages.append({
            "role": "assistant", "content": response.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.name,
                              "arguments": json.dumps(tc.arguments)}}
                for tc in response.tool_calls
            ],
        })
        from ..tools import execute_tool as _exec
        for tc in response.tool_calls:
            r = await _exec(name=tc.name, arguments=tc.arguments,
                            session=session, member_id="chairperson")
            messages.append({"role": "tool", "tool_call_id": tc.id,
                              "content": r.content_for_model[:6000]})

    rd = parse_routing_decision(last_content) or DEFAULT_ROUTING(raw_query)
    return _apply_overrides(rd, user_overrides)
```

Note: the `execute_tool` import inside the loop is local-scoped to keep the
module-load order safe (intake.py and tools.py both import from each other
indirectly via `query_llm`). Hoist to module-top once verified.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_intake.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/board/deliberation/intake.py tests/test_intake.py
git commit -m "feat(intake): run_chair_intake with ChairOverrides + fallback"
```

---

### Task 20: Intake clarification turn — multi-iteration ask_user

**Files:**
- Modify: `tests/test_intake.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_intake.py`:

```python
async def test_run_chair_intake_clarification_then_route(monkeypatch, tmp_path):
    """Chair asks 1 clarifying question, then emits routing on next call."""
    proto = tmp_path / "chair_intake.md"
    proto.write_text("test")
    monkeypatch.setattr(intake_mod, "_PROTOCOL_PATH", str(proto))

    ask_response = llm.LLMResponse(
        content="", model="m", input_tokens=1, output_tokens=1,
        latency_seconds=0.1, finish_reason="tool_calls",
        tool_calls=[llm.ToolCall(
            id="tc_1", name="ask_user_clarifying_question",
            arguments={"question": "Which segment?",
                       "why_it_matters": "TAM differs"})],
    )
    routing_json = json.dumps({
        "interpreted_query": "Q after clarification",
        "decision_type": "strategic", "complexity": "medium",
        "importance": "notable", "rationale": "Routed.",
        "members": [{"member_id": "strategist", "mode": "standard",
                     "focus": "x", "priority": 90}],
        "script": "live_research", "deep_research_dossier": False,
    })
    final_response = llm.LLMResponse(
        content=routing_json, model="m", input_tokens=1, output_tokens=1,
        latency_seconds=0.1, finish_reason="stop", tool_calls=[],
    )
    responses = iter([ask_response, final_response])
    fake_query = AsyncMock(side_effect=lambda *a, **kw: next(responses))

    # Provide an ask_user channel on session
    answers = {"Which segment?": "Independent agencies, US"}
    async def _ask(q: str, why: str) -> str:
        return answers[q]
    session = SimpleNamespace(ask_user=_ask)

    with patch("server.board.deliberation.intake.query_llm", fake_query):
        rd = await intake_mod.run_chair_intake(
            raw_query="Should we build for agencies?",
            user_overrides=intake_mod.ChairOverrides(),
            session=session, on_event=lambda e: None,
            chair_model="kimi/kimi-k2.6",
        )
    assert rd.decision_type == "strategic"
    assert fake_query.call_count == 2
```

- [ ] **Step 2: Run test**

```bash
uv run pytest tests/test_intake.py::test_run_chair_intake_clarification_then_route -v
```
Expected: PASS — already implemented in Task 19's loop. If it FAILs, debug.

- [ ] **Step 3: Commit**

```bash
git add tests/test_intake.py
git commit -m "test(intake): pin clarification turn → routing flow"
```

---

## Day 6 — Live mode integration

### Task 21: `LiveSession.script` field, scripted dispatch

**Files:**
- Modify: `server/board/deliberation/live.py`
- Create: `tests/test_live_research_script.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_live_research_script.py`:

```python
"""Live `live_research` script integration tests."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from server.board import llm
from server.board.deliberation import live, intake as intake_mod


async def test_live_research_runs_intake_then_first_round(monkeypatch, tmp_path):
    """Smoke: live_research script invokes chair intake, then runs assigned members."""
    proto = tmp_path / "chair_intake.md"
    proto.write_text("test")
    monkeypatch.setattr(intake_mod, "_PROTOCOL_PATH", str(proto))

    routing_json = json.dumps({
        "interpreted_query": "Q",
        "decision_type": "strategic", "complexity": "medium",
        "importance": "notable", "rationale": "ok",
        "members": [
            {"member_id": "strategist", "mode": "standard",
             "focus": "x", "priority": 90},
            {"member_id": "researcher", "mode": "standard",
             "focus": "y", "priority": 80},
        ],
        "script": "live_research", "deep_research_dossier": False,
    })
    intake_resp = llm.LLMResponse(
        content=routing_json, model="m", input_tokens=1, output_tokens=1,
        latency_seconds=0.1, finish_reason="stop", tool_calls=[],
    )
    member_resp = llm.LLMResponse(
        content="strategist analysis here", model="m",
        input_tokens=1, output_tokens=1, latency_seconds=0.1,
        finish_reason="stop", tool_calls=[],
    )

    call_log: list[tuple[str, ...]] = []
    async def fake_query(model, messages, **kw):
        # Detect intake by tools list including ask_user
        tools_kw = kw.get("tools") or []
        names = {t.get("function", {}).get("name") for t in tools_kw}
        if "ask_user_clarifying_question" in names:
            call_log.append(("intake",))
            return intake_resp
        call_log.append(("member", model))
        return member_resp

    with patch("server.board.deliberation.intake.query_llm",
               AsyncMock(side_effect=fake_query)), \
         patch("server.board.deliberation.orchestrator.query_llm",
                AsyncMock(side_effect=fake_query)):
        result = await live.run_live_research(
            query="Q",
            user_overrides=intake_mod.ChairOverrides(),
        )
    assert "strategist" in result.member_responses
    assert "researcher" in result.member_responses
    # intake fired first
    assert call_log[0] == ("intake",)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_live_research_script.py -v
```
Expected: FAIL — `run_live_research` not defined.

- [ ] **Step 3: Implement `run_live_research`**

Append to `server/board/deliberation/live.py`:

```python
import asyncio as _aio
from dataclasses import dataclass as _dc, field as _field

from ..config import BoardMember, get_chairman_model, get_council_models, get_members_by_id
from ..tools import TOOLS, Tool
from .intake import (
    ChairOverrides, MemberAssignment, RoutingDecision, run_chair_intake,
)
from .orchestrator import (
    MemberTurnResult, ToolBudget, agentic_member_turn,
)


PHASE1_UPGRADED_MEMBERS = {"strategist", "researcher"}
PHASE1_TOOLS_FOR_MEMBERS = ["web_search", "fetch_url", "open_browser",
                             "ask_user_clarifying_question"]


@_dc
class LiveResearchResult:
    routing: RoutingDecision
    member_responses: dict[str, MemberTurnResult] = _field(default_factory=dict)


def _phase1_mode_override(assignments: list[MemberAssignment]) -> list[MemberAssignment]:
    """Phase 1: only strategist+researcher can run with tools. Force all
    other members to mode=fast."""
    out: list[MemberAssignment] = []
    for a in assignments:
        if a.member_id in PHASE1_UPGRADED_MEMBERS:
            out.append(a)
        else:
            out.append(MemberAssignment(
                member_id=a.member_id, mode="fast",
                focus=a.focus, priority=a.priority,
            ))
    return out


def _select_member_model(member_id: str, council_models: list[str]) -> str:
    """Round-robin council models by member id; deterministic for tests."""
    if not council_models:
        return get_chairman_model()
    members = ["strategist", "product", "researcher", "critic",
               "architect", "builder"]
    try:
        idx = members.index(member_id)
    except ValueError:
        idx = 0
    return council_models[idx % len(council_models)]


def _budget_descriptor(budget: ToolBudget) -> str:
    return (f"{budget.tool_calls_max} tool calls, "
            f"{budget.web_search_max} web searches, "
            f"{budget.open_browser_max} browser opens, "
            f"{budget.wall_seconds_max}s wall budget")


def _user_message_for_member(query: str, focus: str, budget: ToolBudget) -> str:
    return (f"User query: {query}\n\n"
            f"Your focus: {focus}\n\n"
            f"Your tool budget: {_budget_descriptor(budget)}.\n\n"
            "Produce your Stage 1 analysis per your role's operating procedures.")


async def run_live_research(
    *,
    query: str,
    user_overrides: ChairOverrides | None = None,
    on_event=None,
) -> LiveResearchResult:
    """Phase 1 live_research script: intake → first round → return.
    Secretary brief is added in Task 23."""
    overrides = user_overrides or ChairOverrides()
    on_event = on_event or (lambda e: None)
    session = SimpleNamespace(session_id=None, ask_user=getattr(overrides, "ask_user", None))

    routing = await run_chair_intake(
        raw_query=query,
        user_overrides=overrides,
        session=session,
        on_event=on_event,
        chair_model=get_chairman_model(),
    )
    routing_with_phase1 = RoutingDecision(
        interpreted_query=routing.interpreted_query,
        decision_type=routing.decision_type,
        complexity=routing.complexity,
        importance=routing.importance,
        rationale=routing.rationale,
        members=_phase1_mode_override(routing.members),
        script=routing.script,
        deep_research_dossier=routing.deep_research_dossier,
    )

    members_by_id = get_members_by_id()
    council = get_council_models()
    available_tools = [TOOLS[n] for n in PHASE1_TOOLS_FOR_MEMBERS if n in TOOLS]

    async def _run_one(asg: MemberAssignment):
        member = members_by_id.get(asg.member_id)
        if member is None:
            return asg.member_id, None
        budget = ToolBudget.for_mode(asg.mode, member_role="member")
        tools_for_member = available_tools if asg.mode != "fast" else []
        model = _select_member_model(asg.member_id, council)
        result = await agentic_member_turn(
            member=member,
            model=model,
            system_prompt=member.system_prompt,
            initial_user_message=_user_message_for_member(
                routing_with_phase1.interpreted_query, asg.focus, budget),
            tools=tools_for_member,
            budget=budget,
            session=session,
            stage=1,
            on_event=on_event,
        )
        return asg.member_id, result

    pairs = await _aio.gather(*[_run_one(a) for a in routing_with_phase1.members])
    responses = {mid: r for mid, r in pairs if r is not None}
    return LiveResearchResult(routing=routing_with_phase1, member_responses=responses)
```

If `SimpleNamespace` isn't already imported in live.py, add `from types import SimpleNamespace`.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_live_research_script.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/board/deliberation/live.py tests/test_live_research_script.py
git commit -m "feat(live): live_research script — intake + first round"
```

---

### Task 22: Phase-1 mode override (forces non-upgraded members to fast)

**Files:**
- Modify: `tests/test_live_research_script.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_live_research_script.py`:

```python
async def test_live_research_forces_non_upgraded_members_to_fast(monkeypatch, tmp_path):
    """Phase 1: critic/architect/etc. must run mode=fast even if chair routes 'deep'."""
    proto = tmp_path / "chair_intake.md"
    proto.write_text("test")
    monkeypatch.setattr(intake_mod, "_PROTOCOL_PATH", str(proto))

    routing_json = json.dumps({
        "interpreted_query": "Q",
        "decision_type": "strategic", "complexity": "high",
        "importance": "critical", "rationale": "deep all",
        "members": [
            {"member_id": "strategist", "mode": "deep",
             "focus": "x", "priority": 90},
            {"member_id": "critic",     "mode": "deep",
             "focus": "x", "priority": 75},
        ],
        "script": "live_research", "deep_research_dossier": False,
    })
    intake_resp = llm.LLMResponse(
        content=routing_json, model="m", input_tokens=1, output_tokens=1,
        latency_seconds=0.1, finish_reason="stop", tool_calls=[],
    )
    member_resp = llm.LLMResponse(
        content="x analysis", model="m", input_tokens=1, output_tokens=1,
        latency_seconds=0.1, finish_reason="stop", tool_calls=[],
    )

    captured_tools_per_call: list[list] = []
    async def fake_query(model, messages, **kw):
        if any(t.get("function", {}).get("name") == "ask_user_clarifying_question"
               for t in (kw.get("tools") or [])):
            return intake_resp
        captured_tools_per_call.append(kw.get("tools"))
        return member_resp

    with patch("server.board.deliberation.intake.query_llm",
               AsyncMock(side_effect=fake_query)), \
         patch("server.board.deliberation.orchestrator.query_llm",
                AsyncMock(side_effect=fake_query)):
        result = await live.run_live_research(
            query="Q", user_overrides=intake_mod.ChairOverrides())
    # critic should have been called with tools=None (fast mode)
    # strategist should have been called with tools=[...]
    # We can't 1:1 attribute calls; assert at least one None and at least one with tools.
    assert any(t is None for t in captured_tools_per_call)
    assert any(t for t in captured_tools_per_call if t)
```

- [ ] **Step 2: Run test**

```bash
uv run pytest tests/test_live_research_script.py::test_live_research_forces_non_upgraded_members_to_fast -v
```
Expected: PASS — Task 21's `_phase1_mode_override` already enforces this.

- [ ] **Step 3: Commit**

```bash
git add tests/test_live_research_script.py
git commit -m "test(live): pin Phase-1 fast-mode override for non-upgraded members"
```

---

### Task 23: CLI integration — `--depth`, `--live-research`, secretary brief

**Files:**
- Modify: `server/cli.py`
- Modify: `server/board/deliberation/live.py`

- [ ] **Step 1: Wire a secretary brief at the end of `run_live_research`**

In `server/board/deliberation/live.py`, modify `run_live_research` to call the existing `format_live_secretary_brief` (already imported in `live.py`) and the chairperson model to produce a brief. Append after the `pairs = await _aio.gather(...)` line:

```python
    # Phase 1: secretary brief (no Sources section yet)
    transcript_lines = [
        f"## {members_by_id[mid].title}\n\n{r.content}"
        for mid, r in responses.items()
    ]
    brief_user_prompt = (
        f"User query: {routing_with_phase1.interpreted_query}\n\n"
        + "\n\n".join(transcript_lines)
    )
    from ..llm import query_llm as _q
    brief_response = await _q(
        get_chairman_model(),
        [{"role": "user", "content": brief_user_prompt}],
        system=format_live_secretary_brief(),
        max_tokens=2000,
        timeout=120.0,
    )
    return LiveResearchResult(
        routing=routing_with_phase1,
        member_responses=responses,
        secretary_brief=brief_response.content,
    )
```

Add `secretary_brief: str = ""` field to `LiveResearchResult`.

(Note: `format_live_secretary_brief` is `format_live_secretary_brief()` in `prompts.py`. Verify the import is `from .prompts import format_live_secretary_brief` and it exists, or use the existing prompt path used by today's live mode.)

- [ ] **Step 2: Add `--depth` and `--live-research` flags to `server/cli.py`**

In `server/cli.py`, find the existing argument parser. Add:

```python
parser.add_argument(
    "--depth", choices=["fast", "standard", "deep"], default=None,
    help="Force depth for all members (overrides chair's routing).",
)
parser.add_argument(
    "--live-research", action="store_true",
    help="Use the new live_research script (chair intake + agentic members).",
)
parser.add_argument(
    "--intake-skip", action="store_true",
    help="Skip chair intake; use DEFAULT_ROUTING.",
)
```

Then add a branch (early in the request-dispatch logic):

```python
if args.live_research:
    from server.board.deliberation.live import run_live_research
    from server.board.deliberation.intake import ChairOverrides

    overrides = ChairOverrides(
        depth=args.depth,
        members_filter=(args.members.split(",") if args.members else None),
        intake=not args.intake_skip,
    )

    async def _ask_user(question: str, why: str) -> str:
        print(f"\n[CHAIR ASKS] {question}\n  (why: {why})")
        try:
            return input("> ").strip()
        except EOFError:
            return "[NO_USER_RESPONSE]"
    overrides.ask_user = _ask_user

    def _print_event(ev):
        kind = getattr(ev, "kind", str(ev))
        args_ = getattr(ev, "args", ())
        print(f"  · {kind}: {args_}")

    result = asyncio.run(run_live_research(
        query=args.query, user_overrides=overrides, on_event=_print_event,
    ))
    print("\n=== Routing ===")
    print(f"  decision_type: {result.routing.decision_type}")
    print(f"  members: {[(m.member_id, m.mode) for m in result.routing.members]}")
    for mid, mr in result.member_responses.items():
        print(f"\n=== {mid} ===\n{mr.content}\n")
    print("\n=== Secretary Brief ===")
    print(result.secretary_brief)
    return
```

(Verify the existing `args.members` and `args.query` argument names in your `cli.py` and adjust accordingly.)

`ChairOverrides` doesn't currently have an `ask_user` field — add it:

In `server/board/deliberation/intake.py`, modify the `ChairOverrides` dataclass:

```python
@dataclass
class ChairOverrides:
    depth: str | None = None
    members_filter: list[str] | None = None
    intake: bool = True
    ask_user: Callable | None = None  # async (q, why) -> str
```

And in `run_live_research`, when building the `session`, propagate `ask_user`:

```python
session = SimpleNamespace(
    session_id=None,
    ask_user=overrides.ask_user,
)
```

- [ ] **Step 3: Run a manual end-to-end test (live API)**

```bash
uv run python -m server.cli --live-research --depth deep \
    --members strategist,researcher \
    "Should I build an AI campaign brief tool for digital marketing agencies?"
```

Expected:
- Chair intake fires; if the query is judged ambiguous, prompts you for clarifications.
- Strategist + Researcher run with tool events streaming as bullets.
- One or both visibly run a `web_search`; one likely runs `open_browser` (Chrome opens).
- Secretary brief prints.
- Total wall time <10 minutes.

- [ ] **Step 4: Commit**

```bash
git add server/cli.py server/board/deliberation/live.py server/board/deliberation/intake.py
git commit -m "feat(cli): --live-research flag + --depth + secretary brief integration"
```

---

### Task 24: Asciinema recording for the demo

**Files:**
- Create: `docs/agentic-research-demo.md`

- [ ] **Step 1: Write the demo README**

Create `docs/agentic-research-demo.md`:

```markdown
# Agentic Research Loop — Demo

Phase 1 demo of board members running real research with tool-use loops.

## Prerequisites

```bash
uv sync
uv run playwright install chromium
```

Set API keys in `.env`:
- `MOONSHOT_API_KEY` (Kimi, chair)
- `DEEPSEEK_API_KEY` (DeepSeek, council)
- `TAVILY_API_KEY` (web search)
- (Optional) `GEMINI_API_KEY` (free fallback)

Set browser mode (default is `chrome`):
- `AGENTIC_BOARD_BROWSER=chrome` — local Chrome (close any running Chrome with the same profile first)
- `AGENTIC_BOARD_BROWSER=tavily` — fallback when Playwright/Chrome aren't usable
- `AGENTIC_BOARD_BROWSER_HEADED=0` — run headless

## Run the demo

```bash
uv run python -m server.cli --live-research --depth deep \
    --members strategist,researcher \
    "Should I build an AI campaign brief tool for digital marketing agencies?"
```

You should see:

1. **Chair intake** — restates your question; may ask 1–3 clarifying
   questions.
2. **Strategist** — runs `web_search`, possibly `open_browser` (Chrome
   opens), produces analysis with `[SEARCH_EVIDENCE]` tags and inline
   citations.
3. **Researcher** — same; may also call `ask_user_clarifying_question`
   if running in `deep` mode.
4. **Secretary brief** — Agreements / Conflicts / Open Questions.

## Troubleshooting

- *"Chrome launch failed"* — Chrome is already running with this profile.
  Close it, OR set `AGENTIC_BOARD_BROWSER=tavily`.
- *Member doesn't call any tools* — the model decided it had enough
  domain knowledge. Re-run with a more specific factual question, or
  raise `--depth deep`.
- *`MOONSHOT_API_KEY` errors* — chair model lookup fails; check `.env`.

## Recording

```bash
asciinema rec docs/agentic-research-demo.cast
# run the demo command above, exit shell
```
```

- [ ] **Step 2: Commit**

```bash
git add docs/agentic-research-demo.md
git commit -m "docs: agentic research demo README"
```

---

## Day 7 — Polish

### Task 25: Error path — `ask_user` non-tty graceful return

**Files:**
- Modify: `server/cli.py`

- [ ] **Step 1: Add a tty check in the `_ask_user` defined inside `cli.py`**

Replace the `_ask_user` defined in Task 23 with:

```python
import sys

async def _ask_user(question: str, why: str) -> str:
    print(f"\n[CHAIR ASKS] {question}\n  (why: {why})")
    if not sys.stdin.isatty():
        print("  (no tty — returning [NO_USER_RESPONSE])")
        return "[NO_USER_RESPONSE]"
    try:
        return input("> ").strip()
    except (EOFError, KeyboardInterrupt):
        return "[NO_USER_RESPONSE]"
```

- [ ] **Step 2: Verify**

```bash
echo "" | uv run python -m server.cli --live-research --depth fast \
    --members strategist "Test query"
```
Expected: clarification prompt prints, `[NO_USER_RESPONSE]` returned, deliberation continues.

- [ ] **Step 3: Commit**

```bash
git add server/cli.py
git commit -m "fix(cli): ask_user gracefully returns [NO_USER_RESPONSE] in non-tty"
```

---

### Task 26: Error path — Playwright not installed → Tavily fallback

**Files:**
- Modify: `server/board/tools.py`
- Modify: `tests/test_open_browser.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_open_browser.py`:

```python
async def test_open_browser_fallback_when_playwright_missing(monkeypatch):
    """If playwright import fails, transparently fall back to Tavily."""
    monkeypatch.setenv("AGENTIC_BOARD_BROWSER", "chrome")
    fake_results = {"results": [
        {"title": "T", "url": "https://x.example", "snippet": "snip",
         "retrieved_at": "2026-05-07"},
    ]}
    fake_search = AsyncMock(return_value=fake_results)

    # Make playwright import fail
    monkeypatch.setattr(
        "builtins.__import__",
        _make_import_blocker("playwright"),
    )
    with patch("server.execution.web_search.web_search", fake_search):
        result = await tools.execute_tool(
            name="open_browser", arguments={"url": "https://x.example"},
            session=None, member_id="strategist",
        )
    assert result.error is None
    assert "T" in result.content_for_model


def _make_import_blocker(blocked_prefix: str):
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) \
        else __import__
    def blocker(name, *args, **kw):
        if name.startswith(blocked_prefix):
            raise ImportError(f"blocked {name}")
        return real_import(name, *args, **kw)
    return blocker
```

- [ ] **Step 2: Run test**

```bash
uv run pytest tests/test_open_browser.py::test_open_browser_fallback_when_playwright_missing -v
```
Expected: FAIL — current code raises ImportError.

- [ ] **Step 3: Wrap the playwright import in `_open_browser_via_playwright`**

In `server/board/tools.py`, modify `_open_browser_via_playwright` first lines:

```python
async def _open_browser_via_playwright(
    *, url: str, wait_for: str | None, extract: str, member_id: str | None,
) -> ToolResult:
    """Drive local Chrome with the user's profile via Playwright.
    Falls back to Tavily-style search if Playwright isn't installed."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        # Fall back transparently
        return await _open_browser_via_tavily(
            url=url, member_id=member_id, session=None,
        )
    # ... rest unchanged
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_open_browser.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add server/board/tools.py tests/test_open_browser.py
git commit -m "fix(tools): open_browser falls back to Tavily when Playwright missing"
```

---

### Task 27: Verifier-decoupling carve-out for demo

**Files:**
- Modify: `docs/agentic-research-demo.md`

- [ ] **Step 1: Document the override**

Append to `docs/agentic-research-demo.md` under Prerequisites:

```markdown
### If using DeepSeek as the chair (Day-1 fallback path)

The default chair is Kimi (`kimi/kimi-k2.6`); the verifier defaults to
DeepSeek. If Day-1 smoke shows Kimi's tool-calling has issues and you
swap the chair to DeepSeek:

```bash
export CHAIRMAN_MODEL=deepseek/deepseek-v4-pro
export AGENTIC_BOARD_ALLOW_SAME_VERIFIER=1   # required because
                                              # chair == verifier provider
```

Phase 1 demos run without verification (Stage 4 is opt-in), but the
guard in `server/board/config.py:_assert_verifier_decoupled` runs at
import time, so the env var is needed for `import server` to succeed.
```

- [ ] **Step 2: Commit**

```bash
git add docs/agentic-research-demo.md
git commit -m "docs: document verifier-decouple carve-out for demo fallback"
```

---

### Task 28: Final verification — three clean demo runs

**Files:** None (verification task)

- [ ] **Step 1: Clean state**

```bash
git status   # confirm working tree clean
```

- [ ] **Step 2: Run demo three times back-to-back**

```bash
for i in 1 2 3; do
    echo "=== Run $i ==="
    uv run python -m server.cli --live-research --depth standard \
        --members strategist,researcher \
        "Should I build an AI campaign brief tool for digital marketing agencies?"
    echo "=== Run $i complete ==="
done
```

Expected for each run:
- Chair intake produces a routing decision (with or without clarifications).
- Both members produce analysis.
- At least one tool call fires across the run.
- Secretary brief prints.
- Run completes without uncaught exceptions in <10 minutes.

- [ ] **Step 3: Run the full test suite**

```bash
uv run pytest tests/test_llm_tool_calls.py tests/test_tools_registry.py \
    tests/test_open_browser.py tests/test_agentic_member_turn.py \
    tests/test_intake.py tests/test_live_research_script.py -v
```
Expected: all PASS.

- [ ] **Step 4: Run the existing test suite (regression check)**

```bash
uv run pytest -q
```
Expected: existing tests still PASS. Investigate any new failures.

- [ ] **Step 5: Tag the demo-ready commit**

```bash
git tag agentic-research-phase1-demo
```

- [ ] **Step 6: Push the branch (when ready)**

```bash
git push -u origin feat/agentic-research
git push origin agentic-research-phase1-demo
```

---

## Self-review checklist (run before handoff)

Before declaring Phase 1 complete:

- [ ] Spec coverage: every section of the design spec maps to a task above. (Phase 2 / 3 items intentionally not implemented; this is by design.)
- [ ] No placeholders ("TBD", "implement later") in the code.
- [ ] No member files modified other than strategist + researcher.
- [ ] Existing live-mode CLI (`--live` without `--live-research`) still works.
- [ ] `CHAIRMAN_MODEL=kimi/kimi-k2.6` (default) runs end-to-end. If the demo had to fall back to DeepSeek as chair, it's documented in the demo README.
- [ ] At least one of the three clean demo runs visibly opened Chrome.

If any item fails, fix and re-run before tagging.

---

## Out-of-scope (deferred to Phase 2/3)

- Other 5 members upgraded with tool use.
- Mid-deliberation follow-up channel.
- Web UI streaming of tool events.
- `validate_claim` tool.
- Role-tuned tool subsets.
- Secretary `## Sources` section.
- Harness ledger tool-call tracking.
- Adaptive depth tuning loop.
- Failure-mode test suite beyond Phase 1's two error paths.
