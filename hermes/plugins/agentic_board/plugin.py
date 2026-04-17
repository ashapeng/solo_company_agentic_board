"""Minimal local-only Agentic Board plugin scaffold.

This module intentionally avoids depending on Hermes internals. It defines the typed tool
boundary that can be registered with Hermes after the local skill has been proven in real use.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from .schemas import (
    DeliberateRequest,
    SotbProposalRequest,
    TaskApprovalRequest,
    TaskArtifactRequest,
    TaskPlanRequest,
    TaskStatusRequest,
)


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "name": "agentic_board_deliberate",
            "description": "Run local Agentic Board deliberation and return the session contract.",
            "requires_approval": False,
        },
        {
            "name": "agentic_board_list_members",
            "description": "List active local board members and capabilities.",
            "requires_approval": False,
        },
        {
            "name": "agentic_board_read_sotb",
            "description": "Read State of the Board memory.",
            "requires_approval": False,
        },
        {
            "name": "agentic_board_propose_sotb_update",
            "description": "Review a proposed SOTB update without applying it.",
            "requires_approval": True,
        },
        {
            "name": "agentic_board_list_execution_agents",
            "description": "List active manager agents for execution units.",
            "requires_approval": False,
        },
        {
            "name": "agentic_board_get_delegation_plan",
            "description": "Read a session's approval-gated delegation plan.",
            "requires_approval": False,
        },
        {
            "name": "agentic_board_approve_task",
            "description": "Approve or reject a delegated task before execution.",
            "requires_approval": True,
        },
        {
            "name": "agentic_board_plan_task",
            "description": "Create a manager-agent subtask plan for an approved task.",
            "requires_approval": False,
        },
        {
            "name": "agentic_board_update_task_status",
            "description": "Update delegated task status and execution summary.",
            "requires_approval": False,
        },
        {
            "name": "agentic_board_attach_task_artifact",
            "description": "Attach an artifact path or URL to a delegated task.",
            "requires_approval": False,
        },
    ]


async def agentic_board_deliberate(
    request: DeliberateRequest,
    *,
    base_url: str = DEFAULT_BASE_URL,
) -> dict[str, Any]:
    base = _local_base_url(base_url)
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(f"{base}/deliberate", json=request.to_dict())
        response.raise_for_status()
        return response.json()


async def agentic_board_list_members(*, base_url: str = DEFAULT_BASE_URL) -> list[dict[str, Any]]:
    base = _local_base_url(base_url)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(f"{base}/members")
        response.raise_for_status()
        return response.json()


async def agentic_board_read_sotb(*, base_url: str = DEFAULT_BASE_URL) -> dict[str, Any]:
    base = _local_base_url(base_url)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(f"{base}/sotb")
        response.raise_for_status()
        return response.json()


async def agentic_board_propose_sotb_update(
    request: SotbProposalRequest,
    *,
    base_url: str = DEFAULT_BASE_URL,
) -> dict[str, Any]:
    base = _local_base_url(base_url)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(f"{base}/sotb/review", json=request.to_dict())
        response.raise_for_status()
        return response.json()


async def agentic_board_list_execution_agents(*, base_url: str = DEFAULT_BASE_URL) -> list[dict[str, Any]]:
    base = _local_base_url(base_url)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(f"{base}/execution-agents")
        response.raise_for_status()
        return response.json()


async def agentic_board_get_delegation_plan(
    session_id: str,
    *,
    base_url: str = DEFAULT_BASE_URL,
) -> dict[str, Any]:
    base = _local_base_url(base_url)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(f"{base}/sessions/{session_id}/delegation-plan")
        response.raise_for_status()
        return response.json()


async def agentic_board_approve_task(
    task_id: str,
    request: TaskApprovalRequest,
    *,
    base_url: str = DEFAULT_BASE_URL,
) -> dict[str, Any]:
    base = _local_base_url(base_url)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(f"{base}/delegated-tasks/{task_id}/approve", json=request.to_dict())
        response.raise_for_status()
        return response.json()


async def agentic_board_plan_task(
    task_id: str,
    request: TaskPlanRequest,
    *,
    base_url: str = DEFAULT_BASE_URL,
) -> dict[str, Any]:
    base = _local_base_url(base_url)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(f"{base}/delegated-tasks/{task_id}/plan", json=request.to_dict())
        response.raise_for_status()
        return response.json()


async def agentic_board_update_task_status(
    task_id: str,
    request: TaskStatusRequest,
    *,
    base_url: str = DEFAULT_BASE_URL,
) -> dict[str, Any]:
    base = _local_base_url(base_url)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(f"{base}/delegated-tasks/{task_id}/status", json=request.to_dict())
        response.raise_for_status()
        return response.json()


async def agentic_board_attach_task_artifact(
    task_id: str,
    request: TaskArtifactRequest,
    *,
    base_url: str = DEFAULT_BASE_URL,
) -> dict[str, Any]:
    base = _local_base_url(base_url)
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(f"{base}/delegated-tasks/{task_id}/artifacts", json=request.to_dict())
        response.raise_for_status()
        return response.json()


def _local_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in LOCAL_HOSTS:
        raise ValueError("Agentic Board plugin only allows localhost API targets.")
    return base_url.rstrip("/")
