"""Explicit board start for promoted discovery candidates."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable


class BoardStartError(ValueError):
    pass


async def start_board(
    candidate: dict[str, Any],
    *,
    orchestrator: Any,
    save_candidate: Callable[[dict[str, Any]], Any],
    verify: bool = False,
    mode: str | None = None,
    new_session: bool = False,
    record_session_fn: Callable[[Any], Any] | None = None,
) -> Any:
    """Start one evidence-grounded session, returning an existing one on retry."""
    is_v2 = candidate.get("schema_version") == 2
    eligible = (
        candidate.get("discovery_status") == "reviewed" and candidate.get("promotion")
        if is_v2 else candidate.get("status") in {"promoted", "board_started"}
    )
    if not eligible:
        raise BoardStartError("only promoted candidates can start the board")
    if mode not in {None, "fast", "standard", "deep"}:
        raise BoardStartError("mode must be fast, standard, or deep")
    promotion = candidate.get("promotion") or {}
    for field in ("id", "venture_id", "evidence_packet_id"):
        if not promotion.get(field):
            raise BoardStartError(f"promotion {field} is required")

    attempts = candidate.setdefault("board_sessions", [])
    completed = [item for item in attempts if item.get("status") == "completed"]
    if completed and not new_session:
        return completed[-1]

    session_id = f"board_{time.time_ns()}"
    now = _utc_now()
    attempt = {"session_id": session_id, "status": "starting", "started_at": now, "finished_at": None}
    attempts.append(attempt)
    candidate["updated_at"] = now
    save_candidate(candidate)

    question = build_board_question(candidate, promotion, mode=mode)
    try:
        session = await orchestrator.deliberate(
            question,
            verify=verify,
            session_id=session_id,
            venture_id=promotion["venture_id"],
        )
        session.discovery_candidate_id = candidate["id"]
        session.discovery_promotion_id = promotion["id"]
        session.evidence_packet_id = promotion["evidence_packet_id"]
        if hasattr(session, "save"):
            session.save()
        if record_session_fn:
            record_session_fn(session)
        else:
            from server.harness.ledger import record_discovery_provenance
            record_discovery_provenance(session)
        attempt["status"] = "completed" if getattr(session, "status", "completed") == "completed" else "failed"
        if attempt["status"] != "completed":
            raise BoardStartError("board deliberation did not complete")
        promotion.setdefault("board_session_id", session_id)
        if is_v2:
            candidate["validation_state"] = "validating"
        else:
            candidate["status"] = "board_started"
        return session
    except BaseException as exc:
        attempt["status"] = "failed"
        attempt["error"] = str(exc)[:500]
        raise
    finally:
        attempt["finished_at"] = _utc_now()
        candidate["updated_at"] = attempt["finished_at"]
        save_candidate(candidate)


def build_board_question(
    candidate: dict[str, Any], promotion: dict[str, Any], *, mode: str | None = None
) -> str:
    """Build a bounded prompt; raw discovery records are intentionally excluded."""
    def clipped(key: str, limit: int) -> str:
        value = " ".join(str(candidate.get(key) or "").split())
        return value[:limit]

    return (
        "Evaluate whether and how the selected venture should pursue this evidence-backed opportunity.\n\n"
        f"Candidate: {clipped('title', 200)}\n"
        f"Audience: {clipped('audience', 300)}\n"
        f"Pain class: {clipped('pain_class', 80)}\n"
        f"Summary: {clipped('summary', 1200)}\n"
        f"Evidence packet: {promotion['evidence_packet_id']}\n\n"
        + (f"Requested deliberation depth: {mode}.\n" if mode else "")
        + "Use only the supplied evidence. Identify the strongest and weakest evidence, the target "
        "customer and urgent job, the smallest validation experiment, material risks, and stop conditions."
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
