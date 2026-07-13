"""Explicit, idempotent promotion of discovery candidates.

The service deliberately accepts a candidate mapping and a persistence callback so
the file-native lifecycle store remains the authority and this module does not
couple promotion to its on-disk implementation.
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from server.execution.evidence import create_evidence_packet
from server.ventures import create_venture, get_venture


class PromotionError(ValueError):
    pass


def promote_candidate(
    candidate: dict[str, Any],
    *,
    save_candidate: Callable[[dict[str, Any]], Any],
    venture_id: str | None = None,
    new_venture_name: str | None = None,
    ventures_db_path: Path | None = None,
    evidence_dir: Path | None = None,
    get_venture_fn: Callable[..., dict[str, Any] | None] = get_venture,
    create_venture_fn: Callable[..., dict[str, Any]] = create_venture,
    create_packet_fn: Callable[..., dict[str, Any]] = create_evidence_packet,
) -> dict[str, Any]:
    """Promote *candidate* without starting board deliberation."""
    if bool(venture_id) == bool(new_venture_name):
        raise PromotionError("choose exactly one of an existing or new venture")
    candidate_id = _required(candidate, "id")
    is_v2 = candidate.get("schema_version") == 2
    status = candidate.get("status") if not is_v2 else candidate.get("discovery_status")
    if candidate.get("board_label") == "reject" or status == "rejected":
        raise PromotionError("rejected candidates cannot be promoted")
    allowed = {"new", "shortlisted", "promoted"} if not is_v2 else {"ready_for_board", "reviewed"}
    if status not in allowed:
        raise PromotionError(f"candidate status {status!r} cannot be promoted")

    existing = candidate.get("promotion")
    if existing and venture_id:
        if existing.get("venture_id") == venture_id:
            return existing
        raise PromotionError("candidate has already been promoted to another venture")
    if existing and new_venture_name:
        prior = get_venture_fn(existing.get("venture_id"), db_path=ventures_db_path)
        if prior and str(prior.get("name") or "").strip() == str(new_venture_name).strip():
            return existing
        raise PromotionError("candidate has already been promoted to another venture")

    if venture_id:
        venture = get_venture_fn(venture_id, db_path=ventures_db_path)
        if not venture or venture.get("status") != "active":
            raise PromotionError(f"active venture not found: {venture_id}")
    else:
        name = str(new_venture_name or "").strip()
        if not name:
            raise PromotionError("new venture name must not be empty")
        venture = create_venture_fn(name, db_path=ventures_db_path)
    resolved_venture_id = str(venture.get("id") or venture.get("venture_id"))
    key = _digest(candidate_id, resolved_venture_id)

    quotes, sources, source_keys = _canonical_evidence(candidate.get("evidence") or [])
    packet = create_packet_fn(
        topic=str(candidate.get("title") or candidate_id),
        claims=[quote["quote"] for quote in quotes],
        sources=sources,
        discovery_candidate_id=candidate_id,
        report_digest=candidate.get("report_digest"),
        source_keys=source_keys,
        canonical_quotes=quotes,
        evidence_dir=evidence_dir,
    )
    now = _utc_now()
    promotion = {
        "id": f"promo_{time.time_ns()}",
        "candidate_id": candidate_id,
        "venture_id": resolved_venture_id,
        "evidence_packet_id": packet["id"],
        "idempotency_key": key,
        "promoted_at": now,
        "board_session_id": None,
    }
    candidate["promotion"] = promotion
    if is_v2:
        candidate["discovery_status"] = "reviewed"
        candidate["board_label"] = "prioritize"
        candidate["validation_state"] = "queued"
    else:
        candidate["status"] = "promoted"
    candidate["updated_at"] = now
    save_candidate(candidate)
    return promotion


def _canonical_evidence(items: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    quotes: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    keys: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("source_key") or item.get("post_key") or "")
        quote = str(item.get("quote") or item.get("snippet") or item.get("text") or "")
        url = str(item.get("url") or "")
        retrieved_at = str(item.get("retrieved_at") or item.get("retrieval_date") or "")
        title = str(item.get("title") or url or key or "Untitled source")
        if key and key not in keys:
            keys.append(key)
        quotes.append({
            "source_key": key, "quote": quote, "url": url,
            "retrieved_at": retrieved_at, "title": title,
        })
        sources.append({
            "title": title, "url": url, "retrieved_at": retrieved_at,
            "claim_ids": [key] if key else [],
        })
    return quotes, sources, keys


def _digest(candidate_id: str, venture_id: str) -> str:
    return "sha256:" + hashlib.sha256(f"{candidate_id}\0{venture_id}".encode()).hexdigest()


def _required(value: dict[str, Any], key: str) -> str:
    result = str(value.get(key) or "").strip()
    if not result:
        raise PromotionError(f"candidate {key} is required")
    return result


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
