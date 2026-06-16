"""Venture scoping (`venture_id`) for the three SQLite schema owners.

Covers additive, back-compatible `venture_id` columns in:
  - server.harness.ledger (session_outcomes)
  - server.execution.tasks (delegated_tasks)
  - server.initiatives.store (initiatives)

All defaults are `'default'` so legacy/untagged rows are unaffected.
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest


def _make_session_stub(session_id: str, *, venture_id=None):
    """Minimal-shape session that `record_session` reads."""
    from server.board.metrics import SessionMetrics

    kwargs = dict(
        session_id=session_id,
        classification={"query_type": "strategy", "complexity": "standard"},
        verification={},
        memory={},
        metrics=SessionMetrics(),
        stage1_responses=[],
        stage2_responses=[],
        delegation_plan={},
        clarification={},
        skills={"used": {}, "missing": {}},
    )
    if venture_id is not None:
        kwargs["venture_id"] = venture_id
    return SimpleNamespace(**kwargs)


# --------------------------------------------------------------------------
# A) ledger.py — session_outcomes
# --------------------------------------------------------------------------

def test_ledger_records_venture_id_and_filters(tmp_path):
    from server.harness.ledger import query_outcomes, record_session

    db = tmp_path / "ledger.db"
    record_session(_make_session_stub("s-acme", venture_id="acme"), config_version=1, db_path=db)
    record_session(_make_session_stub("s-beta", venture_id="beta"), config_version=1, db_path=db)

    acme = query_outcomes(venture_id="acme", db_path=db)
    assert [r["session_id"] for r in acme] == ["s-acme"]
    assert acme[0]["venture_id"] == "acme"

    beta = query_outcomes(venture_id="beta", db_path=db)
    assert [r["session_id"] for r in beta] == ["s-beta"]

    # No filter returns all rows (back-compat).
    assert {r["session_id"] for r in query_outcomes(db_path=db)} == {"s-acme", "s-beta"}


def test_ledger_legacy_session_defaults_to_default(tmp_path):
    from server.harness.ledger import query_outcomes, record_session

    db = tmp_path / "ledger.db"
    # Session object exposes no venture_id attribute at all.
    record_session(_make_session_stub("s-legacy"), config_version=1, db_path=db)

    rows = query_outcomes(venture_id="default", db_path=db)
    assert [r["session_id"] for r in rows] == ["s-legacy"]
    assert rows[0]["venture_id"] == "default"


def test_ledger_fresh_db_has_venture_id_column(tmp_path):
    from server.harness.ledger import init_db

    db = tmp_path / "ledger.db"
    init_db(db)
    conn = sqlite3.connect(str(db))
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(session_outcomes)")}
    finally:
        conn.close()
    assert "venture_id" in cols


# --------------------------------------------------------------------------
# B) tasks.py — delegated_tasks
# --------------------------------------------------------------------------

def _task(task_id: str, session_id: str, *, venture_id=None):
    task = {
        "id": task_id,
        "session_id": session_id,
        "title": "Do a thing",
        "objective": "Accomplish the thing",
        "execution_unit_id": "engineering",
        "manager_agent_id": "engineering_manager",
        "status": "proposed",
    }
    if venture_id is not None:
        task["venture_id"] = venture_id
    return task


def test_task_roundtrips_venture_id_and_filters(tmp_path):
    from server.execution.tasks import get_delegation_plan, save_delegated_task

    db = tmp_path / "tasks.db"
    save_delegated_task(_task("t-acme", "sess-1", venture_id="acme"), db_path=db)
    save_delegated_task(_task("t-beta", "sess-1", venture_id="beta"), db_path=db)

    acme = get_delegation_plan("sess-1", venture_id="acme", db_path=db)
    assert [t["id"] for t in acme["tasks"]] == ["t-acme"]
    assert acme["tasks"][0]["venture_id"] == "acme"

    beta = get_delegation_plan("sess-1", venture_id="beta", db_path=db)
    assert [t["id"] for t in beta["tasks"]] == ["t-beta"]

    # No venture filter -> all tasks for the session (back-compat).
    both = get_delegation_plan("sess-1", db_path=db)
    assert {t["id"] for t in both["tasks"]} == {"t-acme", "t-beta"}


def test_task_legacy_defaults_to_default(tmp_path):
    from server.execution.tasks import get_delegation_plan, save_delegated_task

    db = tmp_path / "tasks.db"
    # No venture_id supplied on the payload.
    saved = save_delegated_task(_task("t-legacy", "sess-2"), db_path=db)
    assert saved["venture_id"] == "default"

    plan = get_delegation_plan("sess-2", venture_id="default", db_path=db)
    assert [t["id"] for t in plan["tasks"]] == ["t-legacy"]


def test_task_legacy_db_migrates(tmp_path):
    """A delegated_tasks table created without venture_id gets the column added."""
    from server.execution.tasks import get_delegation_plan, save_delegated_task

    db = tmp_path / "tasks.db"
    legacy_schema = """
    CREATE TABLE delegated_tasks (
        task_id            TEXT PRIMARY KEY,
        session_id         TEXT NOT NULL,
        manager_agent_id   TEXT NOT NULL,
        execution_unit_id  TEXT NOT NULL,
        status             TEXT NOT NULL,
        payload            TEXT NOT NULL,
        created_at         TEXT NOT NULL,
        updated_at         TEXT NOT NULL
    );
    """
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(legacy_schema)
        conn.commit()
    finally:
        conn.close()

    # save_delegated_task -> _connect_tasks must migrate the missing column.
    save_delegated_task(_task("t-mig", "sess-3", venture_id="acme"), db_path=db)
    plan = get_delegation_plan("sess-3", venture_id="acme", db_path=db)
    assert [t["id"] for t in plan["tasks"]] == ["t-mig"]


# --------------------------------------------------------------------------
# C) initiatives/store.py — initiatives
# --------------------------------------------------------------------------

def test_initiative_venture_scoping(tmp_path):
    from server.initiatives.store import create_initiative, list_initiatives

    db = tmp_path / "init.db"
    acme = create_initiative(
        title="Acme launch", objective="Ship it", venture_id="acme", db_path=db,
    )
    create_initiative(
        title="Beta launch", objective="Ship it too", venture_id="beta", db_path=db,
    )

    assert acme["venture_id"] == "acme"

    acme_rows = list_initiatives(venture_id="acme", db_path=db)
    assert [r["id"] for r in acme_rows] == [acme["id"]]
    assert acme_rows[0]["venture_id"] == "acme"

    # A different venture excludes the acme initiative.
    beta_rows = list_initiatives(venture_id="beta", db_path=db)
    assert acme["id"] not in {r["id"] for r in beta_rows}

    # No filter returns both (back-compat).
    assert len(list_initiatives(db_path=db)) == 2


def test_initiative_legacy_defaults_to_default(tmp_path):
    from server.initiatives.store import create_initiative, list_initiatives

    db = tmp_path / "init.db"
    created = create_initiative(title="Legacy", objective="No venture", db_path=db)
    assert created["venture_id"] == "default"

    rows = list_initiatives(venture_id="default", db_path=db)
    assert [r["id"] for r in rows] == [created["id"]]


def test_initiative_legacy_db_migrates(tmp_path):
    """An initiatives table without venture_id gets the column on connect."""
    from server.initiatives.store import create_initiative, list_initiatives

    db = tmp_path / "init.db"
    legacy_schema = """
    CREATE TABLE initiatives (
        initiative_id    TEXT PRIMARY KEY,
        title            TEXT NOT NULL,
        objective        TEXT NOT NULL,
        status           TEXT NOT NULL,
        approval_state   TEXT NOT NULL,
        created_from     TEXT NOT NULL,
        success_criteria TEXT NOT NULL,
        departments      TEXT NOT NULL,
        timebox_start    TEXT NOT NULL,
        timebox_end      TEXT NOT NULL,
        created_at       TEXT NOT NULL,
        updated_at       TEXT NOT NULL
    );
    """
    conn = sqlite3.connect(str(db))
    try:
        conn.executescript(legacy_schema)
        conn.commit()
    finally:
        conn.close()

    created = create_initiative(
        title="Migrated", objective="Has venture", venture_id="acme", db_path=db,
    )
    assert created["venture_id"] == "acme"
    rows = list_initiatives(venture_id="acme", db_path=db)
    assert [r["id"] for r in rows] == [created["id"]]
