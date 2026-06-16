"""Tests for SOTB snapshot + rollback (white-box memory foundation)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.memory import sotb_snapshot, store


MD_BODY = "# SOTB\n\n## Active Decisions\n- Ship the MVP by Q3\n"
INDEX_BODY = (
    json.dumps({"entry_id": "abc123", "section": "Active Decisions",
                "text": "Ship the MVP by Q3"})
    + "\n"
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "ledger.db"


def _write_memory(tmp_path: Path, *, name: str = "v",
                  md: str = MD_BODY, index: str = INDEX_BODY) -> tuple[Path, Path]:
    md_path = tmp_path / name / "sotb.md"
    index_path = tmp_path / name / "sotb_index.jsonl"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md, encoding="utf-8")
    index_path.write_text(index, encoding="utf-8")
    return md_path, index_path


def test_capture_then_rollback_restores_exact_content(tmp_path, db_path):
    md_path, index_path = _write_memory(tmp_path)

    cap = sotb_snapshot.capture_snapshot(
        venture_id="default", reason="pre-change",
        md_path=md_path, index_path=index_path, db_path=db_path,
    )
    assert cap["snapshot_id"]

    # Mutate both files on disk.
    md_path.write_text("# SOTB\n\n## Active Decisions\n- TOTALLY DIFFERENT\n",
                       encoding="utf-8")
    index_path.write_text(json.dumps({"entry_id": "zzz", "text": "changed"}) + "\n",
                          encoding="utf-8")

    # Patch path resolution so rollback targets our tmp files.
    def fake_paths(venture_id="default"):
        return md_path, index_path

    import server.memory.sotb_snapshot as mod
    orig = mod.venture_memory_paths
    mod.venture_memory_paths = fake_paths
    try:
        res = sotb_snapshot.rollback_to(cap["snapshot_id"], db_path=db_path)
    finally:
        mod.venture_memory_paths = orig

    assert res["restored"] is True
    assert md_path.read_text(encoding="utf-8") == MD_BODY
    assert index_path.read_text(encoding="utf-8") == INDEX_BODY
    assert res["restored_md_bytes"] == len(MD_BODY)
    assert res["restored_index_rows"] == 1


def test_manual_edits_since_flag(tmp_path, db_path, monkeypatch):
    md_path, index_path = _write_memory(tmp_path)
    monkeypatch.setattr(sotb_snapshot, "venture_memory_paths",
                        lambda venture_id="default": (md_path, index_path))

    # Case A: capture + finalize, then edit md, then rollback -> True.
    cap = sotb_snapshot.capture_snapshot(
        reason="r", md_path=md_path, index_path=index_path, db_path=db_path,
    )
    sotb_snapshot.finalize_snapshot(
        cap["snapshot_id"], md_path=md_path, index_path=index_path, db_path=db_path,
    )
    md_path.write_text(MD_BODY + "- extra edit\n", encoding="utf-8")
    res_a = sotb_snapshot.rollback_to(cap["snapshot_id"], db_path=db_path)
    assert res_a["manual_edits_since"] is True

    # Case B: capture + finalize, no edit -> False.
    cap2 = sotb_snapshot.capture_snapshot(
        reason="r", md_path=md_path, index_path=index_path, db_path=db_path,
    )
    sotb_snapshot.finalize_snapshot(
        cap2["snapshot_id"], md_path=md_path, index_path=index_path, db_path=db_path,
    )
    res_b = sotb_snapshot.rollback_to(cap2["snapshot_id"], db_path=db_path)
    assert res_b["manual_edits_since"] is False


def test_venture_scoping(tmp_path, db_path):
    md_a, idx_a = _write_memory(tmp_path, name="A", md="# A md\n", index="rowA\n")
    md_b, idx_b = _write_memory(tmp_path, name="B", md="# B md\n", index="rowB\n")

    cap = sotb_snapshot.capture_snapshot(
        venture_id="A", reason="r", md_path=md_a, index_path=idx_a, db_path=db_path,
    )

    # Mutate A's files; B must remain untouched by rollback.
    md_a.write_text("# A changed\n", encoding="utf-8")

    def fake_paths(venture_id="default"):
        return (md_a, idx_a) if venture_id == "A" else (md_b, idx_b)

    import server.memory.sotb_snapshot as mod
    monkeypatched = mod.venture_memory_paths
    mod.venture_memory_paths = fake_paths
    try:
        res = sotb_snapshot.rollback_to(cap["snapshot_id"], db_path=db_path)
    finally:
        mod.venture_memory_paths = monkeypatched

    assert res["restored"] is True
    assert res["venture_id"] == "A"
    assert md_a.read_text(encoding="utf-8") == "# A md\n"
    # B untouched.
    assert md_b.read_text(encoding="utf-8") == "# B md\n"
    assert idx_b.read_text(encoding="utf-8") == "rowB\n"


def test_list_omits_blobs_and_filters(tmp_path, db_path):
    md_a, idx_a = _write_memory(tmp_path, name="A")
    md_b, idx_b = _write_memory(tmp_path, name="B")

    cap_a1 = sotb_snapshot.capture_snapshot(
        venture_id="A", reason="a1", md_path=md_a, index_path=idx_a, db_path=db_path)
    cap_a2 = sotb_snapshot.capture_snapshot(
        venture_id="A", reason="a2", md_path=md_a, index_path=idx_a, db_path=db_path)
    sotb_snapshot.capture_snapshot(
        venture_id="B", reason="b1", md_path=md_b, index_path=idx_b, db_path=db_path)

    a_list = sotb_snapshot.list_snapshots(venture_id="A", db_path=db_path)
    assert len(a_list) == 2
    for row in a_list:
        assert row["venture_id"] == "A"
        assert "md_text" not in row
        assert "index_json" not in row
        assert row["has_payload"] is True

    # limit respected
    limited = sotb_snapshot.list_snapshots(venture_id="A", limit=1, db_path=db_path)
    assert len(limited) == 1

    # all ventures
    all_list = sotb_snapshot.list_snapshots(db_path=db_path)
    assert len(all_list) == 3

    # get_snapshot returns blobs
    full = store.get_snapshot(cap_a1["snapshot_id"], db_path=db_path)
    assert full["md_text"] == MD_BODY
    assert full["index_json"] == INDEX_BODY
    # sanity: second capture also retrievable
    assert store.get_snapshot(cap_a2["snapshot_id"], db_path=db_path) is not None


def test_capture_never_raises_when_md_missing(tmp_path, db_path):
    md_path = tmp_path / "missing" / "sotb.md"  # does not exist
    index_path = tmp_path / "missing" / "sotb_index.jsonl"  # does not exist

    cap = sotb_snapshot.capture_snapshot(
        reason="r", md_path=md_path, index_path=index_path, db_path=db_path)
    assert cap["snapshot_id"]

    full = store.get_snapshot(cap["snapshot_id"], db_path=db_path)
    assert full["md_text"] == ""
    assert full["index_json"] == ""


def test_rollback_missing_snapshot(db_path):
    res = sotb_snapshot.rollback_to("does-not-exist", db_path=db_path)
    assert res == {"restored": False, "error": "snapshot not found"}
