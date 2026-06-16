"""SOTB memory routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from server.memory.review import review_sotb_update
from server.memory.sotb import SOTB_PATH, read_sotb
from server.memory.sotb_governance import read_sotb_index, venture_memory_paths

from ..schemas import ConsolidateRequest, SotbReviewRequest, SotbUpdate


router = APIRouter()


@router.get("/sotb")
async def get_sotb(venture_id: str = "default"):
    content = read_sotb(venture_id=venture_id)
    return {"content": content, "path": str(SOTB_PATH), "venture_id": venture_id}


# NOTE: PUT /sotb and /sotb/review remain default-venture only for now.
@router.post("/sotb/review")
async def review_sotb(req: SotbReviewRequest):
    return review_sotb_update(
        req.proposed_sotb_update,
        session_id=req.session_id or "",
    )


@router.put("/sotb")
async def update_sotb(req: SotbUpdate):
    SOTB_PATH.parent.mkdir(parents=True, exist_ok=True)
    SOTB_PATH.write_text(req.content, encoding="utf-8")
    return {"status": "updated", "path": str(SOTB_PATH)}


@router.get("/sotb/entries")
async def get_sotb_entries(venture_id: str = "default"):
    """Audit view: the reconciled SOTB sidecar index for a venture."""
    mp, ip = venture_memory_paths(venture_id)
    entries = read_sotb_index(md_path=mp, index_path=ip)
    return {"venture_id": venture_id, "entries": [e.to_dict() for e in entries]}


@router.get("/sotb/snapshots")
async def get_sotb_snapshots(venture_id: str = "default", limit: int = 20):
    """List point-in-time SOTB snapshots for a venture (most recent first)."""
    from server.memory.sotb_snapshot import list_snapshots

    return {
        "venture_id": venture_id,
        "snapshots": list_snapshots(venture_id=venture_id, limit=limit),
    }


@router.post("/sotb/snapshots/{snapshot_id}/rollback")
async def rollback_sotb_snapshot(snapshot_id: str):
    """Restore the SOTB md + index from a stored snapshot."""
    from server.memory.sotb_snapshot import rollback_to

    result = rollback_to(snapshot_id)
    if not result.get("restored"):
        raise HTTPException(
            status_code=404,
            detail=result.get("error", "snapshot not found"),
        )
    return result


@router.post("/sotb/consolidate")
async def consolidate_sotb_endpoint(req: ConsolidateRequest):
    """Run LLM-assisted SOTB consolidation for a venture."""
    from server.memory.sotb_consolidation import consolidate_sotb

    return await consolidate_sotb(venture_id=req.venture_id, verify=req.verify)
