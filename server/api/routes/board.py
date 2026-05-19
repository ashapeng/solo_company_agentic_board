"""Board deliberation and session routes."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path as FilePath

from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import StreamingResponse

from server.board.config import BOARD_MEMBERS
from server.board.deliberation.live import LiveBoardConversation
from server.board.deliberation.orchestrator import BoardDeliberationError, BoardOrchestrator
from server.board.projection import BoardErrorCode, adapt_session_record
from server.board.role_gap import review_role_gap
from server.board.roster import load_roster
from server.execution import get_delegation_plan, record_delegation_plan
from server.harness.ledger import LedgerError, record_feedback, record_routing_signal

from .. import state
from ..schemas import (
    AdjournRequest,
    ContinueRequest,
    FeedbackRequest,
    MemberInfo,
    QueryRequest,
    RoleGapReviewRequest,
    RoutingSignalRequest,
)


router = APIRouter()

_DELIBERATE_REQUESTS: dict[str, deque[float]] = {}


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(0, value)


def _deliberate_bucket_key(request: Request) -> str:
    trust_proxy_header = os.getenv("AGENTIC_BOARD_TRUST_FORWARDED_FOR") == "1"
    if trust_proxy_header:
        xff = request.headers.get("x-forwarded-for", "").strip()
        if xff:
            # Left-most entry is the originating client; strip whitespace.
            first = xff.split(",", 1)[0].strip()
            if first:
                return first
    return request.client.host if request.client else "anon"


def _sweep_empty_deliberate_buckets() -> None:
    """Drop any buckets that emptied between requests. Call from request entry."""
    empties = [key for key, bucket in _DELIBERATE_REQUESTS.items() if not bucket]
    for key in empties:
        _DELIBERATE_REQUESTS.pop(key, None)


def _enforce_deliberate_rate_limit(request: Request) -> None:
    _sweep_empty_deliberate_buckets()
    limit = _positive_int_env("AGENTIC_BOARD_DELIBERATE_RATE_LIMIT", 5)
    window = _positive_int_env("AGENTIC_BOARD_DELIBERATE_RATE_WINDOW_SECONDS", 60)
    if limit <= 0:
        return

    bucket_key = _deliberate_bucket_key(request)
    bucket = _DELIBERATE_REQUESTS.setdefault(bucket_key, deque())
    now = time.monotonic()
    cutoff = now - window
    while bucket and bucket[0] <= cutoff:
        bucket.popleft()
    if len(bucket) >= limit:
        retry_after = max(1, int(bucket[0] + window - now) + 1)
        raise HTTPException(
            429,
            detail={"code": "rate_limited", "retry_after": retry_after},
            headers={"Retry-After": str(retry_after)},
        )
    bucket.append(now)
    # After append, bucket is non-empty by construction; no eviction needed here.


SESSION_ID_PATTERN = re.compile(r"^board_\d+$")


def _public_error_payload(exc: Exception, *, default_code: str = BoardErrorCode.DELIBERATION_FAILED) -> dict[str, str]:
    raw = str(exc)
    normalized = raw.lower()
    if "content_filter" in normalized or "considered high risk" in normalized:
        return {
            "code": "content_filter",
            "message": (
                "A model provider content filter rejected part of the board prompt. "
                "The request was not completed; rephrase ambiguous wording and try again."
            ),
        }
    return {
        "code": default_code,
        "message": raw or "Deliberation failed.",
    }


def _validate_session_id(session_id: str) -> None:
    """Reject any session_id that escapes the sessions directory."""
    if not SESSION_ID_PATTERN.match(session_id):
        raise HTTPException(
            400,
            detail={
                "code": "invalid_session_id",
                "message": "session_id must match ^board_\\d+$",
            },
        )


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
async def deliberate(req: QueryRequest, request: Request):
    _enforce_deliberate_rate_limit(request)
    if req.discussion_mode == "live":
        conversation = LiveBoardConversation()
        try:
            session = await conversation.discuss(
                req.query,
                member_ids=req.member_ids,
                skip_classify=req.full_board,
                verify=req.verify,
                session_id=req.session_id,
                initiative_id=req.initiative_id,
                initiative_mode=req.initiative_mode,
                clarification_answers=req.clarification_answers,
            )
        except BoardDeliberationError as e:
            payload = _public_error_payload(e)
            raise HTTPException(503, detail=payload) from e
        return session.to_dict()

    orchestrator = BoardOrchestrator()
    try:
        session = await orchestrator.deliberate(
            req.query,
            member_ids=req.member_ids,
            skip_classify=req.full_board,
            verify=req.verify,
            session_id=req.session_id,
            initiative_id=req.initiative_id,
            initiative_mode=req.initiative_mode,
            clarification_answers=req.clarification_answers,
        )
    except BoardDeliberationError as e:
        payload = _public_error_payload(e)
        raise HTTPException(
            503,
            detail=payload,
        ) from e
    return session.to_dict()


@router.post("/deliberate/stream")
async def deliberate_stream(req: QueryRequest, request: Request):
    _enforce_deliberate_rate_limit(request)
    queue: asyncio.Queue[dict] = asyncio.Queue()

    def on_stage_start(stage, name):
        queue.put_nowait({"event": "stage_start", "stage": stage, "name": name})

    def on_member_started(stage, member):
        queue.put_nowait({
            "event": "member_speaking",
            "stage": stage,
            "member_id": member.id,
            "member_title": member.title,
        })

    def on_council_selected(member_ids, chairman_id):
        queue.put_nowait({
            "event": "council_selected",
            "member_ids": list(member_ids or []),
            "chairman_id": chairman_id,
        })

    def on_phase(phase, message):
        queue.put_nowait({
            "event": "phase_change",
            "phase": phase,
            "message": message,
        })

    def on_member_done(stage, member, resp, error=None):
        if error:
            payload = _public_error_payload(RuntimeError(str(error)))
            queue.put_nowait({
                "event": "member_failed",
                "stage": stage,
                "member_id": member.id,
                "member_title": member.title,
                "error": payload["message"],
                "code": payload["code"],
            })
        else:
            queue.put_nowait({
                "event": "member_done",
                "stage": stage,
                "member_id": member.id,
                "member_title": member.title,
                "model": resp.model,
                "elapsed": resp.elapsed_seconds,
                "content": resp.content,
            })

    def on_stage_done(stage, responses):
        count = len(responses) if isinstance(responses, list) else 1
        queue.put_nowait({"event": "stage_done", "stage": stage, "count": count})

    def on_intake_card(card):
        queue.put_nowait({"event": "intake_card", "card": card})

    def on_clarification_required(clarification):
        queue.put_nowait({"event": "clarification_required", "clarification": clarification})

    def on_clarification_answered(clarification):
        queue.put_nowait({"event": "clarification_answered", "clarification": clarification})

    def on_structured_output_warning(warning):
        queue.put_nowait({"event": "structured_output_warning", "warning": warning})

    def on_live_event(event):
        queue.put_nowait(event)

    async def event_generator():
        if req.discussion_mode == "live":
            conversation = LiveBoardConversation(on_event=on_live_event)
            task = asyncio.create_task(
                conversation.discuss(
                    req.query,
                    member_ids=req.member_ids,
                    skip_classify=req.full_board,
                    verify=req.verify,
                    session_id=req.session_id,
                    initiative_id=req.initiative_id,
                    initiative_mode=req.initiative_mode,
                    clarification_answers=req.clarification_answers,
                )
            )
        else:
            orchestrator = BoardOrchestrator(
                on_stage_start=on_stage_start,
                on_member_started=on_member_started,
                on_member_done=on_member_done,
                on_stage_done=on_stage_done,
                on_intake_card=on_intake_card,
                on_clarification_required=on_clarification_required,
                on_clarification_answered=on_clarification_answered,
                on_structured_output_warning=on_structured_output_warning,
                on_council_selected=on_council_selected,
                on_phase=on_phase,
            )

            task = asyncio.create_task(
                orchestrator.deliberate(
                    req.query,
                    member_ids=req.member_ids,
                    skip_classify=req.full_board,
                    verify=req.verify,
                    session_id=req.session_id,
                    initiative_id=req.initiative_id,
                    initiative_mode=req.initiative_mode,
                    clarification_answers=req.clarification_answers,
                )
            )

        try:
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
                payload = _public_error_payload(e)
                yield f"data: {json.dumps({'event': 'error', **payload})}\n\n"
            except (asyncio.CancelledError, Exception) as e:
                if isinstance(e, asyncio.CancelledError):
                    # Graceful shutdown — client disconnected or server stopping
                    yield f"data: {json.dumps({'event': 'cancelled', 'message': 'Stream cancelled.'})}\n\n"
                    return
                payload = _public_error_payload(e, default_code="unexpected_error")
                yield f"data: {json.dumps({'event': 'error', **payload})}\n\n"
        except (asyncio.CancelledError, Exception) as e:
            if isinstance(e, asyncio.CancelledError):
                # Top-level cancellation during streaming (e.g. SIGINT / Ctrl-C)
                # Silently exit — this is expected shutdown behaviour.
                return
            raise

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/sessions/{session_id:path}/continue")
async def continue_meeting(
    session_id: str = Path(..., description="Board session id matching ^board_\\d+$"),
    req: ContinueRequest = ...,  # type: ignore[assignment]
    request: Request = ...,  # type: ignore[assignment]
):
    """Resume a meeting waiting on the CEO with a follow-up message."""
    _enforce_deliberate_rate_limit(request)
    _validate_session_id(session_id)

    if not req.user_input or not req.user_input.strip():
        raise HTTPException(400, detail="user_input must be non-empty")

    session_path = None
    for dirname in ("data/sessions", "data/conversations"):
        candidate = FilePath(f"{dirname}/{session_id}.json")
        if candidate.exists():
            session_path = candidate
            break
    if session_path is None:
        raise HTTPException(404, detail="Session not found")

    data = json.loads(session_path.read_text())
    if data.get("status") != "awaiting_chair_decision":
        raise HTTPException(
            409,
            detail=f"Session is in status '{data.get('status')}'; cannot continue.",
        )

    # Re-hydrate BoardSession from persisted JSON.
    from server.board.deliberation.orchestrator import BoardSession, MemberResponse

    def _resp_from_dict(d: dict | None) -> MemberResponse | None:
        if not d:
            return None
        return MemberResponse(
            member_id=d["member_id"], stage=d["stage"], content=d["content"],
            model=d["model"], elapsed_seconds=d["elapsed_seconds"],
        )

    session = BoardSession(session_id=data["session_id"], user_query=data["user_query"])
    session.initiative_id = data.get("initiative_id")
    session.initiative_mode = data.get("initiative_mode", "ad_hoc")
    session.continuation_count = int(data.get("continuation_count", 0))
    session.secretary_briefs = [
        _resp_from_dict(b) for b in (data.get("secretary_briefs") or []) if b is not None
    ]
    session.conversation = data.get("conversation") or {"messages": [], "routing_trace": []}
    session.status = data.get("status", "awaiting_chair_decision")
    # (Other fields like stage1/stage2/stage3 are not required for live continuation.)

    # Restore the original council selection so continuation rounds don't use the full roster.
    selected_ids: list[str] = list(data.get("selected_council_ids") or [])
    session.selected_council_ids = selected_ids

    # Cap check happens both here (for HTTP semantics) and inside discuss() (for direct callers).
    max_continuations = _positive_int_env("AGENTIC_BOARD_LIVE_MAX_CONTINUATIONS", 2)
    if session.continuation_count >= max_continuations:
        raise HTTPException(
            status_code=429,
            detail={
                "event": "meeting_capped",
                "session_id": session_id,
                "continuation_count": session.continuation_count,
                "max_continuations": max_continuations,
                "message": "Continuation cap reached. Adjourn to finalize.",
            },
        )

    queue: asyncio.Queue[dict] = asyncio.Queue()

    def on_event(event: dict) -> None:
        queue.put_nowait(event)

    async def event_generator():
        conversation = LiveBoardConversation(on_event=on_event)
        if selected_ids:
            from server.board.config import get_members_by_id
            members_by_id = get_members_by_id()
            conversation.council = [
                members_by_id[mid] for mid in selected_ids
                if mid in members_by_id and mid != conversation.chairperson.id
            ]
        task = asyncio.create_task(
            conversation.discuss(
                req.user_input,
                existing_session=session,
            )
        )

        try:
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
                resumed = task.result()
                # Persist the updated session so a subsequent /continue or /adjourn sees it.
                resumed.save()
                yield f"data: {json.dumps({'event': 'complete', 'session': resumed.to_dict()})}\n\n"
            except Exception as e:
                payload = _public_error_payload(e, default_code="unexpected_error")
                yield f"data: {json.dumps({'event': 'error', **payload})}\n\n"
        except asyncio.CancelledError:
            return

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/sessions/{session_id:path}/adjourn")
async def adjourn_meeting(
    session_id: str = Path(..., description="Board session id matching ^board_\\d+$"),
    req: AdjournRequest = ...,  # type: ignore[assignment]
):
    """Mark a meeting adjourned. Idempotent."""
    _validate_session_id(session_id)

    session_path = None
    for dirname in ("data/sessions", "data/conversations"):
        candidate = FilePath(f"{dirname}/{session_id}.json")
        if candidate.exists():
            session_path = candidate
            break
    if session_path is None:
        raise HTTPException(404, detail="Session not found")

    data = json.loads(session_path.read_text())
    current_status = data.get("status")

    # Idempotent: already-adjourned sessions are returned as-is.
    if current_status == "adjourned":
        return {
            "session_id": session_id,
            "status": "adjourned",
            "final_brief": data.get("secretary_brief"),
        }

    if current_status != "awaiting_chair_decision":
        raise HTTPException(
            409,
            detail=f"Session is in status '{current_status}'; can only adjourn from 'awaiting_chair_decision'.",
        )

    if req.ceo_decision and req.ceo_decision.strip():
        messages = data.setdefault("conversation", {"messages": [], "routing_trace": []}).setdefault("messages", [])
        messages.append({
            "id": f"user_{len(messages)}",
            "turn_index": len(messages),
            "member_id": "chairperson",
            "member_title": "CEO / Chairperson",
            "role": "CEO",
            "speaker": "user",
            "content": req.ceo_decision.strip(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    data["status"] = "adjourned"
    session_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    return {
        "session_id": session_id,
        "status": "adjourned",
        "final_brief": data.get("secretary_brief"),
    }


@router.get("/sessions")
async def list_sessions():
    sessions = []
    for dirname in ("data/sessions", "data/conversations"):
        path = FilePath(dirname)
        if path.exists():
            sessions.extend(f.stem for f in path.glob("*.json"))
    return sorted(set(sessions), reverse=True)


# NOTE: The sub-routes (/adapter, /delegation-plan, /feedback, /routing-signal)
# MUST be declared before the greedy /sessions/{session_id:path} base route. If
# the base route is declared first, it swallows the sub-paths as part of
# session_id and the path-traversal validator still fires, but the real
# sub-handlers are never reached. Do NOT reorder these routes alphabetically or
# for any other cosmetic reason.
@router.get("/sessions/{session_id:path}/adapter")
async def get_session_adapter(
    session_id: str = Path(..., description="Board session id matching ^board_\\d+$"),
):
    _validate_session_id(session_id)
    for dirname in ("data/sessions", "data/conversations"):
        filepath = FilePath(f"{dirname}/{session_id}.json")
        if filepath.exists():
            return adapt_session_record(json.loads(filepath.read_text()))
    raise HTTPException(404, "Session not found")


@router.get("/sessions/{session_id:path}/delegation-plan")
async def get_session_delegation_plan(
    session_id: str = Path(..., description="Board session id matching ^board_\\d+$"),
):
    _validate_session_id(session_id)
    persisted = get_delegation_plan(session_id)
    if persisted.get("tasks"):
        return persisted

    for dirname in ("data/sessions", "data/conversations"):
        filepath = FilePath(f"{dirname}/{session_id}.json")
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


@router.post("/sessions/{session_id:path}/feedback")
async def feedback(
    session_id: str = Path(..., description="Board session id matching ^board_\\d+$"),
    req: FeedbackRequest = ...,  # type: ignore[assignment]
):
    _validate_session_id(session_id)
    if req.rating not in ("positive", "negative"):
        raise HTTPException(422, detail="rating must be 'positive' or 'negative'")
    if req.note and len(req.note) > 500:
        raise HTTPException(422, detail="note must be 500 characters or fewer")

    try:
        record_feedback(session_id, req.rating, note=req.note, db_path=state._FEEDBACK_DB_PATH)
    except LedgerError:
        raise HTTPException(404, detail=f"Session not found: {session_id}")

    return {"status": "recorded", "session_id": session_id}


@router.post("/sessions/{session_id:path}/routing-signal")
async def routing_signal(
    session_id: str = Path(..., description="Board session id matching ^board_\\d+$"),
    req: RoutingSignalRequest = ...,  # type: ignore[assignment]
):
    _validate_session_id(session_id)

    # Verify member_id is a known roster ID
    member_ids = {m.id for m in BOARD_MEMBERS}
    if req.member_id not in member_ids:
        raise HTTPException(422, detail=f"unknown member_id: {req.member_id}")

    try:
        record_routing_signal(
            session_id,
            req.member_id,
            req.source,
            db_path=state._FEEDBACK_DB_PATH,
        )
    except LedgerError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(404, detail="session not found") from exc
        raise HTTPException(422, detail=msg) from exc

    return {
        "status": "recorded",
        "session_id": session_id,
        "member_id": req.member_id,
        "source": req.source,
    }


@router.get("/sessions/{session_id:path}")
async def get_session(
    session_id: str = Path(..., description="Board session id matching ^board_\\d+$"),
):
    _validate_session_id(session_id)
    for dirname in ("data/sessions", "data/conversations"):
        filepath = FilePath(f"{dirname}/{session_id}.json")
        if filepath.exists():
            return json.loads(filepath.read_text())
    raise HTTPException(404, "Session not found")


@router.post("/role-gap/review")
async def role_gap_review(req: RoleGapReviewRequest):
    return review_role_gap(
        req.missing_capabilities,
        query=req.query or "",
        stage_profile=req.stage_profile,
        recurrence_count=req.recurrence_count,
    )
