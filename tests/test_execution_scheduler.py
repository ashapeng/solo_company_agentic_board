import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from server.execution import scheduler
from server.execution.scheduler import (
    GateDecision,
    evaluate_gates,
    record_run_finish,
    record_run_start,
    tick,
)
from server.execution.tasks import (
    ExecutionError,
    list_tasks_by_status,
    save_delegated_task,
)


def _task(task_id, *, status="approved", venture_id="default", dependencies=None):
    return {
        "id": task_id,
        "session_id": "sched_session",
        "title": f"Task {task_id}",
        "objective": "Do the thing.",
        "execution_unit_id": "engineering",
        "manager_agent_id": "technical_lead",
        "accountable_board_member_id": "architect",
        "status": status,
        "venture_id": venture_id,
        "dependencies": dependencies or [],
        "approval_required": True,
    }


async def _stub_run_task(task_id, **kwargs):
    return {"status": "completed"}


class SchedulerTestBase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "ledger.db"
        # Redirect the harness ledger DB and raise the rate limit so the
        # bundled delegated_task hook does not block our task writes.
        from server.harness import ledger as _ledger_mod
        self._orig_ledger_path = _ledger_mod._DEFAULT_DB_PATH
        _ledger_mod._DEFAULT_DB_PATH = Path(self.tmpdir.name) / "hook_ledger.db"
        self._orig_rate_limit = os.environ.get("AGENTIC_BOARD_DELEGATED_TASK_RATE_LIMIT")
        os.environ["AGENTIC_BOARD_DELEGATED_TASK_RATE_LIMIT"] = "1000"

    def tearDown(self):
        from server.harness import ledger as _ledger_mod
        _ledger_mod._DEFAULT_DB_PATH = self._orig_ledger_path
        if self._orig_rate_limit is None:
            os.environ.pop("AGENTIC_BOARD_DELEGATED_TASK_RATE_LIMIT", None)
        else:
            os.environ["AGENTIC_BOARD_DELEGATED_TASK_RATE_LIMIT"] = self._orig_rate_limit
        self.tmpdir.cleanup()


class ListTasksByStatusTest(SchedulerTestBase):
    def test_filters_by_status_and_venture(self):
        save_delegated_task(_task("a", status="approved", venture_id="v1"), db_path=self.db_path)
        save_delegated_task(_task("b", status="approved", venture_id="v2"), db_path=self.db_path)
        save_delegated_task(_task("c", status="proposed", venture_id="v1"), db_path=self.db_path)

        approved = list_tasks_by_status("approved", db_path=self.db_path)
        self.assertEqual({"a", "b"}, {t["id"] for t in approved})

        approved_v1 = list_tasks_by_status("approved", venture_id="v1", db_path=self.db_path)
        self.assertEqual(["a"], [t["id"] for t in approved_v1])

        proposed = list_tasks_by_status("proposed", db_path=self.db_path)
        self.assertEqual(["c"], [t["id"] for t in proposed])

    def test_invalid_status_raises(self):
        with self.assertRaises(ExecutionError):
            list_tasks_by_status("not-a-status", db_path=self.db_path)


class GateMatrixTest(SchedulerTestBase):
    def _config(self, **overrides):
        cfg = {
            "always_on_enabled": True,
            "daily_budget_per_venture": 6,
            "cooldown_seconds": 1800,
            "max_concurrent_runs": 2,
        }
        cfg.update(overrides)
        return cfg

    def test_feature_disabled(self):
        decision = evaluate_gates(
            venture_id="default",
            config_execution=self._config(always_on_enabled=False),
            db_path=self.db_path,
        )
        self.assertEqual(GateDecision(False, "feature_disabled"), decision)

    def test_fresh_db_allowed(self):
        decision = evaluate_gates(
            venture_id="default",
            config_execution=self._config(),
            db_path=self.db_path,
        )
        self.assertTrue(decision.allowed)
        self.assertEqual("ok", decision.reason)

    def test_daily_budget_reached(self):
        # cooldown 0 so cooldown does not pre-empt the budget gate.
        for _ in range(3):
            rid = record_run_start("t", "default", db_path=self.db_path)
            record_run_finish(rid, "completed", db_path=self.db_path)
        decision = evaluate_gates(
            venture_id="default",
            config_execution=self._config(daily_budget_per_venture=3, cooldown_seconds=0),
            db_path=self.db_path,
        )
        self.assertEqual("daily_budget_reached", decision.reason)
        self.assertFalse(decision.allowed)

    def test_cooldown(self):
        rid = record_run_start("t", "default", db_path=self.db_path)
        record_run_finish(rid, "completed", db_path=self.db_path)
        decision = evaluate_gates(
            venture_id="default",
            config_execution=self._config(daily_budget_per_venture=100, cooldown_seconds=1800),
            db_path=self.db_path,
        )
        self.assertEqual("cooldown", decision.reason)

    def test_cooldown_expired_allowed(self):
        rid = record_run_start("t", "default", db_path=self.db_path)
        record_run_finish(rid, "completed", db_path=self.db_path)
        later = datetime.now(timezone.utc) + timedelta(seconds=3600)
        decision = evaluate_gates(
            venture_id="default",
            config_execution=self._config(daily_budget_per_venture=100, cooldown_seconds=1800),
            now=later,
            db_path=self.db_path,
        )
        self.assertTrue(decision.allowed)

    def test_max_concurrent(self):
        # Two unfinished (running) runs against max_concurrent_runs=2.
        record_run_start("t1", "v1", db_path=self.db_path)
        record_run_start("t2", "v2", db_path=self.db_path)
        decision = evaluate_gates(
            venture_id="other",
            config_execution=self._config(
                daily_budget_per_venture=100, cooldown_seconds=0, max_concurrent_runs=2
            ),
            db_path=self.db_path,
        )
        self.assertEqual("max_concurrent", decision.reason)


class TickTest(SchedulerTestBase):
    def _patch_config(self, **overrides):
        execution = {
            "always_on_enabled": True,
            "daily_budget_per_venture": 6,
            "cooldown_seconds": 0,
            "max_concurrent_runs": 2,
            "poll_interval_seconds": 300,
        }
        execution.update(overrides)
        fake = mock.Mock()
        fake.execution = execution
        return mock.patch.object(scheduler, "get_config", return_value=fake)

    def test_fires_approved_task(self):
        import asyncio
        save_delegated_task(_task("a", status="approved"), db_path=self.db_path)
        with self._patch_config(), \
                mock.patch.object(scheduler, "run_task", side_effect=_stub_run_task) as spy:
            results = asyncio.run(tick(db_path=self.db_path))
            spy.assert_called_once()

        fired = [r for r in results if r["fired"]]
        self.assertEqual(["a"], [r["task_id"] for r in fired])
        self.assertEqual("completed", fired[0]["result_status"])

        # A finished task_runs row was created.
        runs = scheduler._connect(self.db_path).execute(
            "SELECT status, finished_at FROM task_runs"
        ).fetchall()
        self.assertEqual(1, len(runs))
        self.assertEqual("completed", runs[0]["status"])
        self.assertIsNotNone(runs[0]["finished_at"])

    def test_does_not_fire_when_dependency_incomplete(self):
        import asyncio
        save_delegated_task(_task("dep", status="approved"), db_path=self.db_path)
        save_delegated_task(_task("a", status="approved", dependencies=["dep"]), db_path=self.db_path)
        with self._patch_config(max_concurrent_runs=5), \
                mock.patch.object(scheduler, "run_task", side_effect=_stub_run_task):
            results = asyncio.run(tick(db_path=self.db_path))

        by_id = {r["task_id"]: r for r in results}
        # "dep" has no dependencies -> fires. "a" depends on "dep" which is not
        # completed at evaluation time -> not fired.
        self.assertTrue(by_id["dep"]["fired"])
        self.assertFalse(by_id["a"]["fired"])
        self.assertEqual("dependencies_unsatisfied", by_id["a"]["reason"])

    def test_does_not_fire_when_feature_disabled(self):
        import asyncio
        save_delegated_task(_task("a", status="approved"), db_path=self.db_path)
        with self._patch_config(always_on_enabled=False), \
                mock.patch.object(scheduler, "run_task", side_effect=_stub_run_task) as spy:
            results = asyncio.run(tick(db_path=self.db_path))
            spy.assert_not_called()

        self.assertEqual(0, sum(1 for r in results if r["fired"]))
        self.assertEqual("feature_disabled", results[0]["reason"])

    def test_respects_max_concurrent_runs(self):
        import asyncio
        save_delegated_task(_task("a", status="approved", venture_id="v1"), db_path=self.db_path)
        save_delegated_task(_task("b", status="approved", venture_id="v2"), db_path=self.db_path)
        with self._patch_config(max_concurrent_runs=1), \
                mock.patch.object(scheduler, "run_task", side_effect=_stub_run_task) as spy:
            results = asyncio.run(tick(db_path=self.db_path))
            self.assertEqual(1, spy.call_count)

        fired = [r for r in results if r["fired"]]
        self.assertEqual(1, len(fired))


if __name__ == "__main__":
    unittest.main()
