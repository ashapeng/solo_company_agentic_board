"""Compatibility exports for `server.api:app` and direct route tests."""

from __future__ import annotations

from server.board.deliberation.orchestrator import BoardDeliberationError, BoardOrchestrator

from . import state
from .app import app, enforce_local_only
from .routes.board import (
    deliberate,
    deliberate_stream,
    get_session,
    get_session_adapter,
    get_session_delegation_plan,
    list_members,
    list_sessions,
    role_gap_review,
)
from .routes.board import feedback as _feedback
from .routes.execution import (
    approve_task,
    attach_artifact,
    create_evidence,
    delegated_task,
    execution_agent,
    execution_agents,
    execution_units,
    plan_task,
    read_evidence,
    update_task_status,
)
from .routes.harness import (
    apply_harness_review_endpoint,
    approve_harness_review_endpoint,
    latest_harness_review_endpoint,
    run_harness_review_endpoint,
)
from .routes.memory import get_sotb, review_sotb, update_sotb
from .routes.system import metrics_summary, root
from .schemas import (
    EvidencePacketRequest,
    FeedbackRequest,
    HarnessReviewApprovalRequest,
    HarnessReviewRunRequest,
    MemberInfo,
    QueryRequest,
    RoleGapReviewRequest,
    SotbReviewRequest,
    SotbUpdate,
    TaskApprovalRequest,
    TaskArtifactRequest,
    TaskPlanRequest,
    TaskStatusRequest,
)

_FEEDBACK_DB_PATH = state._FEEDBACK_DB_PATH


async def feedback(session_id: str, req: FeedbackRequest):
    """Compatibility wrapper honoring `server.api._FEEDBACK_DB_PATH` patches."""
    state._FEEDBACK_DB_PATH = _FEEDBACK_DB_PATH
    return await _feedback(session_id, req)


__all__ = [
    "BoardDeliberationError",
    "BoardOrchestrator",
    "EvidencePacketRequest",
    "FeedbackRequest",
    "HarnessReviewApprovalRequest",
    "HarnessReviewRunRequest",
    "MemberInfo",
    "QueryRequest",
    "RoleGapReviewRequest",
    "SotbReviewRequest",
    "SotbUpdate",
    "TaskApprovalRequest",
    "TaskArtifactRequest",
    "TaskPlanRequest",
    "TaskStatusRequest",
    "_FEEDBACK_DB_PATH",
    "app",
    "apply_harness_review_endpoint",
    "approve_harness_review_endpoint",
    "approve_task",
    "attach_artifact",
    "create_evidence",
    "delegated_task",
    "deliberate",
    "deliberate_stream",
    "enforce_local_only",
    "execution_agent",
    "execution_agents",
    "execution_units",
    "feedback",
    "get_session",
    "get_session_adapter",
    "get_session_delegation_plan",
    "get_sotb",
    "latest_harness_review_endpoint",
    "list_members",
    "list_sessions",
    "metrics_summary",
    "plan_task",
    "read_evidence",
    "review_sotb",
    "role_gap_review",
    "root",
    "run_harness_review_endpoint",
    "update_sotb",
    "update_task_status",
]
