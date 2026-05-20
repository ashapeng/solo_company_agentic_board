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
    ExternalActionApprovalRequest,
    TaskPlanRequest,
    TaskStatusRequest,
    approve_task_external_action,
    update_task_status,
)
from server.execution import parse_delegation_plan, record_delegation_plan
from server.board.deliberation.orchestrator import BoardDeliberationError, BoardSession


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
        from server.api.routes import board as board_routes
        bucket = getattr(board_routes, "_DELIBERATE_REQUESTS", None)
        if bucket is not None and hasattr(bucket, "clear"):
            bucket.clear()

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
        fake_request = Request({
            "type": "http",
            "method": "POST",
            "path": "/deliberate",
            "headers": [],
            "client": ("127.0.0.1", 9999),
        })
        with patch("server.api.BoardOrchestrator.deliberate", new_callable=AsyncMock) as mock_deliberate:
            mock_deliberate.side_effect = BoardDeliberationError("not enough responses")

            with self.assertRaises(HTTPException) as raised:
                await deliberate(QueryRequest(query="Should we pivot?"), fake_request)

        self.assertEqual(503, raised.exception.status_code)
        self.assertEqual("deliberation_failed", raised.exception.detail["code"])

    def test_content_filter_provider_errors_are_public_safe(self):
        from server.api.routes.board import _public_error_payload

        raw = (
            "Error code: 400 - {'error': {'code': 400, 'message': "
            "'The request was rejected because it was considered high risk', "
            "'param': 'prompt', 'type': 'content_filter'}}"
        )

        payload = _public_error_payload(RuntimeError(raw))

        self.assertEqual("content_filter", payload["code"])
        self.assertIn("content filter", payload["message"].lower())
        self.assertNotIn("{'error'", payload["message"])
        self.assertNotIn("param", payload["message"])

    async def test_deliberate_endpoint_returns_session_contract(self):
        fake_request = Request({
            "type": "http",
            "method": "POST",
            "path": "/deliberate",
            "headers": [],
            "client": ("127.0.0.1", 9999),
        })
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
            ), fake_request)

        self.assertEqual("api_contract_test", payload["session_id"])
        self.assertEqual(8, payload["verification"]["score"])
        self.assertTrue(payload["memory"]["requires_approval"])

    def test_query_request_accepts_initiative_fields(self):
        req = QueryRequest(
            query="Should we pivot?",
            initiative_id="init_123",
            initiative_mode="attach",
        )

        self.assertEqual("init_123", req.initiative_id)
        self.assertEqual("attach", req.initiative_mode)


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
        import server.execution as execution

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
        import server.execution as execution

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

    async def test_external_action_approval_route_approves_and_maps_execution_errors(self):
        external_plan = parse_delegation_plan(
            """### Delegation Plan
```json
{
  "tasks": [{
    "id": "route_external_publish_task",
    "title": "Publish engineering note",
    "objective": "Publish the approved engineering note.",
    "execution_unit_id": "engineering",
    "manager_agent_id": "technical_lead",
    "external_action_type": "publish"
  }]
}
```
""",
            session_id="board_1700000002",
            initiative_id="init_route_external",
        )
        record_delegation_plan(external_plan)

        approved = await approve_task_external_action(
            "route_external_publish_task",
            ExternalActionApprovalRequest(),
        )
        self.assertTrue(approved["external_action_approved"])

        with self.assertRaises(HTTPException) as raised:
            await approve_task_external_action(
                self.task_id,
                ExternalActionApprovalRequest(),
            )

        self.assertEqual(422, raised.exception.status_code)

    async def test_web_search_route_rate_limits_requests(self):
        from unittest.mock import MagicMock
        mock_request = MagicMock(spec=Request)
        mock_request.client = MagicMock()
        mock_request.client.host = "127.0.0.1"

        with patch("server.api.routes.execution.web_search", new_callable=AsyncMock) as mock_search:
            # First call succeeds; second call returns a rate-limit warning (per-session model).
            mock_search.side_effect = [
                {"results": [], "warnings": []},
                {"results": [], "warnings": ["session rate limit: 1/60s"]},
            ]

            first = await execution_web_search(WebSearchRequest(query="market sizing", provider="fake"), mock_request)
            with self.assertRaises(HTTPException) as raised:
                await execution_web_search(WebSearchRequest(query="competitor scan", provider="fake"), mock_request)

        self.assertEqual({"results": [], "warnings": []}, first)
        self.assertEqual(429, raised.exception.status_code)
        self.assertIn("rate limit", str(raised.exception.detail).lower())

    async def test_web_search_request_validates_bounds(self):
        with self.assertRaises(ValidationError):
            WebSearchRequest(query="market sizing", provider="tavily", max_results=50)


class InitiativeVerticalSliceContractTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "ledger.db"
        import server.execution as execution
        import server.initiatives as initiatives

        self._old_init_db = initiatives._DEFAULT_DB_PATH
        self._old_exec_db = execution._DEFAULT_DB_PATH
        initiatives._DEFAULT_DB_PATH = self.db_path
        execution._DEFAULT_DB_PATH = self.db_path

    def tearDown(self):
        import server.execution as execution
        import server.initiatives as initiatives

        initiatives._DEFAULT_DB_PATH = self._old_init_db
        execution._DEFAULT_DB_PATH = self._old_exec_db
        self.tmpdir.cleanup()

    async def test_initiative_api_vertical_slice(self):
        from server.api.routes import initiatives as initiative_routes
        from server.api.schemas import (
            InitiativeActivateRequest,
            InitiativeCloseoutRequest,
            InitiativeCreateRequest,
        )

        created = initiative_routes.create_initiative(
            InitiativeCreateRequest(
                title="Launch concierge demand loop",
                objective="Find and convert the first narrow ICP for a solo-company wedge.",
                success_criteria=["Ten qualified prospects contacted", "Two booked calls"],
                departments=["marketing", "engineering"],
                created_from="founder_command",
                source_session_id="board_initiative_seed",
            )
        )

        activated = initiative_routes.activate_initiative(
            created["id"],
            InitiativeActivateRequest(),
        )
        self.assertEqual("active", activated["status"])

        plan = parse_delegation_plan(
            """### Delegation Plan
```json
{
  "tasks": [{
    "id": "initiative_vertical_slice_outreach",
    "title": "Run founder-led outreach batch",
    "objective": "Send approved outreach to the initial ICP list.",
    "execution_unit_id": "marketing",
    "external_action_type": "outreach",
    "acceptance_criteria": ["Outreach copy approved", "Prospect list prepared"]
  }]
}
```
""",
            session_id="board_initiative_activation",
            initiative_id=created["id"],
        )
        record_delegation_plan(plan)

        tasks = initiative_routes.list_initiative_tasks(created["id"])
        self.assertEqual(created["id"], tasks["initiative_id"])
        self.assertEqual(["initiative_vertical_slice_outreach"], [task["id"] for task in tasks["tasks"]])
        task = tasks["tasks"][0]
        self.assertEqual(created["id"], task["initiative_id"])
        self.assertEqual("marketing", task["execution_unit_id"])
        self.assertEqual("marketing_lead", task["manager_agent_id"])
        self.assertEqual("outreach", task["external_action_type"])
        self.assertTrue(task["external_action_required"])

        closed = initiative_routes.close_initiative(
            created["id"],
            InitiativeCloseoutRequest(
                founder_outcome="mixed",
                founder_notes="Outreach produced signal, but needs another batch.",
                retrospective_session_id="board_initiative_retro",
                memory_proposals=["ICP pain language should be reused in the next outreach batch."],
                carryover_decisions=[
                    {"task_id": "initiative_vertical_slice_outreach", "decision": "carry_over"},
                ],
            ),
        )

        self.assertEqual("closed", closed["status"])
        self.assertEqual("mixed", closed["closeout"]["founder_outcome"])
        self.assertEqual(
            "carry_over",
            closed["closeout"]["carryover_decisions"][0]["decision"],
        )


if __name__ == "__main__":
    unittest.main()
