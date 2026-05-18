import tempfile
import unittest
from pathlib import Path

from server.execution import (
    ExecutionError,
    approve_delegated_task,
    create_evidence_packet,
    get_delegated_task,
    get_delegation_plan,
    get_evidence_packet,
    list_execution_agents,
    list_execution_units,
    parse_delegation_plan,
    plan_delegated_task,
    record_delegation_plan,
    update_delegated_task_status,
)
from server.harness.reviews import (
    approve_harness_review,
    latest_harness_review,
    run_harness_review,
)
from server.board.projection import adapt_session_record


SYNTHESIS_WITH_DELEGATION = """### Executive Summary
Ship the smallest technical slice.

### Delegation Plan
```json
{
  "tasks": [
    {
      "title": "Build the prototype path",
      "objective": "Decompose and implement the first engineering slice.",
      "execution_unit_id": "engineering",
      "manager_agent_id": "technical_lead",
      "accountable_board_member_id": "architect",
      "priority": "p0",
      "acceptance_criteria": ["Prototype path is scoped", "Verification commands are listed"],
      "dependencies": [],
      "approval_required": true
    }
  ]
}
```

### SOTB Update
- Decision: build the smallest technical slice.
"""


class ExecutionRegistryContractTest(unittest.TestCase):
    def test_execution_agents_and_units_expose_manager_agents(self):
        agents = list_execution_agents()
        units = list_execution_units()

        agent_ids = {agent["id"] for agent in agents}
        unit_ids = {unit["id"] for unit in units}

        self.assertIn("technical_lead", agent_ids)
        self.assertIn("research_lead", agent_ids)
        self.assertIn("engineering", unit_ids)
        self.assertIn("legal", unit_ids)
        self.assertTrue(next(agent for agent in agents if agent["id"] == "technical_lead")["subagent_templates"])


class DelegationPlanContractTest(unittest.TestCase):
    def test_parses_chair_delegation_plan(self):
        plan = parse_delegation_plan(SYNTHESIS_WITH_DELEGATION, session_id="board_exec_test")

        self.assertEqual("board_exec_test", plan["session_id"])
        self.assertEqual([], plan["warnings"])
        self.assertEqual(1, len(plan["tasks"]))
        task = plan["tasks"][0]
        self.assertEqual("engineering", task["execution_unit_id"])
        self.assertEqual("technical_lead", task["manager_agent_id"])
        self.assertEqual("proposed", task["status"])
        self.assertTrue(task["approval_required"])

    def test_malformed_delegation_plan_warns_without_failing(self):
        plan = parse_delegation_plan(
            "### Delegation Plan\nnot-json",
            session_id="board_bad_delegation",
        )

        self.assertEqual([], plan["tasks"])
        self.assertIn("parseable JSON", plan["warnings"][0])

    def test_adapter_includes_delegation_plan_for_saved_sessions(self):
        adapted = adapt_session_record({
            "session_id": "board_exec_test",
            "user_query": "What should we build?",
            "stage3": {"content": SYNTHESIS_WITH_DELEGATION},
        })

        self.assertEqual("technical_lead", adapted["delegation_plan"]["tasks"][0]["manager_agent_id"])


class DelegatedTaskLifecycleContractTest(unittest.TestCase):
    def setUp(self):
        import os
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "tasks.db"
        # Redirect the ledger DB so the bundled rate-limit hook counts against a
        # fresh tmp DB (not the shared default path) for each test.
        from server.harness import ledger as _ledger_mod
        self._orig_ledger_path = _ledger_mod._DEFAULT_DB_PATH
        _ledger_mod._DEFAULT_DB_PATH = Path(self.tmpdir.name) / "ledger.db"
        # Raise the rate limit so lifecycle tests (which legitimately make many
        # hook-gated calls per test) aren't blocked by the default 5-op cap.
        self._orig_rate_limit = os.environ.get("AGENTIC_BOARD_DELEGATED_TASK_RATE_LIMIT")
        os.environ["AGENTIC_BOARD_DELEGATED_TASK_RATE_LIMIT"] = "100"
        self.plan = parse_delegation_plan(SYNTHESIS_WITH_DELEGATION, session_id="board_exec_test")
        record_delegation_plan(self.plan, db_path=self.db_path)
        self.task_id = self.plan["tasks"][0]["id"]

    def tearDown(self):
        import os
        from server.harness import ledger as _ledger_mod
        _ledger_mod._DEFAULT_DB_PATH = self._orig_ledger_path
        if self._orig_rate_limit is None:
            os.environ.pop("AGENTIC_BOARD_DELEGATED_TASK_RATE_LIMIT", None)
        else:
            os.environ["AGENTIC_BOARD_DELEGATED_TASK_RATE_LIMIT"] = self._orig_rate_limit
        self.tmpdir.cleanup()

    def test_task_approval_planning_and_completion_are_persisted(self):
        approved = approve_delegated_task(self.task_id, db_path=self.db_path)
        self.assertEqual("approved", approved["status"])

        planned = plan_delegated_task(
            self.task_id,
            manager_agent_id="technical_lead",
            db_path=self.db_path,
        )
        self.assertEqual("running", planned["status"])
        self.assertEqual("technical_lead", planned["subtask_plan"]["manager_agent_id"])
        self.assertGreaterEqual(len(planned["subtask_plan"]["subtasks"]), 1)

        completed = update_delegated_task_status(
            self.task_id,
            status="completed",
            manager_agent_id="technical_lead",
            result_summary="Prototype path scoped.",
            artifacts=["data/artifacts/prototype.md"],
            db_path=self.db_path,
        )
        self.assertEqual("completed", completed["status"])
        self.assertIn("data/artifacts/prototype.md", completed["artifacts"])

        reloaded = get_delegated_task(self.task_id, db_path=self.db_path)
        self.assertEqual("completed", reloaded["status"])

    def test_unapproved_task_cannot_be_planned(self):
        with self.assertRaises(ExecutionError):
            plan_delegated_task(self.task_id, manager_agent_id="technical_lead", db_path=self.db_path)

    def test_only_manager_agent_can_complete_task(self):
        approve_delegated_task(self.task_id, db_path=self.db_path)
        plan_delegated_task(self.task_id, manager_agent_id="technical_lead", db_path=self.db_path)

        with self.assertRaises(ExecutionError):
            update_delegated_task_status(
                self.task_id,
                status="completed",
                manager_agent_id="research_lead",
                db_path=self.db_path,
            )

    def test_planning_requires_manager_and_rejects_nested_subagents(self):
        approve_delegated_task(self.task_id, db_path=self.db_path)

        with self.assertRaises(ExecutionError):
            plan_delegated_task(self.task_id, db_path=self.db_path)

        with self.assertRaises(ExecutionError):
            plan_delegated_task(
                self.task_id,
                manager_agent_id="technical_lead",
                subtask_plan={
                    "manager_agent_id": "technical_lead",
                    "coordination_notes": "Invalid nested hierarchy.",
                    "subtasks": [{
                        "id": "nested",
                        "title": "Nested worker",
                        "objective": "Should be rejected.",
                        "assigned_subagent_template_id": "codebase_explorer",
                        "required_inputs": [self.task_id],
                        "output_contract": "Report.",
                        "status": "planned",
                        "subtasks": [],
                    }],
                },
                db_path=self.db_path,
            )

    def test_session_plan_reads_persisted_task_state(self):
        approve_delegated_task(self.task_id, db_path=self.db_path)
        plan = get_delegation_plan("board_exec_test", db_path=self.db_path)

        self.assertEqual("approved", plan["tasks"][0]["status"])


class EvidencePacketContractTest(unittest.TestCase):
    def test_evidence_packet_round_trip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import server.execution as execution

            old_dir = execution._EVIDENCE_DIR
            execution._EVIDENCE_DIR = Path(tmpdir)
            try:
                packet = create_evidence_packet(
                    topic="Market evidence",
                    claims=["Customers need a faster workflow."],
                    sources=[{"title": "Source", "url": "https://example.com", "claim_ids": ["claim-1"]}],
                    freshness="current",
                )

                loaded = get_evidence_packet(packet["id"])
            finally:
                execution._EVIDENCE_DIR = old_dir

        self.assertEqual(packet["id"], loaded["id"])
        self.assertEqual("current", loaded["freshness"])


class HarnessReviewContractTest(unittest.TestCase):
    def test_harness_review_is_dry_run_and_approval_gated(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import server.harness.reviews as harness_review

            old_dir = harness_review._REVIEWS_DIR
            harness_review._REVIEWS_DIR = Path(tmpdir)
            try:
                review = run_harness_review(dry_run=True)
                self.assertEqual("proposed", review["status"])
                self.assertTrue(review["dry_run"])

                latest = latest_harness_review()
                self.assertEqual(review["id"], latest["id"])

                approved = approve_harness_review(review["id"])
                self.assertEqual("approved", approved["status"])
            finally:
                harness_review._REVIEWS_DIR = old_dir


if __name__ == "__main__":
    unittest.main()
