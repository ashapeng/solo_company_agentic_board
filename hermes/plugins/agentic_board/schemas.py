"""Typed request shapes for the Agentic Board Hermes plugin scaffold."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class DeliberateRequest:
    query: str
    member_ids: list[str] | None = None
    full_board: bool = False
    verify: bool = True
    session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SotbProposalRequest:
    proposed_sotb_update: str
    session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaskApprovalRequest:
    approve: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaskPlanRequest:
    manager_agent_id: str | None = None
    subtask_plan: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TaskStatusRequest:
    status: str
    manager_agent_id: str | None = None
    status_detail: str | None = None
    result_summary: str | None = None
    artifacts: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        if data["artifacts"] is None:
            data["artifacts"] = []
        return data


@dataclass
class TaskArtifactRequest:
    artifact: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
