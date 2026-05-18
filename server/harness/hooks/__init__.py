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


# ─── Exception ─────────────────────────────────────────────────────────────


class HookDeniedError(Exception):
    """Raised by a tool call site when dispatch_pre_hooks returns deny."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
