"""Initiative domain models and serialization helpers."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal


InitiativeStatus = Literal["draft", "active", "closed"]
ApprovalState = Literal["draft", "approved"]
CreatedFrom = Literal["manual", "founder_command", "board_suggestion"]
FounderOutcome = Literal["success", "failure", "mixed"]
LinkTargetType = Literal["sotb_entry", "initiative", "board_session", "delegated_task", "artifact"]
LinkRelationship = Literal["context", "output", "carryover", "evidence", "artifact"]
CarryoverDecisionValue = Literal["carry_over", "abandon", "backlog"]


class InitiativeError(Exception):
    """Raised when initiative state cannot be read or changed."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_timebox() -> tuple[str, str]:
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=7)
    return start.isoformat(), end.isoformat()


def json_list(value: Any) -> str:
    if value is None:
        items: list[Any] = []
    elif isinstance(value, list):
        items = value
    else:
        items = [value]
    return json.dumps(items, ensure_ascii=False)


def parse_json_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise InitiativeError("Stored list payload is not valid JSON.") from exc
    if not isinstance(parsed, list):
        raise InitiativeError("Stored list payload must be a JSON array.")
    return parsed


@dataclass
class Initiative:
    id: str
    title: str
    objective: str
    success_criteria: list[str] = field(default_factory=list)
    departments: list[str] = field(default_factory=list)
    timebox_start: str = ""
    timebox_end: str = ""
    status: InitiativeStatus = "draft"
    approval_state: ApprovalState = "draft"
    created_from: CreatedFrom = "manual"
    source_session_id: str | None = None
    venture_id: str = "default"
    created_at: str = ""
    updated_at: str = ""
    closeout: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.closeout is None:
            payload.pop("closeout", None)
        return payload


@dataclass
class InitiativeLink:
    id: str
    initiative_id: str
    target_type: str
    target_id: str
    relationship: str
    created_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InitiativeCloseout:
    initiative_id: str
    founder_outcome: str
    founder_notes: str
    retrospective_session_id: str | None = None
    memory_proposals: list[str] = field(default_factory=list)
    carryover_decisions: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
