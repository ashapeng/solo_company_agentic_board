"""
FastAPI server for the Agentic Board.

Run:  uv run uvicorn server.api:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from server.board.config import BOARD_MEMBERS
from server.board.ledger import record_feedback, LedgerError
from server.board.memory import read_sotb, SOTB_PATH
from server.board.memory_review import review_sotb_update
from server.board.orchestrator import BoardDeliberationError, BoardOrchestrator
from server.board.role_gap import review_role_gap
from server.board.roster import load_roster
from server.board.schemas import BoardErrorCode, adapt_session_record

_FEEDBACK_DB_PATH = None  # Use default; tests can patch this

UI_DIR = Path("ui")
UI_DIST_DIR = UI_DIR / "dist"
UI_DIST_INDEX = UI_DIST_DIR / "index.html"
UI_DIST_ASSETS = UI_DIST_DIR / "assets"

app = FastAPI(
    title="Agentic Board API",
    description="A council of world-expert AI agents that deliberate as a company board",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def enforce_local_only(request: Request, call_next):
    """Keep the board API local by default until auth is added."""
    if os.getenv("AGENTIC_BOARD_ALLOW_REMOTE") == "1":
        return await call_next(request)

    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1", "localhost"}:
        return JSONResponse(
            status_code=403,
            content={
                "code": "remote_access_disabled",
                "message": "Agentic Board API is local-only by default.",
            },
        )
    return await call_next(request)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    query: str
    session_id: str | None = None
    member_ids: list[str] | None = None   # manual member override
    full_board: bool = False               # skip classifier, invoke all members
    verify: bool = False                   # enable Stage 4 verification


class MemberInfo(BaseModel):
    id: str
    title: str
    role: str
    expertise: list[str]
    tags: list[str]
    governance_seat: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    activation: dict = Field(default_factory=dict)


class SotbUpdate(BaseModel):
    content: str


class SotbReviewRequest(BaseModel):
    proposed_sotb_update: str
    session_id: str | None = None


class RoleGapReviewRequest(BaseModel):
    missing_capabilities: list[str]
    query: str | None = None
    stage_profile: str = "pre_pmf"
    recurrence_count: int = 1


class FeedbackRequest(BaseModel):
    rating: str
    note: str | None = None


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    """Serve the frontend."""
    if UI_DIST_INDEX.exists():
        return FileResponse(UI_DIST_INDEX)
    return FileResponse(UI_DIR / "index.html")


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.get("/members")
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


@app.post("/deliberate")
async def deliberate(req: QueryRequest):
    """Run a full 3-stage board deliberation. Returns the complete session."""
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


@app.post("/deliberate/stream")
async def deliberate_stream(req: QueryRequest):
    """Stream deliberation progress as server-sent events."""

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
                # Drain remaining events
                while not queue.empty():
                    event = queue.get_nowait()
                    yield f"data: {json.dumps(event)}\n\n"
                break

            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                yield f"data: {json.dumps(event)}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"

        # Send final result or error
        try:
            session = task.result()
            yield f"data: {json.dumps({'event': 'complete', 'session': session.to_dict()})}\n\n"
        except BoardDeliberationError as e:
            yield f"data: {json.dumps({'event': 'error', 'code': BoardErrorCode.DELIBERATION_FAILED, 'message': str(e)})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/sessions")
async def list_sessions():
    """List all saved session IDs."""
    # Check both directories for backward compatibility
    sessions = []
    for dirname in ("data/sessions", "data/conversations"):
        path = Path(dirname)
        if path.exists():
            sessions.extend(f.stem for f in path.glob("*.json"))
    return sorted(set(sessions), reverse=True)


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Retrieve a saved session by ID."""
    # Check both directories for backward compatibility
    for dirname in ("data/sessions", "data/conversations"):
        filepath = Path(f"{dirname}/{session_id}.json")
        if filepath.exists():
            return json.loads(filepath.read_text())
    raise HTTPException(404, "Session not found")


@app.get("/sessions/{session_id}/adapter")
async def get_session_adapter(session_id: str):
    """Return the stable integration contract for a saved session."""
    for dirname in ("data/sessions", "data/conversations"):
        filepath = Path(f"{dirname}/{session_id}.json")
        if filepath.exists():
            return adapt_session_record(json.loads(filepath.read_text()))
    raise HTTPException(404, "Session not found")


@app.post("/sessions/{session_id}/feedback")
async def feedback(session_id: str, req: FeedbackRequest):
    """Record founder feedback for a session."""
    if req.rating not in ("positive", "negative"):
        raise HTTPException(422, detail="rating must be 'positive' or 'negative'")
    if req.note and len(req.note) > 500:
        raise HTTPException(422, detail="note must be 500 characters or fewer")

    try:
        record_feedback(session_id, req.rating, note=req.note, db_path=_FEEDBACK_DB_PATH)
    except LedgerError:
        raise HTTPException(404, detail=f"Session not found: {session_id}")

    return {"status": "recorded", "session_id": session_id}


# ---------------------------------------------------------------------------
# SOTB
# ---------------------------------------------------------------------------
@app.get("/sotb")
async def get_sotb():
    """Read the current State of the Board."""
    content = read_sotb()
    return {"content": content, "path": str(SOTB_PATH)}


@app.post("/sotb/review")
async def review_sotb(req: SotbReviewRequest):
    """Return a reviewable SOTB diff without applying it."""
    return review_sotb_update(
        req.proposed_sotb_update,
        session_id=req.session_id or "",
    )


@app.put("/sotb")
async def update_sotb(req: SotbUpdate):
    """Manually update the State of the Board."""
    SOTB_PATH.parent.mkdir(parents=True, exist_ok=True)
    SOTB_PATH.write_text(req.content, encoding="utf-8")
    return {"status": "updated", "path": str(SOTB_PATH)}


@app.post("/role-gap/review")
async def role_gap_review(req: RoleGapReviewRequest):
    """Review whether missing capabilities justify role evolution."""
    return review_role_gap(
        req.missing_capabilities,
        query=req.query or "",
        stage_profile=req.stage_profile,
        recurrence_count=req.recurrence_count,
    )


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@app.get("/metrics/summary")
async def metrics_summary():
    """Return the last session's metrics (simple aggregate)."""
    # Find the most recent session file
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
            }
    return {"session_id": None, "metrics": {}}


# ---------------------------------------------------------------------------
# Static files — mount LAST so API routes take priority
# ---------------------------------------------------------------------------

if UI_DIST_ASSETS.exists():
    app.mount("/assets", StaticFiles(directory=UI_DIST_ASSETS), name="frontend-assets")
app.mount("/ui", StaticFiles(directory="ui"), name="ui")
