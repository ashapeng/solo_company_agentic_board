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
