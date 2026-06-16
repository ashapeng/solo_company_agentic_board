"""SOTB consolidation ("dream-mode") pass (white-box memory).

A periodic maintenance pass over a venture's State of the Board that:
  1. snapshots the current SOTB (so a bad pass can be rolled back),
  2. sweeps expired entries (section-default / per-entry `expires_at`),
  3. de-duplicates near-identical bullets within a section (merge metadata),
  4. (gated) retires entries that a contradiction judge deems superseded by a
     newer overlapping entry, moving the older one to the "Resolved" section,
  5. re-renders the markdown + sidecar index from the surviving entries, and
  6. records an audit row in the shared ledger DB.

Design notes:
- The consolidation NEVER raises on judge/provider errors (the judge already
  swallows them and returns a non-contradictory verdict).
- The render is intentionally lossless for the bullet `(section, text)` set so
  that feeding the output back through `read_sotb_index` is idempotent.
- This module imports `sotb_governance` read-only for its parsing/rendering
  helpers and never mutates governance state directly.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from server.harness.config import get_config
from server.memory.sotb_governance import (
    SECTION_DEFAULTS,
    SotbEntry,
    _contradiction_judge,
    _find_overlapping,
    compute_freshness,
    read_sotb_index,
    venture_memory_paths,
    write_sotb_index,
)
from server.memory.sotb_snapshot import _atomic_write_text, capture_snapshot
from server.memory.store import record_consolidation

logger = logging.getLogger(__name__)

_RESOLVED_SECTION = "Resolved"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #
def _extract_metadata_line(existing_md: str | None) -> str:
    """Return the `> Last updated: ...` metadata line from `existing_md`, or a
    sensible default when absent."""
    if existing_md:
        for raw_line in existing_md.splitlines():
            line = raw_line.strip()
            if line.startswith("> Last updated:"):
                return line
    return f"> Last updated: {_now_iso()} | Sessions: 0"


def render_md_from_entries(
    entries: list[SotbEntry], *, existing_md: str | None = None,
) -> str:
    """Render a SOTB markdown document from a list of entries.

    Emits an H1 title, the preserved/default metadata line, then each section
    from `SECTION_DEFAULTS` IN ORDER. Within a section, entries keep their
    insertion order. Empty CORE sections (everything except "Resolved") get a
    NON-bullet placeholder so the document round-trips cleanly through
    `read_sotb_index`; the "Resolved" heading is omitted entirely when empty.
    """
    by_section: dict[str, list[SotbEntry]] = {}
    for e in entries:
        by_section.setdefault(e.section, []).append(e)

    lines: list[str] = ["# State of the Board"]
    lines.append(_extract_metadata_line(existing_md))

    for section in SECTION_DEFAULTS:
        section_entries = by_section.get(section, [])
        if section == _RESOLVED_SECTION and not section_entries:
            continue
        lines.append("")
        lines.append(f"## {section}")
        if section_entries:
            for e in section_entries:
                lines.append(f"- {e.text}")
        else:
            # Non-bullet placeholder so it does NOT round-trip as an entry.
            lines.append("_(none)_")

    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Result
# --------------------------------------------------------------------------- #
@dataclass
class ConsolidationResult:
    venture_id: str
    snapshot_id: str | None
    merged: int
    superseded: int
    expired: int
    kept: int
    summary: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "venture_id": self.venture_id,
            "snapshot_id": self.snapshot_id,
            "merged": self.merged,
            "superseded": self.superseded,
            "expired": self.expired,
            "kept": self.kept,
            "summary": self.summary,
        }


# --------------------------------------------------------------------------- #
# Merge helpers
# --------------------------------------------------------------------------- #
def _min_iso(a: str, b: str) -> str:
    """Return the earlier of two ISO timestamps (string-min as fallback)."""
    try:
        da = datetime.fromisoformat(a)
        db = datetime.fromisoformat(b)
        return a if da <= db else b
    except (ValueError, TypeError):
        return min(a, b)


def _max_iso(a: str, b: str) -> str:
    """Return the later of two ISO timestamps (string-max as fallback)."""
    try:
        da = datetime.fromisoformat(a)
        db = datetime.fromisoformat(b)
        return a if da >= db else b
    except (ValueError, TypeError):
        return max(a, b)


def _provenance_session_ids(prov: dict[str, Any]) -> list[str]:
    """Collect known session ids from a provenance dict (top-level + merged)."""
    ids: list[str] = []
    sid = prov.get("session_id")
    if sid:
        ids.append(str(sid))
    merged_from = prov.get("merged_from")
    if isinstance(merged_from, list):
        ids.extend(str(x) for x in merged_from if x)
    return ids


def _merge_entries(keep: SotbEntry, dup: SotbEntry) -> SotbEntry:
    """Fold `dup` into `keep`: keep the HIGHER confidence, the EARLIER
    created_at, the LATEST updated_at, and a union of session ids under
    `provenance['merged_from']`."""
    session_ids: list[str] = []
    for sid in _provenance_session_ids(keep.provenance) + _provenance_session_ids(dup.provenance):
        if sid and sid not in session_ids:
            session_ids.append(sid)

    merged_provenance = dict(keep.provenance)
    if session_ids:
        merged_provenance["merged_from"] = session_ids

    keep.confidence = max(keep.confidence, dup.confidence)
    keep.created_at = _min_iso(keep.created_at, dup.created_at)
    keep.updated_at = _max_iso(keep.updated_at, dup.updated_at)
    keep.provenance = merged_provenance
    return keep


# --------------------------------------------------------------------------- #
# Supersession helpers
# --------------------------------------------------------------------------- #
def _retire_to_resolved(older: SotbEntry) -> SotbEntry:
    """Move `older` into the Resolved section with a `[superseded ...]` prefix
    and a recomputed entry_id."""
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    new_text = f"[superseded {date_str}] {older.text}"
    older.section = _RESOLVED_SECTION
    older.text = new_text
    older.updated_at = _now_iso()
    older.entry_id = SotbEntry.compute_entry_id(_RESOLVED_SECTION, new_text)
    return older


def _judge_model() -> str:
    cfg = get_config()
    return (
        cfg.hardening.get("sotb_judge_model")
        or cfg.hardening.get("atomizer_model", "qwen/qwen3.6-max-preview")
    )


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #
async def consolidate_sotb(
    *,
    venture_id: str = "default",
    verify: bool = False,
    session_id: str | None = None,
    md_path: Path | None = None,
    index_path: Path | None = None,
    db_path: Path | None = None,
) -> dict:
    """Run a consolidation ("dream-mode") pass over a venture's SOTB.

    Returns a `ConsolidationResult.to_dict()`. Never raises on judge/provider
    errors.
    """
    _md_default, _idx_default = venture_memory_paths(venture_id)
    mp = md_path or _md_default
    ip = index_path or _idx_default

    # (b) Snapshot first so a bad pass is recoverable.
    snap = capture_snapshot(
        venture_id=venture_id,
        reason="pre_consolidation",
        session_id=session_id,
        md_path=mp,
        index_path=ip,
        db_path=db_path,
    )
    snapshot_id = snap.get("snapshot_id")

    # (c) Load reconciled entries.
    entries = read_sotb_index(md_path=mp, index_path=ip)
    md_text = mp.read_text(encoding="utf-8") if mp.exists() else ""

    # (d) Expiry sweep.
    cfg = get_config()
    stale_days = int(cfg.hardening.get("sotb_stale_days", 90))
    _new_md, health = compute_freshness(
        md=md_text, entries=entries, stale_days=stale_days,
    )
    expired_ids = {e.entry_id for e in health.expired}
    expired_count = len(expired_ids)
    surviving = [e for e in entries if e.entry_id not in expired_ids]

    # Group surviving entries by section, preserving insertion order.
    by_section: dict[str, list[SotbEntry]] = {}
    section_order: list[str] = []
    for e in surviving:
        if e.section not in by_section:
            by_section[e.section] = []
            section_order.append(e.section)
        by_section[e.section].append(e)

    # (e) Dedup + (f) supersession. When the judge is gated ON, overlapping
    # pairs are judged: contradictory pairs retire the OLDER entry to Resolved;
    # non-contradictory overlaps are merged (dedup). When the judge is OFF,
    # all overlaps are merged (pure dedup, no LLM calls).
    merged_count = 0
    superseded_count = 0
    judge_enabled = bool(cfg.hardening.get("sotb_judge_enabled", False))
    judge_on = verify and judge_enabled
    model = _judge_model() if judge_on else ""

    deduped_by_section: dict[str, list[SotbEntry]] = {}
    retired: list[SotbEntry] = []
    for section in section_order:
        kept_section: list[SotbEntry] = []
        for entry in by_section[section]:
            overlap = _find_overlapping(entry, kept_section)
            if overlap is None:
                kept_section.append(entry)
                continue
            # `overlap` is the earlier-inserted (older) entry; `entry` is newer.
            if judge_on and section != _RESOLVED_SECTION:
                contradictory, _rationale = await _contradiction_judge(
                    overlap, entry, model=model,
                )
                if contradictory:
                    kept_section.remove(overlap)
                    retired.append(_retire_to_resolved(overlap))
                    kept_section.append(entry)
                    superseded_count += 1
                    continue
            # Non-contradictory (or judge off): merge the near-dup.
            _merge_entries(overlap, entry)
            merged_count += 1
        deduped_by_section[section] = kept_section
    if retired:
        deduped_by_section.setdefault(_RESOLVED_SECTION, []).extend(retired)

    # Flatten survivors, ordering sections by SECTION_DEFAULTS then any extras.
    final_entries: list[SotbEntry] = []
    seen_sections: set[str] = set()
    for section in SECTION_DEFAULTS:
        if section in deduped_by_section:
            final_entries.extend(deduped_by_section[section])
            seen_sections.add(section)
    for section, ents in deduped_by_section.items():
        if section not in seen_sections:
            final_entries.extend(ents)

    # (g) Render + persist.
    new_md = render_md_from_entries(final_entries, existing_md=md_text)
    _atomic_write_text(mp, new_md)
    write_sotb_index(final_entries, path=ip)

    kept = len(final_entries)
    summary = (
        f"Consolidation: {expired_count} expired, {merged_count} merged, "
        f"{superseded_count} superseded, {kept} kept."
    )

    # (h) Audit row.
    try:
        record_consolidation(
            {
                "consolidation_id": uuid.uuid4().hex,
                "venture_id": venture_id,
                "created_at": _now_iso(),
                "session_id": session_id,
                "snapshot_id": snapshot_id,
                "merged": merged_count,
                "superseded": superseded_count,
                "expired": expired_count,
                "kept": kept,
                "summary": summary,
            },
            db_path=db_path,
        )
    except Exception as exc:  # noqa: BLE001 — auditing must not break the pass
        logger.warning("sotb_consolidation: record_consolidation failed: %s", exc)

    return ConsolidationResult(
        venture_id=venture_id,
        snapshot_id=snapshot_id,
        merged=merged_count,
        superseded=superseded_count,
        expired=expired_count,
        kept=kept,
        summary=summary,
    ).to_dict()
