"""Initiative routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from server import initiatives as initiative_store
from server.initiatives import InitiativeError

from ..schemas import (
    InitiativeActivateRequest,
    InitiativeCloseoutRequest,
    InitiativeCreateRequest,
    InitiativeLinkRequest,
    InitiativeUpdateRequest,
)


router = APIRouter()


@router.get("/initiatives")
def list_initiatives(status: str | None = None):
    try:
        return initiative_store.list_initiatives(status=status)
    except InitiativeError as e:
        raise HTTPException(422, detail=str(e)) from e


@router.post("/initiatives")
def create_initiative(req: InitiativeCreateRequest):
    try:
        return initiative_store.create_initiative(
            title=req.title,
            objective=req.objective,
            success_criteria=req.success_criteria,
            departments=req.departments,
            timebox_start=req.timebox_start,
            timebox_end=req.timebox_end,
            created_from=req.created_from,
            source_session_id=req.source_session_id,
        )
    except InitiativeError as e:
        raise HTTPException(422, detail=str(e)) from e


@router.get("/initiatives/{initiative_id}")
def get_initiative(initiative_id: str):
    initiative = initiative_store.get_initiative(initiative_id)
    if not initiative:
        raise HTTPException(404, detail=f"Initiative not found: {initiative_id}")
    initiative["links"] = initiative_store.list_links(initiative_id)
    return initiative


@router.patch("/initiatives/{initiative_id}")
def update_initiative(initiative_id: str, req: InitiativeUpdateRequest):
    updates = req.model_dump(exclude_unset=True)
    try:
        return initiative_store.update_initiative(initiative_id, **updates)
    except InitiativeError as e:
        raise HTTPException(422, detail=str(e)) from e


@router.post("/initiatives/{initiative_id}/activate")
def activate_initiative(initiative_id: str, req: InitiativeActivateRequest):
    if not req.approve:
        raise HTTPException(422, detail="approve must be true")
    try:
        return initiative_store.activate_initiative(initiative_id)
    except InitiativeError as e:
        raise HTTPException(422, detail=str(e)) from e


@router.post("/initiatives/{initiative_id}/links")
def create_link(initiative_id: str, req: InitiativeLinkRequest):
    try:
        return initiative_store.create_link(
            initiative_id,
            target_type=req.target_type,
            target_id=req.target_id,
            relationship=req.relationship,
        )
    except InitiativeError as e:
        raise HTTPException(422, detail=str(e)) from e


@router.get("/initiatives/{initiative_id}/links")
def list_links(initiative_id: str):
    try:
        return initiative_store.list_links(initiative_id)
    except InitiativeError as e:
        raise HTTPException(404, detail=str(e)) from e


@router.delete("/initiatives/{initiative_id}/links/{link_id}")
def delete_link(initiative_id: str, link_id: str):
    try:
        deleted = initiative_store.delete_link(initiative_id, link_id)
    except InitiativeError as e:
        raise HTTPException(404, detail=str(e)) from e
    return {"status": "deleted", "initiative_id": initiative_id, "link_id": deleted["id"]}


@router.post("/initiatives/{initiative_id}/closeout")
def close_initiative(initiative_id: str, req: InitiativeCloseoutRequest):
    try:
        return initiative_store.close_initiative(
            initiative_id,
            founder_outcome=req.founder_outcome,
            founder_notes=req.founder_notes,
            retrospective_session_id=req.retrospective_session_id,
            memory_proposals=req.memory_proposals,
            carryover_decisions=req.carryover_decisions,
        )
    except InitiativeError as e:
        raise HTTPException(422, detail=str(e)) from e
