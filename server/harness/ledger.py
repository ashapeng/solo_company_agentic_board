"""Append-only SQLite ledger recording structured session outcomes."""

from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter
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
                harness_config_version,
                verifier_model, verifier_provider, chairman_provider, applied_review_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                verification.get("verifier_model"),
                verification.get("verifier_provider"),
                verification.get("chairman_provider"),
                _active_review_id(conn),
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
        "verifier_model": "TEXT",
        "verifier_provider": "TEXT",
        "chairman_provider": "TEXT",
        "applied_review_id": "TEXT",
    }
    for column, column_type in additions.items():
        if column not in existing:
            conn.execute(
                f"ALTER TABLE session_outcomes ADD COLUMN {column} {column_type}"
            )

    conn.execute(
        """CREATE TABLE IF NOT EXISTS harness_config_activations (
            review_id         TEXT PRIMARY KEY,
            activated_at      TEXT NOT NULL,
            reverted_at       TEXT,
            snapshot          TEXT NOT NULL,
            previous_snapshot TEXT,
            reason            TEXT
        )"""
    )


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


def _active_review_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT review_id FROM harness_config_activations "
        "WHERE reverted_at IS NULL ORDER BY activated_at DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def snapshot_activation(
    review_id: str,
    snapshot: dict,
    previous_snapshot: dict | None,
    db_path: Path | None = None,
) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO harness_config_activations
               (review_id, activated_at, snapshot, previous_snapshot)
               VALUES (?, ?, ?, ?)""",
            (
                review_id,
                datetime.now(timezone.utc).isoformat(),
                json.dumps(snapshot),
                json.dumps(previous_snapshot or {}),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def revert_activation(
    review_id: str, reason: str, db_path: Path | None = None,
) -> dict | None:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT previous_snapshot FROM harness_config_activations WHERE review_id = ?",
            (review_id,),
        ).fetchone()
        if not row:
            return None
        previous_snapshot = json.loads(row[0] or "null")
        conn.execute(
            "UPDATE harness_config_activations SET reverted_at = ?, reason = ? WHERE review_id = ?",
            (datetime.now(timezone.utc).isoformat(), reason, review_id),
        )
        conn.commit()
        return previous_snapshot
    finally:
        conn.close()


def rolling_mean(
    field: str, *, limit: int, db_path: Path | None = None,
) -> tuple[float | None, int]:
    if field not in _NUMERIC_COLUMNS:
        raise LedgerError(f"Cannot roll non-numeric field: {field}")
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT {field} FROM session_outcomes "  # nosec B608
            f"WHERE {field} IS NOT NULL ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        values = [row[0] for row in rows if row[0] is not None]
        if not values:
            return None, 0
        return sum(values) / len(values), len(values)
    finally:
        conn.close()


def rolling_stats(
    field: str,
    *,
    recent_n: int = 10,
    baseline_n: int = 100,
    min_baseline: int = 5,
    query_type: str | None = None,
    db_path: Path | None = None,
) -> dict:
    """Compare recent_n-most-recent rows against baseline_n before them.

    Returns a dict with `recent_mean`, `baseline_mean`, `delta`, `recent_n`,
    `baseline_n` — or {'insufficient_samples': True, 'sample_count': N}
    when there aren't enough rows.
    """
    if field not in _NUMERIC_COLUMNS:
        raise LedgerError(f"Cannot roll non-numeric field: {field}")
    conn = _connect(db_path)
    try:
        sql_parts = [
            f"SELECT {field} FROM session_outcomes",  # nosec B608
            f"WHERE {field} IS NOT NULL",
        ]
        params: list = []
        if query_type:
            sql_parts.append("AND query_type = ?")
            params.append(query_type)
        sql_parts.append("ORDER BY timestamp DESC LIMIT ?")
        params.append(recent_n + baseline_n)
        sql = " ".join(sql_parts)
        rows = [
            row[0]
            for row in conn.execute(sql, params).fetchall()
            if row[0] is not None
        ]
    finally:
        conn.close()

    if len(rows) < recent_n + 1:
        return {"insufficient_samples": True, "sample_count": len(rows)}
    recent = rows[:recent_n]
    baseline = rows[recent_n : recent_n + baseline_n]
    if not baseline or len(baseline) < min_baseline:
        return {
            "insufficient_samples": True,
            "sample_count": len(rows),
            "baseline_underpowered": True,
            "baseline_count": len(baseline),
        }
    recent_mean = sum(recent) / len(recent)
    baseline_mean = sum(baseline) / len(baseline)
    return {
        "recent_mean": round(recent_mean, 4),
        "baseline_mean": round(baseline_mean, 4),
        "delta": round(recent_mean - baseline_mean, 4),
        "recent_n": len(recent),
        "baseline_n": len(baseline),
    }


def distribution_shift(
    field: str,
    *,
    recent_n: int = 10,
    baseline_n: int = 100,
    db_path: Path | None = None,
) -> dict:
    """Return the Jensen–Shannon distance between recent and baseline
    label distributions for a categorical field (query_type / complexity).

    Returns {js_distance: float, recent: {label: freq}, baseline: {label: freq}}
    or {'insufficient_samples': True, 'sample_count': N}.
    """
    if field not in {"query_type", "complexity"}:
        raise LedgerError(f"Cannot report distribution for field: {field}")
    conn = _connect(db_path)
    try:
        sql = (
            f"SELECT {field} FROM session_outcomes "  # nosec B608
            f"WHERE {field} IS NOT NULL "
            "ORDER BY timestamp DESC LIMIT ?"
        )
        rows = [
            row[0]
            for row in conn.execute(sql, (recent_n + baseline_n,)).fetchall()
        ]
    finally:
        conn.close()
    if len(rows) < recent_n + 1:
        return {"insufficient_samples": True, "sample_count": len(rows)}
    recent = rows[:recent_n]
    baseline = rows[recent_n : recent_n + baseline_n]
    if not baseline:
        return {"insufficient_samples": True, "sample_count": len(rows)}
    labels = set(recent) | set(baseline)
    recent_counts = Counter(recent)
    baseline_counts = Counter(baseline)
    recent_dist = {lbl: recent_counts.get(lbl, 0) / len(recent) for lbl in labels}
    baseline_dist = {lbl: baseline_counts.get(lbl, 0) / len(baseline) for lbl in labels}
    mix = {
        lbl: (recent_dist[lbl] + baseline_dist[lbl]) / 2 for lbl in labels
    }

    def _kl(p, q):
        total = 0.0
        for lbl in labels:
            if p[lbl] > 0 and q[lbl] > 0:
                total += p[lbl] * math.log2(p[lbl] / q[lbl])
        return total

    js = 0.5 * _kl(recent_dist, mix) + 0.5 * _kl(baseline_dist, mix)
    return {
        "js_distance": round(math.sqrt(max(0.0, js)), 4),
        "recent": {lbl: round(v, 3) for lbl, v in recent_dist.items()},
        "baseline": {lbl: round(v, 3) for lbl, v in baseline_dist.items()},
    }
