"""SQLite persistence for SOTB snapshots + consolidations (white-box memory).

Shares the harness ledger DB (`data/harness_ledger.db`). Two tables:
- `sotb_snapshots`: full point-in-time copies of a venture's SOTB md + index,
  with pre/post content hashes for drift detection.
- `sotb_consolidations`: audit rows for memory-consolidation passes.

This is the DB layer only — snapshot/rollback logic lives in
`server.memory.sotb_snapshot`. The schema mirrors the venture store pattern
(`server.ventures.store`): shared DB path, `_connect` + `executescript(SCHEMA)`,
`sqlite3.Row` rows, and `db_path` kwargs throughout.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DB_PATH = Path("data/harness_ledger.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sotb_snapshots (
    snapshot_id       TEXT PRIMARY KEY,
    venture_id        TEXT NOT NULL,
    reason            TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    session_id        TEXT,
    md_sha256         TEXT,
    index_sha256      TEXT,
    md_text           TEXT,
    index_json        TEXT,
    post_md_sha256    TEXT,
    post_index_sha256 TEXT
);
CREATE INDEX IF NOT EXISTS idx_sotb_snapshots_venture_created
ON sotb_snapshots(venture_id, created_at);

CREATE TABLE IF NOT EXISTS sotb_consolidations (
    consolidation_id  TEXT PRIMARY KEY,
    venture_id        TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    session_id        TEXT,
    snapshot_id       TEXT,
    merged            INTEGER,
    superseded        INTEGER,
    expired           INTEGER,
    kept              INTEGER,
    summary           TEXT
);
"""

# Columns returned by list_snapshots (metadata only — blobs omitted).
_LIST_COLUMNS = (
    "snapshot_id",
    "venture_id",
    "reason",
    "created_at",
    "session_id",
    "md_sha256",
    "index_sha256",
    "post_md_sha256",
    "post_index_sha256",
)

_SNAPSHOT_COLUMNS = (
    "snapshot_id",
    "venture_id",
    "reason",
    "created_at",
    "session_id",
    "md_sha256",
    "index_sha256",
    "md_text",
    "index_json",
    "post_md_sha256",
    "post_index_sha256",
)

_CONSOLIDATION_COLUMNS = (
    "consolidation_id",
    "venture_id",
    "created_at",
    "session_id",
    "snapshot_id",
    "merged",
    "superseded",
    "expired",
    "kept",
    "summary",
)


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
    """Add any missing columns to existing tables (forward-compatible)."""
    snap_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(sotb_snapshots)").fetchall()
    }
    if snap_columns:
        if "post_md_sha256" not in snap_columns:
            conn.execute("ALTER TABLE sotb_snapshots ADD COLUMN post_md_sha256 TEXT")
        if "post_index_sha256" not in snap_columns:
            conn.execute("ALTER TABLE sotb_snapshots ADD COLUMN post_index_sha256 TEXT")


def insert_snapshot(row: dict, *, db_path: Path | None = None) -> None:
    values = tuple(row.get(col) for col in _SNAPSHOT_COLUMNS)
    placeholders = ", ".join("?" for _ in _SNAPSHOT_COLUMNS)
    columns = ", ".join(_SNAPSHOT_COLUMNS)
    conn = _connect(db_path)
    try:
        conn.execute(
            f"INSERT INTO sotb_snapshots ({columns}) VALUES ({placeholders})",
            values,
        )
        conn.commit()
    finally:
        conn.close()


def update_snapshot_post(
    snapshot_id: str,
    *,
    post_md_sha256: str | None,
    post_index_sha256: str | None,
    db_path: Path | None = None,
) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            """UPDATE sotb_snapshots
            SET post_md_sha256 = ?, post_index_sha256 = ?
            WHERE snapshot_id = ?""",
            (post_md_sha256, post_index_sha256, snapshot_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_snapshot(snapshot_id: str, *, db_path: Path | None = None) -> dict | None:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM sotb_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row is not None else None


def list_snapshots(
    *,
    venture_id: str | None = None,
    limit: int = 20,
    db_path: Path | None = None,
) -> list[dict]:
    """Return snapshot metadata rows (newest first). OMITS the large
    `md_text`/`index_json` blobs; each row carries a `has_payload` bool
    instead so callers can tell whether the full snapshot is restorable."""
    columns = ", ".join(_LIST_COLUMNS)
    params: tuple[Any, ...]
    where = ""
    if venture_id is not None:
        where = "WHERE venture_id = ?"
        params = (venture_id, limit)
    else:
        params = (limit,)
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"""SELECT {columns},
                (md_text IS NOT NULL OR index_json IS NOT NULL) AS has_payload
            FROM sotb_snapshots
            {where}
            ORDER BY created_at DESC
            LIMIT ?""",
            params,
        ).fetchall()
    finally:
        conn.close()
    out: list[dict] = []
    for row in rows:
        d = dict(row)
        d["has_payload"] = bool(d.get("has_payload"))
        out.append(d)
    return out


def record_consolidation(row: dict, *, db_path: Path | None = None) -> None:
    values = tuple(row.get(col) for col in _CONSOLIDATION_COLUMNS)
    placeholders = ", ".join("?" for _ in _CONSOLIDATION_COLUMNS)
    columns = ", ".join(_CONSOLIDATION_COLUMNS)
    conn = _connect(db_path)
    try:
        conn.execute(
            f"INSERT INTO sotb_consolidations ({columns}) VALUES ({placeholders})",
            values,
        )
        conn.commit()
    finally:
        conn.close()
