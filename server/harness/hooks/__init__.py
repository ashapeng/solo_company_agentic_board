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
