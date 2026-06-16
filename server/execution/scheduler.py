"""Bounded always-on scheduler (Plan 3b).

A gate-first, deterministic scheduler that polls for approved delegated tasks
whose dependencies are satisfied and fires them through ``run_task`` — subject
to per-venture daily-budget, cooldown, and global concurrency gates.

Runs are recorded in a small ``task_runs`` table on the shared ledger DB so the
gates can be evaluated from persisted counts. ``tick`` is the single unit of
work; ``run_forever`` is the always-on poll loop the CLI ``--always-on`` calls.

This module imports ``run_task`` from ``server.execution.runner`` and task
helpers from ``server.execution.tasks`` directly. It never modifies them.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from server.harness.config import get_config
from server.ventures.store import get_venture

from .runner import run_task
from .tasks import DEFAULT_DB_PATH, get_delegated_task, list_tasks_by_status

logger = logging.getLogger(__name__)

DAY_SECONDS = 86400

SCHEMA = """
CREATE TABLE IF NOT EXISTS task_runs (
    run_id       TEXT PRIMARY KEY,
    task_id      TEXT NOT NULL,
    venture_id   TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    status       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_task_runs_venture_started
ON task_runs(venture_id, started_at);
"""


@dataclass
class GateDecision:
    allowed: bool
    reason: str


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def record_run_start(task_id: str, venture_id: str, *, db_path: Path | None = None) -> str:
    """Record the start of a run and return its run_id."""
    run_id = uuid.uuid4().hex
    started_at = _utc_now().isoformat()
    conn = _connect(db_path)
    try:
        conn.execute(
            """INSERT INTO task_runs (
                run_id, task_id, venture_id, started_at, finished_at, status
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (run_id, task_id, venture_id, started_at, None, "running"),
        )
        conn.commit()
    finally:
        conn.close()
    return run_id


def record_run_finish(run_id: str, status: str, *, db_path: Path | None = None) -> None:
    """Mark a run as finished with the given terminal status."""
    finished_at = _utc_now().isoformat()
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE task_runs SET finished_at = ?, status = ? WHERE run_id = ?",
            (finished_at, status, run_id),
        )
        conn.commit()
    finally:
        conn.close()


def _runs_in_window(
    venture_id: str,
    window_seconds: int,
    *,
    now: datetime | None = None,
    db_path: Path | None = None,
) -> int:
    cutoff = (now or _utc_now()).timestamp() - window_seconds
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT started_at FROM task_runs WHERE venture_id = ?",
            (venture_id,),
        ).fetchall()
    finally:
        conn.close()
    return sum(1 for row in rows if _parse_dt(row["started_at"]).timestamp() >= cutoff)


def _last_run_at(venture_id: str, *, db_path: Path | None = None) -> str | None:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT started_at FROM task_runs WHERE venture_id = ? "
            "ORDER BY started_at DESC LIMIT 1",
            (venture_id,),
        ).fetchone()
    finally:
        conn.close()
    return row["started_at"] if row else None


def _active_run_count(*, db_path: Path | None = None) -> int:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM task_runs "
            "WHERE status = 'running' AND finished_at IS NULL",
        ).fetchone()
    finally:
        conn.close()
    return int(row["n"])


def evaluate_gates(
    *,
    venture_id: str,
    config_execution: dict[str, Any],
    now: datetime | None = None,
    db_path: Path | None = None,
) -> GateDecision:
    """Evaluate the firing gates for a venture. First-to-block wins."""
    now = now or _utc_now()

    if not config_execution.get("always_on_enabled"):
        return GateDecision(False, "feature_disabled")

    venture = get_venture(venture_id, db_path=db_path)
    if venture is not None and venture.get("status") == "archived":
        return GateDecision(False, "venture_archived")

    daily_budget = int(config_execution.get("daily_budget_per_venture", 0))
    if _runs_in_window(venture_id, DAY_SECONDS, now=now, db_path=db_path) >= daily_budget:
        return GateDecision(False, "daily_budget_reached")

    cooldown_seconds = int(config_execution.get("cooldown_seconds", 0))
    last_run = _last_run_at(venture_id, db_path=db_path)
    if last_run is not None:
        elapsed = (now - _parse_dt(last_run)).total_seconds()
        if elapsed < cooldown_seconds:
            return GateDecision(False, "cooldown")

    max_concurrent = int(config_execution.get("max_concurrent_runs", 0))
    if _active_run_count(db_path=db_path) >= max_concurrent:
        return GateDecision(False, "max_concurrent")

    return GateDecision(True, "ok")


def _dependencies_satisfied(task: dict[str, Any], *, db_path: Path | None = None) -> bool:
    for dep_id in task.get("dependencies") or []:
        dep = get_delegated_task(str(dep_id), db_path=db_path)
        if not dep or dep.get("status") != "completed":
            return False
    return True


async def tick(*, now: datetime | None = None, db_path: Path | None = None) -> list[dict[str, Any]]:
    """Run one scheduler pass. Fire eligible approved tasks subject to gates."""
    now = now or _utc_now()
    config_execution = dict(get_config().execution)
    max_concurrent = int(config_execution.get("max_concurrent_runs", 0))

    results: list[dict[str, Any]] = []
    fired_this_tick = 0

    eligible = list_tasks_by_status("approved", db_path=db_path)
    for task in eligible:
        task_id = str(task.get("id"))
        venture_id = str(task.get("venture_id") or "default")

        if not _dependencies_satisfied(task, db_path=db_path):
            results.append({
                "task_id": task_id,
                "venture_id": venture_id,
                "fired": False,
                "reason": "dependencies_unsatisfied",
                "result_status": None,
            })
            continue

        if fired_this_tick >= max_concurrent:
            results.append({
                "task_id": task_id,
                "venture_id": venture_id,
                "fired": False,
                "reason": "max_concurrent",
                "result_status": None,
            })
            continue

        decision = evaluate_gates(
            venture_id=venture_id,
            config_execution=config_execution,
            now=now,
            db_path=db_path,
        )
        if not decision.allowed:
            results.append({
                "task_id": task_id,
                "venture_id": venture_id,
                "fired": False,
                "reason": decision.reason,
                "result_status": None,
            })
            continue

        run_id = record_run_start(task_id, venture_id, db_path=db_path)
        result_status: Any = None
        try:
            result = await run_task(task_id, db_path=db_path)
            result_status = result.get("status") if isinstance(result, dict) else None
        except Exception as exc:  # noqa: BLE001
            logger.exception("run_task failed for %s: %s", task_id, exc)
            result_status = "error"
        finally:
            record_run_finish(run_id, str(result_status or "error"), db_path=db_path)

        fired_this_tick += 1
        results.append({
            "task_id": task_id,
            "venture_id": venture_id,
            "fired": True,
            "reason": "ok",
            "result_status": result_status,
        })

    return results


async def run_forever(
    *,
    interval_seconds: int | None = None,
    db_path: Path | None = None,
) -> None:
    """Always-on poll loop. Calls tick() each cycle; never dies on errors."""
    while True:
        try:
            await tick(db_path=db_path)
        except Exception as exc:  # noqa: BLE001
            logger.exception("scheduler tick failed: %s", exc)
        sleep_for = interval_seconds
        if sleep_for is None:
            sleep_for = int(get_config().execution.get("poll_interval_seconds", 300))
        await asyncio.sleep(sleep_for)
