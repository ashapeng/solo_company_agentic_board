"""Shortcut command detector for intent-based agent routing.

When the CEO types a directive like ``secretary summarize`` or ``/brief``, this
module detects the *intent* **before** the full deliberation pipeline runs so we
can short-circuit to the targeted agent (e.g. secretary) and skip Stages 1–3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class ShortcutType(str, Enum):
    """Well-known shortcut intents."""

    SECRETARY_BRIEF = "secretary_brief"
    """Produce an executive summary / consolidation."""

    CHAIR_DECISION = "chair_decision"
    """Ask the chairperson directly (future)."""


@dataclass(frozen=True)
class DetectedShortcut:
    """Result of a successful shortcut match."""

    type: ShortcutType
    target_member_id: str          # e.g. ``"secretary"``
    display_label: str              # e.g. ``"Secretary Executive Brief"``
    stripped_query: str             # user query with command prefix removed
    source_session_id: str | None   # if user referenced a prior session
    confidence: float               # 0.0 – 1.0


# ---------------------------------------------------------------------------
# Detection rules  (ordered by priority — first match wins)
# ---------------------------------------------------------------------------

_SECRETARY_TRIGGERS: list[tuple[re.Pattern[str], float]] = [
    # --- exact slash-commands ---
    (re.compile(r"^/(?:summary|brief|secretary)\b", re.I), 0.98),
    (re.compile(r"^@secretary\b", re.I), 0.98),
    (re.compile(r"^/@secretary\b", re.I), 0.98),
    # --- "secretary [summarize|brief|...]" ---
    (re.compile(r"^secretary\s+(?:summarize|summary|brief|consolidate|give\s+me\s+(?:an?\s+)?(?:executive\s+)?(?:brief|summary))\b", re.I), 0.95),
    # --- "give me a summary / executive brief" ---
    (re.compile(r"^(?:please\s+)?(?:give\s+me\s+)?(?:an?\s+)?(?:executive\s+)?(?:brief|summary|consolidation)\b", re.I), 0.85),
    # --- "summarize this / the discussion" ---
    (re.compile(r"^summarize\s+(?:this|the\s+(?:discussion|board|meeting|session|debate|conversation))\b", re.I), 0.92),
]

# Regex that extracts an optional session id like "... from session board_1234"
_SESSION_ID_RE = re.compile(
    r"(?:from\s+|for\s+|session\s+)(board_\d+)",
    re.I,
)


def detect_shortcut(query: str) -> DetectedShortcut | None:
    """Return a :class:`DetectedShortcut` when the query expresses a known
    shortcut intent, otherwise ``None``.

    This is intentionally **fast and rule-based** (no LLM call) so that the
    overhead is negligible compared with a full deliberation cycle.
    """
    q = query.strip()
    if not q:
        return None

    for pattern, confidence in _SECRETARY_TRIGGERS:
        m = pattern.match(q)
        if not m:
            continue

        stripped = q[m.end():].strip() or q
        sid_m = _SESSION_ID_RE.search(stripped)
        source_sid = sid_m.group(1) if sid_m else None

        return DetectedShortcut(
            type=ShortcutType.SECRETARY_BRIEF,
            target_member_id="secretary",
            display_label="Secretary Executive Brief",
            stripped_query=stripped,
            source_session_id=source_sid,
            confidence=confidence,
        )

    return None
