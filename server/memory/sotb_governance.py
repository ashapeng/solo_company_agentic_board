"""SOTB governance (spec §8): JSONL sidecar, freshness checks, conflict log.

Pinned design choices (see plan §Design choices):
- DC1: lazy bootstrap on first read.
- DC2: log-only conflict on write (no auto-resolve in P4).
- DC3: author-supplied confidence via `(confidence: 0.X)` suffix; default 0.5.
- DC4: section-based default `expires_at` (§8.4); per-entry override via
       `(expires: YYYY-MM-DD)` suffix.
- DC5: lazy reconcile on every read (markdown is source of truth).
- DC6: judge LLM calls gated on `verify` (HEAVY proxy) AND
       `hardening.sotb_judge_enabled`.

Public surface:
- `read_sotb_governed(query, *, verify) -> tuple[str, SotbHealth]` (T6)
- `apply_sotb_update_governed(update_text, session_id, *, verify) -> SotbHealth` (T7)
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from server.board.llm import query_llm  # used in T5 only; imported here so tests
                                         # can patch `server.memory.sotb_governance.query_llm`.

logger = logging.getLogger(__name__)


_SOTB_PATH = Path(__file__).resolve().parent / "sotb.md"
_INDEX_PATH = Path(__file__).resolve().parent / "sotb_index.jsonl"

# §8.4 — default expiration days per section. `None` = never expires.
SECTION_DEFAULTS: dict[str, int | None] = {
    "Active Decisions": None,
    "Risk Register": 180,
    "Established Positions": 365,
    "Open Questions": 90,
    "Last Session": 30,
    "Resolved": None,
}

_VALID_SECTIONS = frozenset(SECTION_DEFAULTS.keys())

# (confidence: 0.X) suffix — accepts integers or decimals.
_CONFIDENCE_RE = re.compile(r"\(confidence:\s*([+-]?\d*\.?\d+)\s*\)", re.IGNORECASE)
# (expires: YYYY-MM-DD) suffix.
_EXPIRES_RE = re.compile(r"\(expires:\s*(\d{4}-\d{2}-\d{2})\s*\)", re.IGNORECASE)


@dataclass
class SotbEntry:
    """One sidecar row. Mirrors §8.1's JSON shape."""
    entry_id: str
    section: str
    text: str
    created_at: str
    updated_at: str
    confidence: float = 0.5
    expires_at: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def compute_entry_id(section: str, text: str) -> str:
        """§8.1: `sha256(section + text)[:12]`. Implementation note: we
        separate section and text with `|` so e.g. "AB|C" and "A|BC" don't
        collide. The 12-char prefix gives ~10^14 collision resistance — fine
        for a <1000-word memory file."""
        h = hashlib.sha256(f"{section}|{text}".encode("utf-8")).hexdigest()
        return h[:12]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SotbEntry":
        return cls(
            entry_id=str(d["entry_id"]),
            section=str(d["section"]),
            text=str(d["text"]),
            created_at=str(d["created_at"]),
            updated_at=str(d["updated_at"]),
            confidence=float(d.get("confidence", 0.5)),
            expires_at=d.get("expires_at"),
            provenance=dict(d.get("provenance") or {}),
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expiry_iso_from_days(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _parse_iso_date_to_utc(date_str: str) -> str:
    """Parse YYYY-MM-DD to ISO datetime at UTC midnight."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _strip_suffixes(text: str) -> str:
    """Remove (confidence: X) and (expires: YYYY-MM-DD) suffixes; collapse spaces."""
    text = _CONFIDENCE_RE.sub("", text)
    text = _EXPIRES_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_confidence(text: str) -> float | None:
    m = _CONFIDENCE_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _extract_expires_at(text: str) -> str | None:
    m = _EXPIRES_RE.search(text)
    if not m:
        return None
    try:
        return _parse_iso_date_to_utc(m.group(1))
    except ValueError:
        return None


def _clamp_unit(x: float) -> float:
    return max(0.0, min(1.0, x))


def parse_entries_from_update(
    update_text: str, *, session_id: str, source_member: str,
) -> list[SotbEntry]:
    """Parse a chair-provided SOTB update block into `SotbEntry` objects.

    Sections are `## <Section Name>` headings (markdown H2). Bullets are
    lines starting with `-` or `*`. Sections not in `SECTION_DEFAULTS` are
    silently skipped (DC's parser is permissive — the chair's free-text
    isn't always perfectly formed).
    """
    if not update_text or not update_text.strip():
        return []

    entries: list[SotbEntry] = []
    current_section: str | None = None
    now = _now_iso()

    for raw_line in update_text.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            heading = line[3:].strip().rstrip(":")
            current_section = heading if heading in _VALID_SECTIONS else None
            continue
        if current_section is None:
            continue
        if not (line.startswith("- ") or line.startswith("* ")):
            continue

        bullet = line[2:].strip()
        if not bullet:
            continue

        # Order matters: extract suffixes BEFORE stripping them.
        conf_explicit = _extract_confidence(bullet)
        expires_explicit = _extract_expires_at(bullet)
        clean_text = _strip_suffixes(bullet)
        if not clean_text:
            continue

        confidence = _clamp_unit(conf_explicit) if conf_explicit is not None else 0.5

        if expires_explicit is not None:
            expires_at = expires_explicit
        else:
            default_days = SECTION_DEFAULTS.get(current_section)
            expires_at = _expiry_iso_from_days(default_days) if default_days else None

        entries.append(SotbEntry(
            entry_id=SotbEntry.compute_entry_id(current_section, clean_text),
            section=current_section,
            text=clean_text,
            created_at=now,
            updated_at=now,
            confidence=confidence,
            expires_at=expires_at,
            provenance={"session_id": session_id, "source_member": source_member},
        ))

    return entries
