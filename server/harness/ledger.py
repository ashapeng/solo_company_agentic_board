"""Append-only SQLite ledger recording structured session outcomes."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_DEFAULT_DB_PATH = Path("data/harness_ledger.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_outcomes (
    session_id            TEXT PRIMARY KEY,
    timestamp             TEXT NOT NULL,
    query_type            TEXT,
    complexity            TEXT,
    members_routed        TEXT,
    members_responded     TEXT,
    member_failures       TEXT,
    models_used           TEXT,
    stage1_tokens         INTEGER,
    stage2_tokens         INTEGER,
    stage3_tokens         INTEGER,
    stage1_latency        REAL,
    stage2_latency        REAL,
    stage3_latency        REAL,
    verification_score    INTEGER,
    verification_passed   INTEGER,
    revision_needed       INTEGER,
    total_cost_usd        REAL,
    sotb_update_proposed  INTEGER,
    sotb_update_approved  INTEGER,
    feedback_rating       TEXT,
    feedback_note         TEXT,
    parse_warnings        TEXT,
    structured_output_failed INTEGER,
    truncation_detected   INTEGER,
    blank_member_responses TEXT,
    clarification_questions_count INTEGER,
    clarification_answers_count INTEGER,
    delegation_task_count INTEGER,
    harness_config_version INTEGER
);
"""

_NUMERIC_COLUMNS = {
    "stage1_tokens", "stage2_tokens", "stage3_tokens",
    "stage1_latency", "stage2_latency", "stage3_latency",
    "verification_score", "total_cost_usd",
}
_VALID_GROUP_COLUMNS = {"query_type", "complexity"}


class LedgerError(Exception):
    """Raised on ledger operation failures."""
    pass


def init_db(db_path: Path | None = None) -> None:
    """Create database and schema if missing."""
    path = db_path or _DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute(_SCHEMA)
        _ensure_columns(conn)
        conn.commit()
    finally:
        conn.close()


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or _DEFAULT_DB_PATH
    if not path.exists():
        init_db(path)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    _ensure_columns(conn)
    return conn


def record_session(session: Any, config_version: int, db_path: Path | None = None) -> None:
    """Extract fields from BoardSession and insert a ledger row."""
    classification = session.classification or {}
    verification = session.verification or {}
    memory = session.memory or {}
    metrics = session.metrics

    # Compute per-stage tokens and latency
    stage_tokens = {}
    stage_latency = {}
    for stage in (1, 2, 3):
        calls = metrics.by_stage(stage)
        stage_tokens[stage] = sum(max(c.input_tokens, 0) + max(c.output_tokens, 0) for c in calls)
        stage_latency[stage] = round(sum(c.latency_seconds for c in calls), 2)

    # Members routed vs responded
    members_routed = classification.get("relevant_member_ids", [])
    members_responded = [r.member_id for r in session.stage1_responses]

    # Compute failures as routed minus responded
    responded_set = set(members_responded)
    failures = [mid for mid in members_routed if mid not in responded_set]

    # Models used
    models_used = {}
    for resp in session.stage1_responses:
        models_used[resp.member_id] = resp.model

    # Verification fields
    v_score = verification.get("score") if verification else None
    v_passed = verification.get("passed") if verification else None
    if v_passed is not None:
        v_passed = 1 if v_passed else 0

    # Revision needed: verification existed and didn't pass on first try
    revision_needed = 0
    if verification and not verification.get("passed", True):
        revision_needed = 1

    # SOTB
    sotb_proposed = 1 if memory.get("proposed_sotb_update") else 0
    delegation_plan = session.delegation_plan or {}
    parse_warnings = delegation_plan.get("warnings", []) if isinstance(delegation_plan, dict) else []
    structured_output_failed = 1 if (
        isinstance(delegation_plan, dict) and delegation_plan.get("structured_output_failed")
    ) else 0
    truncation_detected = 1 if (
        isinstance(delegation_plan, dict) and delegation_plan.get("truncated")
    ) else 0
    blank_member_responses = [
        response.member_id
        for response in [*session.stage1_responses, *session.stage2_responses]
        if not str(response.content or "").strip()
    ]
    clarification = getattr(session, "clarification", {}) or {}
    clarification_questions = clarification.get("questions") or []
    clarification_answers = clarification.get("answers") or {}
    if isinstance(clarification_answers, dict):
        answers_count = len([value for value in clarification_answers.values() if str(value).strip()])
    elif clarification_answers:
        answers_count = 1
    else:
        answers_count = 0
    delegation_tasks = delegation_plan.get("tasks", []) if isinstance(delegation_plan, dict) else []

    conn = _connect(db_path)
    try:
        conn.execute(
            """INSERT INTO session_outcomes (
                session_id, timestamp, query_type, complexity,
                members_routed, members_responded, member_failures,
                models_used,
                stage1_tokens, stage2_tokens, stage3_tokens,
                stage1_latency, stage2_latency, stage3_latency,
                verification_score, verification_passed, revision_needed,
                total_cost_usd,
                sotb_update_proposed, sotb_update_approved,
                feedback_rating, feedback_note,
                parse_warnings, structured_output_failed,
                truncation_detected, blank_member_responses,
                clarification_questions_count, clarification_answers_count,
                delegation_task_count,
                harness_config_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session.session_id,
                datetime.now(timezone.utc).isoformat(),
                classification.get("query_type"),
                classification.get("complexity"),
                json.dumps(members_routed),
                json.dumps(members_responded),
                json.dumps([{"member_id": mid} for mid in failures]),
                json.dumps(models_used),
                stage_tokens.get(1, 0),
                stage_tokens.get(2, 0),
                stage_tokens.get(3, 0),
                stage_latency.get(1, 0.0),
                stage_latency.get(2, 0.0),
                stage_latency.get(3, 0.0),
                v_score,
                v_passed,
                revision_needed,
                metrics.total_cost_estimate(),
                sotb_proposed,
                None,
                None,
                None,
                json.dumps(parse_warnings),
                structured_output_failed,
                truncation_detected,
                json.dumps(blank_member_responses),
                len(clarification_questions),
                answers_count,
                len(delegation_tasks) if isinstance(delegation_tasks, list) else 0,
                config_version,
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError as e:
        raise LedgerError(f"Duplicate session_id: {session.session_id}") from e
    finally:
        conn.close()


def record_feedback(
    session_id: str, rating: str, note: str | None = None, db_path: Path | None = None,
) -> None:
    """Update feedback columns for an existing session."""
    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            "UPDATE session_outcomes SET feedback_rating = ?, feedback_note = ? WHERE session_id = ?",
            (rating, note, session_id),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise LedgerError(f"Session not found: {session_id}")
    finally:
        conn.close()


def _ensure_columns(conn: sqlite3.Connection) -> None:
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(session_outcomes)").fetchall()
    }
    additions = {
        "parse_warnings": "TEXT",
        "structured_output_failed": "INTEGER",
        "truncation_detected": "INTEGER",
        "blank_member_responses": "TEXT",
        "clarification_questions_count": "INTEGER",
        "clarification_answers_count": "INTEGER",
        "delegation_task_count": "INTEGER",
    }
    for column, column_type in additions.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE session_outcomes ADD COLUMN {column} {column_type}")


def query_outcomes(
    *,
    query_type: str | None = None,
    complexity: str | None = None,
    since: str | None = None,
    limit: int | None = None,
    db_path: Path | None = None,
) -> list[dict]:
    """Query session outcomes with optional filters."""
    conn = _connect(db_path)
    try:
        sql = "SELECT * FROM session_outcomes WHERE 1=1"
        params: list = []

        if query_type is not None:
            sql += " AND query_type = ?"
            params.append(query_type)
        if complexity is not None:
            sql += " AND complexity = ?"
            params.append(complexity)
        if since is not None:
            sql += " AND timestamp >= ?"
            params.append(since)

        sql += " ORDER BY timestamp DESC"

        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)

        cursor = conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def aggregate(
    field: str,
    group_by: str,
    *,
    query_type: str | None = None,
    complexity: str | None = None,
    since: str | None = None,
    limit: int | None = None,
    db_path: Path | None = None,
) -> dict[str, float]:
    """Grouped average aggregation for tuner consumption."""
    if field not in _NUMERIC_COLUMNS:
        raise LedgerError(f"Cannot aggregate non-numeric field: {field}")
    if group_by not in _VALID_GROUP_COLUMNS:
        raise LedgerError(f"Cannot group by: {group_by}")

    conn = _connect(db_path)
    try:
        # field and group_by are constrained to allowlists above; values stay parameterized.
        sql = f"SELECT {group_by}, AVG({field}) as avg_val FROM session_outcomes WHERE 1=1"  # nosec B608
        params: list = []

        if query_type is not None:
            sql += " AND query_type = ?"
            params.append(query_type)
        if complexity is not None:
            sql += " AND complexity = ?"
            params.append(complexity)
        if since is not None:
            sql += " AND timestamp >= ?"
            params.append(since)

        sql += f" GROUP BY {group_by}"

        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)

        cursor = conn.execute(sql, params)
        return {row[0]: row[1] for row in cursor.fetchall() if row[0] is not None}
    finally:
        conn.close()
