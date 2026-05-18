"""Integration tests for hook gates on server.execution.tasks functions."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch):
    """Redirect both ledger (_DEFAULT_DB_PATH) and tasks DB to a single tmp path."""
    from server.harness import ledger as ledger_mod
    from server.execution import tasks as tasks_mod
    db_path = tmp_path / "ledger.db"
    tasks_db_path = tmp_path / "tasks.db"
    monkeypatch.setattr(ledger_mod, "_DEFAULT_DB_PATH", db_path)
    monkeypatch.setattr(tasks_mod, "DEFAULT_DB_PATH", tasks_db_path)
    return db_path, tasks_db_path


@pytest.fixture
def fresh_registry():
    from server.harness.hooks import _snapshot_registry, _restore_registry
    snapshot = _snapshot_registry()
    yield
    _restore_registry(snapshot)


def _approved_task_payload(task_id: str = "task_t15") -> dict[str, Any]:
    """Minimal approved task payload that plan_delegated_task accepts."""
    return {
        "id": task_id,
        "session_id": "s_t15",
        "title": "Build something",
        "objective": "Do it",
        "execution_unit_id": "engineering",
        "manager_agent_id": "technical_lead",
        "accountable_board_member_id": "architect",
        "priority": "p1",
        "status": "approved",
        "acceptance_criteria": [],
        "dependencies": [],
        "approval_required": False,
        "subtask_plan": None,
        "artifacts": [],
        "source": "board_synthesis",
        "result_summary": "",
        "status_detail": "",
    }


# ─── T15: plan_delegated_task wrap ────────────────────────────────────────


def test_plan_delegated_task_denied_raises_HookDeniedError(tmp_db, fresh_registry):
    ledger_path, tasks_path = tmp_db
    from server.harness.hooks import (
        HookContext, HookVerdict, HookDeniedError, register_pre_hook,
    )
    from server.execution.tasks import plan_delegated_task, save_delegated_task

    save_delegated_task(_approved_task_payload("t15_a"), db_path=tasks_path)

    def denying(ctx: HookContext) -> HookVerdict:
        return HookVerdict("deny", "blocked by test", {"reason_code": "test"})

    register_pre_hook("delegated_task", denying)

    with pytest.raises(HookDeniedError) as excinfo:
        plan_delegated_task(
            "t15_a",
            manager_agent_id="technical_lead",
            db_path=tasks_path,
        )
    assert "blocked by test" in str(excinfo.value)


def test_plan_delegated_task_denied_writes_event_and_does_not_change_state(tmp_db, fresh_registry):
    ledger_path, tasks_path = tmp_db
    from server.harness.hooks import (
        HookVerdict, HookDeniedError, register_pre_hook,
    )
    from server.execution.tasks import (
        plan_delegated_task, save_delegated_task, get_delegated_task,
    )

    save_delegated_task(_approved_task_payload("t15_b"), db_path=tasks_path)

    def denying(ctx):
        return HookVerdict("deny", "no plan today", {})

    register_pre_hook("delegated_task", denying)

    with pytest.raises(HookDeniedError):
        plan_delegated_task(
            "t15_b",
            manager_agent_id="technical_lead",
            db_path=tasks_path,
        )

    task = get_delegated_task("t15_b", db_path=tasks_path)
    assert task["status"] == "approved"
    conn = sqlite3.connect(str(ledger_path))
    try:
        rows = conn.execute(
            "SELECT action, reason FROM hook_events "
            "WHERE tool_name = 'delegated_task' AND session_id = ?",
            ("s_t15",),
        ).fetchall()
    finally:
        conn.close()
    assert ("deny", "no plan today") in rows


def test_plan_delegated_task_allow_completes_normally(tmp_db, fresh_registry):
    ledger_path, tasks_path = tmp_db
    from server.harness.hooks import HookVerdict, register_pre_hook
    from server.execution.tasks import (
        plan_delegated_task, save_delegated_task, get_delegated_task,
    )

    save_delegated_task(_approved_task_payload("t15_c"), db_path=tasks_path)

    def allowing(ctx):
        return HookVerdict("allow", None, {"pre": True})

    register_pre_hook("delegated_task", allowing)

    plan_delegated_task(
        "t15_c",
        manager_agent_id="technical_lead",
        db_path=tasks_path,
    )

    task = get_delegated_task("t15_c", db_path=tasks_path)
    assert task["status"] == "running"
    conn = sqlite3.connect(str(ledger_path))
    try:
        rows = conn.execute(
            "SELECT action FROM hook_events "
            "WHERE tool_name = 'delegated_task' AND session_id = ?",
            ("s_t15",),
        ).fetchall()
    finally:
        conn.close()
    assert any(r[0] == "allow" for r in rows)
