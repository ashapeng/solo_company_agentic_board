"""Board deliberation and session routes."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from server.board.config import BOARD_MEMBERS
from server.board.deliberation.orchestrator import BoardDeliberationError, BoardOrchestrator
from server.board.projection import BoardErrorCode, adapt_session_record
from server.board.role_gap import review_role_gap
from server.board.roster import load_roster
from server.execution import get_delegation_plan, record_delegation_plan
from server.harness.ledger import LedgerError, record_feedback

from .. import state
from ..schemas import FeedbackRequest, MemberInfo, QueryRequest, RoleGapReviewRequest


router = APIRouter()


@router.get("/members")
async def list_members() -> list[MemberInfo]:
    roster_members = load_roster().get("members", {})
    return [
        MemberInfo(
            id=m.id,
            title=m.title,
            role=m.role,
            expertise=m.expertise,
            tags=m.tags,
            governance_seat=roster_members.get(m.id, {}).get("governance_seat"),
            capabilities=roster_members.get(m.id, {}).get("capabilities", []),
            activation=roster_members.get(m.id, {}).get("activation", {}),
        )
        for m in BOARD_MEMBERS
    ]


@router.post("/deliberate")
async def deliberate(req: QueryRequest):
    orchestrator = BoardOrchestrator()
    try:
        session = await orchestrator.deliberate(
            req.query,
            member_ids=req.member_ids,
            skip_classify=req.full_board,
            verify=req.verify,
            session_id=req.session_id,
        )
    except BoardDeliberationError as e:
        raise HTTPException(
            503,
            detail={
                "code": BoardErrorCode.DELIBERATION_FAILED,
                "message": str(e),
            },
        )
    return session.to_dict()


@router.post("/deliberate/stream")
async def deliberate_stream(req: QueryRequest):
    queue: asyncio.Queue[dict] = asyncio.Queue()

    def on_stage_start(stage, name):
        queue.put_nowait({"event": "stage_start", "stage": stage, "name": name})

    def on_member_done(stage, member, resp, error=None):
        if error:
            queue.put_nowait({
                "event": "member_failed",
                "stage": stage,
                "member_id": member.id,
                "member_title": member.title,
                "error": error,
            })
        else:
            queue.put_nowait({
                "event": "member_done",
                "stage": stage,
                "member_id": member.id,
                "member_title": member.title,
                "model": resp.model,
                "elapsed": resp.elapsed_seconds,
            })

    def on_stage_done(stage, responses):
        count = len(responses) if isinstance(responses, list) else 1
        queue.put_nowait({"event": "stage_done", "stage": stage, "count": count})

    async def event_generator():
        orchestrator = BoardOrchestrator(
            on_stage_start=on_stage_start,
            on_member_done=on_member_done,
            on_stage_done=on_stage_done,
        )

        task = asyncio.create_task(
            orchestrator.deliberate(
                req.query,
                member_ids=req.member_ids,
                skip_classify=req.full_board,
                verify=req.verify,
                session_id=req.session_id,
            )
        )

        while True:
            if task.done():
                while not queue.empty():
                    event = queue.get_nowait()
                    yield f"data: {json.dumps(event)}\n\n"
                break

            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                yield f"data: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"

        try:
            session = task.result()
            yield f"data: {json.dumps({'event': 'complete', 'session': session.to_dict()})}\n\n"
        except BoardDeliberationError as e:
            yield f"data: {json.dumps({'event': 'error', 'code': BoardErrorCode.DELIBERATION_FAILED, 'message': str(e)})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/sessions")
async def list_sessions():
    sessions = []
    for dirname in ("data/sessions", "data/conversations"):
        path = Path(dirname)
        if path.exists():
            sessions.extend(f.stem for f in path.glob("*.json"))
    return sorted(set(sessions), reverse=True)


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    for dirname in ("data/sessions", "data/conversations"):
        filepath = Path(f"{dirname}/{session_id}.json")
        if filepath.exists():
            return json.loads(filepath.read_text())
    raise HTTPException(404, "Session not found")


@router.get("/sessions/{session_id}/adapter")
async def get_session_adapter(session_id: str):
    for dirname in ("data/sessions", "data/conversations"):
        filepath = Path(f"{dirname}/{session_id}.json")
        if filepath.exists():
            return adapt_session_record(json.loads(filepath.read_text()))
    raise HTTPException(404, "Session not found")


@router.get("/sessions/{session_id}/delegation-plan")
async def get_session_delegation_plan(session_id: str):
    persisted = get_delegation_plan(session_id)
    if persisted.get("tasks"):
        return persisted

    for dirname in ("data/sessions", "data/conversations"):
        filepath = Path(f"{dirname}/{session_id}.json")
        if filepath.exists():
            data = json.loads(filepath.read_text())
            plan = data.get("delegation_plan") or {
                "session_id": session_id,
                "tasks": [],
                "warnings": ["Session has no delegation plan."],
                "requires_approval": True,
            }
            record_delegation_plan(plan)
            return plan
    raise HTTPException(404, "Session not found")


@router.post("/sessions/{session_id}/feedback")
async def feedback(session_id: str, req: FeedbackRequest):
    if req.rating not in ("positive", "negative"):
        raise HTTPException(422, detail="rating must be 'positive' or 'negative'")
    if req.note and len(req.note) > 500:
        raise HTTPException(422, detail="note must be 500 characters or fewer")

    try:
        record_feedback(session_id, req.rating, note=req.note, db_path=state._FEEDBACK_DB_PATH)
    except LedgerError:
        raise HTTPException(404, detail=f"Session not found: {session_id}")

    return {"status": "recorded", "session_id": session_id}


@router.post("/role-gap/review")
async def role_gap_review(req: RoleGapReviewRequest):
    return review_role_gap(
        req.missing_capabilities,
        query=req.query or "",
        stage_profile=req.stage_profile,
        recurrence_count=req.recurrence_count,
    )
