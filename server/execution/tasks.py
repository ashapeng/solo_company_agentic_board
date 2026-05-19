"""Delegated task parsing and approval-gated task state."""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .agents import AGENTS_BY_ID, AGENTS_BY_UNIT


def _run_async_blocking(coro) -> Any:
    """Run an async coroutine from synchronous code.

    Fast path: when no event loop is running in this thread, use asyncio.run.
    Slow path: when a loop is running, spawn a fresh loop in a worker thread.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result_box: dict[str, Any] = {}

    def _worker():
        new_loop = asyncio.new_event_loop()
        try:
            result_box["value"] = new_loop.run_until_complete(coro)
        except BaseException as exc:  # noqa: BLE001
            result_box["error"] = exc
        finally:
            new_loop.close()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join()
    if "error" in result_box:
        raise result_box["error"]
    return result_box["value"]


def _hook_gate_sync(
    *,
    session_id: str,
    member_id: str | None,
    request: dict[str, Any],
) -> None:
    """Sync façade around dispatch_pre_hooks for tasks.py wraps.

    Raises HookDeniedError on deny; returns None on allow. Always records a
    hook_events row.
    """
    from server.harness.hooks import (
        HookContext, HookDeniedError, dispatch_pre_hooks,
    )
    from server.harness.ledger import record_hook_event

    ctx = HookContext(
        tool_name="delegated_task",
        stage=0,
        session_id=session_id or "anon",
        member_id=member_id,
        request=request,
    )
    verdict = _run_async_blocking(dispatch_pre_hooks(ctx))
    record_hook_event(
        session_id=ctx.session_id,
        tool_name="delegated_task",
        action=verdict.action,
        reason=verdict.reason,
        metadata=verdict.metadata,
    )
    if verdict.action == "deny":
        raise HookDeniedError(verdict.reason or "delegated_task denied")


def _hook_post_sync(
    *,
    session_id: str,
    member_id: str | None,
    request: dict[str, Any],
    result: dict[str, Any],
) -> None:
    """Sync façade around dispatch_post_hooks for tasks.py wraps."""
    from server.harness.hooks import HookContext, dispatch_post_hooks

    ctx = HookContext(
        tool_name="delegated_task",
        stage=0,
        session_id=session_id or "anon",
        member_id=member_id,
        request=request,
    )
    _run_async_blocking(dispatch_post_hooks(ctx, result))


DEFAULT_DB_PATH = Path("data/harness_ledger.db")
TASK_STATUSES = {"proposed", "approved", "running", "completed", "blocked", "rejected"}
SUBTASK_STATUSES = {"planned", "running", "completed", "blocked", "failed"}
PRIORITIES = {"p0", "p1", "p2"}
EXTERNAL_ACTION_TYPES = {"outreach", "publish", "deploy", "spend", "none"}

TASK_SCHEMA = """
CREATE TABLE IF NOT EXISTS delegated_tasks (
    task_id            TEXT PRIMARY KEY,
    session_id         TEXT NOT NULL,
    manager_agent_id   TEXT NOT NULL,
    execution_unit_id  TEXT NOT NULL,
    status             TEXT NOT NULL,
    payload            TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_delegated_tasks_session_id
ON delegated_tasks(session_id);
"""

BOARD_MEMBER_BY_UNIT = {
    "strategy": "strategist",
    "product": "product",
    "research": "researcher",
    "engineering": "architect",
    "security": "guardian",
    "operations": "operator",
    "marketing": "strategist",
    "finance": "chairperson",
    "legal": "critic",
}


class ExecutionError(Exception):
    """Raised when execution task state cannot be updated."""


@dataclass
class Subtask:
    id: str
    title: str
    objective: str
    assigned_subagent_template_id: str
    required_inputs: list[str]
    output_contract: str
    status: str = "planned"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SubtaskPlan:
    manager_agent_id: str
    subtasks: list[Subtask] = field(default_factory=list)
    coordination_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "manager_agent_id": self.manager_agent_id,
            "subtasks": [subtask.to_dict() for subtask in self.subtasks],
            "coordination_notes": self.coordination_notes,
        }


@dataclass
class DelegatedTask:
    id: str
    session_id: str
    title: str
    objective: str
    execution_unit_id: str
    manager_agent_id: str
    accountable_board_member_id: str
    priority: str = "p1"
    status: str = "proposed"
    acceptance_criteria: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    approval_required: bool = True
    subtask_plan: dict[str, Any] | None = None
    artifacts: list[str] = field(default_factory=list)
    source: str = "board_synthesis"
    result_summary: str = ""
    status_detail: str = ""
    initiative_id: str | None = None
    external_action_required: bool = False
    external_action_type: str = "none"
    external_action_approved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DelegationPlan:
    session_id: str
    initiative_id: str | None = None
    tasks: list[DelegatedTask] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    requires_approval: bool = True
    structured_output_failed: bool = False
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "initiative_id": self.initiative_id,
            "tasks": [task.to_dict() for task in self.tasks],
            "warnings": self.warnings,
            "requires_approval": self.requires_approval,
            "structured_output_failed": self.structured_output_failed,
            "truncated": self.truncated,
        }


def parse_delegation_plan(
    synthesis_content: str | None,
    *,
    session_id: str,
    initiative_id: str | None = None,
) -> dict[str, Any]:
    """Parse a chairman Delegation Plan section into a stable task contract."""
    warnings: list[str] = []
    section = _extract_markdown_section(synthesis_content or "", "Delegation Plan")
    if not section:
        return DelegationPlan(
            session_id=session_id,
            initiative_id=initiative_id,
            warnings=["No Delegation Plan section found in chair synthesis."],
        ).to_dict()

    payload = _parse_delegation_json(section)
    if payload is None:
        truncated = _looks_truncated_json(section)
        return DelegationPlan(
            session_id=session_id,
            initiative_id=initiative_id,
            warnings=["Delegation Plan section did not contain parseable JSON."],
            structured_output_failed=True,
            truncated=truncated,
        ).to_dict()

    raw_tasks = payload.get("tasks") if isinstance(payload, dict) else payload
    if not isinstance(raw_tasks, list):
        return DelegationPlan(
            session_id=session_id,
            initiative_id=initiative_id,
            warnings=["Delegation Plan JSON must be an object with tasks or a task array."],
            structured_output_failed=True,
        ).to_dict()

    tasks: list[DelegatedTask] = []
    for index, raw_task in enumerate(raw_tasks):
        if not isinstance(raw_task, dict):
            warnings.append(f"Skipped delegation task {index + 1}: not an object.")
            continue
        task = _normalize_delegated_task(
            raw_task,
            session_id=session_id,
            initiative_id=initiative_id,
            index=index,
        )
        if task is None:
            warnings.append(f"Skipped delegation task {index + 1}: missing title and objective.")
            continue
        tasks.append(task)

    if not tasks:
        warnings.append("Delegation Plan contained no valid tasks.")

    plan = DelegationPlan(
        session_id=session_id,
        initiative_id=initiative_id,
        tasks=tasks,
        warnings=warnings,
    ).to_dict()
    plan["initiative_id"] = initiative_id
    return plan


def default_subtask_plan(task: dict[str, Any]) -> dict[str, Any]:
    manager_id = str(task.get("manager_agent_id") or "")
    agent = AGENTS_BY_ID.get(manager_id)
    if not agent:
        raise ExecutionError(f"Unknown manager agent: {manager_id}")

    templates = agent.subagent_templates[: max(agent.max_parallel_subagents, 1)]
    task_id = str(task.get("id"))
    subtasks = [
        Subtask(
            id=f"{task_id}_{template.id}",
            title=template.title,
            objective=f"{template.purpose} for: {task.get('title', task_id)}",
            assigned_subagent_template_id=template.id,
            required_inputs=[task_id],
            output_contract=template.output_contract,
        )
        for template in templates
    ]

    return SubtaskPlan(
        manager_agent_id=manager_id,
        subtasks=subtasks,
        coordination_notes=(
            "The manager agent owns final synthesis. Temporary sub-agents are "
            "single-task workers and cannot spawn additional agents."
        ),
    ).to_dict()


def record_delegation_plan(plan: dict[str, Any], *, db_path: Path | None = None) -> None:
    tasks = plan.get("tasks") if isinstance(plan, dict) else None
    if not isinstance(tasks, list):
        return
    for task in tasks:
        if isinstance(task, dict):
            save_delegated_task(task, db_path=db_path)


def save_delegated_task(task: dict[str, Any], *, db_path: Path | None = None) -> dict[str, Any]:
    task_id = str(task.get("id") or "").strip()
    if not task_id:
        raise ExecutionError("Task id is required.")
    status = str(task.get("status") or "proposed")
    if status not in TASK_STATUSES:
        raise ExecutionError(f"Invalid task status: {status}")

    session_id = str(task.get("session_id") or "")
    _hook_gate_sync(
        session_id=session_id,
        member_id=None,
        request={"op": "save_delegated_task", "task_id": task_id, "status": status},
    )

    now = _utc_now()
    payload = dict(task)
    payload["id"] = task_id
    payload["status"] = status
    payload.setdefault("approval_required", True)
    payload.setdefault("artifacts", [])

    conn = _connect_tasks(db_path)
    try:
        existing = conn.execute(
            "SELECT created_at FROM delegated_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        created_at = existing["created_at"] if existing else now
        conn.execute(
            """INSERT OR REPLACE INTO delegated_tasks (
                task_id, session_id, manager_agent_id, execution_unit_id,
                status, payload, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                task_id,
                str(payload.get("session_id") or ""),
                str(payload.get("manager_agent_id") or ""),
                str(payload.get("execution_unit_id") or ""),
                status,
                json.dumps(payload, ensure_ascii=False),
                created_at,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    _hook_post_sync(
        session_id=session_id,
        member_id=None,
        request={"op": "save_delegated_task", "task_id": task_id, "status": status},
        result=payload,
    )
    return payload


def get_delegated_task(task_id: str, *, db_path: Path | None = None) -> dict[str, Any] | None:
    conn = _connect_tasks(db_path)
    try:
        row = conn.execute(
            "SELECT payload FROM delegated_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return json.loads(row["payload"])


def get_delegation_plan(session_id: str, *, db_path: Path | None = None) -> dict[str, Any]:
    conn = _connect_tasks(db_path)
    try:
        rows = conn.execute(
            "SELECT payload FROM delegated_tasks WHERE session_id = ? ORDER BY created_at, task_id",
            (session_id,),
        ).fetchall()
    finally:
        conn.close()
    tasks = [json.loads(row["payload"]) for row in rows]
    return {
        "session_id": session_id,
        "initiative_id": _initiative_id_for_tasks(tasks),
        "tasks": tasks,
        "warnings": [],
        "requires_approval": True,
    }


def get_delegated_tasks_for_initiative(
    initiative_id: str,
    *,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    conn = _connect_tasks(db_path)
    try:
        rows = conn.execute(
            "SELECT payload FROM delegated_tasks ORDER BY created_at, task_id",
        ).fetchall()
    finally:
        conn.close()
    return [
        task
        for row in rows
        if (task := json.loads(row["payload"])).get("initiative_id") == initiative_id
    ]


def approve_delegated_task(
    task_id: str,
    *,
    approve: bool = True,
    db_path: Path | None = None,
) -> dict[str, Any]:
    task = _load_required_task(task_id, db_path=db_path)
    if task["status"] not in {"proposed", "approved", "rejected"}:
        raise ExecutionError(f"Task cannot be approved from status: {task['status']}")
    task["status"] = "approved" if approve else "rejected"
    return save_delegated_task(task, db_path=db_path)


def approve_external_action(
    task_id: str,
    *,
    approve: bool = True,
    db_path: Path | None = None,
) -> dict[str, Any]:
    task = _load_required_task(task_id, db_path=db_path)
    if not _coerce_bool(task.get("external_action_required"), default=False):
        raise ExecutionError("Task does not require an external action.")
    task["external_action_approved"] = bool(approve)
    return save_delegated_task(task, db_path=db_path)


def plan_delegated_task(
    task_id: str,
    *,
    manager_agent_id: str | None = None,
    subtask_plan: dict[str, Any] | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    task = _load_required_task(task_id, db_path=db_path)
    _hook_gate_sync(
        session_id=str(task.get("session_id") or ""),
        member_id=None,
        request={
            "op": "plan_delegated_task",
            "task_id": task_id,
            "manager_agent_id": manager_agent_id,
            "has_subtask_plan": subtask_plan is not None,
        },
    )
    if task["status"] not in {"approved", "running"}:
        raise ExecutionError(f"Task must be approved before planning; current status: {task['status']}")
    if not manager_agent_id:
        raise ExecutionError("Manager agent id is required to plan this task.")
    if manager_agent_id != task.get("manager_agent_id"):
        raise ExecutionError("Only the assigned manager agent can plan this task.")

    plan = subtask_plan or default_subtask_plan(task)
    _validate_subtask_plan(plan, expected_manager_id=str(task.get("manager_agent_id") or ""))
    task["subtask_plan"] = plan
    task["status"] = "running"
    result = save_delegated_task(task, db_path=db_path)
    _hook_post_sync(
        session_id=str(task.get("session_id") or ""),
        member_id=None,
        request={"op": "plan_delegated_task", "task_id": task_id},
        result=result,
    )
    return result


def update_delegated_task_status(
    task_id: str,
    *,
    status: str,
    manager_agent_id: str | None = None,
    status_detail: str | None = None,
    result_summary: str | None = None,
    artifacts: list[str] | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    if status not in TASK_STATUSES:
        raise ExecutionError(f"Invalid task status: {status}")
    task = _load_required_task(task_id, db_path=db_path)
    _hook_gate_sync(
        session_id=str(task.get("session_id") or ""),
        member_id=None,
        request={
            "op": "update_delegated_task_status",
            "task_id": task_id,
            "new_status": status,
            "manager_agent_id": manager_agent_id,
        },
    )
    if status == "completed" and manager_agent_id != task.get("manager_agent_id"):
        raise ExecutionError("Only the assigned manager agent can complete this task.")
    if status == "running" and task.get("status") not in {"approved", "running"}:
        raise ExecutionError("Only approved tasks can run.")

    task["status"] = status
    if status_detail is not None:
        task["status_detail"] = status_detail
    if result_summary is not None:
        task["result_summary"] = result_summary
    if artifacts:
        task["artifacts"] = _dedupe([*(task.get("artifacts") or []), *artifacts])
    result = save_delegated_task(task, db_path=db_path)
    _hook_post_sync(
        session_id=str(task.get("session_id") or ""),
        member_id=None,
        request={
            "op": "update_delegated_task_status",
            "task_id": task_id,
            "new_status": status,
            "manager_agent_id": manager_agent_id,
        },
        result=result,
    )
    return result


def attach_task_artifact(
    task_id: str,
    *,
    artifact: str,
    db_path: Path | None = None,
) -> dict[str, Any]:
    task = _load_required_task(task_id, db_path=db_path)
    task["artifacts"] = _dedupe([*(task.get("artifacts") or []), artifact])
    return save_delegated_task(task, db_path=db_path)


def _normalize_delegated_task(
    raw: dict[str, Any],
    *,
    session_id: str,
    initiative_id: str | None,
    index: int,
) -> DelegatedTask | None:
    title = str(raw.get("title") or raw.get("task") or "").strip()
    objective = str(raw.get("objective") or raw.get("description") or "").strip()
    if not title and not objective:
        return None
    if not title:
        title = objective[:80]
    if not objective:
        objective = title

    unit_id = str(raw.get("execution_unit_id") or raw.get("execution_unit") or "").strip().lower()
    manager_id = str(raw.get("manager_agent_id") or raw.get("manager_agent") or "").strip()
    if manager_id in AGENTS_BY_ID:
        unit_id = AGENTS_BY_ID[manager_id].execution_unit_id
    if unit_id not in AGENTS_BY_UNIT:
        unit_id = _infer_execution_unit(f"{title} {objective}")
    agent = AGENTS_BY_UNIT[unit_id]
    manager_id = agent.id

    priority = str(raw.get("priority") or "p1").lower()
    if priority not in PRIORITIES:
        priority = "p1"
    status = str(raw.get("status") or "proposed").lower()
    if status not in TASK_STATUSES:
        status = "proposed"

    task_id = str(raw.get("id") or raw.get("task_id") or f"{session_id}_task_{index + 1}").strip()
    accountable = str(raw.get("accountable_board_member_id") or "").strip()
    if not accountable:
        accountable = BOARD_MEMBER_BY_UNIT.get(unit_id, "chairperson")

    external_type = str(raw.get("external_action_type") or "none").strip().lower()
    if external_type not in EXTERNAL_ACTION_TYPES:
        external_type = "none"
    external_required = _coerce_bool(
        raw.get("external_action_required"),
        default=external_type != "none",
    )
    external_approved = _coerce_bool(raw.get("external_action_approved"), default=False)
    task_initiative_id = initiative_id or raw.get("initiative_id")

    return DelegatedTask(
        id=task_id,
        session_id=session_id,
        title=title,
        objective=objective,
        execution_unit_id=unit_id,
        manager_agent_id=manager_id,
        accountable_board_member_id=accountable,
        priority=priority,
        status=status,
        acceptance_criteria=_string_list(raw.get("acceptance_criteria")),
        dependencies=_string_list(raw.get("dependencies")),
        approval_required=bool(raw.get("approval_required", agent.default_approval_required)),
        artifacts=_string_list(raw.get("artifacts")),
        source="board_synthesis",
        initiative_id=str(task_initiative_id) if task_initiative_id else None,
        external_action_required=external_required,
        external_action_type=external_type,
        external_action_approved=external_approved,
    )


def _parse_delegation_json(section: str) -> Any | None:
    fenced = re.search(r"```(?:json)?\s*(.*?)```", section, flags=re.DOTALL | re.IGNORECASE)
    raw = fenced.group(1).strip() if fenced else section.strip()
    candidates = [raw]

    first_obj = raw.find("{")
    last_obj = raw.rfind("}")
    if first_obj != -1 and last_obj > first_obj:
        candidates.append(raw[first_obj:last_obj + 1])
    first_arr = raw.find("[")
    last_arr = raw.rfind("]")
    if first_arr != -1 and last_arr > first_arr:
        candidates.append(raw[first_arr:last_arr + 1])

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _looks_truncated_json(section: str) -> bool:
    text = section.strip()
    if "```" in text and not re.search(r"```\s*$", text):
        return True
    raw = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()
    if raw.count("{") > raw.count("}") or raw.count("[") > raw.count("]"):
        return True
    if raw.count('"') % 2 == 1:
        return True
    return False


def _extract_markdown_section(markdown: str, heading: str) -> str:
    target = heading.lower()
    current: str | None = None
    lines: list[str] = []
    for line in markdown.splitlines():
        match = re.match(r"^\s{0,3}#{2,3}\s+(.+?)\s*$", line)
        if match:
            normalized = " ".join(match.group(1).strip().rstrip(":").split()).lower()
            if current == target:
                break
            current = normalized
            continue
        if current == target:
            lines.append(line)
    return "\n".join(lines).strip()


def _infer_execution_unit(text: str) -> str:
    lower = text.lower()
    keyword_map = [
        ("security", ["security", "privacy", "threat", "compliance", "auth"]),
        ("operations", ["release", "monitoring", "runbook", "incident", "deploy"]),
        ("research", ["research", "interview", "evidence", "customer", "source"]),
        ("product", ["mvp", "roadmap", "feature", "product", "pmf"]),
        ("marketing", ["marketing", "campaign", "outreach", "content", "distribution", "launch"]),
        ("strategy", ["market", "strategy", "positioning", "gtm", "competition"]),
        ("engineering", ["build", "implementation", "architecture", "technical", "code"]),
    ]
    for unit, keywords in keyword_map:
        if any(keyword in lower for keyword in keywords):
            return unit
    return "engineering"


def _validate_subtask_plan(plan: dict[str, Any], *, expected_manager_id: str) -> None:
    if not isinstance(plan, dict):
        raise ExecutionError("Subtask plan must be an object.")
    if plan.get("manager_agent_id") != expected_manager_id:
        raise ExecutionError("Subtask plan manager does not match task manager.")
    agent = AGENTS_BY_ID.get(expected_manager_id)
    if not agent:
        raise ExecutionError(f"Unknown manager agent: {expected_manager_id}")
    subtasks = plan.get("subtasks")
    if not isinstance(subtasks, list):
        raise ExecutionError("Subtask plan requires a subtasks array.")
    if len(subtasks) > agent.max_parallel_subagents:
        raise ExecutionError("Subtask plan exceeds the manager agent parallel sub-agent limit.")
    template_ids = {template.id for template in agent.subagent_templates}
    for subtask in subtasks:
        if not isinstance(subtask, dict):
            raise ExecutionError("Each subtask must be an object.")
        status = str(subtask.get("status") or "planned")
        if status not in SUBTASK_STATUSES:
            raise ExecutionError(f"Invalid subtask status: {status}")
        template_id = str(subtask.get("assigned_subagent_template_id") or "")
        if template_id not in template_ids:
            raise ExecutionError(f"Unknown sub-agent template for manager {expected_manager_id}: {template_id}")
        if any(key in subtask for key in ("subtasks", "subtask_plan", "subagents")):
            raise ExecutionError("Temporary sub-agents cannot create additional sub-agents.")


def _load_required_task(task_id: str, *, db_path: Path | None = None) -> dict[str, Any]:
    task = get_delegated_task(task_id, db_path=db_path)
    if not task:
        raise ExecutionError(f"Delegated task not found: {task_id}")
    return task


def _connect_tasks(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(TASK_SCHEMA)
    conn.commit()
    return conn


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _initiative_id_for_tasks(tasks: list[dict[str, Any]]) -> str | None:
    for task in tasks:
        initiative_id = task.get("initiative_id")
        if initiative_id:
            return str(initiative_id)
    return None


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off", ""}:
            return False
    return bool(value)


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
