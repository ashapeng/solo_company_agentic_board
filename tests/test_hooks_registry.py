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
