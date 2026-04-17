"""Pydantic request/response models for the Agentic Board API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str
    session_id: str | None = None
    member_ids: list[str] | None = None
    full_board: bool = False
    verify: bool = False


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


class TaskApprovalRequest(BaseModel):
    approve: bool = True


class TaskPlanRequest(BaseModel):
    manager_agent_id: str | None = None
    subtask_plan: dict | None = None


class TaskStatusRequest(BaseModel):
    status: str
    manager_agent_id: str | None = None
    status_detail: str | None = None
    result_summary: str | None = None
    artifacts: list[str] = Field(default_factory=list)


class TaskArtifactRequest(BaseModel):
    artifact: str


class EvidencePacketRequest(BaseModel):
    topic: str
    claims: list[str] = Field(default_factory=list)
    sources: list[dict] = Field(default_factory=list)
    freshness: str = "unknown"
    warnings: list[str] = Field(default_factory=list)


class HarnessReviewRunRequest(BaseModel):
    dry_run: bool = True


class HarnessReviewApprovalRequest(BaseModel):
    approve: bool = True
