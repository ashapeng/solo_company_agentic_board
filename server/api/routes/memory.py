"""SOTB memory routes."""

from __future__ import annotations

from fastapi import APIRouter

from server.memory.review import review_sotb_update
from server.memory.sotb import SOTB_PATH, read_sotb

from ..schemas import SotbReviewRequest, SotbUpdate


router = APIRouter()


@router.get("/sotb")
async def get_sotb():
    content = read_sotb()
    return {"content": content, "path": str(SOTB_PATH)}


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
