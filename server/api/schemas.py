"""Pydantic request/response models for the Agentic Board API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    query: str
    session_id: str | None = None
    venture_id: str | None = None
    initiative_id: str | None = None
    initiative_mode: Literal["ad_hoc", "attach", "create_draft"] = "ad_hoc"
    member_ids: list[str] | None = None
    full_board: bool = False
    verify: bool = False
    clarification_answers: dict | None = None
    discussion_mode: Literal["staged", "live"] = "staged"


class WebSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=300)
    provider: Literal["disabled", "fake", "tavily"] | None = None
    max_results: int = Field(default=5, ge=1, le=10)


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


class RoutingSignalRequest(BaseModel):
    member_id: str
    source: Literal["manual_add", "missing_voice_flag"]


class TaskApprovalRequest(BaseModel):
    approve: bool = True


class ExternalActionApprovalRequest(BaseModel):
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


class InitiativeCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    objective: str = Field(min_length=1, max_length=2000)
    success_criteria: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)
    created_from: Literal["manual", "founder_command", "board_suggestion"] = "manual"
    source_session_id: str | None = None
    timebox_start: str | None = None
    timebox_end: str | None = None


class InitiativeUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    objective: str | None = Field(default=None, min_length=1, max_length=2000)
    success_criteria: list[str] | None = None
    departments: list[str] | None = None
    timebox_start: str | None = None
    timebox_end: str | None = None


class InitiativeActivateRequest(BaseModel):
    approve: bool = True


class InitiativeLinkRequest(BaseModel):
    target_type: Literal["sotb_entry", "initiative", "board_session", "delegated_task", "artifact"]
    target_id: str = Field(min_length=1, max_length=300)
    relationship: Literal["context", "output", "carryover", "evidence", "artifact"]


class InitiativeCloseoutRequest(BaseModel):
    founder_outcome: Literal["success", "failure", "mixed"]
    founder_notes: str = ""
    retrospective_session_id: str | None = None
    memory_proposals: list[str] = Field(default_factory=list)
    carryover_decisions: list[dict[str, Any]] = Field(default_factory=list)


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


class HarnessValidateRequest(BaseModel):
    candidate: dict | None = None


class ContinueRequest(BaseModel):
    user_input: str

class AdjournRequest(BaseModel):
    ceo_decision: str | None = None
