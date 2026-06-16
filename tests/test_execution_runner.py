"""Tests for the bounded task executor (server/execution/runner.py)."""

from __future__ import annotations

import asyncio

import pytest

from server.board.llm import LLMResponse, ToolCall
from server.execution import runner as runner_mod
from server.execution.runner import RunnerBudget, run_task
from server.execution.tasks import get_delegated_task, save_delegated_task


@pytest.fixture(autouse=True)
def _high_rate_limit(monkeypatch):
    """Disable the delegated-task rate-limit hook across multi-write runs."""
    monkeypatch.setenv("AGENTIC_BOARD_DELEGATED_TASK_RATE_LIMIT", "1000")


def _make_response(model: str) -> LLMResponse:
    return LLMResponse(
        content="<deliverable>",
        model=model,
        input_tokens=10,
        output_tokens=20,
        latency_seconds=0.0,
        finish_reason="stop",
        tool_calls=[],
    )


def _approved_task(task_id: str = "t1", **overrides) -> dict:
    task = {
        "id": task_id,
        "session_id": "s1",
        "title": "x",
        "objective": "y",
        "execution_unit_id": "strategy",
        "manager_agent_id": "strategy_lead",
        "status": "approved",
    }
    task.update(overrides)
    return task


def test_run_task_completes(tmp_path, monkeypatch):
    calls = {"n": 0}

    async def _stub(model, messages, **kwargs):
        calls["n"] += 1
        return _make_response(model)

    monkeypatch.setattr(runner_mod, "query_llm", _stub)

    db = tmp_path / "ledger.db"
    artifacts = tmp_path / "artifacts"
    save_delegated_task(_approved_task(), db_path=db)

    result = asyncio.run(run_task("t1", artifacts_dir=artifacts, db_path=db))

    assert result["status"] == "completed"
    assert result["result_summary"]
    assert calls["n"] > 0

    stored = get_delegated_task("t1", db_path=db)
    assert stored["status"] == "completed"

    # Artifact files exist on disk.
    assert result["artifacts"]
    for path in result["artifacts"]:
        from pathlib import Path

        assert Path(path).exists()
    summary_files = list(artifacts.rglob("_summary.md"))
    assert summary_files and summary_files[0].read_text()


def test_run_task_external_action_refused(tmp_path, monkeypatch):
    calls = {"n": 0}

    async def _stub(model, messages, **kwargs):
        calls["n"] += 1
        return _make_response(model)

    monkeypatch.setattr(runner_mod, "query_llm", _stub)

    db = tmp_path / "ledger.db"
    save_delegated_task(
        _approved_task(
            external_action_required=True,
            external_action_approved=False,
        ),
        db_path=db,
    )

    result = asyncio.run(
        run_task("t1", artifacts_dir=tmp_path / "artifacts", db_path=db)
    )

    assert result["status"] == "blocked"
    assert result["reason"] == "external_action_not_approved"
    # No LLM was ever invoked.
    assert calls["n"] == 0
    assert get_delegated_task("t1", db_path=db)["status"] == "blocked"


def test_run_task_skipped_when_proposed(tmp_path, monkeypatch):
    calls = {"n": 0}

    async def _stub(model, messages, **kwargs):
        calls["n"] += 1
        return _make_response(model)

    monkeypatch.setattr(runner_mod, "query_llm", _stub)

    db = tmp_path / "ledger.db"
    save_delegated_task(_approved_task(status="proposed"), db_path=db)

    result = asyncio.run(
        run_task("t1", artifacts_dir=tmp_path / "artifacts", db_path=db)
    )

    assert result["status"] == "skipped"
    assert calls["n"] == 0


def test_run_task_terminates_under_tool_budget(tmp_path, monkeypatch):
    """Always return one web_search tool call; assert the loop terminates and
    the LLM is invoked a bounded number of times (no infinite loop)."""
    calls = {"n": 0}

    async def _stub(model, messages, tools=None, tool_choice="auto", **kwargs):
        calls["n"] += 1
        # When tools are offered, keep asking for a tool; otherwise prose.
        if tools and tool_choice != "none":
            return LLMResponse(
                content="",
                model=model,
                input_tokens=10,
                output_tokens=20,
                latency_seconds=0.0,
                finish_reason="tool_calls",
                tool_calls=[
                    ToolCall(id="c1", name="web_search", arguments={"query": "x"})
                ],
            )
        return _make_response(model)

    class _ToolResult:
        content_for_model = "ok"
        summary = "ok"
        cost_units = 1.0
        error = None

    async def _exec_stub(*, name, arguments, session, member_id):
        return _ToolResult()

    monkeypatch.setattr(runner_mod, "query_llm", _stub)
    monkeypatch.setattr(runner_mod, "execute_tool", _exec_stub)

    db = tmp_path / "ledger.db"
    save_delegated_task(_approved_task(), db_path=db)

    budget = RunnerBudget(
        max_turns=3,
        max_tool_calls=2,
        wall_seconds_max=1200,
        max_parallel_subagents=3,
    )

    result = asyncio.run(
        run_task("t1", budget=budget, artifacts_dir=tmp_path / "art", db_path=db)
    )

    # Must terminate (completed or blocked), not hang.
    assert result["status"] in {"completed", "blocked"}
    # Bounded: 2 subtasks + 1 synthesis, each capped at max_turns=3 → <= 9-ish.
    assert calls["n"] <= 20
    if result["status"] == "completed":
        assert result["metrics"]["tool_calls"] <= 2 * 3  # cap per loop * loops
