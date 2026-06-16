"""Execution unit, task, and evidence routes."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request

from server.execution import (
    ExecutionError,
    approve_delegated_task,
    approve_external_action,
    attach_task_artifact,
    create_evidence_packet,
    get_delegated_task,
    get_evidence_packet,
    get_execution_agent,
    list_execution_agents,
    list_execution_units,
    plan_delegated_task,
    update_delegated_task_status,
    web_search,
)

from ..schemas import (
    EvidencePacketRequest,
    ExternalActionApprovalRequest,
    TaskApprovalRequest,
    TaskArtifactRequest,
    TaskPlanRequest,
    TaskStatusRequest,
    WebSearchRequest,
)


router = APIRouter()


@router.get("/execution-units")
async def execution_units():
    return list_execution_units()


@router.get("/execution-agents")
async def execution_agents():
    return list_execution_agents()


@router.get("/execution-agents/{agent_id}")
async def execution_agent(agent_id: str):
    agent = get_execution_agent(agent_id)
    if not agent:
        raise HTTPException(404, detail=f"Execution agent not found: {agent_id}")
    return agent


@router.get("/delegated-tasks/{task_id}")
async def delegated_task(task_id: str):
    task = get_delegated_task(task_id)
    if not task:
        raise HTTPException(404, detail=f"Delegated task not found: {task_id}")
    return task


@router.post("/delegated-tasks/{task_id}/run")
async def run_task_endpoint(task_id: str):
    from server.execution.runner import run_task

    try:
        result = await run_task(task_id)
    except ExecutionError as e:
        raise HTTPException(400, detail=str(e))
    if result.get("status") == "not_found":
        raise HTTPException(404, detail=f"Delegated task not found: {task_id}")
    return result


@router.post("/delegated-tasks/{task_id}/approve")
async def approve_task(task_id: str, req: TaskApprovalRequest):
    try:
        return approve_delegated_task(task_id, approve=req.approve)
    except ExecutionError as e:
        raise HTTPException(422, detail=str(e))


@router.post("/delegated-tasks/{task_id}/approve-external-action")
async def approve_task_external_action(task_id: str, req: ExternalActionApprovalRequest):
    try:
        return approve_external_action(task_id, approve=req.approve)
    except ExecutionError as e:
        raise HTTPException(422, detail=str(e))


@router.post("/delegated-tasks/{task_id}/plan")
async def plan_task(task_id: str, req: TaskPlanRequest):
    try:
        return plan_delegated_task(
            task_id,
            manager_agent_id=req.manager_agent_id,
            subtask_plan=req.subtask_plan,
        )
    except ExecutionError as e:
        raise HTTPException(422, detail=str(e))


@router.post("/delegated-tasks/{task_id}/status")
async def update_task_status(task_id: str, req: TaskStatusRequest):
    try:
        return update_delegated_task_status(
            task_id,
            status=req.status,
            manager_agent_id=req.manager_agent_id,
            status_detail=req.status_detail,
            result_summary=req.result_summary,
            artifacts=req.artifacts,
        )
    except ExecutionError as e:
        raise HTTPException(422, detail=str(e))


@router.post("/delegated-tasks/{task_id}/artifacts")
async def attach_artifact(task_id: str, req: TaskArtifactRequest):
    try:
        return attach_task_artifact(task_id, artifact=req.artifact)
    except ExecutionError as e:
        raise HTTPException(422, detail=str(e))


@router.post("/evidence-packets")
async def create_evidence(req: EvidencePacketRequest):
    if not req.topic.strip():
        raise HTTPException(422, detail="topic is required")
    return create_evidence_packet(
        topic=req.topic,
        claims=req.claims,
        sources=req.sources,
        freshness=req.freshness,
        warnings=req.warnings,
    )


@router.get("/evidence-packets/{packet_id}")
async def read_evidence(packet_id: str):
    packet = get_evidence_packet(packet_id)
    if not packet:
        raise HTTPException(404, detail=f"Evidence packet not found: {packet_id}")
    return packet


@router.post("/web-search")
async def execution_web_search(req: WebSearchRequest, request: Request):
    if not req.query.strip():
        raise HTTPException(422, detail="query is required")
    client_host = request.client.host if request.client else "anon"
    result = await web_search(
        req.query,
        provider=req.provider,
        max_results=req.max_results,
        session_id=f"ip:{client_host}",
    )
    warnings = result.get("warnings", []) or []
    if any("rate limit" in w.lower() for w in warnings):
        raise HTTPException(
            429,
            detail={
                "code": "web_search_rate_limited",
                "message": "; ".join(warnings),
            },
        )
    return result
