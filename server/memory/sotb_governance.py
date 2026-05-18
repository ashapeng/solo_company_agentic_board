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


@dataclass
class SotbHealth:
    """Result of read-time freshness + conflict checks (§8.2).

    `expired`, `low_confidence`, `stale` are populated by the pure
    `compute_freshness`. `query_conflicts` and `conflicts_logged` are
    populated by the LLM-judge paths (T5 read-side, T7 write-side) and
    stay empty when the judges are disabled.
    """
    expired: list[SotbEntry] = field(default_factory=list)
    low_confidence: list[SotbEntry] = field(default_factory=list)
    stale: list[SotbEntry] = field(default_factory=list)
    query_conflicts: list[dict] = field(default_factory=list)
    conflicts_logged: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "expired": [e.to_dict() for e in self.expired],
            "low_confidence": [e.to_dict() for e in self.low_confidence],
            "stale": [e.to_dict() for e in self.stale],
            "query_conflicts": list(self.query_conflicts),
            "conflicts_logged": list(self.conflicts_logged),
            "warnings_count": (
                len(self.expired) + len(self.low_confidence) + len(self.stale)
                + len(self.query_conflicts) + len(self.conflicts_logged)
            ),
        }


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


def _parse_markdown_entries(md_text: str) -> list[tuple[str, str]]:
    """Walk markdown, return list of (section, bullet_text) for every bullet
    under a recognized section heading. Skips placeholders like `[No ...]`.
    Pure function — no IO."""
    out: list[tuple[str, str]] = []
    current_section: str | None = None
    for raw_line in md_text.splitlines():
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
        if not bullet or bullet.startswith("[No "):
            continue
        # Strip any suffixes if a manual-edit included them (defensive).
        clean = _strip_suffixes(bullet)
        if not clean:
            continue
        out.append((current_section, clean))
    return out


def _bootstrap_entries_from_markdown(md_text: str) -> list[SotbEntry]:
    """DC1: lazy bootstrap. Every markdown bullet becomes a sidecar row
    with `provenance.source_member='manual'`, `session_id='bootstrap'`,
    `confidence=0.5`, and a section-default `expires_at`."""
    now = _now_iso()
    entries: list[SotbEntry] = []
    for section, text in _parse_markdown_entries(md_text):
        default_days = SECTION_DEFAULTS.get(section)
        expires_at = _expiry_iso_from_days(default_days) if default_days else None
        entries.append(SotbEntry(
            entry_id=SotbEntry.compute_entry_id(section, text),
            section=section, text=text,
            created_at=now, updated_at=now,
            confidence=0.5, expires_at=expires_at,
            provenance={"session_id": "bootstrap", "source_member": "manual"},
        ))
    return entries


def write_sotb_index(entries: list[SotbEntry], *, path: Path | None = None) -> None:
    """Atomic write: write to *.tmp, fsync, rename."""
    target = path or _INDEX_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e.to_dict(), ensure_ascii=False) + "\n")
        f.flush()
        try:
            import os
            os.fsync(f.fileno())
        except (OSError, AttributeError):  # best-effort
            pass
    tmp.replace(target)


def _read_index_raw(path: Path) -> list[SotbEntry]:
    """Read the sidecar JSONL into SotbEntry objects. No bootstrap, no
    reconcile. Returns [] if missing."""
    if not path.exists():
        return []
    out: list[SotbEntry] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(SotbEntry.from_dict(json.loads(line)))
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning("sotb_index: skipping malformed line: %s", exc)
            continue
    return out


def read_sotb_index(
    *, md_path: Path | None = None, index_path: Path | None = None,
) -> list[SotbEntry]:
    """Return the reconciled index for the current sotb.md.

    DC1 (bootstrap): If the sidecar doesn't exist, parse markdown into rows
    and persist.

    DC5 (drift reconcile): If the sidecar exists, walk both sides — markdown
    is truth. New markdown rows become sidecar rows with
    `provenance.source_member='manual'`; orphaned sidecar rows are dropped.
    Sidecar metadata for surviving rows is preserved.
    """
    mp = md_path or _SOTB_PATH
    ip = index_path or _INDEX_PATH

    md_text = mp.read_text(encoding="utf-8") if mp.exists() else ""
    md_pairs = _parse_markdown_entries(md_text)
    md_ids = {SotbEntry.compute_entry_id(s, t): (s, t) for s, t in md_pairs}

    if not ip.exists():
        entries = _bootstrap_entries_from_markdown(md_text)
        write_sotb_index(entries, path=ip)
        return entries

    raw = _read_index_raw(ip)
    by_id = {e.entry_id: e for e in raw}

    # Drop orphans (sidecar rows whose md hash no longer exists). When the
    # markdown parses to zero entries we treat that as "no signal" rather
    # than "definitive truth" — otherwise an empty/unparseable md would nuke
    # the sidecar. (Matches the plan's roundtrip-with-empty-md test.)
    if md_ids:
        survivors = [e for e in raw if e.entry_id in md_ids]
    else:
        survivors = list(raw)
    survivor_ids = {e.entry_id for e in survivors}

    # Add manual-drift rows (md entries with no sidecar row).
    now = _now_iso()
    additions: list[SotbEntry] = []
    for mid, (section, text) in md_ids.items():
        if mid in survivor_ids:
            continue
        default_days = SECTION_DEFAULTS.get(section)
        expires_at = _expiry_iso_from_days(default_days) if default_days else None
        additions.append(SotbEntry(
            entry_id=mid, section=section, text=text,
            created_at=now, updated_at=now,
            confidence=0.5, expires_at=expires_at,
            provenance={"session_id": "drift-reconcile", "source_member": "manual"},
        ))

    merged = survivors + additions
    # Only rewrite if reconciliation changed something — keeps file mtime
    # stable on no-op reads.
    if len(merged) != len(raw) or set(e.entry_id for e in merged) != set(by_id.keys()):
        write_sotb_index(merged, path=ip)
    return merged


_LOW_CONFIDENCE_THRESHOLD = 0.5
_STALE_FLAGGED_SECTIONS = frozenset(("Risk Register", "Open Questions"))


def _age_days(created_at_iso: str) -> int:
    try:
        dt = datetime.fromisoformat(created_at_iso)
    except (ValueError, TypeError):
        return 0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).days


def _is_expired(entry: SotbEntry) -> bool:
    if not entry.expires_at:
        return False
    try:
        dt = datetime.fromisoformat(entry.expires_at)
    except (ValueError, TypeError):
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt < datetime.now(timezone.utc)


def _remove_entry_from_md(md: str, entry: SotbEntry) -> str:
    """Remove the `- <text>` bullet matching `entry.text` from `md`.
    Conservative: only drops the FIRST exact match to avoid collateral
    damage on duplicates."""
    target = f"- {entry.text}"
    lines = md.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == target:
            lines.pop(i)
            return "\n".join(lines) + ("\n" if md.endswith("\n") else "")
    return md


def compute_freshness(
    *, md: str, entries: list[SotbEntry], stale_days: int = 90,
) -> tuple[str, SotbHealth]:
    """§8.2 non-LLM portion. Pure (modulo the wall clock). Returns the
    (possibly-trimmed) markdown plus a `SotbHealth` with three populated
    lists (LLM-populated lists stay empty here)."""
    health = SotbHealth()
    new_md = md

    for entry in entries:
        if _is_expired(entry):
            health.expired.append(entry)
            new_md = _remove_entry_from_md(new_md, entry)
            continue
        if entry.confidence < _LOW_CONFIDENCE_THRESHOLD:
            health.low_confidence.append(entry)
            # don't continue — an entry can be both low-confidence AND stale.
        if entry.section in _STALE_FLAGGED_SECTIONS and _age_days(entry.created_at) > stale_days:
            health.stale.append(entry)

    return new_md, health
