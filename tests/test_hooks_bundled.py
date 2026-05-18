"""Tests for bundled hooks in server.harness.hooks._bundled."""
from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch):
    """Redirect ledger writes/reads to a tmp DB for this test only."""
    from server.harness import ledger as ledger_mod
    db_path = tmp_path / "ledger.db"
    monkeypatch.setattr(ledger_mod, "_DEFAULT_DB_PATH", db_path)
    ledger_mod.init_db(db_path)
    return db_path


@pytest.fixture
def fresh_registry():
    """Snapshot + clear + restore so tests don't collide with bundled hooks."""
    from server.harness.hooks import (
        _snapshot_registry, _restore_registry, _pre_hooks, _post_hooks,
    )
    snapshot = _snapshot_registry()
    _pre_hooks.clear()
    _post_hooks.clear()
    yield
    _restore_registry(snapshot)


# ─── T11: cap_web_search_per_session ──────────────────────────────────────


@pytest.mark.asyncio
async def test_cap_web_search_allows_below_cap(tmp_db, fresh_registry, monkeypatch):
    monkeypatch.setenv("AGENTIC_BOARD_WEB_SEARCH_SESSION_CAP", "3")
    from server.harness.hooks._bundled.cap_web_search_per_session import (
        cap_web_search_per_session,
    )
    from server.harness.hooks import HookContext
    from server.harness.ledger import record_hook_event

    for _ in range(2):
        record_hook_event(
            session_id="s1", tool_name="web_search",
            action="allow", reason=None, metadata={},
        )

    ctx = HookContext("web_search", 1, "s1", "strategist", {"query": "x"})
    verdict = cap_web_search_per_session(ctx)
    assert verdict.action == "allow"
    assert verdict.metadata.get("session_count") == 2
    assert verdict.metadata.get("cap") == 3


@pytest.mark.asyncio
async def test_cap_web_search_denies_at_cap(tmp_db, fresh_registry, monkeypatch):
    monkeypatch.setenv("AGENTIC_BOARD_WEB_SEARCH_SESSION_CAP", "3")
    from server.harness.hooks._bundled.cap_web_search_per_session import (
        cap_web_search_per_session,
    )
    from server.harness.hooks import HookContext
    from server.harness.ledger import record_hook_event

    for _ in range(3):
        record_hook_event(
            session_id="s1", tool_name="web_search",
            action="allow", reason=None, metadata={},
        )

    ctx = HookContext("web_search", 1, "s1", "strategist", {"query": "x"})
    verdict = cap_web_search_per_session(ctx)
    assert verdict.action == "deny"
    assert verdict.reason and "cap" in verdict.reason.lower()
    assert verdict.metadata.get("session_count") == 3
    assert verdict.metadata.get("cap") == 3


@pytest.mark.asyncio
async def test_cap_web_search_isolates_by_session(tmp_db, fresh_registry, monkeypatch):
    monkeypatch.setenv("AGENTIC_BOARD_WEB_SEARCH_SESSION_CAP", "2")
    from server.harness.hooks._bundled.cap_web_search_per_session import (
        cap_web_search_per_session,
    )
    from server.harness.hooks import HookContext
    from server.harness.ledger import record_hook_event

    for _ in range(2):
        record_hook_event(
            session_id="A", tool_name="web_search",
            action="allow", reason=None, metadata={},
        )

    ctx_b = HookContext("web_search", 1, "B", "strategist", {"query": "x"})
    verdict = cap_web_search_per_session(ctx_b)
    assert verdict.action == "allow", "session B's count is independent"


@pytest.mark.asyncio
async def test_cap_web_search_falls_back_to_default_on_bad_env(tmp_db, fresh_registry, monkeypatch):
    monkeypatch.setenv("AGENTIC_BOARD_WEB_SEARCH_SESSION_CAP", "not-a-number")
    from server.harness.hooks._bundled.cap_web_search_per_session import (
        cap_web_search_per_session,
    )
    from server.harness.hooks import HookContext

    ctx = HookContext("web_search", 1, "s1", "strategist", {"query": "x"})
    verdict = cap_web_search_per_session(ctx)
    assert verdict.action == "allow"
    assert verdict.metadata.get("cap") == 20


def test_cap_web_search_registered_at_import():
    """Importing the bundled module registers it for web_search."""
    from server.harness.hooks import _list_pre_hooks_for_tests
    from server.harness.hooks._bundled.cap_web_search_per_session import (
        cap_web_search_per_session,
    )
    assert cap_web_search_per_session in _list_pre_hooks_for_tests("web_search")


# ─── T12: rate_limit_delegated_tasks ──────────────────────────────────────


@pytest.mark.asyncio
async def test_rate_limit_delegated_allows_below_threshold(tmp_db, fresh_registry, monkeypatch):
    monkeypatch.setenv("AGENTIC_BOARD_DELEGATED_TASK_RATE_LIMIT", "3")
    monkeypatch.setenv("AGENTIC_BOARD_DELEGATED_TASK_RATE_WINDOW_SECONDS", "60")
    from server.harness.hooks._bundled.rate_limit_delegated_tasks import (
        rate_limit_delegated_tasks,
    )
    from server.harness.hooks import HookContext
    from server.harness.ledger import record_hook_event

    for _ in range(2):
        record_hook_event(
            session_id="s1", tool_name="delegated_task",
            action="allow", reason=None, metadata={},
        )

    ctx = HookContext("delegated_task", 0, "s1", None, {"task_id": "t"})
    verdict = rate_limit_delegated_tasks(ctx)
    assert verdict.action == "allow"
    assert verdict.metadata.get("window_count") == 2
    assert verdict.metadata.get("limit") == 3


@pytest.mark.asyncio
async def test_rate_limit_delegated_denies_at_threshold(tmp_db, fresh_registry, monkeypatch):
    monkeypatch.setenv("AGENTIC_BOARD_DELEGATED_TASK_RATE_LIMIT", "3")
    monkeypatch.setenv("AGENTIC_BOARD_DELEGATED_TASK_RATE_WINDOW_SECONDS", "60")
    from server.harness.hooks._bundled.rate_limit_delegated_tasks import (
        rate_limit_delegated_tasks,
    )
    from server.harness.hooks import HookContext
    from server.harness.ledger import record_hook_event

    for _ in range(3):
        record_hook_event(
            session_id="s1", tool_name="delegated_task",
            action="allow", reason=None, metadata={},
        )

    ctx = HookContext("delegated_task", 0, "s1", None, {"task_id": "t"})
    verdict = rate_limit_delegated_tasks(ctx)
    assert verdict.action == "deny"
    assert verdict.reason and "rate" in verdict.reason.lower()


@pytest.mark.asyncio
async def test_rate_limit_delegated_old_rows_outside_window_dont_count(tmp_db, fresh_registry, monkeypatch):
    """Rows older than the window do not count toward the limit."""
    import sqlite3
    from datetime import datetime, timedelta, timezone
    monkeypatch.setenv("AGENTIC_BOARD_DELEGATED_TASK_RATE_LIMIT", "3")
    monkeypatch.setenv("AGENTIC_BOARD_DELEGATED_TASK_RATE_WINDOW_SECONDS", "60")
    from server.harness.hooks._bundled.rate_limit_delegated_tasks import (
        rate_limit_delegated_tasks,
    )
    from server.harness.hooks import HookContext
    from server.harness.ledger import record_hook_event

    record_hook_event(
        session_id="s1", tool_name="delegated_task",
        action="allow", reason=None, metadata={},
    )
    old_ts = (datetime.now(timezone.utc) - timedelta(seconds=300)).isoformat()
    conn = sqlite3.connect(str(tmp_db))
    try:
        for _ in range(3):
            conn.execute(
                "INSERT INTO hook_events (session_id, tool_name, action, reason, metadata, ts) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("s1", "delegated_task", "allow", None, "{}", old_ts),
            )
        conn.commit()
    finally:
        conn.close()

    ctx = HookContext("delegated_task", 0, "s1", None, {"task_id": "t"})
    verdict = rate_limit_delegated_tasks(ctx)
    assert verdict.action == "allow"
    assert verdict.metadata.get("window_count") == 1


@pytest.mark.asyncio
async def test_rate_limit_delegated_falls_back_to_defaults_on_bad_env(tmp_db, fresh_registry, monkeypatch):
    monkeypatch.setenv("AGENTIC_BOARD_DELEGATED_TASK_RATE_LIMIT", "garbage")
    monkeypatch.setenv("AGENTIC_BOARD_DELEGATED_TASK_RATE_WINDOW_SECONDS", "garbage")
    from server.harness.hooks._bundled.rate_limit_delegated_tasks import (
        rate_limit_delegated_tasks,
    )
    from server.harness.hooks import HookContext

    ctx = HookContext("delegated_task", 0, "s1", None, {"task_id": "t"})
    verdict = rate_limit_delegated_tasks(ctx)
    assert verdict.action == "allow"
    assert verdict.metadata.get("limit") == 5
    assert verdict.metadata.get("window_seconds") == 60


def test_rate_limit_delegated_registered_at_import():
    from server.harness.hooks import _list_pre_hooks_for_tests
    from server.harness.hooks._bundled.rate_limit_delegated_tasks import (
        rate_limit_delegated_tasks,
    )
    assert rate_limit_delegated_tasks in _list_pre_hooks_for_tests("delegated_task")


# ─── T13: web_search writes hook events ───────────────────────────────────


@pytest.mark.asyncio
async def test_web_search_records_allow_event(tmp_db, fresh_registry, monkeypatch):
    """When no denying hook is registered, web_search runs and writes an allow event."""
    monkeypatch.setenv("AGENTIC_BOARD_WEB_SEARCH_SESSION_CAP", "20")
    from server.execution import evidence as ev
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        old = ev._EVIDENCE_DIR
        ev._EVIDENCE_DIR = Path(tmpdir)
        try:
            from server.execution.web_search import web_search
            await web_search("test query", provider="fake", session_id="s_t13")
        finally:
            ev._EVIDENCE_DIR = old

    import sqlite3
    conn = sqlite3.connect(str(tmp_db))
    try:
        rows = conn.execute(
            "SELECT action, tool_name FROM hook_events WHERE session_id = ? "
            "ORDER BY ts ASC",
            ("s_t13",),
        ).fetchall()
    finally:
        conn.close()
    assert any(r[0] == "allow" and r[1] == "web_search" for r in rows)
