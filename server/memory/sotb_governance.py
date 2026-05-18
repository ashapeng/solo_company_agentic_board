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
from server.harness.config import get_config

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


def _append_entries_to_md(md: str, entries: list[SotbEntry]) -> str:
    """Append new bullets under their `## <Section>` heading. Existing
    content is NEVER mutated (DC2 log-only). When a section heading is
    missing, append it at the end. Skips entries whose bullet already
    appears in `md` (idempotency)."""
    if not entries:
        return md
    # Build a quick lookup of (section, text) tuples already present.
    existing_pairs = set(_parse_markdown_entries(md))

    # Group new entries by section, preserving plan order.
    by_section: dict[str, list[SotbEntry]] = {}
    for e in entries:
        if (e.section, e.text) in existing_pairs:
            continue
        by_section.setdefault(e.section, []).append(e)
    if not by_section:
        return md

    lines = md.splitlines()
    trailing_newline = md.endswith("\n")

    # Map heading name -> index of the heading line, plus index where its
    # section ends (next H2 or EOF).
    heading_idx: dict[str, int] = {}
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("## "):
            name = s[3:].strip().rstrip(":")
            if name in _VALID_SECTIONS and name not in heading_idx:
                heading_idx[name] = i

    def _section_end(start: int) -> int:
        for j in range(start + 1, len(lines)):
            if lines[j].strip().startswith("## "):
                return j
            if lines[j].strip().startswith("# "):
                return j
        return len(lines)

    # Process sections in reverse order of their heading position so
    # inserts don't shift earlier indices.
    section_inserts = sorted(
        ((heading_idx[s], s) for s in by_section if s in heading_idx),
        key=lambda x: -x[0],
    )
    for idx, section in section_inserts:
        end = _section_end(idx)
        # Strip trailing empty lines inside the section.
        insert_at = end
        while insert_at - 1 > idx and lines[insert_at - 1].strip() == "":
            insert_at -= 1
        new_bullets = [f"- {e.text}" for e in by_section[section]]
        lines[insert_at:insert_at] = new_bullets

    # Append sections that don't have an existing heading.
    for section, ents in by_section.items():
        if section in heading_idx:
            continue
        if lines and lines[-1].strip() != "":
            lines.append("")
        lines.append(f"## {section}")
        for e in ents:
            lines.append(f"- {e.text}")

    out = "\n".join(lines)
    if trailing_newline and not out.endswith("\n"):
        out += "\n"
    return out


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


_QUERY_CONFLICT_PROMPT = """\
You are reviewing the State of the Board (SOTB) against a new user query to
flag direct contradictions. A contradiction means the query's stated direction
conflicts with an established SOTB decision/position/risk such that the board
should be aware before answering.

USER QUERY:
{query}

SOTB ENTRIES (entry_id | section | text):
{entries_block}

Return a JSON object EXACTLY like:
{{"conflicts": [{{"entry_id": "<id>", "rationale": "<1 sentence>"}}, ...]}}

If nothing conflicts, return {{"conflicts": []}}. Do not include any other text.
"""


def _format_entries_for_judge(entries: list[SotbEntry], *, max_chars: int = 2000) -> str:
    lines = []
    used = 0
    for e in entries:
        text = e.text[:200]
        line = f"{e.entry_id} | {e.section} | {text}"
        if used + len(line) > max_chars:
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines) if lines else "(none)"


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    """Best-effort: find the first `{...}` JSON object in `raw`. None if
    no parseable object found."""
    if not raw:
        return None
    start = raw.find("{")
    if start == -1:
        return None
    # Greedy from start to last `}`.
    end = raw.rfind("}")
    if end <= start:
        return None
    try:
        return json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return None


async def _detect_query_conflicts(
    *, query: str, entries: list[SotbEntry], model: str,
) -> list[dict]:
    """Return a list of `{"entry_id": str, "rationale": str}` conflict
    records. Never raises — provider errors and malformed JSON both return
    []."""
    if not entries:
        return []
    prompt = _QUERY_CONFLICT_PROMPT.format(
        query=query[:1000],
        entries_block=_format_entries_for_judge(entries),
    )
    try:
        resp = await query_llm(
            model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=400,
        )
    except Exception as exc:
        logger.warning("sotb_governance: query-conflict judge failed: %s", exc)
        return []

    obj = _extract_json_object(resp.content or "")
    if not isinstance(obj, dict):
        return []
    raw_conflicts = obj.get("conflicts")
    if not isinstance(raw_conflicts, list):
        return []
    out: list[dict] = []
    valid_ids = {e.entry_id for e in entries}
    for c in raw_conflicts:
        if not isinstance(c, dict):
            continue
        eid = str(c.get("entry_id", "")).strip()
        rationale = str(c.get("rationale", "")).strip()
        if not eid or eid not in valid_ids:
            continue
        out.append({"entry_id": eid, "rationale": rationale})
    return out


async def read_sotb_governed(
    query: str, *, verify: bool,
    md_path: Path | None = None,
    index_path: Path | None = None,
) -> tuple[str, SotbHealth]:
    """§8.2: read the SOTB markdown plus a `SotbHealth` report.

    `verify=True` is the HEAVY-tier proxy (matches the orchestrator's
    atomized_claims / contradictions gating). The query-conflict LLM judge
    runs only when `verify=True` AND `hardening.sotb_judge_enabled is True`
    (DC6). The non-LLM freshness checks always run.

    Returns `(md, health)`. The markdown has expired entries removed.
    Never raises — provider errors in the judge return empty conflict lists.
    """
    mp = md_path or _SOTB_PATH
    ip = index_path or _INDEX_PATH

    md_text = mp.read_text(encoding="utf-8") if mp.exists() else ""
    entries = read_sotb_index(md_path=mp, index_path=ip)

    cfg = get_config()
    stale_days = int(cfg.hardening.get("sotb_stale_days", 90))
    new_md, health = compute_freshness(md=md_text, entries=entries, stale_days=stale_days)

    judge_enabled = bool(cfg.hardening.get("sotb_judge_enabled", False))
    if verify and judge_enabled and entries:
        model = (
            cfg.hardening.get("sotb_judge_model")
            or cfg.hardening.get("atomizer_model", "qwen/qwen3.6-max-preview")
        )
        health.query_conflicts = await _detect_query_conflicts(
            query=query, entries=entries, model=model,
        )

    return new_md, health


_CONTRADICTION_JUDGE_PROMPT = """\
Two SOTB entries from a board's institutional memory may be in conflict.
Compare them and judge whether they contradict each other.

EXISTING entry (section: {section_a}):
{text_a}

NEW entry (section: {section_b}):
{text_b}

Return a JSON object EXACTLY like:
{{"verdict": "CONTRADICTORY" | "CONSISTENT", "rationale": "<1 sentence>"}}

Do not include any other text.
"""


def _find_overlapping(new_entry: SotbEntry, existing: list[SotbEntry]) -> SotbEntry | None:
    """DC2-cheap overlap heuristic: same section + substring overlap on
    normalized text. Returns the first overlap or None. (A future P4.1 can
    upgrade to embedding similarity.)"""
    new_norm = re.sub(r"\W+", " ", new_entry.text.lower()).strip()
    new_tokens = set(new_norm.split())
    if len(new_tokens) < 3:
        return None
    for e in existing:
        if e.section != new_entry.section:
            continue
        e_norm = re.sub(r"\W+", " ", e.text.lower()).strip()
        e_tokens = set(e_norm.split())
        if not e_tokens:
            continue
        # Use min(|new|, |existing|) as denominator so overlap is symmetric
        # and triggers when either entry is largely contained in the other.
        # (max() denominator under-fires on short existing entries — e.g.
        # 3-token "sunset feature X" vs 6-token "invest in feature X next
        # quarter" with 2 shared tokens gives 0.33 against |new| but 0.67
        # against min, matching the spec test's contradiction expectation.)
        overlap = len(new_tokens & e_tokens) / max(min(len(new_tokens), len(e_tokens)), 1)
        if overlap >= 0.4:  # at least 40% token overlap
            return e
    return None


async def _contradiction_judge(
    existing: SotbEntry, new_entry: SotbEntry, *, model: str,
) -> tuple[bool, str]:
    """Returns `(contradictory: bool, rationale: str)`. Never raises —
    provider errors return `(False, "judge_failed: ...")`."""
    prompt = _CONTRADICTION_JUDGE_PROMPT.format(
        section_a=existing.section, text_a=existing.text[:500],
        section_b=new_entry.section, text_b=new_entry.text[:500],
    )
    try:
        resp = await query_llm(
            model, messages=[{"role": "user", "content": prompt}], max_tokens=200,
        )
    except Exception as exc:
        logger.warning("sotb_governance: contradiction judge failed: %s", exc)
        return False, f"judge_failed: {exc}"

    obj = _extract_json_object(resp.content or "")
    if not isinstance(obj, dict):
        return False, "judge_returned_no_json"
    verdict = str(obj.get("verdict", "")).strip().upper()
    rationale = str(obj.get("rationale", "")).strip()
    return verdict == "CONTRADICTORY", rationale


async def apply_sotb_update_governed(
    *, update_text: str, session_id: str, verify: bool,
    source_member: str = "chairperson",
    md_path: Path | None = None,
    index_path: Path | None = None,
) -> SotbHealth:
    """§8.3 LOG-ONLY mode (per DC2). Parses the chair's update, runs the
    contradiction judge per new entry against any overlapping existing
    entry (when verify AND flag), logs conflicts to
    `SotbHealth.conflicts_logged` and the harness ledger, and appends ALL
    new entries to the index (no supersession in P4).

    Auto-resolve / move-to-Resolved / markdown rewrite is deferred to P4.1.
    Returns a `SotbHealth` with `conflicts_logged` populated.
    """
    health = SotbHealth()
    new_entries = parse_entries_from_update(
        update_text, session_id=session_id, source_member=source_member,
    )
    if not new_entries:
        return health

    mp = md_path or _SOTB_PATH
    ip = index_path or _INDEX_PATH

    existing = read_sotb_index(md_path=mp, index_path=ip)
    cfg = get_config()
    judge_enabled = bool(cfg.hardening.get("sotb_judge_enabled", False))
    judge_model = (
        cfg.hardening.get("sotb_judge_model")
        or cfg.hardening.get("atomizer_model", "qwen/qwen3.6-max-preview")
    )

    if verify and judge_enabled:
        for new_e in new_entries:
            overlap = _find_overlapping(new_e, existing)
            if overlap is None:
                continue
            contradictory, rationale = await _contradiction_judge(
                overlap, new_e, model=judge_model,
            )
            if contradictory:
                health.conflicts_logged.append({
                    "existing_entry_id": overlap.entry_id,
                    "existing_text": overlap.text,
                    "new_entry_id": new_e.entry_id,
                    "new_text": new_e.text,
                    "rationale": rationale,
                    "session_id": session_id,
                    "logged_at": _now_iso(),
                })
                logger.warning(
                    "sotb_governance: conflict logged (P4 log-only mode)",
                    extra={
                        "existing_entry_id": overlap.entry_id,
                        "new_entry_id": new_e.entry_id,
                        "rationale": rationale[:200],
                    },
                )

    # DC2: write all new entries regardless of conflict verdict.
    # Append-only markdown patch so the next read_sotb_index reconcile
    # treats them as canonical (existing content is never mutated; that's
    # the log-only contract).
    md_text = mp.read_text(encoding="utf-8") if mp.exists() else ""
    new_md = _append_entries_to_md(md_text, new_entries)
    if new_md != md_text:
        mp.write_text(new_md, encoding="utf-8")

    write_sotb_index(existing + new_entries, path=ip)
    return health
