"""Contract tests for routing signal capture (Phase A-lite)."""

import json
import sqlite3
from pathlib import Path

import pytest

from server.harness import ledger


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "routing_ledger.db"


def test_routing_misses_column_is_created(tmp_db: Path) -> None:
    """init_db must create the routing_misses TEXT column with '[]' default."""
    ledger.init_db(tmp_db)

    conn = sqlite3.connect(str(tmp_db))
    try:
        columns = {row[1]: row for row in conn.execute("PRAGMA table_info(session_outcomes)").fetchall()}
    finally:
        conn.close()

    assert "routing_misses" in columns
    # PRAGMA row: (cid, name, type, notnull, dflt_value, pk)
    assert columns["routing_misses"][2] == "TEXT"


def test_ensure_columns_is_idempotent_for_routing_misses(tmp_db: Path) -> None:
    """Calling init_db twice must not error and must not duplicate the column."""
    ledger.init_db(tmp_db)
    ledger.init_db(tmp_db)  # second call — no error

    conn = sqlite3.connect(str(tmp_db))
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(session_outcomes)").fetchall()]
    finally:
        conn.close()

    assert cols.count("routing_misses") == 1


def test_record_routing_signal_appends_entry(tmp_db: Path, monkeypatch) -> None:
    """record_routing_signal appends to routing_misses JSON array."""
    ledger.init_db(tmp_db)

    # Seed a session row so the UPDATE has a target
    conn = sqlite3.connect(str(tmp_db))
    try:
        conn.execute(
            "INSERT INTO session_outcomes (session_id, timestamp) VALUES (?, ?)",
            ("board_1", "2026-04-21T14:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()

    ledger.record_routing_signal(
        "board_1",
        "critic",
        "missing_voice_flag",
        db_path=tmp_db,
    )

    conn = sqlite3.connect(str(tmp_db))
    try:
        row = conn.execute(
            "SELECT routing_misses FROM session_outcomes WHERE session_id = ?",
            ("board_1",),
        ).fetchone()
    finally:
        conn.close()

    parsed = json.loads(row[0])
    assert len(parsed) == 1
    entry = parsed[0]
    assert entry["member_id"] == "critic"
    assert entry["source"] == "missing_voice_flag"
    assert "ts" in entry and entry["ts"].endswith("Z")


def test_record_routing_signal_preserves_existing_entries(tmp_db: Path) -> None:
    """Multiple calls for the same session must append, not overwrite."""
    ledger.init_db(tmp_db)
    conn = sqlite3.connect(str(tmp_db))
    try:
        conn.execute(
            "INSERT INTO session_outcomes (session_id, timestamp, routing_misses) VALUES (?, ?, ?)",
            ("board_2", "2026-04-21T14:00:00Z", "[]"),
        )
        conn.commit()
    finally:
        conn.close()

    ledger.record_routing_signal("board_2", "architect", "manual_add", db_path=tmp_db)
    ledger.record_routing_signal("board_2", "critic", "missing_voice_flag", db_path=tmp_db)

    conn = sqlite3.connect(str(tmp_db))
    try:
        row = conn.execute(
            "SELECT routing_misses FROM session_outcomes WHERE session_id = ?",
            ("board_2",),
        ).fetchone()
    finally:
        conn.close()

    parsed = json.loads(row[0])
    assert len(parsed) == 2
    assert parsed[0]["member_id"] == "architect"
    assert parsed[1]["member_id"] == "critic"


def test_record_routing_signal_raises_on_missing_session(tmp_db: Path) -> None:
    """Unknown session_id must raise LedgerError."""
    ledger.init_db(tmp_db)

    with pytest.raises(ledger.LedgerError):
        ledger.record_routing_signal("board_nope", "critic", "manual_add", db_path=tmp_db)


def test_record_routing_signal_handles_null_column(tmp_db: Path) -> None:
    """Rows created before the column existed have NULL routing_misses; function must treat as empty."""
    ledger.init_db(tmp_db)
    conn = sqlite3.connect(str(tmp_db))
    try:
        # Simulate an existing pre-migration row by explicitly setting NULL
        conn.execute(
            "INSERT INTO session_outcomes (session_id, timestamp, routing_misses) VALUES (?, ?, NULL)",
            ("board_legacy", "2026-04-20T10:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()

    ledger.record_routing_signal("board_legacy", "critic", "manual_add", db_path=tmp_db)

    conn = sqlite3.connect(str(tmp_db))
    try:
        row = conn.execute(
            "SELECT routing_misses FROM session_outcomes WHERE session_id = ?",
            ("board_legacy",),
        ).fetchone()
    finally:
        conn.close()

    parsed = json.loads(row[0])
    assert len(parsed) == 1
