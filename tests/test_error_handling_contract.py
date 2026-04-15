import unittest
from unittest.mock import patch

from server.board.config import BoardMember
from server.board.orchestrator import BoardDeliberationError, BoardOrchestrator, MemberResponse


def _member(member_id: str) -> BoardMember:
    return BoardMember(
        id=member_id,
        title=f"{member_id.title()} Member",
        role="Test Role",
        expertise=[],
        system_prompt=f"{member_id} system",
        stage2_behavior="Challenge weak evidence.",
    )


def _response(member_id: str, stage: int) -> MemberResponse:
    return MemberResponse(
        member_id=member_id,
        stage=stage,
        content=f"{member_id} response",
        model="test-model",
        elapsed_seconds=0.1,
    )


class ErrorHandlingAsyncContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_stage1_continues_when_threshold_is_met(self):
        orchestrator = BoardOrchestrator(members=[
            _member("alpha"),
            _member("beta"),
            _member("gamma"),
            _member("delta"),
        ])
        failures: list[tuple[int, str, str]] = []
        orchestrator._on_member_done = (
            lambda stage, member, resp, error=None: failures.append((stage, member.id, error))
            if error
            else None
        )

        async def fake_query(member, prompt, stage):
            if member.id == "delta":
                raise RuntimeError("provider unavailable")
            return _response(member.id, stage)

        with patch.object(orchestrator, "_query_member", side_effect=fake_query):
            with patch("server.board.orchestrator.logger.warning"):
                responses = await orchestrator.stage1("query")

        self.assertEqual(["alpha", "beta", "gamma"], [response.member_id for response in responses])
        self.assertEqual([(1, "delta", "provider unavailable")], failures)

    async def test_stage1_aborts_when_threshold_is_not_met(self):
        orchestrator = BoardOrchestrator(members=[
            _member("alpha"),
            _member("beta"),
            _member("gamma"),
            _member("delta"),
        ])

        async def fake_query(member, prompt, stage):
            if member.id in {"alpha", "beta"}:
                return _response(member.id, stage)
            raise RuntimeError("provider unavailable")

        with patch.object(orchestrator, "_query_member", side_effect=fake_query):
            with patch("server.board.orchestrator.logger.warning"):
                with self.assertRaisesRegex(BoardDeliberationError, "Stage 1 failed: only 2/4"):
                    await orchestrator.stage1("query")

    async def test_stage2_aborts_when_threshold_is_not_met(self):
        orchestrator = BoardOrchestrator(members=[
            _member("alpha"),
            _member("beta"),
            _member("gamma"),
        ])

        async def fake_query(member, prompt, stage):
            if member.id == "alpha":
                return _response(member.id, stage)
            raise RuntimeError("provider unavailable")

        with patch.object(orchestrator, "_query_member", side_effect=fake_query):
            with patch("server.board.orchestrator.logger.warning"):
                with self.assertRaisesRegex(BoardDeliberationError, "Stage 2 failed: only 1/3"):
                    await orchestrator.stage2("query", [_response("alpha", 1), _response("beta", 1)])

    async def test_stage1_threshold_scales_down_for_focused_route(self):
        orchestrator = BoardOrchestrator(members=[
            _member("alpha"),
            _member("beta"),
        ])

        async def fake_query(member, prompt, stage):
            return _response(member.id, stage)

        with patch.object(orchestrator, "_query_member", side_effect=fake_query):
            responses = await orchestrator.stage1("query")

        self.assertEqual(["alpha", "beta"], [response.member_id for response in responses])

    async def test_stage2_skips_for_single_member_route(self):
        orchestrator = BoardOrchestrator(members=[
            _member("alpha"),
        ])

        responses = await orchestrator.stage2("query", [_response("alpha", 1)])

        self.assertEqual([], responses)


if __name__ == "__main__":
    unittest.main()
