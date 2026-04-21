import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from server.api import (
    QueryRequest,
    SotbReviewRequest,
    WebSearchRequest,
    deliberate,
    delegated_task,
    enforce_local_only,
    execution_agent,
    execution_agents,
    execution_web_search,
    get_session_adapter,
    get_session_delegation_plan,
    list_members,
    approve_task,
    plan_task,
    review_sotb,
    TaskApprovalRequest,
    TaskPlanRequest,
    TaskStatusRequest,
    update_task_status,
)
from server.board.execution import parse_delegation_plan, record_delegation_plan
from server.board.orchestrator import BoardDeliberationError, BoardSession


class ApiCliContractTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._old_remote = os.environ.get("AGENTIC_BOARD_ALLOW_REMOTE")
        os.environ["AGENTIC_BOARD_ALLOW_REMOTE"] = "1"
        self.session_path = Path("data/sessions/board_1700000000.json")
        self.session_path.parent.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if self._old_remote is None:
            os.environ.pop("AGENTIC_BOARD_ALLOW_REMOTE", None)
        else:
            os.environ["AGENTIC_BOARD_ALLOW_REMOTE"] = self._old_remote
        if self.session_path.exists():
            self.session_path.unlink()

    async def test_members_endpoint_exposes_roster_metadata(self):
        payload = await list_members()

        member = next(item for item in payload if item.id == "strategist")
        self.assertEqual("CSO", member.governance_seat)
        self.assertIn("market_strategy", member.capabilities)

    async def test_session_adapter_endpoint_uses_stable_contract(self):
        self.session_path.write_text(json.dumps({
            "session_id": "board_1700000000",
            "user_query": "What should we build?",
            "stage3": {
                "content": "### Executive Summary\nShip a concierge MVP.\n\n### SOTB Update\n- Decision: concierge MVP."
            },
            "memory": {"requires_approval": True},
        }), encoding="utf-8")

        payload = await get_session_adapter("board_1700000000")

        self.assertEqual("board_1700000000", payload["session_id"])
        self.assertIn("concierge MVP", payload["decision"]["executive_summary"])
        self.assertTrue(payload["memory"]["requires_approval"])
        self.assertEqual("data/sessions/board_1700000000.json", payload["artifacts"]["session_json_path"])

    async def test_sotb_review_endpoint_returns_diff_without_applying(self):
        payload = await review_sotb(SotbReviewRequest(
            session_id="api_contract_test",
            proposed_sotb_update="- Decision: keep memory gated.",
        ))

        self.assertTrue(payload["requires_approval"])
        self.assertIn("candidate_sotb.md", payload["diff"])

    async def test_deliberate_endpoint_returns_stable_error_code(self):
        with patch("server.api.BoardOrchestrator.deliberate", new_callable=AsyncMock) as mock_deliberate:
            mock_deliberate.side_effect = BoardDeliberationError("not enough responses")

            with self.assertRaises(HTTPException) as raised:
                await deliberate(QueryRequest(query="Should we pivot?"))

        self.assertEqual(503, raised.exception.status_code)
        self.assertEqual("deliberation_failed", raised.exception.detail["code"])

    async def test_deliberate_endpoint_returns_session_contract(self):
        session = BoardSession(
            session_id="api_contract_test",
            user_query="Should we pivot?",
            decision={"executive_summary": "Do not pivot yet."},
            verification={"score": 8, "passed": True, "deficiencies": [], "suggestions": []},
            memory={"proposed_sotb_update": None, "requires_approval": True},
        )

        with patch("server.api.BoardOrchestrator.deliberate", new_callable=AsyncMock) as mock_deliberate:
            mock_deliberate.return_value = session

            payload = await deliberate(QueryRequest(
                query="Should we pivot?",
                verify=True,
            ))

        self.assertEqual("api_contract_test", payload["session_id"])
        self.assertEqual(8, payload["verification"]["score"])
        self.assertTrue(payload["memory"]["requires_approval"])


class ApiLocalOnlyContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_api_rejects_non_local_request_when_remote_is_disabled(self):
        old_remote = os.environ.pop("AGENTIC_BOARD_ALLOW_REMOTE", None)
        try:
            request = Request({
                "type": "http",
                "method": "GET",
                "path": "/members",
                "headers": [],
                "client": ("203.0.113.10", 12345),
                "server": ("testserver", 80),
                "scheme": "http",
            })

            response = await enforce_local_only(
                request,
                lambda _request: None,
            )
        finally:
            if old_remote is not None:
                os.environ["AGENTIC_BOARD_ALLOW_REMOTE"] = old_remote

        self.assertEqual(403, response.status_code)
        self.assertIn(b"remote_access_disabled", response.body)

    async def test_remote_access_requires_configured_bearer_token(self):
        old_remote = os.environ.get("AGENTIC_BOARD_ALLOW_REMOTE")
        old_token = os.environ.get("AGENTIC_BOARD_REMOTE_TOKEN")
        try:
            os.environ["AGENTIC_BOARD_ALLOW_REMOTE"] = "1"
            os.environ["AGENTIC_BOARD_REMOTE_TOKEN"] = "remote-secret"
            request = Request({
                "type": "http",
                "method": "GET",
                "path": "/members",
                "headers": [],
                "client": ("203.0.113.10", 12345),
                "server": ("testserver", 80),
                "scheme": "http",
            })

            async def ok_response(_request):
                return JSONResponse({"ok": True})

            response = await enforce_local_only(
                request,
                ok_response,
            )

            authorized_request = Request({
                "type": "http",
                "method": "GET",
                "path": "/members",
                "headers": [(b"authorization", b"Bearer remote-secret")],
                "client": ("203.0.113.10", 12345),
                "server": ("testserver", 80),
                "scheme": "http",
            })
            authorized = await enforce_local_only(
                authorized_request,
                ok_response,
            )
        finally:
            if old_remote is None:
                os.environ.pop("AGENTIC_BOARD_ALLOW_REMOTE", None)
            else:
                os.environ["AGENTIC_BOARD_ALLOW_REMOTE"] = old_remote
            if old_token is None:
                os.environ.pop("AGENTIC_BOARD_REMOTE_TOKEN", None)
            else:
                os.environ["AGENTIC_BOARD_REMOTE_TOKEN"] = old_token

        self.assertEqual(401, response.status_code)
        self.assertIn(b"remote_auth_required", response.body)
        self.assertEqual(200, authorized.status_code)


class ApiExecutionContractTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "ledger.db"
        from server.board import execution

        self._old_db_path = execution._DEFAULT_DB_PATH
        execution._DEFAULT_DB_PATH = self.db_path
        self.plan = parse_delegation_plan(
            """### Delegation Plan
```json
{
  "tasks": [{
    "title": "Build the prototype path",
    "objective": "Plan and verify the engineering slice.",
    "execution_unit_id": "engineering",
    "manager_agent_id": "technical_lead",
    "accountable_board_member_id": "architect",
    "priority": "p1",
    "acceptance_criteria": ["Plan exists"],
    "dependencies": [],
    "approval_required": true
  }]
}
```
""",
            session_id="board_1700000001",
        )
        record_delegation_plan(self.plan)
        self.task_id = self.plan["tasks"][0]["id"]

    def tearDown(self):
        from server.board import execution

        execution._DEFAULT_DB_PATH = self._old_db_path
        self.tmpdir.cleanup()

    async def test_execution_agent_routes_expose_manager_agents(self):
        agents = await execution_agents()
        agent_ids = {agent["id"] for agent in agents}

        self.assertIn("technical_lead", agent_ids)
        agent = await execution_agent("technical_lead")
        self.assertEqual("engineering", agent["execution_unit_id"])

    async def test_delegated_task_routes_are_approval_and_manager_gated(self):
        task = await delegated_task(self.task_id)
        self.assertEqual("proposed", task["status"])

        with self.assertRaises(HTTPException):
            await plan_task(self.task_id, TaskPlanRequest(manager_agent_id="technical_lead"))

        approved = await approve_task(self.task_id, TaskApprovalRequest())
        self.assertEqual("approved", approved["status"])

        planned = await plan_task(self.task_id, TaskPlanRequest(manager_agent_id="technical_lead"))
        self.assertEqual("running", planned["status"])
        self.assertEqual("technical_lead", planned["subtask_plan"]["manager_agent_id"])

        with self.assertRaises(HTTPException):
            await update_task_status(
                self.task_id,
                TaskStatusRequest(status="completed", manager_agent_id="research_lead"),
            )

    async def test_session_delegation_plan_route_returns_persisted_tasks(self):
        plan = await get_session_delegation_plan("board_1700000001")

        self.assertEqual(self.task_id, plan["tasks"][0]["id"])
        self.assertTrue(plan["requires_approval"])

    async def test_web_search_route_rate_limits_requests(self):
        old_limit = os.environ.get("AGENTIC_BOARD_WEB_SEARCH_RATE_LIMIT")
        old_window = os.environ.get("AGENTIC_BOARD_WEB_SEARCH_RATE_WINDOW_SECONDS")
        try:
            os.environ["AGENTIC_BOARD_WEB_SEARCH_RATE_LIMIT"] = "1"
            os.environ["AGENTIC_BOARD_WEB_SEARCH_RATE_WINDOW_SECONDS"] = "60"

            with patch("server.api.routes.execution.web_search", new_callable=AsyncMock) as mock_search:
                mock_search.return_value = {"results": [], "warnings": []}

                first = await execution_web_search(WebSearchRequest(query="market sizing", provider="disabled"))
                with self.assertRaises(HTTPException) as raised:
                    await execution_web_search(WebSearchRequest(query="competitor scan", provider="disabled"))
        finally:
            if old_limit is None:
                os.environ.pop("AGENTIC_BOARD_WEB_SEARCH_RATE_LIMIT", None)
            else:
                os.environ["AGENTIC_BOARD_WEB_SEARCH_RATE_LIMIT"] = old_limit
            if old_window is None:
                os.environ.pop("AGENTIC_BOARD_WEB_SEARCH_RATE_WINDOW_SECONDS", None)
            else:
                os.environ["AGENTIC_BOARD_WEB_SEARCH_RATE_WINDOW_SECONDS"] = old_window

        self.assertEqual({"results": [], "warnings": []}, first)
        self.assertEqual(429, raised.exception.status_code)
        self.assertIn("rate limit", str(raised.exception.detail).lower())

    async def test_web_search_request_validates_bounds(self):
        with self.assertRaises(ValidationError):
            WebSearchRequest(query="market sizing", provider="tavily", max_results=50)


if __name__ == "__main__":
    unittest.main()
