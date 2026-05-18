"""Unit tests for hook_events table + helpers in server.harness.ledger."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Fresh sqlite path per test; ledger init_db creates schema on demand."""
    return tmp_path / "ledger.db"


def test_record_hook_event_creates_table_idempotently(tmp_db):
    from server.harness.ledger import record_hook_event

    record_hook_event(
        session_id="s1",
        tool_name="web_search",
        action="allow",
        reason=None,
        metadata={"k": "v"},
        db_path=tmp_db,
    )
    conn = sqlite3.connect(str(tmp_db))
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(hook_events)").fetchall()]
    finally:
        conn.close()
    assert set(cols) >= {"session_id", "tool_name", "action", "reason", "metadata", "ts"}


def test_record_hook_event_persists_fields_with_json_metadata(tmp_db):
    from server.harness.ledger import record_hook_event

    record_hook_event(
        session_id="s1",
        tool_name="web_search",
        action="deny",
        reason="cap exceeded",
        metadata={"count": 21, "cap": 20},
        db_path=tmp_db,
    )
    conn = sqlite3.connect(str(tmp_db))
    try:
        row = conn.execute(
            "SELECT session_id, tool_name, action, reason, metadata, ts "
            "FROM hook_events WHERE session_id = ?",
            ("s1",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    sid, tn, action, reason, metadata_raw, ts = row
    assert sid == "s1"
    assert tn == "web_search"
    assert action == "deny"
    assert reason == "cap exceeded"
    assert json.loads(metadata_raw) == {"count": 21, "cap": 20}
    parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None


def test_record_hook_event_allows_none_reason(tmp_db):
    from server.harness.ledger import record_hook_event

    record_hook_event(
        session_id="s1",
        tool_name="web_search",
        action="allow",
        reason=None,
        metadata={},
        db_path=tmp_db,
    )
    conn = sqlite3.connect(str(tmp_db))
    try:
        row = conn.execute(
            "SELECT reason FROM hook_events WHERE session_id = ?",
            ("s1",),
        ).fetchone()
    finally:
        conn.close()
    assert row[0] is None


def test_count_in_window_returns_zero_when_no_rows(tmp_db):
    from server.harness.ledger import _count_in_window, record_hook_event

    record_hook_event(
        session_id="other_sess",
        tool_name="web_search",
        action="allow",
        reason=None,
        metadata={},
        db_path=tmp_db,
    )
    count = _count_in_window(
        session_id="s1",
        tool_name="web_search",
        window_seconds=60,
        db_path=tmp_db,
    )
    assert count == 0


def test_count_in_window_counts_only_matching_session_and_tool(tmp_db):
    from server.harness.ledger import _count_in_window, record_hook_event

    for _ in range(3):
        record_hook_event(
            session_id="s1", tool_name="web_search",
            action="allow", reason=None, metadata={}, db_path=tmp_db,
        )
    record_hook_event(
        session_id="s2", tool_name="web_search",
        action="allow", reason=None, metadata={}, db_path=tmp_db,
    )
    record_hook_event(
        session_id="s1", tool_name="delegated_task",
        action="allow", reason=None, metadata={}, db_path=tmp_db,
    )

    assert _count_in_window(
        session_id="s1", tool_name="web_search",
        window_seconds=3600, db_path=tmp_db,
    ) == 3


def test_count_in_window_respects_window_seconds(tmp_db):
    """Old rows outside the window do not count."""
    from server.harness.ledger import _count_in_window, record_hook_event

    # First call initializes the db schema
    record_hook_event(
        session_id="s1", tool_name="web_search",
        action="allow", reason=None, metadata={}, db_path=tmp_db,
    )

    # Now manually insert an old row
    conn = sqlite3.connect(str(tmp_db))
    try:
        old_ts = (datetime.now(timezone.utc) - timedelta(seconds=7200)).isoformat()
        conn.execute(
            "INSERT INTO hook_events (session_id, tool_name, action, reason, metadata, ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("s1", "web_search", "allow", None, "{}", old_ts),
        )
        conn.commit()
    finally:
        conn.close()

    count = _count_in_window(
        session_id="s1", tool_name="web_search",
        window_seconds=60, db_path=tmp_db,
    )
    assert count == 1
