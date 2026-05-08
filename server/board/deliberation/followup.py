"""Mid-deliberation follow-up channel.

User types follow-ups during a live_research run. Lines are parsed into
Followup records, queued, and drained between member rounds.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass


@dataclass
class Followup:
    target: str | None       # member_id or None for unrouted
    text: str                # the follow-up content
    raw: str                 # original input line (for logging)


_TARGET_PATTERN = re.compile(r"^\s*([a-zA-Z_][a-zA-Z_0-9-]*)\s*:\s*(.+)$")


def parse_followup_line(line: str) -> Followup | None:
    """Parse a CLI follow-up line.
    Format: '<member_id>: <text>' (e.g., 'strategist: search more on X').
    Lines without a target prefix return target=None.
    Empty/whitespace-only lines return None entirely."""
    line = line.strip()
    if not line:
        return None
    m = _TARGET_PATTERN.match(line)
    if m:
        return Followup(target=m.group(1).lower(), text=m.group(2).strip(), raw=line)
    # Unrouted; let caller decide what to do with it.
    return Followup(target=None, text=line, raw=line)


class FollowupBuffer:
    """Async-safe buffer of pending follow-ups."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._buffer: list[Followup] = []

    async def add(self, item: Followup) -> None:
        async with self._lock:
            self._buffer.append(item)

    async def take_for_member(self, member_id: str) -> list[Followup]:
        async with self._lock:
            taken = [f for f in self._buffer if f.target == member_id]
            self._buffer = [f for f in self._buffer if f.target != member_id]
            return taken

    async def take_unrouted(self) -> list[Followup]:
        async with self._lock:
            taken = [f for f in self._buffer if f.target is None]
            self._buffer = [f for f in self._buffer if f.target is not None]
            return taken

    async def is_empty(self) -> bool:
        async with self._lock:
            return not self._buffer

    async def snapshot(self) -> list[Followup]:
        """Drain everything; for one-shot processing."""
        async with self._lock:
            taken = list(self._buffer)
            self._buffer = []
            return taken
