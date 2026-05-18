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
