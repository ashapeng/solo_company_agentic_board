"""Board member definitions and model configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Model defaults (overridable via env vars)
# ---------------------------------------------------------------------------

DEFAULT_CHAIRMAN_MODEL = "anthropic/claude-opus-4"
DEFAULT_COUNCIL_MODELS = [
    "anthropic/claude-sonnet-4",
    "google/gemini-2.5-pro",
    "openai/gpt-4.1",
    "x-ai/grok-3",
]


def get_chairman_model() -> str:
    return os.getenv("CHAIRMAN_MODEL", DEFAULT_CHAIRMAN_MODEL)


def get_council_models() -> list[str]:
    raw = os.getenv("COUNCIL_MODELS")
    if raw:
        return [m.strip() for m in raw.split(",") if m.strip()]
    return DEFAULT_COUNCIL_MODELS


# ---------------------------------------------------------------------------
# Board member definitions
# ---------------------------------------------------------------------------

@dataclass
class BoardMember:
    """A single board member with a defined role and expertise."""
    id: str
    title: str
    role: str
    expertise: list[str]
    system_prompt: str
    stage2_behavior: str = ""         # peer review behavior instructions
    stage2_addendum: str = ""          # deprecated alias for stage2_behavior
    model_override: str | None = None  # use specific model for this member
    priority: int = 0                  # higher = speaks earlier in synthesis
    tags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Member loading — all members live in members/*.md files
# ---------------------------------------------------------------------------

_cached_members: list[BoardMember] | None = None


def _load_default_members() -> list[BoardMember]:
    """Load members from the members/ directory using the markdown loader."""
    from .loader import load_members
    from .roster import active_member_ids

    active_ids = set(active_member_ids())
    return load_members(include_shelved_ids=active_ids)


def get_board_members() -> list[BoardMember]:
    """Return all board members, loading from markdown files on first call."""
    global _cached_members
    if _cached_members is None:
        _cached_members = _load_default_members()
    return _cached_members


def get_members_by_id() -> dict[str, BoardMember]:
    """Return a dict of member_id -> BoardMember."""
    return {m.id: m for m in get_board_members()}


# Backward-compatible module-level aliases.
# These are properties that evaluate lazily so imports like
#   from board.config import BOARD_MEMBERS, MEMBERS_BY_ID
# continue to work.  Since Python module-level variables can't be
# descriptors, we use a simple approach: define them as empty and
# populate on first access via __getattr__.

def __getattr__(name: str):
    if name == "BOARD_MEMBERS":
        return get_board_members()
    if name == "MEMBERS_BY_ID":
        return get_members_by_id()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
