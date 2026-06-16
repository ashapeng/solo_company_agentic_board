"""SQLite persistence for initiatives."""

from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, get_args

from .models import (
    ApprovalState,
    CarryoverDecisionValue,
    CreatedFrom,
    FounderOutcome,
    Initiative,
    InitiativeCloseout,
    InitiativeError,
    InitiativeLink,
    InitiativeStatus,
    LinkRelationship,
    LinkTargetType,
    default_timebox,
    json_list,
    parse_json_list,
    utc_now,
)


DEFAULT_DB_PATH = Path("data/harness_ledger.db")
INITIATIVE_STATUSES = get_args(InitiativeStatus)
APPROVAL_STATES = get_args(ApprovalState)
CREATED_FROM_VALUES = get_args(CreatedFrom)
FOUNDER_OUTCOMES = get_args(FounderOutcome)
LINK_TARGET_TYPES = get_args(LinkTargetType)
LINK_RELATIONSHIPS = get_args(LinkRelationship)
CARRYOVER_DECISION_VALUES = get_args(CarryoverDecisionValue)

SCHEMA = """
CREATE TABLE IF NOT EXISTS initiatives (
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
    source_session_id TEXT,
    venture_id       TEXT NOT NULL DEFAULT 'default',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_initiatives_status
ON initiatives(status);

CREATE TABLE IF NOT EXISTS initiative_links (
    link_id       TEXT PRIMARY KEY,
    initiative_id TEXT NOT NULL,
    target_type   TEXT NOT NULL,
    target_id     TEXT NOT NULL,
    relationship  TEXT NOT NULL,
    metadata      TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    FOREIGN KEY (initiative_id) REFERENCES initiatives(initiative_id)
);
CREATE INDEX IF NOT EXISTS idx_initiative_links_initiative_id
ON initiative_links(initiative_id);

CREATE TABLE IF NOT EXISTS initiative_closeouts (
    initiative_id             TEXT PRIMARY KEY,
    founder_outcome           TEXT NOT NULL,
    founder_notes             TEXT NOT NULL,
    retrospective_session_id  TEXT,
    memory_proposals          TEXT NOT NULL,
    carryover_decisions       TEXT NOT NULL,
    created_at                TEXT NOT NULL,
    FOREIGN KEY (initiative_id) REFERENCES initiatives(initiative_id)
);
"""


def create_initiative(
    *,
    title: str,
    objective: str,
    success_criteria: list[str] | None = None,
    departments: list[str] | None = None,
    timebox_start: str | None = None,
    timebox_end: str | None = None,
    created_from: str = "manual",
    source_session_id: str | None = None,
    venture_id: str = "default",
    db_path: Path | None = None,
) -> dict[str, Any]:
    title = _required_text(title, "Title")
    objective = _required_text(objective, "Objective")
    created_from = _validate_choice(created_from, CREATED_FROM_VALUES, "created_from")
    start, end = _resolve_timebox(timebox_start, timebox_end)
    now = utc_now()
    initiative = Initiative(
        id=_new_id("init"),
        title=title,
        objective=objective,
        success_criteria=_string_list(success_criteria),
        departments=_string_list(departments),
        timebox_start=start,
        timebox_end=end,
        status="draft",
        approval_state="draft",
        created_from=created_from,
        source_session_id=source_session_id,
        venture_id=str(venture_id or "default"),
        created_at=now,
        updated_at=now,
    )

    conn = _connect(db_path)
    try:
        conn.execute(
            """INSERT INTO initiatives (
                initiative_id, title, objective, status, approval_state,
                created_from, success_criteria, departments, timebox_start,
                timebox_end, source_session_id, venture_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            _initiative_values(initiative),
        )
        conn.commit()
    finally:
        conn.close()
    return initiative.to_dict()


def get_initiative(initiative_id: str, *, db_path: Path | None = None) -> dict[str, Any] | None:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM initiatives WHERE initiative_id = ?",
            (initiative_id,),
        ).fetchone()
        if not row:
            return None
        closeout = _get_closeout(conn, initiative_id)
    finally:
        conn.close()
    return _initiative_from_row(row, closeout=closeout).to_dict()


def list_initiatives(
    *,
    status: str | None = None,
    venture_id: str | None = None,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params_list: list[Any] = []
    if status is not None:
        status = _validate_choice(status, INITIATIVE_STATUSES, "status")
        clauses.append("status = ?")
        params_list.append(status)
    if venture_id is not None:
        clauses.append("venture_id = ?")
        params_list.append(venture_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params: tuple[Any, ...] = tuple(params_list)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT * FROM initiatives {where} ORDER BY created_at, initiative_id",
            params,
        ).fetchall()
        closeouts = {
            row["initiative_id"]: _get_closeout(conn, row["initiative_id"])
            for row in rows
        }
    finally:
        conn.close()
    return [
        _initiative_from_row(row, closeout=closeouts[row["initiative_id"]]).to_dict()
        for row in rows
    ]


def update_initiative(
    initiative_id: str,
    *,
    title: str | None = None,
    objective: str | None = None,
    success_criteria: list[str] | None = None,
    departments: list[str] | None = None,
    timebox_start: str | None = None,
    timebox_end: str | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    initiative = _load_required(initiative_id, db_path=db_path)
    _reject_closed(initiative)
    if title is not None:
        initiative["title"] = _required_text(title, "Title")
    if objective is not None:
        initiative["objective"] = _required_text(objective, "Objective")
    if success_criteria is not None:
        initiative["success_criteria"] = _string_list(success_criteria)
    if departments is not None:
        initiative["departments"] = _string_list(departments)
    if timebox_start is not None:
        initiative["timebox_start"] = str(timebox_start)
    if timebox_end is not None:
        initiative["timebox_end"] = str(timebox_end)
    initiative["updated_at"] = utc_now()
    _save_initiative(initiative, db_path=db_path)
    return _load_required(initiative_id, db_path=db_path)


def activate_initiative(initiative_id: str, *, db_path: Path | None = None) -> dict[str, Any]:
    initiative = _load_required(initiative_id, db_path=db_path)
    _reject_closed(initiative)
    initiative["status"] = "active"
    initiative["approval_state"] = "approved"
    initiative["updated_at"] = utc_now()
    _save_initiative(initiative, db_path=db_path)
    return _load_required(initiative_id, db_path=db_path)


def create_link(
    initiative_id: str,
    target_type: str,
    target_id: str,
    relationship: str,
    *,
    metadata: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    _load_required(initiative_id, db_path=db_path)
    target_type = _validate_choice(target_type, LINK_TARGET_TYPES, "target_type")
    relationship = _validate_choice(relationship, LINK_RELATIONSHIPS, "relationship")
    target_id = _required_text(target_id, "Target id")
    now = utc_now()
    link = InitiativeLink(
        id=_new_id("link"),
        initiative_id=initiative_id,
        target_type=target_type,
        target_id=target_id,
        relationship=relationship,
        created_at=now,
        metadata=metadata or {},
    )
    conn = _connect(db_path)
    try:
        conn.execute(
            """INSERT INTO initiative_links (
                link_id, initiative_id, target_type, target_id, relationship,
                metadata, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                link.id,
                link.initiative_id,
                link.target_type,
                link.target_id,
                link.relationship,
                json.dumps(link.metadata, ensure_ascii=False),
                link.created_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return link.to_dict()


def list_links(initiative_id: str, *, db_path: Path | None = None) -> list[dict[str, Any]]:
    _load_required(initiative_id, db_path=db_path)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM initiative_links WHERE initiative_id = ? ORDER BY created_at, link_id",
            (initiative_id,),
        ).fetchall()
    finally:
        conn.close()
    return [_link_from_row(row).to_dict() for row in rows]


def list_linked_session_ids(initiative_id: str, *, db_path: Path | None = None) -> list[str]:
    links = list_links(initiative_id, db_path=db_path)
    return [str(link["target_id"]) for link in links if link.get("target_type") == "board_session"]


def delete_link(initiative_id: str, link_id: str, *, db_path: Path | None = None) -> dict[str, Any]:
    _load_required(initiative_id, db_path=db_path)
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM initiative_links WHERE initiative_id = ? AND link_id = ?",
            (initiative_id, link_id),
        ).fetchone()
        if not row:
            raise InitiativeError(f"Initiative link not found: {link_id}")
        conn.execute("DELETE FROM initiative_links WHERE link_id = ?", (link_id,))
        conn.commit()
    finally:
        conn.close()
    return _link_from_row(row).to_dict()


def get_closeout(initiative_id: str, *, db_path: Path | None = None) -> dict[str, Any] | None:
    _load_required(initiative_id, db_path=db_path)
    conn = _connect(db_path)
    try:
        return _get_closeout(conn, initiative_id)
    finally:
        conn.close()


def close_initiative(
    initiative_id: str,
    founder_outcome: str,
    founder_notes: str,
    retrospective_session_id: str | None,
    memory_proposals: list[str],
    carryover_decisions: list[dict[str, Any]],
    *,
    db_path: Path | None = None,
) -> dict[str, Any]:
    initiative = _load_required(initiative_id, db_path=db_path)
    if initiative["status"] == "closed":
        raise InitiativeError("Closed initiatives cannot be closed again.")
    founder_outcome = _validate_choice(founder_outcome, FOUNDER_OUTCOMES, "founder_outcome")
    carryover_decisions = _validate_carryover_decisions(carryover_decisions)
    closeout = InitiativeCloseout(
        initiative_id=initiative_id,
        founder_outcome=founder_outcome,
        founder_notes=str(founder_notes or ""),
        retrospective_session_id=str(retrospective_session_id) if retrospective_session_id else None,
        memory_proposals=_string_list(memory_proposals),
        carryover_decisions=carryover_decisions,
        created_at=utc_now(),
    )

    initiative["status"] = "closed"
    initiative["updated_at"] = utc_now()
    conn = _connect(db_path)
    try:
        conn.execute(
            """UPDATE initiatives SET
                title = ?, objective = ?, status = ?, approval_state = ?,
                created_from = ?, success_criteria = ?, departments = ?,
                timebox_start = ?, timebox_end = ?, source_session_id = ?,
                created_at = ?, updated_at = ?
            WHERE initiative_id = ?""",
            (
                initiative["title"],
                initiative["objective"],
                initiative["status"],
                initiative["approval_state"],
                initiative["created_from"],
                json_list(initiative["success_criteria"]),
                json_list(initiative["departments"]),
                initiative["timebox_start"],
                initiative["timebox_end"],
                initiative.get("source_session_id"),
                initiative["created_at"],
                initiative["updated_at"],
                initiative["id"],
            ),
        )
        conn.execute(
            """INSERT OR REPLACE INTO initiative_closeouts (
                initiative_id, founder_outcome, founder_notes,
                retrospective_session_id, memory_proposals,
                carryover_decisions, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                closeout.initiative_id,
                closeout.founder_outcome,
                closeout.founder_notes,
                closeout.retrospective_session_id,
                json_list(closeout.memory_proposals),
                json.dumps(closeout.carryover_decisions, ensure_ascii=False),
                closeout.created_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return _load_required(initiative_id, db_path=db_path)


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _ensure_schema_migrations(conn)
    conn.commit()
    return conn


def _ensure_schema_migrations(conn: sqlite3.Connection) -> None:
    initiative_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(initiatives)").fetchall()
    }
    if "source_session_id" not in initiative_columns:
        conn.execute("ALTER TABLE initiatives ADD COLUMN source_session_id TEXT")
    if "venture_id" not in initiative_columns:
        conn.execute(
            "ALTER TABLE initiatives ADD COLUMN venture_id TEXT NOT NULL DEFAULT 'default'"
        )

    _recover_legacy_closeouts(conn)

    closeout_columns = conn.execute("PRAGMA table_info(initiative_closeouts)").fetchall()
    retrospective_column = next(
        (row for row in closeout_columns if row["name"] == "retrospective_session_id"),
        None,
    )
    if retrospective_column is not None and retrospective_column["notnull"]:
        _rebuild_closeouts_with_nullable_retrospective(conn)


def _recover_legacy_closeouts(conn: sqlite3.Connection) -> None:
    legacy_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("initiative_closeouts_legacy",),
    ).fetchone()
    if not legacy_exists:
        return
    conn.execute(
        """INSERT OR IGNORE INTO initiative_closeouts (
            initiative_id, founder_outcome, founder_notes, retrospective_session_id,
            memory_proposals, carryover_decisions, created_at
        )
        SELECT
            initiative_id, founder_outcome, founder_notes, retrospective_session_id,
            memory_proposals, carryover_decisions, created_at
        FROM initiative_closeouts_legacy"""
    )
    conn.execute("DROP TABLE initiative_closeouts_legacy")


def _rebuild_closeouts_with_nullable_retrospective(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE initiative_closeouts RENAME TO initiative_closeouts_legacy")
    conn.execute(
        """CREATE TABLE initiative_closeouts (
            initiative_id             TEXT PRIMARY KEY,
            founder_outcome           TEXT NOT NULL,
            founder_notes             TEXT NOT NULL,
            retrospective_session_id  TEXT,
            memory_proposals          TEXT NOT NULL,
            carryover_decisions       TEXT NOT NULL,
            created_at                TEXT NOT NULL,
            FOREIGN KEY (initiative_id) REFERENCES initiatives(initiative_id)
        )"""
    )
    conn.execute(
        """INSERT INTO initiative_closeouts (
            initiative_id, founder_outcome, founder_notes, retrospective_session_id,
            memory_proposals, carryover_decisions, created_at
        )
        SELECT
            initiative_id, founder_outcome, founder_notes, retrospective_session_id,
            memory_proposals, carryover_decisions, created_at
        FROM initiative_closeouts_legacy"""
    )
    conn.execute("DROP TABLE initiative_closeouts_legacy")


def _initiative_values(initiative: Initiative) -> tuple[Any, ...]:
    return (
        initiative.id,
        initiative.title,
        initiative.objective,
        initiative.status,
        initiative.approval_state,
        initiative.created_from,
        json_list(initiative.success_criteria),
        json_list(initiative.departments),
        initiative.timebox_start,
        initiative.timebox_end,
        initiative.source_session_id,
        initiative.venture_id,
        initiative.created_at,
        initiative.updated_at,
    )


def _initiative_from_row(
    row: sqlite3.Row,
    *,
    closeout: dict[str, Any] | None = None,
) -> Initiative:
    return Initiative(
        id=row["initiative_id"],
        title=row["title"],
        objective=row["objective"],
        status=row["status"],
        approval_state=row["approval_state"],
        created_from=row["created_from"],
        source_session_id=row["source_session_id"],
        venture_id=(row["venture_id"] if "venture_id" in row.keys() else "default") or "default",
        success_criteria=_string_list(parse_json_list(row["success_criteria"])),
        departments=_string_list(parse_json_list(row["departments"])),
        timebox_start=row["timebox_start"],
        timebox_end=row["timebox_end"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        closeout=closeout,
    )


def _link_from_row(row: sqlite3.Row) -> InitiativeLink:
    return InitiativeLink(
        id=row["link_id"],
        initiative_id=row["initiative_id"],
        target_type=row["target_type"],
        target_id=row["target_id"],
        relationship=row["relationship"],
        metadata=_parse_json_object(row["metadata"]),
        created_at=row["created_at"],
    )


def _closeout_from_row(row: sqlite3.Row) -> InitiativeCloseout:
    return InitiativeCloseout(
        initiative_id=row["initiative_id"],
        founder_outcome=row["founder_outcome"],
        founder_notes=row["founder_notes"],
        retrospective_session_id=row["retrospective_session_id"],
        memory_proposals=_string_list(parse_json_list(row["memory_proposals"])),
        carryover_decisions=_parse_carryover_json(row["carryover_decisions"]),
        created_at=row["created_at"],
    )


def _get_closeout(conn: sqlite3.Connection, initiative_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM initiative_closeouts WHERE initiative_id = ?",
        (initiative_id,),
    ).fetchone()
    if not row:
        return None
    return _closeout_from_row(row).to_dict()


def _save_initiative(initiative: dict[str, Any], *, db_path: Path | None = None) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            """UPDATE initiatives SET
                title = ?, objective = ?, status = ?, approval_state = ?,
                created_from = ?, success_criteria = ?, departments = ?,
                timebox_start = ?, timebox_end = ?, source_session_id = ?,
                created_at = ?, updated_at = ?
            WHERE initiative_id = ?""",
            (
                initiative["title"],
                initiative["objective"],
                initiative["status"],
                initiative["approval_state"],
                initiative["created_from"],
                json_list(initiative["success_criteria"]),
                json_list(initiative["departments"]),
                initiative["timebox_start"],
                initiative["timebox_end"],
                initiative.get("source_session_id"),
                initiative["created_at"],
                initiative["updated_at"],
                initiative["id"],
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _load_required(initiative_id: str, *, db_path: Path | None = None) -> dict[str, Any]:
    initiative = get_initiative(initiative_id, db_path=db_path)
    if not initiative:
        raise InitiativeError(f"Initiative not found: {initiative_id}")
    return initiative


def _reject_closed(initiative: dict[str, Any]) -> None:
    if initiative["status"] == "closed":
        raise InitiativeError("Closed initiatives cannot be activated or edited.")


def _validate_carryover_decisions(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if decisions is None:
        return []
    if not isinstance(decisions, list):
        raise InitiativeError("Carryover decisions must be a list.")
    validated: list[dict[str, Any]] = []
    for decision in decisions:
        if not isinstance(decision, dict):
            raise InitiativeError("Each carryover decision must be an object.")
        task_id = _required_text(str(decision.get("task_id") or ""), "Carryover task id")
        value = _validate_choice(
            str(decision.get("decision") or ""),
            CARRYOVER_DECISION_VALUES,
            "carryover decision",
        )
        item = dict(decision)
        item["task_id"] = task_id
        item["decision"] = value
        validated.append(item)
    return validated


def _parse_carryover_json(value: str | None) -> list[dict[str, Any]]:
    parsed = parse_json_list(value)
    result: list[dict[str, Any]] = []
    for item in parsed:
        if isinstance(item, dict):
            result.append(item)
    return result


def _parse_json_object(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise InitiativeError("Stored metadata payload is not valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise InitiativeError("Stored metadata payload must be a JSON object.")
    return parsed


def _resolve_timebox(timebox_start: str | None, timebox_end: str | None) -> tuple[str, str]:
    default_start, default_end = default_timebox()
    return str(timebox_start or default_start), str(timebox_end or default_end)


def _validate_choice(value: str, allowed_values: tuple[str, ...], label: str) -> str:
    if value in allowed_values:
        return value
    allowed = ", ".join(allowed_values)
    raise InitiativeError(f"Invalid {label}: {value}. Expected one of: {allowed}")


def _required_text(value: str, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise InitiativeError(f"{label} is required.")
    return text


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"
