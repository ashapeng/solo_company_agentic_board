import ast
import importlib
from pathlib import Path
import unittest

from fastapi import FastAPI


EXPECTED_ENDPOINT_PATHS = {
    "/",
    "/members",
    "/execution-units",
    "/execution-agents",
    "/execution-agents/{agent_id}",
    "/deliberate",
    "/deliberate/stream",
    "/sessions",
    "/sessions/{session_id:path}",
    "/sessions/{session_id:path}/adapter",
    "/sessions/{session_id:path}/delegation-plan",
    "/delegated-tasks/{task_id}",
    "/delegated-tasks/{task_id}/approve",
    "/delegated-tasks/{task_id}/plan",
    "/delegated-tasks/{task_id}/status",
    "/delegated-tasks/{task_id}/artifacts",
    "/sessions/{session_id:path}/feedback",
    "/sotb",
    "/sotb/review",
    "/role-gap/review",
    "/evidence-packets",
    "/evidence-packets/{packet_id}",
    "/harness/review/run",
    "/harness/review/latest",
    "/harness/review/{review_id}/approve",
    "/harness/review/{review_id}/apply",
    "/metrics/summary",
}


class ArchitectureContractTest(unittest.TestCase):
    def test_new_and_legacy_harness_imports_share_objects(self):
        legacy = importlib.import_module("server.board.tuner")
        modern = importlib.import_module("server.harness.tuning")
        self.assertIs(legacy.tune_token_budgets, modern.tune_token_budgets)

        legacy_config = importlib.import_module("server.board.harness_config")
        modern_config = importlib.import_module("server.harness.config")
        self.assertIs(legacy_config.HarnessConfig, modern_config.HarnessConfig)

        legacy_ledger = importlib.import_module("server.board.ledger")
        modern_ledger = importlib.import_module("server.harness.ledger")
        self.assertIs(legacy_ledger.record_session, modern_ledger.record_session)

    def test_new_and_legacy_board_memory_execution_imports_share_objects(self):
        legacy_orchestrator = importlib.import_module("server.board.orchestrator")
        modern_orchestrator = importlib.import_module("server.board.deliberation.orchestrator")
        self.assertIs(legacy_orchestrator.BoardOrchestrator, modern_orchestrator.BoardOrchestrator)

        legacy_memory = importlib.import_module("server.board.memory_review")
        modern_memory = importlib.import_module("server.memory.review")
        self.assertIs(legacy_memory.review_sotb_update, modern_memory.review_sotb_update)

        legacy_execution = importlib.import_module("server.board.execution")
        modern_execution = importlib.import_module("server.execution")
        self.assertIs(legacy_execution.parse_delegation_plan, modern_execution.parse_delegation_plan)

    def test_api_app_and_compatibility_exports_resolve(self):
        api = importlib.import_module("server.api")

        self.assertIsInstance(api.app, FastAPI)
        self.assertTrue(callable(api.feedback))
        self.assertEqual(api.FeedbackRequest(rating="positive").rating, "positive")

    def test_existing_endpoint_paths_remain_registered(self):
        api = importlib.import_module("server.api")
        registered = {route.path for route in api.app.routes}

        missing = EXPECTED_ENDPOINT_PATHS - registered
        self.assertEqual(set(), missing)

    def test_domain_packages_do_not_import_api_layer(self):
        root = Path(__file__).resolve().parents[1]
        domain_roots = [
            root / "server" / "board",
            root / "server" / "harness",
            root / "server" / "execution",
            root / "server" / "memory",
        ]
        violations: list[str] = []

        for domain_root in domain_roots:
            if not domain_root.exists():
                continue
            for path in domain_root.rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("server.api"):
                        violations.append(str(path.relative_to(root)))
                    elif isinstance(node, ast.Import):
                        if any(alias.name.startswith("server.api") for alias in node.names):
                            violations.append(str(path.relative_to(root)))

        self.assertEqual([], sorted(set(violations)))


if __name__ == "__main__":
    unittest.main()
