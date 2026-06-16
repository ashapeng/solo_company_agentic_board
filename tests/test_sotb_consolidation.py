"""Tests for SOTB consolidation ("dream-mode") pass."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from server.memory import store
from server.memory.sotb_governance import (
    SotbEntry,
    read_sotb_index,
    write_sotb_index,
)
from server.memory.sotb_consolidation import (
    consolidate_sotb,
    render_md_from_entries,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _past_iso(days: int = 5) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _entry(
    section: str,
    text: str,
    *,
    confidence: float = 0.6,
    created_at: str | None = None,
    updated_at: str | None = None,
    expires_at: str | None = None,
    provenance: dict | None = None,
) -> SotbEntry:
    now = _now_iso()
    return SotbEntry(
        entry_id=SotbEntry.compute_entry_id(section, text),
        section=section,
        text=text,
        created_at=created_at or now,
        updated_at=updated_at or now,
        confidence=confidence,
        expires_at=expires_at,
        provenance=provenance or {"session_id": "s1", "source_member": "manual"},
    )


@pytest.fixture
def mem(tmp_path: Path):
    md_path = tmp_path / "sotb.md"
    index_path = tmp_path / "sotb_index.jsonl"
    db_path = tmp_path / "ledger.db"
    return md_path, index_path, db_path


def _seed(md_path: Path, index_path: Path, entries: list[SotbEntry]) -> None:
    md = render_md_from_entries(entries)
    md_path.write_text(md, encoding="utf-8")
    write_sotb_index(entries, path=index_path)


# --------------------------------------------------------------------------- #
# Rendering / round-trip
# --------------------------------------------------------------------------- #
def test_render_round_trips_via_read_sotb_index(mem):
    md_path, index_path, _db = mem
    entries = [
        _entry("Active Decisions", "Ship the MVP by Q3"),
        _entry("Risk Register", "Vendor lock-in on payments provider"),
        _entry("Established Positions", "We sell to SMBs not enterprise"),
    ]
    md = render_md_from_entries(entries)
    md_path.write_text(md, encoding="utf-8")

    reparsed = read_sotb_index(md_path=md_path, index_path=index_path)
    expected = {(e.section, e.text) for e in entries}
    got = {(e.section, e.text) for e in reparsed}
    assert got == expected


def test_empty_core_section_placeholder_not_a_bullet(mem):
    md_path, _idx, _db = mem
    md = render_md_from_entries([_entry("Active Decisions", "Only one decision")])
    # Every core section heading present; Resolved omitted.
    assert "## Active Decisions" in md
    assert "## Risk Register" in md
    assert "## Resolved" not in md
    # Placeholder lines must not parse as bullets.
    for line in md.splitlines():
        if line.strip() == "_(none)_":
            assert not line.lstrip().startswith(("- ", "* "))


def test_consolidate_idempotent(mem):
    md_path, index_path, db_path = mem
    entries = [
        _entry("Active Decisions", "Ship the MVP by Q3"),
        _entry("Open Questions", "Do we need SOC2 before first enterprise deal"),
    ]
    _seed(md_path, index_path, entries)

    first = asyncio.run(consolidate_sotb(
        md_path=md_path, index_path=index_path, db_path=db_path,
    ))
    assert first["kept"] == 2

    second = asyncio.run(consolidate_sotb(
        md_path=md_path, index_path=index_path, db_path=db_path,
    ))
    assert second["merged"] == 0
    assert second["superseded"] == 0
    assert second["expired"] == 0
    assert second["kept"] == 2


# --------------------------------------------------------------------------- #
# Dedup
# --------------------------------------------------------------------------- #
def test_dedup_merges_near_identical_and_unions_provenance(mem):
    md_path, index_path, db_path = mem
    a = _entry(
        "Active Decisions",
        "Ship the MVP by the end of Q3 this year",
        confidence=0.6,
        created_at="2026-01-01T00:00:00+00:00",
        provenance={"session_id": "sess-A", "source_member": "manual"},
    )
    b = _entry(
        "Active Decisions",
        "Ship the MVP by end of Q3 this year please",
        confidence=0.9,
        created_at="2026-02-01T00:00:00+00:00",
        provenance={"session_id": "sess-B", "source_member": "manual"},
    )
    _seed(md_path, index_path, [a, b])

    res = asyncio.run(consolidate_sotb(
        md_path=md_path, index_path=index_path, db_path=db_path,
    ))
    assert res["merged"] == 1
    assert res["kept"] == 1

    survivors = read_sotb_index(md_path=md_path, index_path=index_path)
    assert len(survivors) == 1
    kept = survivors[0]
    # Higher confidence kept.
    assert kept.confidence == 0.9
    # Earlier created_at kept.
    assert kept.created_at == "2026-01-01T00:00:00+00:00"
    # Provenance union preserved.
    merged_from = kept.provenance.get("merged_from", [])
    assert "sess-A" in merged_from
    assert "sess-B" in merged_from


# --------------------------------------------------------------------------- #
# Expiry
# --------------------------------------------------------------------------- #
def test_expired_entry_dropped(mem):
    md_path, index_path, db_path = mem
    live = _entry("Active Decisions", "Keep building the core product")
    dead = _entry(
        "Risk Register",
        "Temporary supply risk during launch window",
        expires_at=_past_iso(3),
    )
    _seed(md_path, index_path, [live, dead])

    res = asyncio.run(consolidate_sotb(
        md_path=md_path, index_path=index_path, db_path=db_path,
    ))
    assert res["expired"] == 1
    survivors = read_sotb_index(md_path=md_path, index_path=index_path)
    texts = {e.text for e in survivors}
    assert "Keep building the core product" in texts
    assert "Temporary supply risk during launch window" not in texts


# --------------------------------------------------------------------------- #
# Supersession
# --------------------------------------------------------------------------- #
def test_supersession_moves_older_to_resolved(mem, monkeypatch):
    md_path, index_path, db_path = mem
    older = _entry(
        "Established Positions",
        "We will invest in feature X next quarter heavily",
        created_at="2026-01-01T00:00:00+00:00",
    )
    newer = _entry(
        "Established Positions",
        "We will sunset feature X next quarter entirely",
        created_at="2026-03-01T00:00:00+00:00",
    )
    _seed(md_path, index_path, [older, newer])

    # Enable judge flag.
    from server.harness.config import get_config
    get_config().hardening["sotb_judge_enabled"] = True

    # Monkeypatch the underlying LLM call to return CONTRADICTORY.
    import server.memory.sotb_governance as gov

    async def fake_query_llm(model, *, messages, max_tokens=200, **kwargs):
        class _Resp:
            content = '{"verdict": "CONTRADICTORY", "rationale": "opposite plans"}'
        return _Resp()

    monkeypatch.setattr(gov, "query_llm", fake_query_llm)

    try:
        res = asyncio.run(consolidate_sotb(
            verify=True,
            md_path=md_path, index_path=index_path, db_path=db_path,
        ))
    finally:
        get_config().hardening["sotb_judge_enabled"] = False

    assert res["superseded"] == 1
    survivors = read_sotb_index(md_path=md_path, index_path=index_path)
    resolved = [e for e in survivors if e.section == "Resolved"]
    assert len(resolved) == 1
    assert resolved[0].text.startswith("[superseded ")
    assert "invest in feature X" in resolved[0].text
    # Newer entry stays in Established Positions.
    established = {e.text for e in survivors if e.section == "Established Positions"}
    assert "We will sunset feature X next quarter entirely" in established


def test_supersession_skipped_when_flag_off(mem, monkeypatch):
    md_path, index_path, db_path = mem
    older = _entry("Established Positions", "We will invest in feature X next quarter")
    newer = _entry("Established Positions", "We will sunset feature X next quarter")
    _seed(md_path, index_path, [older, newer])

    import server.memory.sotb_governance as gov

    called = {"n": 0}

    async def boom_query_llm(*args, **kwargs):
        called["n"] += 1
        raise AssertionError("judge should not be called when flag off")

    monkeypatch.setattr(gov, "query_llm", boom_query_llm)

    res = asyncio.run(consolidate_sotb(
        verify=True,  # verify on, but flag off → no judge
        md_path=md_path, index_path=index_path, db_path=db_path,
    ))
    assert called["n"] == 0
    assert res["superseded"] == 0


# --------------------------------------------------------------------------- #
# Snapshot
# --------------------------------------------------------------------------- #
def test_consolidation_creates_pre_snapshot(mem):
    md_path, index_path, db_path = mem
    _seed(md_path, index_path, [_entry("Active Decisions", "Build the thing")])

    res = asyncio.run(consolidate_sotb(
        venture_id="default",
        md_path=md_path, index_path=index_path, db_path=db_path,
    ))
    assert res["snapshot_id"]

    snaps = store.list_snapshots(venture_id="default", db_path=db_path)
    reasons = {s["reason"] for s in snaps}
    assert "pre_consolidation" in reasons
    ids = {s["snapshot_id"] for s in snaps}
    assert res["snapshot_id"] in ids
