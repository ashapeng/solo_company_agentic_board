"""Bounded task executor (Plan 3a).

`run_task` resolves a delegated task, refuses unapproved external actions,
plans subtasks via the assigned manager agent, runs each sub-agent in a
bounded tool-use loop, writes artifacts to disk, and synthesizes a manager
result summary. Every loop is hard-bounded (turns, tool calls, wall-clock)
so it can NEVER infinite-loop.

This module deliberately imports from ``server.execution.tasks`` and
``server.execution.agents`` directly (not the package ``__init__`` and never
``server.board.deliberation.orchestrator``) to avoid an import cycle.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from server.board.llm import LLMResponse, ToolCall, query_llm
from server.board.tools import TOOLS, execute_tool
from server.harness.config import get_config
from server.harness.hooks import HookDeniedError
from server.ventures import venture_slug

from .agents import AGENTS_BY_ID
from .tasks import (
    attach_task_artifact,
    get_delegated_task,
    plan_delegated_task,
    update_delegated_task_status,
)

MAX_TOOL_RESULT_CHARS = 8000
MAX_RESULT_SUMMARY_CHARS = 2000
_RUNNABLE_STATUSES = {"approved", "running"}


@dataclass
class RunnerBudget:
    """Hard bounds on a single run_task invocation."""

    max_turns: int = 12
    max_tool_calls: int = 40
    wall_seconds_max: int = 1200
    max_parallel_subagents: int = 3

    @classmethod
    def from_config(cls) -> "RunnerBudget":
        execution = getattr(get_config(), "execution", {}) or {}
        return cls(
            max_turns=int(execution.get("runner_max_turns", 12)),
            max_tool_calls=int(execution.get("runner_max_tool_calls", 40)),
            wall_seconds_max=int(execution.get("runner_wall_seconds_max", 1200)),
            max_parallel_subagents=int(
                execution.get("runner_max_parallel_subagents", 3)
            ),
        )


class _SessionStub:
    """Lightweight session stand-in for execute_tool handlers.

    Handlers only read ``getattr(session, "session_id", None)`` etc., so a
    bare object carrying ``session_id`` is sufficient.
    """

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id


def _available_tool_schemas(allowed: list[str]) -> list[dict]:
    """Intersect ``allowed`` tool names with the registered TOOLS."""
    matches = [name for name in (allowed or []) if name in TOOLS]
    return [TOOLS[name].to_openai_schema() for name in matches]


def _tool_call_message(resp: LLMResponse) -> dict[str, Any]:
    """Mirror the board orchestrator's assistant tool-call message shape."""
    return {
        "role": "assistant",
        "content": resp.content or "",
        "tool_calls": [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
            }
            for tc in resp.tool_calls
        ],
    }


async def _run_agent_loop(
    *,
    model: str,
    system: str,
    prompt: str,
    allowed_tools: list[str],
    agent_id: str,
    session_id: str,
    budget: RunnerBudget,
) -> tuple[str, dict]:
    """Bounded tool-use loop mirroring the board orchestrator.

    Caps: at most ``budget.max_turns`` LLM calls; tool calls capped at
    ``budget.max_tool_calls``; wall-clock capped at ``budget.wall_seconds_max``.
    When the tool/turn budget is exhausted, a final ``tool_choice="none"`` call
    produces prose. Returns ``(final_text, metrics_dict)``.
    """
    session = _SessionStub(session_id)
    schemas = _available_tool_schemas(allowed_tools)
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]

    t_start = time.monotonic()
    turns = 0
    tool_calls_used = 0
    input_tokens = 0
    output_tokens = 0
    final_text = ""
    final_call_done = False

    while True:
        wall = time.monotonic() - t_start
        # Stop initiating new tool turns once any hard bound is hit. We still
        # allow one terminal tool_choice="none" call to extract prose.
        budget_hit = (
            turns >= budget.max_turns
            or tool_calls_used >= budget.max_tool_calls
            or wall >= budget.wall_seconds_max
        )
        no_more_tools = budget_hit or not schemas

        resp: LLMResponse = await query_llm(
            model,
            messages,
            system=system,
            tools=None if no_more_tools else schemas,
            tool_choice="none" if no_more_tools else "auto",
        )
        turns += 1
        input_tokens += max(int(resp.input_tokens or 0), 0)
        output_tokens += max(int(resp.output_tokens or 0), 0)
        final_text = resp.content or final_text

        if no_more_tools:
            # Terminal prose call already made; we're done.
            final_call_done = True
            break

        if not resp.tool_calls:
            # Model produced prose without tools — natural completion.
            break

        # Record the assistant tool-call request, then dispatch tools.
        messages.append(_tool_call_message(resp))
        for tc in resp.tool_calls:
            if tool_calls_used >= budget.max_tool_calls:
                # Tool cap reached mid-batch: answer outstanding calls with a
                # placeholder so the message history stays valid, then the next
                # loop iteration will fall into the terminal no_more_tools path.
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": "[tool budget exhausted]",
                    }
                )
                continue
            tool_calls_used += 1
            result = await execute_tool(
                name=tc.name,
                arguments=tc.arguments,
                session=session,
                member_id=agent_id,
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": (result.content_for_model or "")[:MAX_TOOL_RESULT_CHARS],
                }
            )

    metrics = {
        "turns": turns,
        "tool_calls": tool_calls_used,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "final_call_forced": final_call_done,
    }
    return final_text, metrics


def _merge_metrics(target: dict, source: dict) -> None:
    for key in ("turns", "tool_calls", "input_tokens", "output_tokens"):
        target[key] = target.get(key, 0) + int(source.get(key, 0))


async def run_task(
    task_id: str,
    *,
    budget: RunnerBudget | None = None,
    artifacts_dir: Path | None = None,
    db_path: Path | None = None,
) -> dict:
    """Execute one approved/running delegated task within hard bounds.

    Returns a status dict. Never raises: unexpected exceptions mark the task
    blocked and return ``{"status": "error", ...}``.
    """
    budget = budget or RunnerBudget.from_config()
    artifacts_dir = artifacts_dir or Path("data/artifacts")

    task = get_delegated_task(task_id, db_path=db_path)
    if task is None:
        return {"task_id": task_id, "status": "not_found"}

    if task.get("status") not in _RUNNABLE_STATUSES:
        return {
            "task_id": task_id,
            "status": "skipped",
            "reason": f"status={task.get('status')}",
        }

    manager_agent_id = task.get("manager_agent_id")

    def _block(reason: str, detail: str) -> dict:
        try:
            update_delegated_task_status(
                task_id,
                status="blocked",
                manager_agent_id=manager_agent_id,
                status_detail=detail,
                db_path=db_path,
            )
        except HookDeniedError:
            pass
        return {"task_id": task_id, "status": "blocked", "reason": reason}

    try:
        # 4. External-action refusal — never calls any LLM.
        if task.get("external_action_required") and not task.get(
            "external_action_approved"
        ):
            return _block(
                "external_action_not_approved", "external action not approved"
            )

        # 5. Resolve manager agent.
        agent = AGENTS_BY_ID.get(manager_agent_id)
        if agent is None:
            return _block("unknown_manager_agent", "unknown manager agent")

        # 6. Ensure plan/running.
        try:
            plan_delegated_task(
                task_id,
                manager_agent_id=manager_agent_id,
                db_path=db_path,
            )
        except HookDeniedError:
            return _block("hook_denied", "hook denied during planning")

        task = get_delegated_task(task_id, db_path=db_path) or task
        subtask_plan = task.get("subtask_plan") or {}
        subtasks = subtask_plan.get("subtasks") or []

        venture_id = str(task.get("venture_id") or "default")
        objective = str(task.get("objective") or task.get("title") or "")
        task_dir = artifacts_dir / venture_slug(venture_id) / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        templates_by_id = {t.id: t for t in agent.subagent_templates}
        run_metrics: dict[str, int] = {}
        written_paths: list[str] = []
        subtask_results: list[dict[str, Any]] = []
        subtask_outputs: list[tuple[str, str]] = []  # (title, text)

        subagent_model = get_config().execution.get(
            "subagent_model", "qwen/qwen3.6-flash"
        )

        async def _run_subtask(subtask: dict[str, Any]) -> dict[str, Any]:
            subtask_id = str(subtask.get("id") or "subtask")
            template_id = str(subtask.get("assigned_subagent_template_id") or "")
            template = templates_by_id.get(template_id)
            if template is None:
                text = f"[no sub-agent template for {template_id}]"
                allowed: list[str] = []
                contract = ""
                title = subtask.get("title") or subtask_id
            else:
                contract = template.output_contract
                allowed = list(template.allowed_tools)
                title = template.title
                prompt = (
                    f"{template.purpose}\n\n"
                    f"Task objective: {objective}\n\n"
                    f"Output contract: {contract}"
                )
                text, metrics = await _run_agent_loop(
                    model=subagent_model,
                    system=agent.system_prompt,
                    prompt=prompt,
                    allowed_tools=allowed,
                    agent_id=manager_agent_id,
                    session_id=str(task.get("session_id") or ""),
                    budget=budget,
                )
                _merge_metrics(run_metrics, metrics)
            return {"id": subtask_id, "title": title, "text": text or ""}

        # 7. Bounded parallelism over subtasks via gather over chunks.
        chunk_size = max(
            1, min(agent.max_parallel_subagents, budget.max_parallel_subagents)
        )
        ordered_outputs: list[dict[str, Any]] = []
        for start in range(0, len(subtasks), chunk_size):
            chunk = subtasks[start : start + chunk_size]
            results = await asyncio.gather(*[_run_subtask(st) for st in chunk])
            ordered_outputs.extend(results)

        for out in ordered_outputs:
            subtask_id = out["id"]
            path = task_dir / f"{subtask_id}.md"
            path.write_text(out["text"], encoding="utf-8")
            written_paths.append(str(path))
            try:
                attach_task_artifact(task_id, artifact=str(path), db_path=db_path)
            except HookDeniedError:
                return _block("hook_denied", "hook denied attaching artifact")
            subtask_results.append({"id": subtask_id, "ok": bool(out["text"])})
            subtask_outputs.append((out["title"], out["text"]))

        # 8. Manager synthesis.
        joined = "\n\n".join(
            f"### {title}\n{text}" for title, text in subtask_outputs
        )
        manager_model = get_config().execution.get(
            "manager_model", "qwen/qwen3.6-plus-2026-04-02"
        )
        synthesis_prompt = (
            f"Task objective: {objective}\n\n"
            f"Sub-agent outputs:\n{joined}\n\n"
            "Synthesize a result summary and next steps."
        )
        result_summary, metrics = await _run_agent_loop(
            model=manager_model,
            system=agent.system_prompt,
            prompt=synthesis_prompt,
            allowed_tools=list(agent.allowed_tools),
            agent_id=manager_agent_id,
            session_id=str(task.get("session_id") or ""),
            budget=budget,
        )
        _merge_metrics(run_metrics, metrics)

        summary_path = task_dir / "_summary.md"
        summary_path.write_text(result_summary or "", encoding="utf-8")
        written_paths.append(str(summary_path))
        result_summary = (result_summary or "")[:MAX_RESULT_SUMMARY_CHARS]

        # 9. Complete.
        try:
            update_delegated_task_status(
                task_id,
                status="completed",
                manager_agent_id=manager_agent_id,
                result_summary=result_summary,
                artifacts=written_paths,
                db_path=db_path,
            )
        except HookDeniedError:
            return _block("hook_denied", "hook denied on completion")

        return {
            "task_id": task_id,
            "status": "completed",
            "result_summary": result_summary,
            "artifacts": written_paths,
            "subtasks": subtask_results,
            "metrics": run_metrics,
        }

    except Exception as exc:  # noqa: BLE001 — never raise out of the runner.
        try:
            update_delegated_task_status(
                task_id,
                status="blocked",
                manager_agent_id=manager_agent_id,
                status_detail=str(exc)[:300],
                db_path=db_path,
            )
        except Exception:  # noqa: BLE001
            pass
        return {"task_id": task_id, "status": "error", "error": str(exc)}
