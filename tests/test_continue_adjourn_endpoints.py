"""Contract tests for /sessions/{sid}/continue and /sessions/{sid}/adjourn."""

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.requests import Request

from server.api.routes import board as board_routes
from server.api.schemas import ContinueRequest
from server.board.deliberation.orchestrator import BoardSession, MemberResponse


def _fake_request(client_ip: str = "127.0.0.1") -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/sessions/test/continue",
        "headers": [],
        "client": (client_ip, 9999),
    })


class ContinueEndpointTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp_dir = Path("data/sessions").resolve()
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = "board_99999"
        self.session_path = self.tmp_dir / f"{self.session_id}.json"
        # Seed a session in awaiting_chair_decision state.
        seed = {
            "session_id": self.session_id,
            "user_query": "Q1",
            "stage1": [],
            "stage2": [],
            "stage3": None,
            "secretary_brief": {"member_id": "secretary", "stage": 4, "content": "brief r0", "model": "m", "elapsed_seconds": 0.1},
            "secretary_briefs": [{"member_id": "secretary", "stage": 4, "content": "brief r0", "model": "m", "elapsed_seconds": 0.1}],
            "continuation_count": 0,
            "status": "awaiting_chair_decision",
            "conversation": {"messages": [{"id": "user_0", "speaker": "user", "content": "Q1"}], "routing_trace": []},
            "decision": None,
            "delegation_plan": None,
            "verification": None,
            "memory": None,
            "intake_cards": [],
            "clarification": {},
            "structured_output_warnings": [],
            "evidence_packets": {},
            "participation": [],
            "classification": None,
        }
        self.session_path.write_text(json.dumps(seed))

    def tearDown(self) -> None:
        if self.session_path.exists():
            self.session_path.unlink()
        board_routes._DELIBERATE_REQUESTS.clear()

    async def test_continue_unknown_session_returns_404(self) -> None:
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            await board_routes.continue_meeting(
                session_id="board_99404",
                req=ContinueRequest(user_input="hello"),
                request=_fake_request(),
            )
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_continue_invalid_session_id_format_returns_400(self) -> None:
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            await board_routes.continue_meeting(
                session_id="not-a-valid-id",
                req=ContinueRequest(user_input="hello"),
                request=_fake_request(),
            )
        # _validate_session_id raises 400 for non-conforming IDs.
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_continue_empty_user_input_returns_400(self) -> None:
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            await board_routes.continue_meeting(
                session_id=self.session_id,
                req=ContinueRequest(user_input=""),
                request=_fake_request(),
            )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_continue_session_not_awaiting_returns_409(self) -> None:
        # Flip persisted status to running so the endpoint must reject.
        data = json.loads(self.session_path.read_text())
        data["status"] = "running"
        self.session_path.write_text(json.dumps(data))

        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            await board_routes.continue_meeting(
                session_id=self.session_id,
                req=ContinueRequest(user_input="Follow up"),
                request=_fake_request(),
            )
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_continue_at_cap_emits_meeting_capped_429(self) -> None:
        os.environ["AGENTIC_BOARD_LIVE_MAX_CONTINUATIONS"] = "1"
        try:
            data = json.loads(self.session_path.read_text())
            data["continuation_count"] = 1  # already at cap
            self.session_path.write_text(json.dumps(data))

            from fastapi import HTTPException
            with self.assertRaises(HTTPException) as ctx:
                await board_routes.continue_meeting(
                    session_id=self.session_id,
                    req=ContinueRequest(user_input="One more"),
                    request=_fake_request(),
                )
            self.assertEqual(ctx.exception.status_code, 429)
            detail = ctx.exception.detail
            if isinstance(detail, dict):
                self.assertEqual(detail.get("event"), "meeting_capped")
        finally:
            os.environ.pop("AGENTIC_BOARD_LIVE_MAX_CONTINUATIONS", None)


if __name__ == "__main__":
    unittest.main()
