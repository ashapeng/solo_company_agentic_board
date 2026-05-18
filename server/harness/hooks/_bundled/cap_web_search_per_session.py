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
