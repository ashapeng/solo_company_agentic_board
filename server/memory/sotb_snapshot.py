"""SOTB snapshot + rollback (foundation for white-box memory).

Captures point-in-time copies of a venture's SOTB markdown and sidecar index
into the shared ledger DB, and restores them atomically. Drift detection
("manual edits since this snapshot") compares current content hashes against
the snapshot's post-write hashes.

Design notes:
- Capture/finalize are best-effort: they NEVER raise on IO or DB errors; they
  log a warning and degrade gracefully. Snapshotting must never break a
  deliberation.
- Restore is atomic per file (tmp + fsync + rename), copying the approach
  `sotb_governance.write_sotb_index` uses so a crash mid-write can't leave a
  half-written SOTB.
- This module imports `sotb_governance` read-only (path resolution + nothing
  that mutates the live SOTB).
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from server.memory import store
from server.memory.sotb_governance import venture_memory_paths

logger = logging.getLogger(__name__)


@dataclass
class SotbSnapshot:
    """Metadata view of a stored snapshot (blobs not carried here)."""

    snapshot_id: str
    venture_id: str
    reason: str
    created_at: str
    session_id: str | None = None
    md_sha256: str | None = None
    index_sha256: str | None = None
    post_md_sha256: str | None = None
    post_index_sha256: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _atomic_write_text(path: Path, text: str) -> None:
    """Write `text` to `path` atomically: tmp file + flush + fsync + rename.
    Mirrors `sotb_governance.write_sotb_index`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        try:
            os.fsync(f.fileno())
        except (OSError, AttributeError):  # best-effort
            pass
    tmp.replace(path)


def _read_text_or_empty(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError as exc:  # pragma: no cover — defensive
        logger.warning("sotb_snapshot: failed to read %s: %s", path, exc)
        return ""


def _count_index_rows(index_json: str) -> int:
    return sum(1 for line in index_json.splitlines() if line.strip())


def capture_snapshot(
    *,
    venture_id: str = "default",
    reason: str,
    session_id: str | None = None,
    md_path: Path | None = None,
    index_path: Path | None = None,
    db_path: Path | None = None,
) -> dict:
    """Capture the current SOTB md + raw index for a venture into the DB.

    Resolves paths via `venture_memory_paths(venture_id)` when not given.
    Missing files are treated as empty content. Best-effort: never raises —
    returns `{"snapshot_id": None, "error": str(exc)}` on failure.
    """
    try:
        if md_path is None or index_path is None:
            _md_default, _idx_default = venture_memory_paths(venture_id)
            md_path = md_path or _md_default
            index_path = index_path or _idx_default

        md_text = _read_text_or_empty(md_path)
        index_json = _read_text_or_empty(index_path)
        md_sha = _sha256(md_text)
        index_sha = _sha256(index_json)
        snapshot_id = uuid.uuid4().hex

        store.insert_snapshot(
            {
                "snapshot_id": snapshot_id,
                "venture_id": venture_id,
                "reason": reason,
                "created_at": _now_iso(),
                "session_id": session_id,
                "md_sha256": md_sha,
                "index_sha256": index_sha,
                "md_text": md_text,
                "index_json": index_json,
                "post_md_sha256": None,
                "post_index_sha256": None,
            },
            db_path=db_path,
        )
        return {
            "snapshot_id": snapshot_id,
            "venture_id": venture_id,
            "reason": reason,
            "md_sha256": md_sha,
            "index_sha256": index_sha,
        }
    except Exception as exc:  # noqa: BLE001 — snapshotting must never break a run
        logger.warning("sotb_snapshot: capture failed: %s", exc)
        return {"snapshot_id": None, "error": str(exc)}


def finalize_snapshot(
    snapshot_id: str,
    *,
    venture_id: str = "default",
    md_path: Path | None = None,
    index_path: Path | None = None,
    db_path: Path | None = None,
) -> None:
    """Record post-write content hashes for an existing snapshot so later
    rollbacks can detect manual edits made after this snapshot's write.
    Best-effort: never raises."""
    try:
        if md_path is None or index_path is None:
            _md_default, _idx_default = venture_memory_paths(venture_id)
            md_path = md_path or _md_default
            index_path = index_path or _idx_default

        post_md_sha = _sha256(_read_text_or_empty(md_path))
        post_index_sha = _sha256(_read_text_or_empty(index_path))
        store.update_snapshot_post(
            snapshot_id,
            post_md_sha256=post_md_sha,
            post_index_sha256=post_index_sha,
            db_path=db_path,
        )
    except Exception as exc:  # noqa: BLE001 — best-effort
        logger.warning("sotb_snapshot: finalize failed: %s", exc)


def list_snapshots(
    *,
    venture_id: str | None = None,
    limit: int = 20,
    db_path: Path | None = None,
) -> list[dict]:
    """Thin wrapper over `store.list_snapshots` (metadata only, no blobs)."""
    return store.list_snapshots(venture_id=venture_id, limit=limit, db_path=db_path)


def rollback_to(snapshot_id: str, *, db_path: Path | None = None) -> dict:
    """Restore the SOTB md + index from a stored snapshot, atomically.

    Resolves the snapshot's venture paths via `venture_memory_paths`. Reports
    whether the live SOTB was manually edited since this snapshot was written
    (`manual_edits_since`): True when the snapshot has a `post_md_sha256` and
    the current md hash differs from it.
    """
    snapshot = store.get_snapshot(snapshot_id, db_path=db_path)
    if snapshot is None:
        return {"restored": False, "error": "snapshot not found"}

    venture_id = snapshot["venture_id"]
    md_path, index_path = venture_memory_paths(venture_id)

    md_text = snapshot.get("md_text") or ""
    index_json = snapshot.get("index_json") or ""

    # Detect manual edits since this snapshot's write (head changed).
    current_md_sha = _sha256(_read_text_or_empty(md_path))
    post_md_sha = snapshot.get("post_md_sha256")
    manual_edits_since = bool(post_md_sha) and current_md_sha != post_md_sha

    _atomic_write_text(md_path, md_text)
    _atomic_write_text(index_path, index_json)

    return {
        "restored": True,
        "venture_id": venture_id,
        "snapshot_id": snapshot_id,
        "manual_edits_since": manual_edits_since,
        "restored_md_bytes": len(md_text),
        "restored_index_rows": _count_index_rows(index_json),
    }
