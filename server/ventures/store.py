"""SQLite persistence for ventures (WorkSpaces)."""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from typing import Any, get_args

from .models import (
    DEFAULT_VENTURE_ID,
    DEFAULT_VENTURE_SLUG,
    Venture,
    VentureError,
    VentureStatus,
    utc_now,
    venture_slug,
)


DEFAULT_DB_PATH = Path("data/harness_ledger.db")
VENTURE_STATUSES = get_args(VentureStatus)

SCHEMA = """
CREATE TABLE IF NOT EXISTS ventures (
    venture_id  TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,
    status      TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ventures_status
ON ventures(status);
"""


def create_venture(
    name: str,
    *,
    venture_id: str | None = None,
    slug: str | None = None,
    status: str = "active",
    db_path: Path | None = None,
) -> dict[str, Any]:
    name = _required_text(name, "Name")
    status = _validate_choice(status, VENTURE_STATUSES, "status")
    venture_id = str(venture_id).strip() if venture_id else _new_id()
    slug = venture_slug(slug) if slug else venture_slug(name)
    now = utc_now()
    venture = Venture(
        id=venture_id,
        name=name,
        slug=slug,
        status=status,
        created_at=now,
        updated_at=now,
    )

    conn = _connect(db_path)
    try:
        if _row_by_slug(conn, slug) is not None:
            raise VentureError(f"Venture slug already exists: {slug}")
        if _row_by_id(conn, venture_id) is not None:
            raise VentureError(f"Venture id already exists: {venture_id}")
        conn.execute(
            """INSERT INTO ventures (
                venture_id, name, slug, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            _venture_values(venture),
        )
        conn.commit()
    finally:
        conn.close()
    return venture.to_dict()


def get_venture(venture_id: str, *, db_path: Path | None = None) -> dict[str, Any] | None:
    conn = _connect(db_path)
    try:
        row = _row_by_id(conn, venture_id)
    finally:
        conn.close()
    return _venture_from_row(row).to_dict() if row else None


def get_venture_by_slug(slug: str, *, db_path: Path | None = None) -> dict[str, Any] | None:
    conn = _connect(db_path)
    try:
        row = _row_by_slug(conn, slug)
    finally:
        conn.close()
    return _venture_from_row(row).to_dict() if row else None


def list_ventures(
    *,
    status: str | None = None,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    params: tuple[Any, ...] = ()
    where = ""
    if status is not None:
        status = _validate_choice(status, VENTURE_STATUSES, "status")
        where = "WHERE status = ?"
        params = (status,)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT * FROM ventures {where} ORDER BY created_at, venture_id",
            params,
        ).fetchall()
    finally:
        conn.close()
    return [_venture_from_row(row).to_dict() for row in rows]


def ensure_default_venture(*, db_path: Path | None = None) -> dict[str, Any]:
    """Idempotently create and return the default venture."""
    conn = _connect(db_path)
    try:
        row = _row_by_id(conn, DEFAULT_VENTURE_ID)
        if row is not None:
            return _venture_from_row(row).to_dict()
        now = utc_now()
        venture = Venture(
            id=DEFAULT_VENTURE_ID,
            name="Default",
            slug=DEFAULT_VENTURE_SLUG,
            status="active",
            created_at=now,
            updated_at=now,
        )
        conn.execute(
            """INSERT OR IGNORE INTO ventures (
                venture_id, name, slug, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            _venture_values(venture),
        )
        conn.commit()
        row = _row_by_id(conn, DEFAULT_VENTURE_ID)
    finally:
        conn.close()
    return _venture_from_row(row).to_dict()


def update_venture(
    venture_id: str,
    *,
    name: str | None = None,
    status: str | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    conn = _connect(db_path)
    try:
        row = _row_by_id(conn, venture_id)
        if row is None:
            raise VentureError(f"Venture not found: {venture_id}")
        venture = _venture_from_row(row)
        if name is not None:
            venture.name = _required_text(name, "Name")
        if status is not None:
            venture.status = _validate_choice(status, VENTURE_STATUSES, "status")
        venture.updated_at = utc_now()
        conn.execute(
            """UPDATE ventures SET
                name = ?, slug = ?, status = ?, created_at = ?, updated_at = ?
            WHERE venture_id = ?""",
            (
                venture.name,
                venture.slug,
                venture.status,
                venture.created_at,
                venture.updated_at,
                venture.id,
            ),
        )
        conn.commit()
        row = _row_by_id(conn, venture_id)
    finally:
        conn.close()
    return _venture_from_row(row).to_dict()


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
    venture_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(ventures)").fetchall()
    }
    if not venture_columns:
        return
    if "status" not in venture_columns:
        conn.execute("ALTER TABLE ventures ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")


def _row_by_id(conn: sqlite3.Connection, venture_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM ventures WHERE venture_id = ?",
        (venture_id,),
    ).fetchone()


def _row_by_slug(conn: sqlite3.Connection, slug: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM ventures WHERE slug = ?",
        (slug,),
    ).fetchone()


def _venture_values(venture: Venture) -> tuple[Any, ...]:
    return (
        venture.id,
        venture.name,
        venture.slug,
        venture.status,
        venture.created_at,
        venture.updated_at,
    )


def _venture_from_row(row: sqlite3.Row) -> Venture:
    return Venture(
        id=row["venture_id"],
        name=row["name"],
        slug=row["slug"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _validate_choice(value: str, allowed_values: tuple[str, ...], label: str) -> str:
    if value in allowed_values:
        return value
    allowed = ", ".join(allowed_values)
    raise VentureError(f"Invalid {label}: {value}. Expected one of: {allowed}")


def _required_text(value: str, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise VentureError(f"{label} is required.")
    return text


def _new_id() -> str:
    return uuid.uuid4().hex
