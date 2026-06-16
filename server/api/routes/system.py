"""System, UI, and metrics routes."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from ..state import UI_DIR, UI_DIST_INDEX


router = APIRouter()


@router.get("/")
async def root():
    if UI_DIST_INDEX.exists():
        return FileResponse(UI_DIST_INDEX)
    return FileResponse(UI_DIR / "index.html")


@router.get("/metrics/summary")
async def metrics_summary():
    for dirname in ("data/sessions", "data/conversations"):
        path = Path(dirname)
        if not path.exists():
            continue
        files = sorted(path.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        if files:
            data = json.loads(files[0].read_text())
            return {
                "session_id": data.get("session_id"),
                "metrics": data.get("metrics", {}),
                "cumulative_savings": _cumulative_savings(),
            }
    return {
        "session_id": None,
        "metrics": {},
        "cumulative_savings": _cumulative_savings(),
    }


def _cumulative_savings() -> dict:
    """Read cumulative savings from the ledger, never raising on a fresh DB."""
    try:
        from server.harness import ledger

        return ledger.cumulative_savings()
    except Exception:
        return {}
