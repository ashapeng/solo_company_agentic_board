"""SQLite ledger for eval runs.

Mirrors the pattern in server/harness/ledger.py but lives in its own DB
(`data/eval_runs.db`) so eval runs don't pollute the tuner ledger.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DB_PATH = Path("data/eval_runs.db")

_SCHEMA_RUNS = """
CREATE TABLE IF NOT EXISTS runs (
    run_id           TEXT PRIMARY KEY,
    label            TEXT NOT NULL,
    started_at       TEXT NOT NULL,
    completed_at     TEXT,
    config_version   INTEGER,
    tier             TEXT NOT NULL,
    prompt_count     INTEGER NOT NULL,
    total_passed     INTEGER,
    total_cost_usd   REAL,
    notes            TEXT
);
"""

_SCHEMA_SIGNALS = """
CREATE TABLE IF NOT EXISTS signals (
    signal_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                 TEXT NOT NULL,
    prompt_id              TEXT NOT NULL,
    category               TEXT NOT NULL,
    expected_outcome_json  TEXT NOT NULL,
    observed_signals_json  TEXT NOT NULL,
    passed                 INTEGER NOT NULL,
    latency_ms             INTEGER,
    tokens                 INTEGER,
    cost_usd               REAL,
    raw_session_id         TEXT,
    error                  TEXT,
    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);
"""

_SCHEMA_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_signals_run_id ON signals(run_id);",
    "CREATE INDEX IF NOT EXISTS idx_signals_category ON signals(category);",
    "CREATE INDEX IF NOT EXISTS idx_runs_label ON runs(label);",
)


class LedgerError(Exception):
    """Raised on eval ledger operation failures."""


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db(db_path: Path | None = None) -> None:
    path = db_path or _DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(_SCHEMA_RUNS)
        conn.execute(_SCHEMA_SIGNALS)
        for ddl in _SCHEMA_INDEXES:
            conn.execute(ddl)
        conn.commit()
    finally:
        conn.close()


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or _DEFAULT_DB_PATH
    if not path.exists():
        init_db(path)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def create_run(
    *,
    label: str,
    tier: str,
    config_version: int,
    prompt_count: int,
    notes: str | None = None,
    db_path: Path | None = None,
) -> str:
    run_id = f"eval_{int(datetime.now(timezone.utc).timestamp())}_{uuid.uuid4().hex[:8]}"
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO runs (run_id, label, started_at, config_version, tier, prompt_count, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, label, _utcnow(), config_version, tier, prompt_count, notes),
        )
        conn.commit()
    finally:
        conn.close()
    return run_id


def complete_run(
    run_id: str,
    *,
    total_passed: int,
    total_cost_usd: float,
    db_path: Path | None = None,
) -> None:
    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            "UPDATE runs SET completed_at = ?, total_passed = ?, total_cost_usd = ? WHERE run_id = ?",
            (_utcnow(), total_passed, total_cost_usd, run_id),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise LedgerError(f"unknown run: {run_id}")
    finally:
        conn.close()


def record_signal(
    *,
    run_id: str,
    prompt_id: str,
    category: str,
    expected_outcome: dict[str, Any],
    observed_signals: dict[str, Any],
    passed: bool,
    latency_ms: int,
    tokens: int,
    cost_usd: float,
    raw_session_id: str | None,
    error: str | None,
    db_path: Path | None = None,
) -> None:
    conn = _connect(db_path)
    try:
        run = conn.execute("SELECT 1 FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if run is None:
            raise LedgerError(f"unknown run: {run_id}")
        conn.execute(
            """INSERT INTO signals (
                run_id, prompt_id, category,
                expected_outcome_json, observed_signals_json,
                passed, latency_ms, tokens, cost_usd, raw_session_id, error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id, prompt_id, category,
                json.dumps(expected_outcome, ensure_ascii=False),
                json.dumps(observed_signals, ensure_ascii=False),
                1 if passed else 0,
                latency_ms, tokens, cost_usd, raw_session_id, error,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_run(run_id: str, *, db_path: Path | None = None) -> dict | None:
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_signals_for_run(run_id: str, *, db_path: Path | None = None) -> list[dict]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM signals WHERE run_id = ? ORDER BY signal_id ASC",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def find_run_by_label(label: str, *, db_path: Path | None = None) -> str | None:
    """Return the most-recent run_id for a given label, or None."""
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT run_id FROM runs WHERE label = ? ORDER BY started_at DESC LIMIT 1",
            (label,),
        ).fetchone()
        return row["run_id"] if row else None
    finally:
        conn.close()
