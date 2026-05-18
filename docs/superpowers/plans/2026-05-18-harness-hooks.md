# Harness Hooks (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pre/post-tool hook registry to `server/harness/hooks/` with observe+block semantics, wire it into `server/execution/web_search.py` and `server/execution/tasks.py`, and ship two bundled hooks plus a `hook_events` ledger table.

**Architecture:** New subpackage `server/harness/hooks/` exposes `register_pre_hook`, `register_post_hook`, `dispatch_pre_hooks`, `dispatch_post_hooks`, frozen dataclasses `HookContext` and `HookVerdict`, and an exception `HookDeniedError`. Bundled hooks in `_bundled/` auto-import at startup; site-specific hooks in `_project/` (gitignored) also auto-import. Execution call sites build a `HookContext`, await `dispatch_pre_hooks`, run the tool on `allow`, raise `HookDeniedError` on `deny`, then await `dispatch_post_hooks`. Pre-hooks may not mutate `request`; post-hooks may not mutate the result. New SQLite table `hook_events(session_id, tool_name, action, reason, metadata, ts)` recorded via the existing `_ensure_columns` pattern.

**Tech Stack:** Python 3.x asyncio, dataclasses, sqlite3, pytest, existing execution layer.

---

## Preconditions

Before starting, verify the design spec exists and the gate sites are unmodified:

```bash
test -f docs/superpowers/specs/2026-05-18-harness-cross-cutting-expansion-design.md \
  && grep -q "async def web_search" server/execution/web_search.py \
  && grep -q "^def plan_delegated_task" server/execution/tasks.py \
  && grep -q "^def save_delegated_task" server/execution/tasks.py \
  && grep -q "^def update_delegated_task_status" server/execution/tasks.py \
  && echo "preconditions OK" \
  || echo "MISSING precursor — stop and read spec §5"
```

Expected: `preconditions OK`.

If `server/harness/hooks/__init__.py` already exists, stop — another branch is in progress.

## Design choices (pinned)

These are pinned by the spec (`docs/superpowers/specs/2026-05-18-harness-cross-cutting-expansion-design.md` §5) and the planning brief. Do **not** re-decide them inside tasks.

| Topic | Pinned answer | Code-facing rule |
|---|---|---|
| Public ABI dataclasses | Frozen | `@dataclass(frozen=True)` on both `HookContext` and `HookVerdict`. Pre-hooks cannot mutate `request`; post-hooks cannot mutate `result` (caller passes a read-only dict reference; ABI enforces by convention via frozen + documented contract). |
| Dispatch order | Registration order | Pre-hooks fire in the order they were registered for the given `tool_name`. First `deny` short-circuits. |
| All-allow merge | Metadata concat | When all pre-hooks return `allow`, final verdict is `allow` with `metadata = {**hook1.metadata, **hook2.metadata, ...}`. Later hooks overwrite earlier keys on collision (intentional: last-writer-wins). |
| Hook crash semantics | Treated as deny | Any exception inside a pre-hook → verdict `("deny", reason=f"hook crashed: {type(exc).__name__}", metadata={})`. Traceback is logged via `logging.exception` but never propagated to the caller. |
| Timeout per hook | `asyncio.wait_for(fn(...), timeout=5.0)` | On `asyncio.TimeoutError` → verdict `("deny", reason="hook timeout", metadata={})`. Hard-coded constant `_HOOK_TIMEOUT_SECONDS = 5.0` at module top. "Configurable" is **out of scope for V1**. |
| Post-hook semantics | Best-effort | All post-hooks fire (no short-circuit). Exceptions are logged via `logging.exception` and dropped. Timeouts use the same 5.0s wrapper but on timeout the dispatcher logs and moves on (no raise). |
| Hook discovery | Auto-import at package import | `server.harness.hooks.__init__` walks `_bundled/` and (if exists) `_project/` and `importlib.import_module`s every `*.py` that doesn't start with `_`. Modules call `register_pre_hook` / `register_post_hook` at import time. |
| `_project/` presence | Optional | If the directory doesn't exist or is empty, no error. A one-line `logging.info` records "loaded N bundled, M project hooks". |
| `HookDeniedError` | Raised from call site, not dispatch | `dispatch_pre_hooks` returns a `HookVerdict`. The call site (web_search / tasks.py) inspects `action` and raises `HookDeniedError(reason)` itself. This keeps `dispatch_pre_hooks` reusable. |
| Ledger location | Reuse `_DEFAULT_DB_PATH` from `server.harness.ledger` | `record_hook_event(...)` reads `_DEFAULT_DB_PATH` like other ledger writers; new `hook_events` table is created idempotently inside `_ensure_columns`. |
| Sync→async bridge in `tasks.py` | Small `_run_async_blocking` helper inside `tasks.py` | The three task functions are sync. They cannot `await`. The wrap uses `asyncio.run(coro)` when no event loop is running in this thread, and `asyncio.new_event_loop().run_until_complete(coro)` on a worker thread when one is. Two thin sync façades `_hook_gate_sync` and `_hook_post_sync` wrap the dispatcher. Implementation in T15 has the exact code. |
| Pre-hook async/sync calling convention | Dispatcher coerces | If a hook returns a `HookVerdict` synchronously, dispatcher wraps it via `asyncio.to_thread` only if a coroutine is *not* returned. Concretely: call `fn(ctx)`, then `if inspect.isawaitable(result): result = await asyncio.wait_for(result, timeout=5.0)`. Sync hooks therefore execute inline (no thread). The 5.0s timeout only applies to awaitables. |
| Post-hook async/sync calling convention | Same coercion | `fn(ctx, result)` then `if inspect.isawaitable(...): await asyncio.wait_for(..., 5.0)`. |
| Bundled hook persistence read | Direct sqlite query, `record_hook_event` for writes | Bundled hooks read counts/timestamps from `hook_events` via a tiny `_count_in_window(session_id, tool_name, *, window_seconds)` helper exposed by the ledger module. They do **not** maintain in-process counters (process restart safety). |
| Cap default | 20 web_search/session | `cap_web_search_per_session`: env override `AGENTIC_BOARD_WEB_SEARCH_SESSION_CAP=20` (parsed as int; falls back to 20 on parse failure). |
| Rate limit default | 5 delegated_task ops in 60s | `rate_limit_delegated_tasks`: env overrides `AGENTIC_BOARD_DELEGATED_TASK_RATE_LIMIT=5` and `AGENTIC_BOARD_DELEGATED_TASK_RATE_WINDOW_SECONDS=60`. |

## Spec ↔ Plan crosswalk

| Spec §5 element | Plan task(s) |
|---|---|
| §5.1 `HookContext` / `HookVerdict` dataclasses + frozen | T1 |
| §5.1 `PreHook` / `PostHook` type aliases | T1 |
| §5.2 `register_pre_hook` / `register_post_hook` | T2 |
| §5.2 `dispatch_pre_hooks` registration-order + merged metadata | T3 |
| §5.2 first `deny` short-circuit | T4 |
| §5.5 hook crash → deny w/ reason `"hook crashed: <type>"` | T5 |
| §5.5 timeout → deny w/ reason `"hook timeout"` | T6 |
| §5.2 `dispatch_post_hooks` all-fire, log-not-raise | T7 |
| Public `HookDeniedError` exception (gate site uses it) | T8 |
| §7 `hook_events` table via `_ensure_columns` | T9 |
| §5.2 hook discovery (`_bundled/` and `_project/`) | T10 |
| §5.4 `cap_web_search_per_session` bundled hook | T11 |
| §5.4 `rate_limit_delegated_tasks` bundled hook | T12 |
| §5.3 wrap `web_search` entry function | T13 |
| §8 integration test: denying hook → `HookDeniedError` from `web_search` | T14 |
| §5.3 wrap `plan_delegated_task` | T15 |
| §5.3 wrap `save_delegated_task` | T16 |
| §5.3 wrap `update_delegated_task_status` | T17 |
| §8 integration test under denying hook (task wrap) | T18 |

## File structure

### Created (PR2)

| File | Responsibility |
|---|---|
| `server/harness/hooks/__init__.py` | Public ABI: dataclasses, exception, registry, dispatch, auto-import walker. |
| `server/harness/hooks/_bundled/__init__.py` | Empty marker so the dir is a package. |
| `server/harness/hooks/_bundled/cap_web_search_per_session.py` | Bundled hook (T11). Registers on import. |
| `server/harness/hooks/_bundled/rate_limit_delegated_tasks.py` | Bundled hook (T12). Registers on import. |
| `tests/test_hooks_registry.py` | T1–T7 unit tests for the registry + dispatch. |
| `tests/test_hooks_ledger.py` | T9 unit tests for `record_hook_event` + `hook_events` schema. |
| `tests/test_hooks_discovery.py` | T10 auto-import + sentinel tests. |
| `tests/test_hooks_bundled.py` | T11–T12 tests for the two bundled hooks. |
| `tests/test_web_search_hook_integration.py` | T14 integration test (denying hook → `HookDeniedError`). |

### Modified (PR2)

| File | Change |
|---|---|
| `server/harness/ledger.py` | Add `hook_events` table creation inside `_ensure_columns`; add `record_hook_event(...)` and `_count_in_window(...)` public helpers (T9). |
| `server/execution/web_search.py` | Wrap the `web_search` async entry function in pre/post-hook dispatch (T13). |
| `server/execution/__init__.py` | Re-export `HookDeniedError` from `server.harness.hooks` (so call sites can `from server.execution import HookDeniedError`). |

### Created (PR3)

| File | Responsibility |
|---|---|
| `tests/test_tasks_hook_integration.py` | T18 integration test (denying hook → `HookDeniedError` from one of the three wrapped task fns). |

### Modified (PR3)

| File | Change |
|---|---|
| `server/execution/tasks.py` | Wrap `plan_delegated_task` (T15), `save_delegated_task` (T16), `update_delegated_task_status` (T17) in hook dispatch via a `_run_dispatch_sync` helper. |

### Gitignored

| Path | Reason |
|---|---|
| `server/harness/hooks/_project/` | Site-specific hooks must not leak into the repo. Added to `.gitignore`. |

### Untouched (out of scope)

- `server/board/tools.py` — `_handle_web_search` already wraps `web_search`. The hook gate fires inside `web_search` itself; nothing in `tools.py` needs to change.
- `server/api/routes/execution.py` — `execution_web_search` already awaits `web_search`; the hook gate is transparent.
- `server/board/deliberation/orchestrator.py` — awaits `web_search` via `from server.execution.web_search import web_search`; transparent.
- `server/harness/config.py` — no new config keys for hooks; bundled hooks use env vars (out of scope for V1 to make configurable from `HarnessConfig`).
- Mutation hooks. Observe + block only (spec §5.1, §10).
- `record_hook_event` integration with tuners. Tuners learn from `hook_events` is a future concern; this plan only writes the table.

---

# PR2 — Hook infra and web_search wrap

## Task 1: Dataclasses (`HookContext`, `HookVerdict`) + type aliases

**Files:**
- Create: `server/harness/hooks/__init__.py` (skeleton — just imports + dataclasses; registry/dispatch in later tasks)
- Create: `tests/test_hooks_registry.py`

Pin the public ABI. Both dataclasses are frozen so pre-hooks cannot mutate `request` and post-hook authors cannot mutate `result` via the verdict object. The type aliases stay at module-level for readability and tuner-friendly introspection later.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_hooks_registry.py`:

```python
"""Unit tests for server.harness.hooks registry and dispatch."""
from __future__ import annotations

import asyncio
import dataclasses

import pytest


def test_hook_context_is_frozen_dataclass():
    from server.harness.hooks import HookContext
    ctx = HookContext(
        tool_name="web_search",
        stage=1,
        session_id="sess_abc",
        member_id="strategist",
        request={"query": "anything"},
    )
    assert ctx.tool_name == "web_search"
    assert ctx.stage == 1
    assert ctx.session_id == "sess_abc"
    assert ctx.member_id == "strategist"
    assert ctx.request == {"query": "anything"}
    # Frozen: assignment must raise.
    with pytest.raises(dataclasses.FrozenInstanceError):
        ctx.tool_name = "other"  # type: ignore[misc]


def test_hook_context_allows_none_member_id():
    """Harness-internal calls have no member_id."""
    from server.harness.hooks import HookContext
    ctx = HookContext(
        tool_name="delegated_task",
        stage=0,
        session_id="sess_abc",
        member_id=None,
        request={"task_id": "t1"},
    )
    assert ctx.member_id is None


def test_hook_verdict_is_frozen_dataclass_with_allow():
    from server.harness.hooks import HookVerdict
    v = HookVerdict(action="allow", reason=None, metadata={"k": "v"})
    assert v.action == "allow"
    assert v.reason is None
    assert v.metadata == {"k": "v"}
    with pytest.raises(dataclasses.FrozenInstanceError):
        v.action = "deny"  # type: ignore[misc]


def test_hook_verdict_deny_carries_reason():
    from server.harness.hooks import HookVerdict
    v = HookVerdict(action="deny", reason="cap exceeded", metadata={"count": 21})
    assert v.action == "deny"
    assert v.reason == "cap exceeded"
    assert v.metadata == {"count": 21}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_hooks_registry.py -v -k "hook_context or hook_verdict"`

Expected: 4 FAIL with `ModuleNotFoundError: No module named 'server.harness.hooks'`.

- [ ] **Step 3: Create the package skeleton with dataclasses**

Create `server/harness/hooks/__init__.py`:

```python
"""Pre/post-tool hook registry (spec §5).

Public ABI:
  - HookContext  (frozen dataclass; pre-hooks may not mutate request)
  - HookVerdict  (frozen dataclass; allow|deny + reason + metadata)
  - PreHook, PostHook  (type aliases)
  - register_pre_hook / register_post_hook  (registration)
  - dispatch_pre_hooks / dispatch_post_hooks  (async dispatch)
  - HookDeniedError  (raised by call sites on deny verdict)

Bundled hooks under _bundled/ and (if present) _project/ are auto-imported
at package import so their @register_* calls fire exactly once.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, Union


@dataclass(frozen=True)
class HookContext:
    """Read-only context handed to every hook.

    Pre-hooks must not mutate `request`. The dataclass is frozen, but
    `request` is a dict (mutable). The contract is enforced by convention
    and documented here; misbehaving hooks are caller-traceable via the
    `hook_events` ledger row's `metadata` field.
    """
    tool_name: str
    stage: int
    session_id: str
    member_id: str | None
    request: dict


@dataclass(frozen=True)
class HookVerdict:
    """A pre-hook's decision. Post-hooks return None, not a HookVerdict."""
    action: Literal["allow", "deny"]
    reason: str | None
    metadata: dict


PreHook = Callable[[HookContext], Union[HookVerdict, Awaitable[HookVerdict]]]
PostHook = Callable[[HookContext, dict], Union[None, Awaitable[None]]]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_hooks_registry.py -v -k "hook_context or hook_verdict"`

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add server/harness/hooks/__init__.py tests/test_hooks_registry.py
git commit -m "$(cat <<'EOF'
hooks(p2): add HookContext/HookVerdict frozen dataclasses + type aliases

Spec §5.1 — public ABI dataclasses for the harness hook registry.
HookContext is frozen so pre-hooks cannot mutate it; the `request`
dict's read-only contract is documented in the docstring.
EOF
)"
```

---

## Task 2: Registry (`register_pre_hook`, `register_post_hook`, reset helper)

**Files:**
- Modify: `server/harness/hooks/__init__.py`
- Modify: `tests/test_hooks_registry.py`

In-memory registry of `{tool_name → [hook_fn, ...]}`. Tests need snapshot/restore helpers (rather than a hard reset) so each test starts from a clean slate without permanently wiping bundled hooks loaded at package import. Both helpers are underscore-prefixed (`_snapshot_registry`, `_restore_registry`) so production code never calls them.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hooks_registry.py`:

```python
# ─── T2: registry ──────────────────────────────────────────────────────────


@pytest.fixture
def fresh_registry():
    """Snapshot + restore the registry so tests run in isolation."""
    from server.harness.hooks import _snapshot_registry, _restore_registry
    snapshot = _snapshot_registry()
    yield
    _restore_registry(snapshot)


def test_register_pre_hook_stores_callable_for_tool(fresh_registry):
    from server.harness.hooks import (
        HookContext, HookVerdict, register_pre_hook, _list_pre_hooks_for_tests,
    )

    def hook(ctx: HookContext) -> HookVerdict:
        return HookVerdict(action="allow", reason=None, metadata={})

    register_pre_hook("web_search", hook)
    hooks = _list_pre_hooks_for_tests("web_search")
    assert len(hooks) == 1
    assert hooks[0] is hook


def test_register_pre_hook_preserves_registration_order(fresh_registry):
    from server.harness.hooks import (
        HookVerdict, register_pre_hook, _list_pre_hooks_for_tests,
    )

    def a(ctx):
        return HookVerdict("allow", None, {})

    def b(ctx):
        return HookVerdict("allow", None, {})

    def c(ctx):
        return HookVerdict("allow", None, {})

    register_pre_hook("web_search", a)
    register_pre_hook("web_search", b)
    register_pre_hook("web_search", c)
    hooks = _list_pre_hooks_for_tests("web_search")
    assert hooks == [a, b, c]


def test_register_post_hook_stores_callable_for_tool(fresh_registry):
    from server.harness.hooks import (
        HookContext, register_post_hook, _list_post_hooks_for_tests,
    )

    def hook(ctx: HookContext, result: dict) -> None:
        return None

    register_post_hook("delegated_task", hook)
    hooks = _list_post_hooks_for_tests("delegated_task")
    assert len(hooks) == 1
    assert hooks[0] is hook


def test_register_isolates_by_tool_name(fresh_registry):
    from server.harness.hooks import (
        HookVerdict, register_pre_hook, _list_pre_hooks_for_tests,
    )

    def hook(ctx):
        return HookVerdict("allow", None, {})

    register_pre_hook("web_search", hook)
    assert len(_list_pre_hooks_for_tests("web_search")) == 1
    assert _list_pre_hooks_for_tests("delegated_task") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_hooks_registry.py -v -k "register"`

Expected: 4 FAIL with `ImportError: cannot import name 'register_pre_hook'`.

- [ ] **Step 3: Implement the registry**

Append to `server/harness/hooks/__init__.py`:

```python
# ─── Registry ──────────────────────────────────────────────────────────────

_pre_hooks: dict[str, list[PreHook]] = {}
_post_hooks: dict[str, list[PostHook]] = {}


def register_pre_hook(tool_name: str, fn: PreHook) -> None:
    """Append a pre-hook for `tool_name`. Idempotent per (tool, fn) pair."""
    bucket = _pre_hooks.setdefault(tool_name, [])
    if fn not in bucket:
        bucket.append(fn)


def register_post_hook(tool_name: str, fn: PostHook) -> None:
    """Append a post-hook for `tool_name`. Idempotent per (tool, fn) pair."""
    bucket = _post_hooks.setdefault(tool_name, [])
    if fn not in bucket:
        bucket.append(fn)


# ─── Test-only helpers (underscore = private; never call from production) ─

def _snapshot_registry() -> tuple[dict, dict]:
    """Deep-ish snapshot for test fixture restoration."""
    return (
        {k: list(v) for k, v in _pre_hooks.items()},
        {k: list(v) for k, v in _post_hooks.items()},
    )


def _restore_registry(snapshot: tuple[dict, dict]) -> None:
    pre, post = snapshot
    _pre_hooks.clear()
    _pre_hooks.update({k: list(v) for k, v in pre.items()})
    _post_hooks.clear()
    _post_hooks.update({k: list(v) for k, v in post.items()})


def _list_pre_hooks_for_tests(tool_name: str) -> list[PreHook]:
    return list(_pre_hooks.get(tool_name, []))


def _list_post_hooks_for_tests(tool_name: str) -> list[PostHook]:
    return list(_post_hooks.get(tool_name, []))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_hooks_registry.py -v -k "register"`

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add server/harness/hooks/__init__.py tests/test_hooks_registry.py
git commit -m "$(cat <<'EOF'
hooks(p2): add register_pre_hook/register_post_hook with idempotent append

Spec §5.2 — in-memory registry keyed by tool_name. Registration
preserves insertion order (load-bearing for first-deny short-circuit).
Snapshot/restore helpers gate test isolation.
EOF
)"
```

---

## Task 3: `dispatch_pre_hooks` happy path (all-allow + merged metadata)

**Files:**
- Modify: `server/harness/hooks/__init__.py`
- Modify: `tests/test_hooks_registry.py`

When every pre-hook returns `allow`, the dispatcher returns one `HookVerdict(action="allow", reason=None, metadata=<merged>)`. Metadata merges via `{**a.metadata, **b.metadata}` so later hooks overwrite earlier keys on collision. Sync and async hooks both supported; sync hooks execute inline.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hooks_registry.py`:

```python
# ─── T3: dispatch_pre_hooks happy path ─────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_pre_hooks_no_hooks_returns_allow(fresh_registry):
    from server.harness.hooks import HookContext, dispatch_pre_hooks

    ctx = HookContext("web_search", 1, "s", None, {"query": "x"})
    verdict = await dispatch_pre_hooks(ctx)
    assert verdict.action == "allow"
    assert verdict.reason is None
    assert verdict.metadata == {}


@pytest.mark.asyncio
async def test_dispatch_pre_hooks_all_allow_returns_allow(fresh_registry):
    from server.harness.hooks import (
        HookContext, HookVerdict, dispatch_pre_hooks, register_pre_hook,
    )

    def hook_a(ctx):
        return HookVerdict("allow", None, {"a": 1})

    def hook_b(ctx):
        return HookVerdict("allow", None, {"b": 2})

    register_pre_hook("web_search", hook_a)
    register_pre_hook("web_search", hook_b)

    ctx = HookContext("web_search", 1, "s", None, {"query": "x"})
    verdict = await dispatch_pre_hooks(ctx)
    assert verdict.action == "allow"
    assert verdict.reason is None
    assert verdict.metadata == {"a": 1, "b": 2}


@pytest.mark.asyncio
async def test_dispatch_pre_hooks_supports_async_hooks(fresh_registry):
    from server.harness.hooks import (
        HookContext, HookVerdict, dispatch_pre_hooks, register_pre_hook,
    )

    async def hook(ctx):
        return HookVerdict("allow", None, {"async": True})

    register_pre_hook("web_search", hook)

    ctx = HookContext("web_search", 1, "s", None, {"query": "x"})
    verdict = await dispatch_pre_hooks(ctx)
    assert verdict.action == "allow"
    assert verdict.metadata == {"async": True}


@pytest.mark.asyncio
async def test_dispatch_pre_hooks_later_hook_overwrites_metadata_key(fresh_registry):
    from server.harness.hooks import (
        HookContext, HookVerdict, dispatch_pre_hooks, register_pre_hook,
    )

    def hook_a(ctx):
        return HookVerdict("allow", None, {"shared": "first"})

    def hook_b(ctx):
        return HookVerdict("allow", None, {"shared": "second"})

    register_pre_hook("web_search", hook_a)
    register_pre_hook("web_search", hook_b)

    ctx = HookContext("web_search", 1, "s", None, {"query": "x"})
    verdict = await dispatch_pre_hooks(ctx)
    assert verdict.metadata == {"shared": "second"}
```

Add a project-level pytest marker so `pytest.mark.asyncio` works:

```bash
grep -q "asyncio_mode" pyproject.toml && echo "asyncio_mode already set" \
  || grep -q "^\[tool.pytest.ini_options\]" pyproject.toml && echo "pytest section exists — manually verify asyncio_mode" \
  || echo "no pytest config — pytest-asyncio still works with @pytest.mark.asyncio explicit"
```

If the project already uses `pytest-asyncio`, this should be sufficient. If `pyproject.toml` lacks `[tool.pytest.ini_options]` with `asyncio_mode = "auto"`, the explicit `@pytest.mark.asyncio` marker on each async test handles it.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_hooks_registry.py -v -k "dispatch_pre_hooks"`

Expected: 4 FAIL with `ImportError: cannot import name 'dispatch_pre_hooks'`.

- [ ] **Step 3: Implement `dispatch_pre_hooks` (happy path only — deny/exception/timeout added in T4–T6)**

Append to `server/harness/hooks/__init__.py`:

```python
# ─── Dispatch ──────────────────────────────────────────────────────────────

import inspect

_HOOK_TIMEOUT_SECONDS: float = 5.0


async def _await_if_needed_pre(fn: PreHook, ctx: HookContext) -> HookVerdict:
    """Call a pre-hook; await if it returned a coroutine.

    Sync hooks execute inline (no thread). Async hooks are wrapped in
    asyncio.wait_for with the module-level timeout.
    """
    import asyncio  # local import keeps the module's top section visible

    result = fn(ctx)
    if inspect.isawaitable(result):
        result = await asyncio.wait_for(result, timeout=_HOOK_TIMEOUT_SECONDS)
    return result


async def dispatch_pre_hooks(ctx: HookContext) -> HookVerdict:
    """Run every pre-hook registered for ctx.tool_name in registration order.

    On all-allow: returns one verdict with merged metadata (later hook
    overwrites earlier on key collision).
    On first-deny: short-circuit and return that verdict.  (Implemented in T4.)
    On hook crash: convert to deny.  (Implemented in T5.)
    On hook timeout: convert to deny.  (Implemented in T6.)
    """
    merged_metadata: dict = {}
    for fn in _pre_hooks.get(ctx.tool_name, []):
        verdict = await _await_if_needed_pre(fn, ctx)
        if verdict.action == "deny":
            return verdict  # short-circuit (test in T4)
        merged_metadata = {**merged_metadata, **verdict.metadata}
    return HookVerdict(action="allow", reason=None, metadata=merged_metadata)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_hooks_registry.py -v -k "dispatch_pre_hooks"`

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add server/harness/hooks/__init__.py tests/test_hooks_registry.py
git commit -m "$(cat <<'EOF'
hooks(p2): add dispatch_pre_hooks happy path with metadata merge

Spec §5.2 — sync and async pre-hooks. All-allow returns one verdict
with metadata merged via dict-spread (later hook wins on collision).
First-deny short-circuit branch exists but is not yet test-covered
(T4 will cover; ledger writes wait until T9).
EOF
)"
```

---

## Task 4: `dispatch_pre_hooks` first-deny short-circuits

**Files:**
- Modify: `tests/test_hooks_registry.py`

Behavior is already coded in T3. This task just covers it with explicit tests so a regression future-developer can't silently drop the short-circuit.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hooks_registry.py`:

```python
# ─── T4: dispatch_pre_hooks first-deny short-circuits ──────────────────────


@pytest.mark.asyncio
async def test_dispatch_pre_hooks_first_deny_returns_immediately(fresh_registry):
    from server.harness.hooks import (
        HookContext, HookVerdict, dispatch_pre_hooks, register_pre_hook,
    )

    def hook_a(ctx):
        return HookVerdict("deny", "first", {"first": True})

    calls: list[str] = []

    def hook_b(ctx):
        calls.append("b")
        return HookVerdict("allow", None, {})

    register_pre_hook("web_search", hook_a)
    register_pre_hook("web_search", hook_b)

    ctx = HookContext("web_search", 1, "s", None, {"query": "x"})
    verdict = await dispatch_pre_hooks(ctx)

    assert verdict.action == "deny"
    assert verdict.reason == "first"
    assert verdict.metadata == {"first": True}
    assert calls == [], "hook_b must not run when hook_a denies"


@pytest.mark.asyncio
async def test_dispatch_pre_hooks_second_deny_after_first_allow(fresh_registry):
    from server.harness.hooks import (
        HookContext, HookVerdict, dispatch_pre_hooks, register_pre_hook,
    )

    def hook_a(ctx):
        return HookVerdict("allow", None, {"a": 1})

    def hook_b(ctx):
        return HookVerdict("deny", "second", {})

    register_pre_hook("web_search", hook_a)
    register_pre_hook("web_search", hook_b)

    ctx = HookContext("web_search", 1, "s", None, {"query": "x"})
    verdict = await dispatch_pre_hooks(ctx)

    assert verdict.action == "deny"
    assert verdict.reason == "second"
```

- [ ] **Step 2: Run tests to verify they pass (already implemented in T3)**

Run: `uv run pytest tests/test_hooks_registry.py -v -k "first_deny or second_deny"`

Expected: 2 PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_hooks_registry.py
git commit -m "$(cat <<'EOF'
hooks(p2): test first-deny short-circuit in dispatch_pre_hooks

Spec §5.2 — pins the short-circuit semantics (later hooks must not
run after a deny) so a future refactor can't silently re-introduce
full-chain evaluation.
EOF
)"
```

---

## Task 5: `dispatch_pre_hooks` exception → deny conversion

**Files:**
- Modify: `server/harness/hooks/__init__.py`
- Modify: `tests/test_hooks_registry.py`

A buggy hook that raises must not take down the call site. Conversion: `verdict = HookVerdict("deny", f"hook crashed: {type(exc).__name__}", {})`; the traceback is `logging.exception`-ed.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hooks_registry.py`:

```python
# ─── T5: hook crash → deny ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_pre_hooks_sync_hook_raise_becomes_deny(fresh_registry, caplog):
    import logging
    from server.harness.hooks import (
        HookContext, dispatch_pre_hooks, register_pre_hook,
    )

    def crashy(ctx):
        raise ValueError("kaboom")

    register_pre_hook("web_search", crashy)

    ctx = HookContext("web_search", 1, "s", None, {"query": "x"})
    with caplog.at_level(logging.ERROR, logger="server.harness.hooks"):
        verdict = await dispatch_pre_hooks(ctx)

    assert verdict.action == "deny"
    assert verdict.reason == "hook crashed: ValueError"
    assert verdict.metadata == {}
    # Traceback was logged, not propagated.
    assert any("kaboom" in rec.message or "kaboom" in str(rec.exc_info) for rec in caplog.records), \
        "exception traceback should be logged via logging.exception"


@pytest.mark.asyncio
async def test_dispatch_pre_hooks_async_hook_raise_becomes_deny(fresh_registry):
    from server.harness.hooks import (
        HookContext, dispatch_pre_hooks, register_pre_hook,
    )

    async def crashy(ctx):
        raise RuntimeError("async kaboom")

    register_pre_hook("web_search", crashy)

    ctx = HookContext("web_search", 1, "s", None, {"query": "x"})
    verdict = await dispatch_pre_hooks(ctx)

    assert verdict.action == "deny"
    assert verdict.reason == "hook crashed: RuntimeError"


@pytest.mark.asyncio
async def test_dispatch_pre_hooks_crash_short_circuits_remaining(fresh_registry):
    """A crashed hook denies; later hooks must not run."""
    from server.harness.hooks import (
        HookContext, HookVerdict, dispatch_pre_hooks, register_pre_hook,
    )

    def crashy(ctx):
        raise ValueError("boom")

    calls: list[str] = []

    def later(ctx):
        calls.append("later")
        return HookVerdict("allow", None, {})

    register_pre_hook("web_search", crashy)
    register_pre_hook("web_search", later)

    ctx = HookContext("web_search", 1, "s", None, {"query": "x"})
    verdict = await dispatch_pre_hooks(ctx)

    assert verdict.action == "deny"
    assert calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_hooks_registry.py -v -k "crash"`

Expected: 3 FAIL — the dispatch propagates the raised exception (no try/except yet).

- [ ] **Step 3: Wrap each hook call in try/except**

Modify `dispatch_pre_hooks` in `server/harness/hooks/__init__.py`. Replace the existing function body with:

```python
import logging

_logger = logging.getLogger(__name__)


async def dispatch_pre_hooks(ctx: HookContext) -> HookVerdict:
    """Run every pre-hook registered for ctx.tool_name in registration order.

    On all-allow: returns one verdict with merged metadata (later hook
    overwrites earlier on key collision).
    On first-deny: short-circuit and return that verdict.
    On hook crash: convert to deny with reason 'hook crashed: <Type>'.
    On hook timeout: convert to deny with reason 'hook timeout' (T6).
    """
    import asyncio

    merged_metadata: dict = {}
    for fn in _pre_hooks.get(ctx.tool_name, []):
        try:
            verdict = await _await_if_needed_pre(fn, ctx)
        except asyncio.TimeoutError:
            # Handled in T6; placeholder to silence pyflakes ordering.
            verdict = HookVerdict(
                action="deny",
                reason="hook timeout",
                metadata={},
            )
        except Exception as exc:  # noqa: BLE001 — intentional broad catch
            _logger.exception("Hook %r crashed for tool %s", fn, ctx.tool_name)
            verdict = HookVerdict(
                action="deny",
                reason=f"hook crashed: {type(exc).__name__}",
                metadata={},
            )
        if verdict.action == "deny":
            return verdict
        merged_metadata = {**merged_metadata, **verdict.metadata}
    return HookVerdict(action="allow", reason=None, metadata=merged_metadata)
```

Place the `import logging` and `_logger = ...` lines at the top of the module's dispatch section (after the `_HOOK_TIMEOUT_SECONDS` constant). Remove the inline `import asyncio` from `_await_if_needed_pre` since it's now used in `dispatch_pre_hooks` too — replace both with one module-level `import asyncio` near the top.

The cleaned dispatch section should read:

```python
# ─── Dispatch ──────────────────────────────────────────────────────────────

import asyncio
import inspect
import logging

_logger = logging.getLogger(__name__)
_HOOK_TIMEOUT_SECONDS: float = 5.0


async def _await_if_needed_pre(fn: PreHook, ctx: HookContext) -> HookVerdict:
    result = fn(ctx)
    if inspect.isawaitable(result):
        result = await asyncio.wait_for(result, timeout=_HOOK_TIMEOUT_SECONDS)
    return result


async def dispatch_pre_hooks(ctx: HookContext) -> HookVerdict:
    merged_metadata: dict = {}
    for fn in _pre_hooks.get(ctx.tool_name, []):
        try:
            verdict = await _await_if_needed_pre(fn, ctx)
        except asyncio.TimeoutError:
            verdict = HookVerdict(
                action="deny",
                reason="hook timeout",
                metadata={},
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception("Hook %r crashed for tool %s", fn, ctx.tool_name)
            verdict = HookVerdict(
                action="deny",
                reason=f"hook crashed: {type(exc).__name__}",
                metadata={},
            )
        if verdict.action == "deny":
            return verdict
        merged_metadata = {**merged_metadata, **verdict.metadata}
    return HookVerdict(action="allow", reason=None, metadata=merged_metadata)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_hooks_registry.py -v -k "crash"`

Expected: 3 PASS.

Re-run the whole test_hooks_registry suite to confirm T3/T4 didn't regress:

Run: `uv run pytest tests/test_hooks_registry.py -v`

Expected: all tests in the file PASS (T1+T2+T3+T4+T5 = 17).

- [ ] **Step 5: Commit**

```bash
git add server/harness/hooks/__init__.py tests/test_hooks_registry.py
git commit -m "$(cat <<'EOF'
hooks(p2): convert hook exceptions to deny verdict

Spec §5.5 — a buggy hook cannot take down the call site. The
exception traceback is logged via logging.exception; the dispatcher
returns a deny verdict with reason 'hook crashed: <Type>'. Both sync
and async hook crashes are covered.
EOF
)"
```

---

## Task 6: `dispatch_pre_hooks` timeout → deny conversion

**Files:**
- Modify: `tests/test_hooks_registry.py`

The `asyncio.TimeoutError` branch already exists in T5. This task pins behavior by simulating a slow async hook. To keep the test fast, temporarily monkeypatch `_HOOK_TIMEOUT_SECONDS` to a small value.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hooks_registry.py`:

```python
# ─── T6: hook timeout → deny ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_pre_hooks_async_hook_timeout_becomes_deny(fresh_registry, monkeypatch):
    import asyncio
    from server.harness import hooks as hooks_mod
    from server.harness.hooks import (
        HookContext, dispatch_pre_hooks, register_pre_hook,
    )

    # Shrink the timeout so the test stays under 1s wall-clock.
    monkeypatch.setattr(hooks_mod, "_HOOK_TIMEOUT_SECONDS", 0.05)

    async def slow_hook(ctx):
        await asyncio.sleep(1.0)  # > 0.05 → must time out
        from server.harness.hooks import HookVerdict
        return HookVerdict("allow", None, {})

    register_pre_hook("web_search", slow_hook)

    ctx = HookContext("web_search", 1, "s", None, {"query": "x"})
    verdict = await dispatch_pre_hooks(ctx)

    assert verdict.action == "deny"
    assert verdict.reason == "hook timeout"
    assert verdict.metadata == {}


@pytest.mark.asyncio
async def test_dispatch_pre_hooks_sync_hook_never_times_out(fresh_registry, monkeypatch):
    """The 5s timeout only applies to coroutines. A sync hook ignores it."""
    import time
    from server.harness import hooks as hooks_mod
    from server.harness.hooks import (
        HookContext, HookVerdict, dispatch_pre_hooks, register_pre_hook,
    )

    monkeypatch.setattr(hooks_mod, "_HOOK_TIMEOUT_SECONDS", 0.05)

    def sync_slow(ctx):
        time.sleep(0.1)  # > timeout but sync — runs to completion
        return HookVerdict("allow", None, {"ran": True})

    register_pre_hook("web_search", sync_slow)

    ctx = HookContext("web_search", 1, "s", None, {"query": "x"})
    verdict = await dispatch_pre_hooks(ctx)

    assert verdict.action == "allow"
    assert verdict.metadata == {"ran": True}
```

- [ ] **Step 2: Run tests to verify they pass (T5 already implemented timeout branch)**

Run: `uv run pytest tests/test_hooks_registry.py -v -k "timeout or never_times_out"`

Expected: 2 PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_hooks_registry.py
git commit -m "$(cat <<'EOF'
hooks(p2): test async-hook timeout → deny conversion

Spec §5.5 — asyncio.wait_for(..., 5.0s) on awaitable hooks; on
TimeoutError the dispatcher returns deny with reason 'hook timeout'.
Sync hooks bypass the timeout entirely (no thread) — covered too,
so we don't accidentally regress sync-hook fast-path behavior.
EOF
)"
```

---

## Task 7: `dispatch_post_hooks` (all-fire, no short-circuit, exceptions logged)

**Files:**
- Modify: `server/harness/hooks/__init__.py`
- Modify: `tests/test_hooks_registry.py`

Post-hooks observe the call result but cannot deny (the call already happened). They all fire; exceptions and timeouts are logged via `logging.exception` and dropped.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hooks_registry.py`:

```python
# ─── T7: dispatch_post_hooks ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_post_hooks_no_hooks_is_noop(fresh_registry):
    from server.harness.hooks import HookContext, dispatch_post_hooks

    ctx = HookContext("web_search", 1, "s", None, {"query": "x"})
    # Must not raise.
    await dispatch_post_hooks(ctx, {"ok": True})


@pytest.mark.asyncio
async def test_dispatch_post_hooks_all_fire(fresh_registry):
    from server.harness.hooks import (
        HookContext, dispatch_post_hooks, register_post_hook,
    )

    calls: list[str] = []

    def hook_a(ctx, result):
        calls.append("a")

    def hook_b(ctx, result):
        calls.append("b")

    register_post_hook("web_search", hook_a)
    register_post_hook("web_search", hook_b)

    ctx = HookContext("web_search", 1, "s", None, {"query": "x"})
    await dispatch_post_hooks(ctx, {"results": []})

    assert calls == ["a", "b"]


@pytest.mark.asyncio
async def test_dispatch_post_hooks_supports_async(fresh_registry):
    from server.harness.hooks import (
        HookContext, dispatch_post_hooks, register_post_hook,
    )

    calls: list[str] = []

    async def hook(ctx, result):
        calls.append("ran")

    register_post_hook("web_search", hook)

    ctx = HookContext("web_search", 1, "s", None, {"query": "x"})
    await dispatch_post_hooks(ctx, {"results": []})

    assert calls == ["ran"]


@pytest.mark.asyncio
async def test_dispatch_post_hooks_exception_is_logged_not_raised(fresh_registry, caplog):
    import logging
    from server.harness.hooks import (
        HookContext, dispatch_post_hooks, register_post_hook,
    )

    def crashy(ctx, result):
        raise ValueError("post kaboom")

    calls: list[str] = []

    def later(ctx, result):
        calls.append("later")

    register_post_hook("web_search", crashy)
    register_post_hook("web_search", later)

    ctx = HookContext("web_search", 1, "s", None, {"query": "x"})
    with caplog.at_level(logging.ERROR, logger="server.harness.hooks"):
        await dispatch_post_hooks(ctx, {"results": []})

    assert calls == ["later"], "later hook must still fire after earlier crash"
    assert any("post kaboom" in str(rec.exc_info) or "post kaboom" in rec.message
               for rec in caplog.records), "crash traceback should be logged"


@pytest.mark.asyncio
async def test_dispatch_post_hooks_timeout_is_logged_not_raised(fresh_registry, monkeypatch):
    import asyncio
    from server.harness import hooks as hooks_mod
    from server.harness.hooks import (
        HookContext, dispatch_post_hooks, register_post_hook,
    )

    monkeypatch.setattr(hooks_mod, "_HOOK_TIMEOUT_SECONDS", 0.05)

    async def slow(ctx, result):
        await asyncio.sleep(1.0)

    calls: list[str] = []

    def later(ctx, result):
        calls.append("later")

    register_post_hook("web_search", slow)
    register_post_hook("web_search", later)

    ctx = HookContext("web_search", 1, "s", None, {"query": "x"})
    await dispatch_post_hooks(ctx, {"results": []})

    assert calls == ["later"], "timeout in earlier hook must not block later hooks"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_hooks_registry.py -v -k "dispatch_post"`

Expected: 5 FAIL with `ImportError: cannot import name 'dispatch_post_hooks'`.

- [ ] **Step 3: Implement `dispatch_post_hooks`**

Append to `server/harness/hooks/__init__.py` (after `dispatch_pre_hooks`):

```python
async def _await_if_needed_post(fn: PostHook, ctx: HookContext, result: dict) -> None:
    out = fn(ctx, result)
    if inspect.isawaitable(out):
        await asyncio.wait_for(out, timeout=_HOOK_TIMEOUT_SECONDS)


async def dispatch_post_hooks(ctx: HookContext, result: dict) -> None:
    """Fire every post-hook registered for ctx.tool_name. No short-circuit.

    Exceptions and timeouts are logged via logging.exception and dropped;
    the call already happened, so the dispatcher cannot meaningfully fail.
    """
    for fn in _post_hooks.get(ctx.tool_name, []):
        try:
            await _await_if_needed_post(fn, ctx, result)
        except asyncio.TimeoutError:
            _logger.exception(
                "Post-hook %r timed out for tool %s", fn, ctx.tool_name
            )
        except Exception:  # noqa: BLE001
            _logger.exception(
                "Post-hook %r crashed for tool %s", fn, ctx.tool_name
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_hooks_registry.py -v -k "dispatch_post"`

Expected: 5 PASS.

Re-run the whole file:

Run: `uv run pytest tests/test_hooks_registry.py -v`

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add server/harness/hooks/__init__.py tests/test_hooks_registry.py
git commit -m "$(cat <<'EOF'
hooks(p2): add dispatch_post_hooks (all-fire, log-not-raise)

Spec §5.2/§5.5 — post-hooks observe the call result. They cannot
deny (the call already happened), so the dispatcher fires every
post-hook in registration order. Exceptions and timeouts are logged
via logging.exception and dropped; a later post-hook keeps running.
EOF
)"
```

---

## Task 8: `HookDeniedError` exception

**Files:**
- Modify: `server/harness/hooks/__init__.py`
- Modify: `tests/test_hooks_registry.py`

Public exception that the gate sites (`web_search` in T13, `tasks.py` in T15–T17) raise on deny verdicts.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hooks_registry.py`:

```python
# ─── T8: HookDeniedError ───────────────────────────────────────────────────


def test_hook_denied_error_is_exception_subclass():
    from server.harness.hooks import HookDeniedError
    assert issubclass(HookDeniedError, Exception)


def test_hook_denied_error_carries_reason_str():
    from server.harness.hooks import HookDeniedError
    err = HookDeniedError("cap exceeded")
    assert str(err) == "cap exceeded"


def test_hook_denied_error_carries_reason_attribute():
    """Call sites and tests may want structured access without parsing str()."""
    from server.harness.hooks import HookDeniedError
    err = HookDeniedError("rate limited")
    assert err.reason == "rate limited"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_hooks_registry.py -v -k "denied_error"`

Expected: 3 FAIL with `ImportError: cannot import name 'HookDeniedError'`.

- [ ] **Step 3: Implement `HookDeniedError`**

Append to `server/harness/hooks/__init__.py`:

```python
# ─── Exception ─────────────────────────────────────────────────────────────


class HookDeniedError(Exception):
    """Raised by a tool call site when dispatch_pre_hooks returns deny."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_hooks_registry.py -v -k "denied_error"`

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add server/harness/hooks/__init__.py tests/test_hooks_registry.py
git commit -m "$(cat <<'EOF'
hooks(p2): add HookDeniedError public exception

Spec §5.3 — gate sites (web_search, tasks.py) raise this on a deny
verdict so callers can either swallow it or surface it as a 4xx.
EOF
)"
```

---

## Task 9: `hook_events` table + `record_hook_event` + `_count_in_window`

**Files:**
- Modify: `server/harness/ledger.py`
- Create: `tests/test_hooks_ledger.py`

Append-only table keyed only by `session_id` (no FK constraint, per spec §7). Schema additions go through `_ensure_columns` to mirror the existing additive-only pattern. `_count_in_window` is exposed for bundled hooks to read counts without each hook reimplementing sqlite glue.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_hooks_ledger.py`:

```python
"""Unit tests for hook_events table + helpers in server.harness.ledger."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Fresh sqlite path per test; ledger init_db creates schema on demand."""
    return tmp_path / "ledger.db"


def test_record_hook_event_creates_table_idempotently(tmp_db):
    from server.harness.ledger import record_hook_event

    record_hook_event(
        session_id="s1",
        tool_name="web_search",
        action="allow",
        reason=None,
        metadata={"k": "v"},
        db_path=tmp_db,
    )
    conn = sqlite3.connect(str(tmp_db))
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(hook_events)").fetchall()]
    finally:
        conn.close()
    assert set(cols) >= {"session_id", "tool_name", "action", "reason", "metadata", "ts"}


def test_record_hook_event_persists_fields_with_json_metadata(tmp_db):
    from server.harness.ledger import record_hook_event

    record_hook_event(
        session_id="s1",
        tool_name="web_search",
        action="deny",
        reason="cap exceeded",
        metadata={"count": 21, "cap": 20},
        db_path=tmp_db,
    )
    conn = sqlite3.connect(str(tmp_db))
    try:
        row = conn.execute(
            "SELECT session_id, tool_name, action, reason, metadata, ts "
            "FROM hook_events WHERE session_id = ?",
            ("s1",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    sid, tn, action, reason, metadata_raw, ts = row
    assert sid == "s1"
    assert tn == "web_search"
    assert action == "deny"
    assert reason == "cap exceeded"
    assert json.loads(metadata_raw) == {"count": 21, "cap": 20}
    # ts is an ISO8601 string ending in '+00:00' or 'Z'.
    parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None


def test_record_hook_event_allows_none_reason(tmp_db):
    from server.harness.ledger import record_hook_event

    record_hook_event(
        session_id="s1",
        tool_name="web_search",
        action="allow",
        reason=None,
        metadata={},
        db_path=tmp_db,
    )
    conn = sqlite3.connect(str(tmp_db))
    try:
        row = conn.execute(
            "SELECT reason FROM hook_events WHERE session_id = ?",
            ("s1",),
        ).fetchone()
    finally:
        conn.close()
    assert row[0] is None


def test_count_in_window_returns_zero_when_no_rows(tmp_db):
    from server.harness.ledger import _count_in_window, record_hook_event

    # Touch DB so the table exists.
    record_hook_event(
        session_id="other_sess",
        tool_name="web_search",
        action="allow",
        reason=None,
        metadata={},
        db_path=tmp_db,
    )
    count = _count_in_window(
        session_id="s1",
        tool_name="web_search",
        window_seconds=60,
        db_path=tmp_db,
    )
    assert count == 0


def test_count_in_window_counts_only_matching_session_and_tool(tmp_db):
    from server.harness.ledger import _count_in_window, record_hook_event

    for _ in range(3):
        record_hook_event(
            session_id="s1", tool_name="web_search",
            action="allow", reason=None, metadata={}, db_path=tmp_db,
        )
    record_hook_event(
        session_id="s2", tool_name="web_search",
        action="allow", reason=None, metadata={}, db_path=tmp_db,
    )
    record_hook_event(
        session_id="s1", tool_name="delegated_task",
        action="allow", reason=None, metadata={}, db_path=tmp_db,
    )

    assert _count_in_window(
        session_id="s1", tool_name="web_search",
        window_seconds=3600, db_path=tmp_db,
    ) == 3


def test_count_in_window_respects_window_seconds(tmp_db):
    """Old rows outside the window do not count."""
    from server.harness.ledger import _count_in_window, record_hook_event

    # Insert a row manually with an old ts.
    conn = sqlite3.connect(str(tmp_db))
    try:
        # First, trigger schema creation via the public path.
        record_hook_event(
            session_id="s1", tool_name="web_search",
            action="allow", reason=None, metadata={}, db_path=tmp_db,
        )
        old_ts = (datetime.now(timezone.utc) - timedelta(seconds=7200)).isoformat()
        conn.execute(
            "INSERT INTO hook_events (session_id, tool_name, action, reason, metadata, ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("s1", "web_search", "allow", None, "{}", old_ts),
        )
        conn.commit()
    finally:
        conn.close()

    # Window of 60s: old row (7200s ago) excluded; the just-recorded row included.
    count = _count_in_window(
        session_id="s1", tool_name="web_search",
        window_seconds=60, db_path=tmp_db,
    )
    assert count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_hooks_ledger.py -v`

Expected: 6 FAIL with `ImportError: cannot import name 'record_hook_event'`.

- [ ] **Step 3: Add table creation in `_ensure_columns` + helpers**

In `server/harness/ledger.py`, locate `_ensure_columns`. After the `CREATE TABLE IF NOT EXISTS harness_config_activations (...)` block (around line 308), append before the function ends:

```python
    conn.execute(
        """CREATE TABLE IF NOT EXISTS hook_events (
            session_id TEXT NOT NULL,
            tool_name  TEXT NOT NULL,
            action     TEXT NOT NULL,
            reason     TEXT,
            metadata   TEXT NOT NULL,
            ts         TEXT NOT NULL
        )"""
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_hook_events_session_tool_ts "
        "ON hook_events(session_id, tool_name, ts)"
    )
```

Then append two public helpers at the end of `server/harness/ledger.py`:

```python
def record_hook_event(
    *,
    session_id: str,
    tool_name: str,
    action: str,
    reason: str | None,
    metadata: dict,
    db_path: Path | None = None,
) -> None:
    """Append a row to hook_events. Called by hook dispatch and gate sites."""
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO hook_events (session_id, tool_name, action, reason, metadata, ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                session_id,
                tool_name,
                action,
                reason,
                json.dumps(metadata or {}, ensure_ascii=False),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _count_in_window(
    *,
    session_id: str,
    tool_name: str,
    window_seconds: int,
    db_path: Path | None = None,
) -> int:
    """Count hook_events rows for (session_id, tool_name) within the last
    `window_seconds`. Used by bundled hooks to make cap / rate-limit decisions
    without each hook re-implementing the sqlite read.
    """
    from datetime import timedelta

    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=window_seconds)).isoformat()
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM hook_events "
            "WHERE session_id = ? AND tool_name = ? AND ts >= ?",
            (session_id, tool_name, cutoff),
        ).fetchone()
    finally:
        conn.close()
    return int(row[0]) if row else 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_hooks_ledger.py -v`

Expected: 6 PASS.

Re-run the ledger contract suite to confirm no regression:

Run: `uv run pytest tests/test_ledger_contract.py -v`

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add server/harness/ledger.py tests/test_hooks_ledger.py
git commit -m "$(cat <<'EOF'
hooks(p2): add hook_events table + record_hook_event/_count_in_window

Spec §7 — append-only hook_events table created idempotently inside
_ensure_columns (mirrors the existing additive pattern). Index on
(session_id, tool_name, ts) so bundled hooks can read counts cheaply.
_count_in_window exposes the read so each bundled hook doesn't repeat
sqlite glue.
EOF
)"
```

---

## Task 10: Bundled + project hook auto-discovery

**Files:**
- Modify: `server/harness/hooks/__init__.py`
- Create: `server/harness/hooks/_bundled/__init__.py` (empty marker)
- Create: `tests/test_hooks_discovery.py`
- Modify: `.gitignore` (add `server/harness/hooks/_project/`)

At package import, walk `_bundled/` and (if it exists) `_project/`, and `importlib.import_module` every `*.py` whose name doesn't start with `_`. Each module's `register_*` calls fire at import time. Log a single INFO line listing what was loaded.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_hooks_discovery.py`:

```python
"""Tests for hook auto-discovery from _bundled/ and _project/."""
from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path

import pytest


def test_bundled_directory_exists_as_package():
    from server.harness.hooks import _bundled
    pkg_path = Path(_bundled.__file__).parent
    assert pkg_path.is_dir()
    assert (pkg_path / "__init__.py").is_file()


def test_importing_hooks_package_triggers_bundled_discovery(caplog):
    """Discovery is wired to package import; re-importing should not raise."""
    # Reload the hooks package to re-run discovery.
    with caplog.at_level(logging.INFO, logger="server.harness.hooks"):
        if "server.harness.hooks" in sys.modules:
            importlib.reload(sys.modules["server.harness.hooks"])
        else:
            importlib.import_module("server.harness.hooks")
    # Look for a startup line listing bundled count.
    assert any("bundled" in rec.message.lower() for rec in caplog.records), \
        "expected an INFO line listing bundled hooks loaded"


def test_discovery_skips_underscore_modules(tmp_path, monkeypatch):
    """Modules starting with '_' (e.g. __init__, _helpers) are not imported."""
    from server.harness.hooks import _discover_hooks_in
    bundled = tmp_path / "fake_bundled"
    bundled.mkdir()
    (bundled / "__init__.py").write_text("")
    (bundled / "_helpers.py").write_text("raise RuntimeError('should not import')\n")
    (bundled / "real_hook.py").write_text(
        "loaded = True\n"
    )

    # Make tmp dir importable as a package.
    monkeypatch.syspath_prepend(str(tmp_path))
    count = _discover_hooks_in("fake_bundled")
    assert count == 1, "only real_hook.py should have imported"


def test_discovery_tolerates_missing_project_dir():
    """_project/ is optional; no error if it doesn't exist."""
    from server.harness.hooks import _discover_hooks_in
    # 'definitely_not_a_package_xyz' does not exist.
    count = _discover_hooks_in("definitely_not_a_package_xyz")
    assert count == 0


def test_discovery_logs_hook_module_crash_without_raising(tmp_path, monkeypatch, caplog):
    """A buggy hook module must not block other hooks from loading."""
    from server.harness.hooks import _discover_hooks_in
    bundled = tmp_path / "fake_bundled2"
    bundled.mkdir()
    (bundled / "__init__.py").write_text("")
    (bundled / "crashy.py").write_text("raise ValueError('module crash')\n")
    (bundled / "good.py").write_text("ok = True\n")

    monkeypatch.syspath_prepend(str(tmp_path))
    with caplog.at_level(logging.ERROR, logger="server.harness.hooks"):
        count = _discover_hooks_in("fake_bundled2")
    assert count == 1, "good.py should still load"
    assert any("crashy" in rec.message for rec in caplog.records), \
        "module import crash should be logged"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_hooks_discovery.py -v`

Expected: 5 FAIL — `_bundled` subpackage missing; `_discover_hooks_in` missing.

- [ ] **Step 3: Create `_bundled/__init__.py` and add discovery to the package**

Create `server/harness/hooks/_bundled/__init__.py` with content:

```python
"""Bundled hooks. Each module registers its hooks at import time."""
```

Append to `server/harness/hooks/__init__.py` (at the very bottom, after every other definition):

```python
# ─── Auto-discovery ────────────────────────────────────────────────────────


def _discover_hooks_in(package_name: str) -> int:
    """Import every non-underscore-prefixed module in `package_name`.

    Returns the count of modules actually loaded. Missing packages count
    as zero (not an error). A module that raises on import is logged and
    skipped; other modules in the same package still load.
    """
    import importlib
    import pkgutil

    try:
        pkg = importlib.import_module(package_name)
    except ModuleNotFoundError:
        return 0
    pkg_path = getattr(pkg, "__path__", None)
    if pkg_path is None:
        return 0

    count = 0
    for module_info in pkgutil.iter_modules(pkg_path):
        if module_info.name.startswith("_"):
            continue
        fqn = f"{package_name}.{module_info.name}"
        try:
            importlib.import_module(fqn)
        except Exception:  # noqa: BLE001
            _logger.exception("Failed to import hook module %s", fqn)
            continue
        count += 1
    return count


def _autodiscover_at_startup() -> None:
    bundled = _discover_hooks_in("server.harness.hooks._bundled")
    project = _discover_hooks_in("server.harness.hooks._project")
    _logger.info(
        "hooks: loaded %d bundled, %d project hooks", bundled, project
    )


_autodiscover_at_startup()
```

Add the gitignore line. In `.gitignore`, after the existing
`# Override global gitignore for project docs` block (around line 30), append:

```
# Hook plugins are auto-loaded from these dirs; site-specific must not commit
server/harness/hooks/_project/
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_hooks_discovery.py -v`

Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add server/harness/hooks/__init__.py \
        server/harness/hooks/_bundled/__init__.py \
        tests/test_hooks_discovery.py \
        .gitignore
git commit -m "$(cat <<'EOF'
hooks(p2): auto-discover bundled + project hooks at package import

Spec §5.2 — _bundled/ ships in-tree; _project/ is gitignored for
site-specific gates. Each module's register_*-time side effects fire
exactly once at package import. Module import crashes are logged
and skipped so one bad hook can't take down the whole registry.
EOF
)"
```

---

## Task 11: Bundled hook — `cap_web_search_per_session`

**Files:**
- Create: `server/harness/hooks/_bundled/cap_web_search_per_session.py`
- Create: `tests/test_hooks_bundled.py`

Reads count from `hook_events` for the current `(session_id, "web_search")` rows with `action="allow"`. If count ≥ cap, deny. Cap default 20, override via env `AGENTIC_BOARD_WEB_SEARCH_SESSION_CAP`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_hooks_bundled.py`:

```python
"""Tests for bundled hooks in server.harness.hooks._bundled."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch):
    """Redirect ledger writes/reads to a tmp DB for this test only."""
    from server.harness import ledger as ledger_mod
    db_path = tmp_path / "ledger.db"
    monkeypatch.setattr(ledger_mod, "_DEFAULT_DB_PATH", db_path)
    return db_path


@pytest.fixture
def fresh_registry():
    from server.harness.hooks import _snapshot_registry, _restore_registry
    snapshot = _snapshot_registry()
    yield
    _restore_registry(snapshot)


# ─── T11: cap_web_search_per_session ──────────────────────────────────────


@pytest.mark.asyncio
async def test_cap_web_search_allows_below_cap(tmp_db, fresh_registry, monkeypatch):
    monkeypatch.setenv("AGENTIC_BOARD_WEB_SEARCH_SESSION_CAP", "3")
    from server.harness.hooks._bundled.cap_web_search_per_session import (
        cap_web_search_per_session,
    )
    from server.harness.hooks import HookContext
    from server.harness.ledger import record_hook_event

    # Two prior allows; cap is 3 → next should still be allowed.
    for _ in range(2):
        record_hook_event(
            session_id="s1", tool_name="web_search",
            action="allow", reason=None, metadata={},
        )

    ctx = HookContext("web_search", 1, "s1", "strategist", {"query": "x"})
    verdict = cap_web_search_per_session(ctx)
    assert verdict.action == "allow"
    assert verdict.metadata.get("session_count") == 2
    assert verdict.metadata.get("cap") == 3


@pytest.mark.asyncio
async def test_cap_web_search_denies_at_cap(tmp_db, fresh_registry, monkeypatch):
    monkeypatch.setenv("AGENTIC_BOARD_WEB_SEARCH_SESSION_CAP", "3")
    from server.harness.hooks._bundled.cap_web_search_per_session import (
        cap_web_search_per_session,
    )
    from server.harness.hooks import HookContext
    from server.harness.ledger import record_hook_event

    for _ in range(3):
        record_hook_event(
            session_id="s1", tool_name="web_search",
            action="allow", reason=None, metadata={},
        )

    ctx = HookContext("web_search", 1, "s1", "strategist", {"query": "x"})
    verdict = cap_web_search_per_session(ctx)
    assert verdict.action == "deny"
    assert verdict.reason and "cap" in verdict.reason.lower()
    assert verdict.metadata.get("session_count") == 3
    assert verdict.metadata.get("cap") == 3


@pytest.mark.asyncio
async def test_cap_web_search_isolates_by_session(tmp_db, fresh_registry, monkeypatch):
    monkeypatch.setenv("AGENTIC_BOARD_WEB_SEARCH_SESSION_CAP", "2")
    from server.harness.hooks._bundled.cap_web_search_per_session import (
        cap_web_search_per_session,
    )
    from server.harness.hooks import HookContext
    from server.harness.ledger import record_hook_event

    # Saturate session A.
    for _ in range(2):
        record_hook_event(
            session_id="A", tool_name="web_search",
            action="allow", reason=None, metadata={},
        )

    ctx_b = HookContext("web_search", 1, "B", "strategist", {"query": "x"})
    verdict = cap_web_search_per_session(ctx_b)
    assert verdict.action == "allow", "session B's count is independent"


@pytest.mark.asyncio
async def test_cap_web_search_falls_back_to_default_on_bad_env(tmp_db, fresh_registry, monkeypatch):
    monkeypatch.setenv("AGENTIC_BOARD_WEB_SEARCH_SESSION_CAP", "not-a-number")
    from server.harness.hooks._bundled.cap_web_search_per_session import (
        cap_web_search_per_session,
    )
    from server.harness.hooks import HookContext

    ctx = HookContext("web_search", 1, "s1", "strategist", {"query": "x"})
    verdict = cap_web_search_per_session(ctx)
    # Below default (20), no prior rows → allow with cap=20.
    assert verdict.action == "allow"
    assert verdict.metadata.get("cap") == 20


def test_cap_web_search_registered_at_import():
    """Importing the bundled module registers it for web_search."""
    from server.harness.hooks import _list_pre_hooks_for_tests
    from server.harness.hooks._bundled.cap_web_search_per_session import (
        cap_web_search_per_session,
    )
    assert cap_web_search_per_session in _list_pre_hooks_for_tests("web_search")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_hooks_bundled.py -v -k "cap_web_search"`

Expected: 5 FAIL with `ModuleNotFoundError: No module named 'server.harness.hooks._bundled.cap_web_search_per_session'`.

- [ ] **Step 3: Implement the bundled hook**

Create `server/harness/hooks/_bundled/cap_web_search_per_session.py`:

```python
"""Bundled hook: cap web_search per session.

Reads the count of prior allow events for (session_id, "web_search") from
the hook_events ledger; denies once the cap is reached. Default cap 20,
override via env AGENTIC_BOARD_WEB_SEARCH_SESSION_CAP.
"""
from __future__ import annotations

import os

from server.harness.hooks import HookContext, HookVerdict, register_pre_hook
from server.harness.ledger import _count_in_window


_DEFAULT_CAP = 20
_SESSION_WINDOW_SECONDS = 24 * 3600  # "per session" approximated as last 24h


def _read_cap() -> int:
    raw = os.getenv("AGENTIC_BOARD_WEB_SEARCH_SESSION_CAP", "")
    try:
        value = int(raw)
        return value if value > 0 else _DEFAULT_CAP
    except (TypeError, ValueError):
        return _DEFAULT_CAP


def cap_web_search_per_session(ctx: HookContext) -> HookVerdict:
    cap = _read_cap()
    count = _count_in_window(
        session_id=ctx.session_id,
        tool_name="web_search",
        window_seconds=_SESSION_WINDOW_SECONDS,
    )
    if count >= cap:
        return HookVerdict(
            action="deny",
            reason=f"web_search cap reached: {count}/{cap} per session",
            metadata={"session_count": count, "cap": cap},
        )
    return HookVerdict(
        action="allow",
        reason=None,
        metadata={"session_count": count, "cap": cap},
    )


register_pre_hook("web_search", cap_web_search_per_session)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_hooks_bundled.py -v -k "cap_web_search"`

Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add server/harness/hooks/_bundled/cap_web_search_per_session.py \
        tests/test_hooks_bundled.py
git commit -m "$(cat <<'EOF'
hooks(p2): bundled cap_web_search_per_session

Spec §5.4 — denies once a session reaches the cap (default 20,
env override AGENTIC_BOARD_WEB_SEARCH_SESSION_CAP). Count is read
from hook_events so the cap survives process restarts.
EOF
)"
```

---

## Task 12: Bundled hook — `rate_limit_delegated_tasks`

**Files:**
- Create: `server/harness/hooks/_bundled/rate_limit_delegated_tasks.py`
- Modify: `tests/test_hooks_bundled.py`

Sliding-window rate limit over `hook_events` for `(session_id, "delegated_task")` rows. Default 5 ops per 60s. Env overrides `AGENTIC_BOARD_DELEGATED_TASK_RATE_LIMIT` and `AGENTIC_BOARD_DELEGATED_TASK_RATE_WINDOW_SECONDS`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_hooks_bundled.py`:

```python
# ─── T12: rate_limit_delegated_tasks ──────────────────────────────────────


@pytest.mark.asyncio
async def test_rate_limit_delegated_allows_below_threshold(tmp_db, fresh_registry, monkeypatch):
    monkeypatch.setenv("AGENTIC_BOARD_DELEGATED_TASK_RATE_LIMIT", "3")
    monkeypatch.setenv("AGENTIC_BOARD_DELEGATED_TASK_RATE_WINDOW_SECONDS", "60")
    from server.harness.hooks._bundled.rate_limit_delegated_tasks import (
        rate_limit_delegated_tasks,
    )
    from server.harness.hooks import HookContext
    from server.harness.ledger import record_hook_event

    for _ in range(2):
        record_hook_event(
            session_id="s1", tool_name="delegated_task",
            action="allow", reason=None, metadata={},
        )

    ctx = HookContext("delegated_task", 0, "s1", None, {"task_id": "t"})
    verdict = rate_limit_delegated_tasks(ctx)
    assert verdict.action == "allow"
    assert verdict.metadata.get("window_count") == 2
    assert verdict.metadata.get("limit") == 3


@pytest.mark.asyncio
async def test_rate_limit_delegated_denies_at_threshold(tmp_db, fresh_registry, monkeypatch):
    monkeypatch.setenv("AGENTIC_BOARD_DELEGATED_TASK_RATE_LIMIT", "3")
    monkeypatch.setenv("AGENTIC_BOARD_DELEGATED_TASK_RATE_WINDOW_SECONDS", "60")
    from server.harness.hooks._bundled.rate_limit_delegated_tasks import (
        rate_limit_delegated_tasks,
    )
    from server.harness.hooks import HookContext
    from server.harness.ledger import record_hook_event

    for _ in range(3):
        record_hook_event(
            session_id="s1", tool_name="delegated_task",
            action="allow", reason=None, metadata={},
        )

    ctx = HookContext("delegated_task", 0, "s1", None, {"task_id": "t"})
    verdict = rate_limit_delegated_tasks(ctx)
    assert verdict.action == "deny"
    assert verdict.reason and "rate" in verdict.reason.lower()


@pytest.mark.asyncio
async def test_rate_limit_delegated_old_rows_outside_window_dont_count(tmp_db, fresh_registry, monkeypatch):
    """Rows older than the window do not count toward the limit."""
    import sqlite3
    from datetime import datetime, timedelta, timezone
    monkeypatch.setenv("AGENTIC_BOARD_DELEGATED_TASK_RATE_LIMIT", "3")
    monkeypatch.setenv("AGENTIC_BOARD_DELEGATED_TASK_RATE_WINDOW_SECONDS", "60")
    from server.harness.hooks._bundled.rate_limit_delegated_tasks import (
        rate_limit_delegated_tasks,
    )
    from server.harness.hooks import HookContext
    from server.harness.ledger import record_hook_event

    # Insert 3 old rows (300s ago) manually.
    record_hook_event(
        session_id="s1", tool_name="delegated_task",
        action="allow", reason=None, metadata={},
    )  # triggers table creation
    old_ts = (datetime.now(timezone.utc) - timedelta(seconds=300)).isoformat()
    conn = sqlite3.connect(str(tmp_db))
    try:
        for _ in range(3):
            conn.execute(
                "INSERT INTO hook_events (session_id, tool_name, action, reason, metadata, ts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("s1", "delegated_task", "allow", None, "{}", old_ts),
            )
        conn.commit()
    finally:
        conn.close()

    ctx = HookContext("delegated_task", 0, "s1", None, {"task_id": "t"})
    verdict = rate_limit_delegated_tasks(ctx)
    # Only 1 in-window row (the seeded one); limit 3 → allow.
    assert verdict.action == "allow"
    assert verdict.metadata.get("window_count") == 1


@pytest.mark.asyncio
async def test_rate_limit_delegated_falls_back_to_defaults_on_bad_env(tmp_db, fresh_registry, monkeypatch):
    monkeypatch.setenv("AGENTIC_BOARD_DELEGATED_TASK_RATE_LIMIT", "garbage")
    monkeypatch.setenv("AGENTIC_BOARD_DELEGATED_TASK_RATE_WINDOW_SECONDS", "garbage")
    from server.harness.hooks._bundled.rate_limit_delegated_tasks import (
        rate_limit_delegated_tasks,
    )
    from server.harness.hooks import HookContext

    ctx = HookContext("delegated_task", 0, "s1", None, {"task_id": "t"})
    verdict = rate_limit_delegated_tasks(ctx)
    assert verdict.action == "allow"
    assert verdict.metadata.get("limit") == 5
    assert verdict.metadata.get("window_seconds") == 60


def test_rate_limit_delegated_registered_at_import():
    from server.harness.hooks import _list_pre_hooks_for_tests
    from server.harness.hooks._bundled.rate_limit_delegated_tasks import (
        rate_limit_delegated_tasks,
    )
    assert rate_limit_delegated_tasks in _list_pre_hooks_for_tests("delegated_task")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_hooks_bundled.py -v -k "rate_limit"`

Expected: 5 FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement the bundled hook**

Create `server/harness/hooks/_bundled/rate_limit_delegated_tasks.py`:

```python
"""Bundled hook: sliding-window rate limit on delegated_task ops.

Default 5 ops per 60s per session. Env overrides:
  AGENTIC_BOARD_DELEGATED_TASK_RATE_LIMIT
  AGENTIC_BOARD_DELEGATED_TASK_RATE_WINDOW_SECONDS
"""
from __future__ import annotations

import os

from server.harness.hooks import HookContext, HookVerdict, register_pre_hook
from server.harness.ledger import _count_in_window


_DEFAULT_LIMIT = 5
_DEFAULT_WINDOW_SECONDS = 60


def _read_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "")
    try:
        value = int(raw)
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


def rate_limit_delegated_tasks(ctx: HookContext) -> HookVerdict:
    limit = _read_int_env("AGENTIC_BOARD_DELEGATED_TASK_RATE_LIMIT", _DEFAULT_LIMIT)
    window = _read_int_env(
        "AGENTIC_BOARD_DELEGATED_TASK_RATE_WINDOW_SECONDS", _DEFAULT_WINDOW_SECONDS
    )
    count = _count_in_window(
        session_id=ctx.session_id,
        tool_name="delegated_task",
        window_seconds=window,
    )
    if count >= limit:
        return HookVerdict(
            action="deny",
            reason=f"delegated_task rate limit: {count} ops in last {window}s (limit {limit})",
            metadata={"window_count": count, "limit": limit, "window_seconds": window},
        )
    return HookVerdict(
        action="allow",
        reason=None,
        metadata={"window_count": count, "limit": limit, "window_seconds": window},
    )


register_pre_hook("delegated_task", rate_limit_delegated_tasks)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_hooks_bundled.py -v -k "rate_limit"`

Expected: 5 PASS.

Re-run the full bundled test file:

Run: `uv run pytest tests/test_hooks_bundled.py -v`

Expected: all PASS (T11 + T12 = 10).

- [ ] **Step 5: Commit**

```bash
git add server/harness/hooks/_bundled/rate_limit_delegated_tasks.py \
        tests/test_hooks_bundled.py
git commit -m "$(cat <<'EOF'
hooks(p2): bundled rate_limit_delegated_tasks (5/min default)

Spec §5.4 — sliding window over hook_events for (session_id,
'delegated_task') with action='allow'. Env overrides
AGENTIC_BOARD_DELEGATED_TASK_RATE_LIMIT and
AGENTIC_BOARD_DELEGATED_TASK_RATE_WINDOW_SECONDS.
EOF
)"
```

---

## Task 13: Wrap `web_search` in pre/post-hook dispatch + ledger write

**Files:**
- Modify: `server/execution/web_search.py`
- Modify: `server/execution/__init__.py`

The wrap surrounds the existing body: build `HookContext`, await `dispatch_pre_hooks`, write a ledger row (`record_hook_event`) for the verdict, raise `HookDeniedError` on deny, run the existing logic on allow, then await `dispatch_post_hooks` + write a second ledger row for the post phase. Stage is best-effort: pass `0` (harness-internal); callers can override via a new optional `stage` kwarg.

Note: `web_search` has callers in `server/board/tools.py`, `server/board/deliberation/orchestrator.py`, `server/board/deliberation/live.py`, and `server/api/routes/execution.py`. None of them pass `stage` today; default of `0` keeps backward compatibility. The signature change is additive.

- [ ] **Step 1: Write the failing tests (integration test happens in T14; here we cover the per-call ledger write)**

Add a short test to `tests/test_hooks_bundled.py` to confirm the wrap writes events when called directly. Append:

```python
# ─── T13: web_search writes hook events ───────────────────────────────────


@pytest.mark.asyncio
async def test_web_search_records_allow_event(tmp_db, fresh_registry, monkeypatch):
    """When no denying hook is registered, web_search runs and writes an allow event."""
    monkeypatch.setenv("AGENTIC_BOARD_WEB_SEARCH_SESSION_CAP", "20")
    # Avoid hitting evidence dir.
    from server.execution import evidence as ev
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        old = ev._EVIDENCE_DIR
        ev._EVIDENCE_DIR = Path(tmpdir)
        try:
            from server.execution.web_search import web_search
            await web_search("test query", provider="fake", session_id="s_t13")
        finally:
            ev._EVIDENCE_DIR = old

    import sqlite3
    conn = sqlite3.connect(str(tmp_db))
    try:
        rows = conn.execute(
            "SELECT action, tool_name FROM hook_events WHERE session_id = ? "
            "ORDER BY ts ASC",
            ("s_t13",),
        ).fetchall()
    finally:
        conn.close()
    # Expect at least a pre-allow row (post-event row also written but we don't
    # require a separate ledger entry for post — see implementation note below).
    assert any(r[0] == "allow" and r[1] == "web_search" for r in rows)
```

- [ ] **Step 2: Run the new test to verify it fails**

Run: `uv run pytest tests/test_hooks_bundled.py -v -k "records_allow_event"`

Expected: FAIL — no `hook_events` row written yet (the wrap isn't in place).

- [ ] **Step 3: Wrap the `web_search` function**

In `server/execution/web_search.py`, modify the public `web_search` function. Replace the signature line and add the wrap. The change is purely additive — the existing body is unchanged except for being indented inside a try-flow.

Locate the existing signature (around line 85):

```python
async def web_search(
    query: str,
    *,
    provider: str | None = None,
    max_results: int = 5,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Search the web from execution workflows and persist an evidence packet."""
```

Replace the signature and add the wrap. The full new function header + opening wrap block reads:

```python
async def web_search(
    query: str,
    *,
    provider: str | None = None,
    max_results: int = 5,
    session_id: str | None = None,
    stage: int = 0,
    member_id: str | None = None,
) -> dict[str, Any]:
    """Search the web from execution workflows and persist an evidence packet.

    Hook gate: dispatch_pre_hooks fires before any provider call. A deny
    verdict raises HookDeniedError; the call site is responsible for
    surfacing the error (HTTP 429 / SSE event / etc.). On allow, the
    existing logic runs unchanged, then dispatch_post_hooks fires for
    observability.
    """
    from server.harness.hooks import (
        HookContext, HookDeniedError, dispatch_pre_hooks, dispatch_post_hooks,
    )
    from server.harness.ledger import record_hook_event

    hook_ctx = HookContext(
        tool_name="web_search",
        stage=stage,
        session_id=session_id or "anon",
        member_id=member_id,
        request={
            "query": query,
            "provider": provider,
            "max_results": max_results,
        },
    )
    pre_verdict = await dispatch_pre_hooks(hook_ctx)
    record_hook_event(
        session_id=hook_ctx.session_id,
        tool_name="web_search",
        action=pre_verdict.action,
        reason=pre_verdict.reason,
        metadata=pre_verdict.metadata,
    )
    if pre_verdict.action == "deny":
        raise HookDeniedError(pre_verdict.reason or "web_search denied")
```

Continue with the existing body — keep every line from `selected = (provider or os.getenv(...))` through `_cache.put(cache_key, response)` exactly as written today. The only difference is the function now ends with the post-hook dispatch instead of `return response`. Replace the existing `return response` (last line before the function body ends) with:

```python
    await dispatch_post_hooks(hook_ctx, response)
    return response
```

For the early-return paths (`return _disabled_result(query)`, `return cached`, and the rate-limit early-return at `return {... warnings: [...]}`), apply the same wrap: just before each `return X`, add:

```python
    await dispatch_post_hooks(hook_ctx, X)
```

Concretely:

After the `if selected in {"", "disabled", "none"}:` block, change:

```python
    if selected in {"", "disabled", "none"}:
        return _disabled_result(query)
```

to:

```python
    if selected in {"", "disabled", "none"}:
        disabled_response = _disabled_result(query)
        await dispatch_post_hooks(hook_ctx, disabled_response)
        return disabled_response
```

After the cache probe, change:

```python
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached
```

to:

```python
    cached = _cache.get(cache_key)
    if cached is not None:
        await dispatch_post_hooks(hook_ctx, cached)
        return cached
```

After the rate-limit block, change:

```python
        if len(bucket) >= limit:
            return {
                "query": query,
                "provider": selected,
                "results": [],
                "evidence_packet": None,
                "warnings": [f"session rate limit: {limit}/{window}s"],
            }
```

to:

```python
        if len(bucket) >= limit:
            rate_limited_response = {
                "query": query,
                "provider": selected,
                "results": [],
                "evidence_packet": None,
                "warnings": [f"session rate limit: {limit}/{window}s"],
            }
            await dispatch_post_hooks(hook_ctx, rate_limited_response)
            return rate_limited_response
```

After the unknown-provider block, change:

```python
    else:
        return {
            "query": query,
            "provider": selected,
            "results": [],
            "evidence_packet": None,
            "warnings": [f"Web search provider '{selected}' is unavailable."],
        }
```

to:

```python
    else:
        unknown_response = {
            "query": query,
            "provider": selected,
            "results": [],
            "evidence_packet": None,
            "warnings": [f"Web search provider '{selected}' is unavailable."],
        }
        await dispatch_post_hooks(hook_ctx, unknown_response)
        return unknown_response
```

Also export `HookDeniedError` from `server/execution/__init__.py`. Locate the `from .web_search import WebSearchError, web_search` line and below it add:

```python
from server.harness.hooks import HookDeniedError
```

And in `__all__`, add `"HookDeniedError",`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_hooks_bundled.py -v -k "records_allow_event"`

Expected: PASS.

Re-run the existing web_search contract suite to confirm no regression:

Run: `uv run pytest tests/test_web_search_contract.py -v`

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add server/execution/web_search.py \
        server/execution/__init__.py \
        tests/test_hooks_bundled.py
git commit -m "$(cat <<'EOF'
hooks(p2): wrap web_search entry function in pre/post-hook dispatch

Spec §5.3 — pre-hook gate fires before provider selection; on deny
raises HookDeniedError. Post-hook fires on every return path
(disabled, cache hit, rate limit, unknown provider, real result).
Each pre verdict is persisted to hook_events. New stage/member_id
kwargs default to 0/None so existing call sites are untouched.
HookDeniedError is re-exported from server.execution.
EOF
)"
```

---

## Task 14: Integration test — denying hook causes `web_search` to raise `HookDeniedError`

**Files:**
- Create: `tests/test_web_search_hook_integration.py`

End-to-end: register a denying pre-hook, call `web_search`, assert `HookDeniedError`. Also assert the `hook_events` row was written. Provider="fake" so no live API.

- [ ] **Step 1: Write the failing test**

Create `tests/test_web_search_hook_integration.py`:

```python
"""Integration tests: denying hook surfaces HookDeniedError from web_search."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch):
    from server.harness import ledger as ledger_mod
    db_path = tmp_path / "ledger.db"
    monkeypatch.setattr(ledger_mod, "_DEFAULT_DB_PATH", db_path)
    return db_path


@pytest.fixture
def fresh_registry():
    from server.harness.hooks import _snapshot_registry, _restore_registry
    snapshot = _snapshot_registry()
    yield
    _restore_registry(snapshot)


@pytest.mark.asyncio
async def test_denying_hook_blocks_web_search_with_HookDeniedError(tmp_db, fresh_registry):
    from server.harness.hooks import (
        HookContext, HookVerdict, HookDeniedError, register_pre_hook,
    )
    from server.execution.web_search import web_search

    def denying_hook(ctx: HookContext) -> HookVerdict:
        return HookVerdict(action="deny", reason="test denial", metadata={"x": 1})

    register_pre_hook("web_search", denying_hook)

    with pytest.raises(HookDeniedError) as excinfo:
        await web_search("q", provider="fake", session_id="s_t14")
    assert "test denial" in str(excinfo.value)
    assert excinfo.value.reason == "test denial"


@pytest.mark.asyncio
async def test_denying_hook_writes_deny_event_to_ledger(tmp_db, fresh_registry):
    from server.harness.hooks import (
        HookContext, HookVerdict, HookDeniedError, register_pre_hook,
    )
    from server.execution.web_search import web_search

    def denying_hook(ctx: HookContext) -> HookVerdict:
        return HookVerdict(action="deny", reason="cap exceeded", metadata={"cap": 0})

    register_pre_hook("web_search", denying_hook)

    with pytest.raises(HookDeniedError):
        await web_search("q", provider="fake", session_id="s_t14_b")

    conn = sqlite3.connect(str(tmp_db))
    try:
        rows = conn.execute(
            "SELECT action, reason FROM hook_events "
            "WHERE session_id = ? AND tool_name = 'web_search'",
            ("s_t14_b",),
        ).fetchall()
    finally:
        conn.close()
    assert (("deny", "cap exceeded")) in rows


@pytest.mark.asyncio
async def test_allowing_hook_lets_web_search_complete_normally(tmp_db, fresh_registry):
    from server.harness.hooks import (
        HookContext, HookVerdict, register_pre_hook,
    )
    from server.execution.web_search import web_search
    from server.execution import evidence as ev

    def allowing(ctx):
        return HookVerdict("allow", None, {"checked": True})

    register_pre_hook("web_search", allowing)

    with tempfile.TemporaryDirectory() as tmpdir:
        old = ev._EVIDENCE_DIR
        ev._EVIDENCE_DIR = Path(tmpdir)
        try:
            result = await web_search("q", provider="fake", session_id="s_t14_c")
        finally:
            ev._EVIDENCE_DIR = old

    assert result["query"] == "q"
    assert result["results"]
```

- [ ] **Step 2: Run tests to verify they fail then pass**

Run: `uv run pytest tests/test_web_search_hook_integration.py -v`

Expected: all 3 PASS (T13's wrap already enables this; the test pins the contract).

If any FAIL, re-read T13 and confirm `HookDeniedError` is raised on deny.

- [ ] **Step 3: Commit**

```bash
git add tests/test_web_search_hook_integration.py
git commit -m "$(cat <<'EOF'
hooks(p2): integration test for denying hook on web_search

Spec §8 — end-to-end: denying pre-hook raises HookDeniedError out
of web_search, deny event is persisted to hook_events, and an
allowing hook lets the call complete normally.
EOF
)"
```

This is the end of PR2. At this point a clean PR can be opened with branches PR2 = T1..T14.

---

# PR3 — tasks.py wraps

PR3 wires hooks into the three task functions (`plan_delegated_task`, `save_delegated_task`, `update_delegated_task_status`). These are **synchronous** — the dispatch is async. A thin sync→async bridge `_run_dispatch_sync` lives at the top of `tasks.py`.

## Task 15: Wrap `plan_delegated_task`

**Files:**
- Modify: `server/execution/tasks.py`
- Create: `tests/test_tasks_hook_integration.py` (start file; T18 adds more)

The wrap shape mirrors web_search: build a `HookContext` with `tool_name="delegated_task"`, dispatch pre-hooks via the sync bridge, write a `hook_events` row, raise `HookDeniedError` on deny, run the existing body, dispatch post-hooks. The bridge uses `asyncio.run(...)` when no event loop is running; if a loop is running (i.e. called from inside an async context that mistakenly invoked the sync function), it runs the coroutine in a fresh loop on a worker thread to avoid the "asyncio.run() cannot be called from a running event loop" RuntimeError. This is a defensive backstop; production callers of `plan_delegated_task` today are sync (FastAPI route handlers convert via FastAPI's threadpool when needed; see `server/api/routes/execution.py`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tasks_hook_integration.py`:

```python
"""Integration tests for hook gates on server.execution.tasks functions."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch):
    """Redirect both ledger (_DEFAULT_DB_PATH) and tasks DB to a single tmp path."""
    from server.harness import ledger as ledger_mod
    from server.execution import tasks as tasks_mod
    db_path = tmp_path / "ledger.db"
    tasks_db_path = tmp_path / "tasks.db"
    monkeypatch.setattr(ledger_mod, "_DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(tasks_mod, "DEFAULT_DB_PATH", tasks_db_path)
    return db_path, tasks_db_path


@pytest.fixture
def fresh_registry():
    from server.harness.hooks import _snapshot_registry, _restore_registry
    snapshot = _snapshot_registry()
    yield
    _restore_registry(snapshot)


def _approved_task_payload(task_id: str = "task_t15") -> dict[str, Any]:
    """Minimal approved task payload that plan_delegated_task accepts."""
    return {
        "id": task_id,
        "session_id": "s_t15",
        "title": "Build something",
        "objective": "Do it",
        "execution_unit_id": "engineering",
        "manager_agent_id": "technical_lead",
        "accountable_board_member_id": "architect",
        "priority": "p1",
        "status": "approved",
        "acceptance_criteria": [],
        "dependencies": [],
        "approval_required": False,
        "subtask_plan": None,
        "artifacts": [],
        "source": "board_synthesis",
        "result_summary": "",
        "status_detail": "",
    }


# ─── T15: plan_delegated_task wrap ────────────────────────────────────────


def test_plan_delegated_task_denied_raises_HookDeniedError(tmp_db, fresh_registry):
    ledger_path, tasks_path = tmp_db
    from server.harness.hooks import (
        HookContext, HookVerdict, HookDeniedError, register_pre_hook,
    )
    from server.execution.tasks import plan_delegated_task, save_delegated_task

    # Pre-seed an approved task so plan_delegated_task can find it.
    save_delegated_task(_approved_task_payload("t15_a"), db_path=tasks_path)

    def denying(ctx: HookContext) -> HookVerdict:
        return HookVerdict("deny", "blocked by test", {"reason_code": "test"})

    register_pre_hook("delegated_task", denying)

    with pytest.raises(HookDeniedError) as excinfo:
        plan_delegated_task(
            "t15_a",
            manager_agent_id="technical_lead",
            db_path=tasks_path,
        )
    assert "blocked by test" in str(excinfo.value)


def test_plan_delegated_task_denied_writes_event_and_does_not_change_state(tmp_db, fresh_registry):
    ledger_path, tasks_path = tmp_db
    from server.harness.hooks import (
        HookVerdict, HookDeniedError, register_pre_hook,
    )
    from server.execution.tasks import (
        plan_delegated_task, save_delegated_task, get_delegated_task,
    )

    save_delegated_task(_approved_task_payload("t15_b"), db_path=tasks_path)

    def denying(ctx):
        return HookVerdict("deny", "no plan today", {})

    register_pre_hook("delegated_task", denying)

    with pytest.raises(HookDeniedError):
        plan_delegated_task(
            "t15_b",
            manager_agent_id="technical_lead",
            db_path=tasks_path,
        )

    # State unchanged.
    task = get_delegated_task("t15_b", db_path=tasks_path)
    assert task["status"] == "approved"  # not "running"
    # Event recorded.
    conn = sqlite3.connect(str(ledger_path))
    try:
        rows = conn.execute(
            "SELECT action, reason FROM hook_events "
            "WHERE tool_name = 'delegated_task' AND session_id = ?",
            ("s_t15",),
        ).fetchall()
    finally:
        conn.close()
    assert ("deny", "no plan today") in rows


def test_plan_delegated_task_allow_completes_normally(tmp_db, fresh_registry):
    ledger_path, tasks_path = tmp_db
    from server.harness.hooks import HookVerdict, register_pre_hook
    from server.execution.tasks import (
        plan_delegated_task, save_delegated_task, get_delegated_task,
    )

    save_delegated_task(_approved_task_payload("t15_c"), db_path=tasks_path)

    def allowing(ctx):
        return HookVerdict("allow", None, {"pre": True})

    register_pre_hook("delegated_task", allowing)

    plan_delegated_task(
        "t15_c",
        manager_agent_id="technical_lead",
        db_path=tasks_path,
    )

    task = get_delegated_task("t15_c", db_path=tasks_path)
    assert task["status"] == "running"
    # Allow event recorded.
    conn = sqlite3.connect(str(ledger_path))
    try:
        rows = conn.execute(
            "SELECT action FROM hook_events "
            "WHERE tool_name = 'delegated_task' AND session_id = ?",
            ("s_t15",),
        ).fetchall()
    finally:
        conn.close()
    assert any(r[0] == "allow" for r in rows)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tasks_hook_integration.py -v -k "plan_delegated_task"`

Expected: 3 FAIL — no wrap exists yet.

- [ ] **Step 3: Add the sync bridge + wrap `plan_delegated_task`**

In `server/execution/tasks.py`, at the **top** (right after the existing imports, around line 14), add a helper:

```python
import asyncio
import threading


def _run_async_blocking(coro) -> Any:
    """Run an async coroutine from synchronous code.

    Fast path: when no event loop is running in this thread, use asyncio.run.
    Slow path: when a loop is running (e.g. inside FastAPI's event loop and
    the function was called via `await asyncio.to_thread(...)` from async
    code... or via run_in_executor from sync handler), spawn a fresh loop
    in a worker thread to avoid the 'cannot run from a running loop' error.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop in this thread → fast path.
        return asyncio.run(coro)

    # A loop is running in this thread → run the coroutine on a fresh
    # loop in a worker thread and wait for it.
    result_box: dict[str, Any] = {}

    def _worker():
        new_loop = asyncio.new_event_loop()
        try:
            result_box["value"] = new_loop.run_until_complete(coro)
        except BaseException as exc:  # noqa: BLE001
            result_box["error"] = exc
        finally:
            new_loop.close()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join()
    if "error" in result_box:
        raise result_box["error"]
    return result_box["value"]


def _hook_gate_sync(
    *,
    session_id: str,
    member_id: str | None,
    request: dict[str, Any],
) -> None:
    """Sync façade around dispatch_pre_hooks for tasks.py wraps.

    Raises HookDeniedError on deny; returns None on allow. Always records a
    hook_events row.
    """
    from server.harness.hooks import (
        HookContext, HookDeniedError, dispatch_pre_hooks,
    )
    from server.harness.ledger import record_hook_event

    ctx = HookContext(
        tool_name="delegated_task",
        stage=0,
        session_id=session_id or "anon",
        member_id=member_id,
        request=request,
    )
    verdict = _run_async_blocking(dispatch_pre_hooks(ctx))
    record_hook_event(
        session_id=ctx.session_id,
        tool_name="delegated_task",
        action=verdict.action,
        reason=verdict.reason,
        metadata=verdict.metadata,
    )
    if verdict.action == "deny":
        raise HookDeniedError(verdict.reason or "delegated_task denied")


def _hook_post_sync(
    *,
    session_id: str,
    member_id: str | None,
    request: dict[str, Any],
    result: dict[str, Any],
) -> None:
    """Sync façade around dispatch_post_hooks for tasks.py wraps."""
    from server.harness.hooks import HookContext, dispatch_post_hooks

    ctx = HookContext(
        tool_name="delegated_task",
        stage=0,
        session_id=session_id or "anon",
        member_id=member_id,
        request=request,
    )
    _run_async_blocking(dispatch_post_hooks(ctx, result))
```

Now wrap `plan_delegated_task`. Locate the function (line 300). Replace the body with:

```python
def plan_delegated_task(
    task_id: str,
    *,
    manager_agent_id: str | None = None,
    subtask_plan: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    task = _load_required_task(task_id, db_path=db_path)
    _hook_gate_sync(
        session_id=str(task.get("session_id") or ""),
        member_id=None,
        request={
            "op": "plan_delegated_task",
            "task_id": task_id,
            "manager_agent_id": manager_agent_id,
            "has_subtask_plan": subtask_plan is not None,
        },
    )
    if task["status"] not in {"approved", "running"}:
        raise ExecutionError(f"Task must be approved before planning; current status: {task['status']}")
    if not manager_agent_id:
        raise ExecutionError("Manager agent id is required to plan this task.")
    if manager_agent_id != task.get("manager_agent_id"):
        raise ExecutionError("Only the assigned manager agent can plan this task.")

    plan = subtask_plan or default_subtask_plan(task)
    _validate_subtask_plan(plan, expected_manager_id=str(task.get("manager_agent_id") or ""))
    task["subtask_plan"] = plan
    task["status"] = "running"
    result = save_delegated_task(task, db_path=db_path)
    _hook_post_sync(
        session_id=str(task.get("session_id") or ""),
        member_id=None,
        request={"op": "plan_delegated_task", "task_id": task_id},
        result=result,
    )
    return result
```

Note: `save_delegated_task` is called transitively from `plan_delegated_task`. It will also be wrapped in T16 — that's intentional (two hook events per `plan_delegated_task` call; one for the outer `plan_delegated_task`, one for the inner `save_delegated_task`). Bundled rate-limit hooks count both, which is the desired conservative behavior.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tasks_hook_integration.py -v -k "plan_delegated_task"`

Expected: 3 PASS.

Re-run the existing execution contract suite to confirm no regression:

Run: `uv run pytest tests/test_execution_contract.py -v`

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add server/execution/tasks.py tests/test_tasks_hook_integration.py
git commit -m "$(cat <<'EOF'
hooks(p3): wrap plan_delegated_task in hook dispatch

Spec §5.3 — sync wrap via _hook_gate_sync. Helper _run_async_blocking
runs the async dispatcher from sync code (asyncio.run fast-path,
worker-thread slow-path when a loop is already running). State
mutations happen only after allow; deny raises HookDeniedError with
no DB write.
EOF
)"
```

---

## Task 16: Wrap `save_delegated_task`

**Files:**
- Modify: `server/execution/tasks.py`
- Modify: `tests/test_tasks_hook_integration.py`

`save_delegated_task` is the lowest-level write. Wrapping it means every call (including transitive ones from `plan_delegated_task`, `approve_delegated_task`, `update_delegated_task_status`, `attach_task_artifact`, `record_delegation_plan`) passes the hook gate. That is the spec's intent: hooks gate *every* delegated-task write.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tasks_hook_integration.py`:

```python
# ─── T16: save_delegated_task wrap ────────────────────────────────────────


def test_save_delegated_task_denied_raises_HookDeniedError(tmp_db, fresh_registry):
    ledger_path, tasks_path = tmp_db
    from server.harness.hooks import (
        HookVerdict, HookDeniedError, register_pre_hook,
    )
    from server.execution.tasks import save_delegated_task

    def denying(ctx):
        return HookVerdict("deny", "save denied", {})

    register_pre_hook("delegated_task", denying)

    with pytest.raises(HookDeniedError) as excinfo:
        save_delegated_task(_approved_task_payload("t16_a"), db_path=tasks_path)
    assert "save denied" in str(excinfo.value)


def test_save_delegated_task_denied_does_not_persist(tmp_db, fresh_registry):
    ledger_path, tasks_path = tmp_db
    from server.harness.hooks import (
        HookVerdict, HookDeniedError, register_pre_hook,
    )
    from server.execution.tasks import save_delegated_task, get_delegated_task

    def denying(ctx):
        return HookVerdict("deny", "save denied", {})

    register_pre_hook("delegated_task", denying)

    with pytest.raises(HookDeniedError):
        save_delegated_task(_approved_task_payload("t16_b"), db_path=tasks_path)

    assert get_delegated_task("t16_b", db_path=tasks_path) is None


def test_save_delegated_task_allow_persists_and_records_event(tmp_db, fresh_registry):
    ledger_path, tasks_path = tmp_db
    from server.harness.hooks import HookVerdict, register_pre_hook
    from server.execution.tasks import save_delegated_task, get_delegated_task

    def allowing(ctx):
        return HookVerdict("allow", None, {})

    register_pre_hook("delegated_task", allowing)

    save_delegated_task(_approved_task_payload("t16_c"), db_path=tasks_path)
    assert get_delegated_task("t16_c", db_path=tasks_path) is not None

    conn = sqlite3.connect(str(ledger_path))
    try:
        rows = conn.execute(
            "SELECT action FROM hook_events WHERE tool_name = 'delegated_task' "
            "AND session_id = ?",
            ("s_t15",),
        ).fetchall()
    finally:
        conn.close()
    assert any(r[0] == "allow" for r in rows)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tasks_hook_integration.py -v -k "save_delegated_task"`

Expected: 3 FAIL — `save_delegated_task` is not yet wrapped.

- [ ] **Step 3: Wrap `save_delegated_task`**

In `server/execution/tasks.py`, locate `save_delegated_task` (line 212). Insert the gate at the top of the function body, before any DB connection logic. Replace the function with:

```python
def save_delegated_task(task: dict[str, Any], *, db_path: Path | None = None) -> dict[str, Any]:
    task_id = str(task.get("id") or "").strip()
    if not task_id:
        raise ExecutionError("Task id is required.")
    status = str(task.get("status") or "proposed")
    if status not in TASK_STATUSES:
        raise ExecutionError(f"Invalid task status: {status}")

    _hook_gate_sync(
        session_id=str(task.get("session_id") or ""),
        member_id=None,
        request={
            "op": "save_delegated_task",
            "task_id": task_id,
            "status": status,
        },
    )

    now = _utc_now()
    payload = dict(task)
    payload["id"] = task_id
    payload["status"] = status
    payload.setdefault("approval_required", True)
    payload.setdefault("artifacts", [])

    conn = _connect_tasks(db_path)
    try:
        existing = conn.execute(
            "SELECT created_at FROM delegated_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        created_at = existing["created_at"] if existing else now
        conn.execute(
            """INSERT OR REPLACE INTO delegated_tasks (
                task_id, session_id, manager_agent_id, execution_unit_id,
                status, payload, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task_id,
                str(payload.get("session_id") or ""),
                str(payload.get("manager_agent_id") or ""),
                str(payload.get("execution_unit_id") or ""),
                status,
                json.dumps(payload, ensure_ascii=False),
                created_at,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    _hook_post_sync(
        session_id=str(payload.get("session_id") or ""),
        member_id=None,
        request={"op": "save_delegated_task", "task_id": task_id},
        result=payload,
    )
    return payload
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tasks_hook_integration.py -v -k "save_delegated_task"`

Expected: 3 PASS.

Re-run the wider task suite:

Run: `uv run pytest tests/test_tasks_hook_integration.py tests/test_execution_contract.py -v`

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add server/execution/tasks.py tests/test_tasks_hook_integration.py
git commit -m "$(cat <<'EOF'
hooks(p3): wrap save_delegated_task in hook dispatch

Spec §5.3 — every delegated-task write passes the hook gate.
Because plan_delegated_task / approve_delegated_task /
update_delegated_task_status all eventually call save_delegated_task,
wrapping the lowest layer ensures complete coverage. Outer
plan/update wraps still gate the operation-level intent (T15, T17)
so a denial reason can reflect the high-level op.
EOF
)"
```

---

## Task 17: Wrap `update_delegated_task_status`

**Files:**
- Modify: `server/execution/tasks.py`
- Modify: `tests/test_tasks_hook_integration.py`

Same shape as T15. Provides an operation-level gate (a hook can deny "running" or "completed" transitions specifically based on `request["new_status"]`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tasks_hook_integration.py`:

```python
# ─── T17: update_delegated_task_status wrap ───────────────────────────────


def test_update_delegated_task_status_denied_raises_HookDeniedError(tmp_db, fresh_registry):
    ledger_path, tasks_path = tmp_db
    from server.harness.hooks import (
        HookVerdict, HookDeniedError, register_pre_hook,
    )
    from server.execution.tasks import update_delegated_task_status, save_delegated_task

    save_delegated_task(_approved_task_payload("t17_a"), db_path=tasks_path)

    # Deny only when the request op is the status-update.
    def denying(ctx):
        if ctx.request.get("op") == "update_delegated_task_status":
            return HookVerdict("deny", "no status change", {})
        return HookVerdict("allow", None, {})

    register_pre_hook("delegated_task", denying)

    with pytest.raises(HookDeniedError) as excinfo:
        update_delegated_task_status(
            "t17_a",
            status="completed",
            manager_agent_id="technical_lead",
            db_path=tasks_path,
        )
    assert "no status change" in str(excinfo.value)


def test_update_delegated_task_status_allow_completes(tmp_db, fresh_registry):
    ledger_path, tasks_path = tmp_db
    from server.harness.hooks import HookVerdict, register_pre_hook
    from server.execution.tasks import (
        update_delegated_task_status, save_delegated_task, get_delegated_task,
    )

    save_delegated_task(_approved_task_payload("t17_b"), db_path=tasks_path)

    def allowing(ctx):
        return HookVerdict("allow", None, {})

    register_pre_hook("delegated_task", allowing)

    update_delegated_task_status(
        "t17_b",
        status="completed",
        manager_agent_id="technical_lead",
        result_summary="done",
        db_path=tasks_path,
    )
    task = get_delegated_task("t17_b", db_path=tasks_path)
    assert task["status"] == "completed"
    assert task["result_summary"] == "done"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_tasks_hook_integration.py -v -k "update_delegated_task_status"`

Expected: 2 FAIL — `update_delegated_task_status` isn't wrapped (the inner `save_delegated_task` is, but the denying hook only fires on the `update_delegated_task_status` op).

- [ ] **Step 3: Wrap `update_delegated_task_status`**

In `server/execution/tasks.py`, locate `update_delegated_task_status` (line 322). Insert the gate after `_load_required_task` and before any state validation:

```python
def update_delegated_task_status(
    task_id: str,
    *,
    status: str,
    manager_agent_id: str | None = None,
    status_detail: str | None = None,
    result_summary: str | None = None,
    artifacts: list[str] | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    if status not in TASK_STATUSES:
        raise ExecutionError(f"Invalid task status: {status}")
    task = _load_required_task(task_id, db_path=db_path)
    _hook_gate_sync(
        session_id=str(task.get("session_id") or ""),
        member_id=None,
        request={
            "op": "update_delegated_task_status",
            "task_id": task_id,
            "new_status": status,
            "manager_agent_id": manager_agent_id,
        },
    )
    if status == "completed" and manager_agent_id != task.get("manager_agent_id"):
        raise ExecutionError("Only the assigned manager agent can complete this task.")
    if status == "running" and task.get("status") not in {"approved", "running"}:
        raise ExecutionError("Only approved tasks can run.")

    task["status"] = status
    if status_detail is not None:
        task["status_detail"] = status_detail
    if result_summary is not None:
        task["result_summary"] = result_summary
    if artifacts:
        task["artifacts"] = _dedupe([*(task.get("artifacts") or []), *artifacts])
    result = save_delegated_task(task, db_path=db_path)
    _hook_post_sync(
        session_id=str(task.get("session_id") or ""),
        member_id=None,
        request={
            "op": "update_delegated_task_status",
            "task_id": task_id,
            "new_status": status,
        },
        result=result,
    )
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tasks_hook_integration.py -v -k "update_delegated_task_status"`

Expected: 2 PASS.

Re-run all tests for this PR to confirm green:

Run: `uv run pytest tests/test_tasks_hook_integration.py tests/test_execution_contract.py -v`

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add server/execution/tasks.py tests/test_tasks_hook_integration.py
git commit -m "$(cat <<'EOF'
hooks(p3): wrap update_delegated_task_status in hook dispatch

Spec §5.3 — operation-level gate so a hook can deny specific
transitions (e.g. completion) by inspecting request['new_status'].
Inner save_delegated_task gate (T16) still fires; bundled
rate-limit counts both, intentionally conservative.
EOF
)"
```

---

## Task 18: Final integration smoke — denying hook surfaces from one task call

**Files:**
- Modify: `tests/test_tasks_hook_integration.py`

A single test that ties everything together: register both bundled hooks (cap + rate-limit) via auto-discovery (already loaded at import), shrink the rate-limit env to 1, call `save_delegated_task` twice. First succeeds; second is denied by the bundled `rate_limit_delegated_tasks`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tasks_hook_integration.py`:

```python
# ─── T18: end-to-end with bundled rate-limit hook ─────────────────────────


def test_bundled_rate_limit_denies_second_save_within_window(tmp_db, monkeypatch):
    """End-to-end: bundled rate_limit_delegated_tasks denies the 2nd save."""
    ledger_path, tasks_path = tmp_db
    monkeypatch.setenv("AGENTIC_BOARD_DELEGATED_TASK_RATE_LIMIT", "1")
    monkeypatch.setenv("AGENTIC_BOARD_DELEGATED_TASK_RATE_WINDOW_SECONDS", "60")

    # No fresh_registry fixture: we WANT the bundled hooks loaded at import.
    # If the bundled hook isn't registered, the test surfaces that fact.
    from server.harness.hooks import _list_pre_hooks_for_tests, HookDeniedError
    from server.harness.hooks._bundled.rate_limit_delegated_tasks import (
        rate_limit_delegated_tasks,
    )
    assert rate_limit_delegated_tasks in _list_pre_hooks_for_tests("delegated_task"), \
        "bundled rate_limit_delegated_tasks must be auto-loaded"

    from server.execution.tasks import save_delegated_task

    # First call: allowed (window count = 0 → < limit 1).
    save_delegated_task(_approved_task_payload("t18_a"), db_path=tasks_path)
    # Second call: denied (window count = 1 → >= limit 1).
    with pytest.raises(HookDeniedError) as excinfo:
        save_delegated_task(_approved_task_payload("t18_b"), db_path=tasks_path)
    assert "rate limit" in str(excinfo.value).lower()
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_tasks_hook_integration.py -v -k "bundled_rate_limit"`

Expected: PASS (T12 and T16 together enable this; T10's auto-discovery already loaded the bundled hook at the first import of `server.harness.hooks`).

If it FAILS with the assertion `bundled rate_limit_delegated_tasks must be auto-loaded`, the issue is auto-discovery; revisit T10. If it fails on the second `save_delegated_task` with "no exception raised", revisit T16's wrap.

Final whole-PR run to confirm:

Run: `uv run pytest tests/test_hooks_registry.py tests/test_hooks_ledger.py tests/test_hooks_discovery.py tests/test_hooks_bundled.py tests/test_web_search_hook_integration.py tests/test_tasks_hook_integration.py tests/test_execution_contract.py tests/test_web_search_contract.py tests/test_ledger_contract.py -v`

Expected: all PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_tasks_hook_integration.py
git commit -m "$(cat <<'EOF'
hooks(p3): end-to-end test for bundled rate-limit on tasks

Spec §8 — confirms auto-discovery loaded the bundled hook and that
the second save_delegated_task within the window is denied with a
HookDeniedError carrying the bundled hook's rate-limit reason.
EOF
)"
```

---

## Done

PR2 covers T1–T14: hook infra, ledger table, auto-discovery, two bundled hooks, web_search wrap, integration test.

PR3 covers T15–T18: three tasks.py wraps + a final bundled-hook end-to-end smoke.

Both PRs are independently shippable. PR2 is mergeable without PR3 (web_search gated; tasks not yet). PR3 depends on PR2 (it uses `HookContext`, `HookDeniedError`, `dispatch_pre_hooks`, `record_hook_event`).
