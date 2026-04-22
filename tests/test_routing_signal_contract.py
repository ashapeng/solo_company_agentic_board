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
