import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from server.board.llm import LLMResponse
from server.board.orchestrator import BoardOrchestrator, BoardSession, MemberResponse
from server.board.verification import VerificationResult, verify_synthesis


class VerificationContractTest(unittest.TestCase):
    def test_board_session_serializes_verification_result(self):
        session = BoardSession(
            session_id="board_verify",
            user_query="Should we pivot?",
            verification=VerificationResult(
                score=8,
                passed=True,
                deficiencies=[],
                suggestions=[],
            ).to_dict(),
        )

        self.assertEqual(8, session.to_dict()["verification"]["score"])
        self.assertTrue(session.to_dict()["verification"]["passed"])


class VerificationAsyncContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_verify_synthesis_parses_plain_json(self):
        with patch("server.board.verification.query_llm", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = LLMResponse(
                content='{"score": 6, "deficiencies": ["too vague"], "suggestions": ["add owner"]}',
                model="verifier",
                input_tokens=1,
                output_tokens=1,
                latency_seconds=0.1,
            )

            result = await verify_synthesis("summary", "peer review", "query")

        self.assertEqual("kimi/kimi-k2.5", mock_query.await_args.kwargs["model"])
        self.assertEqual(6, result.score)
        self.assertFalse(result.passed)
        self.assertEqual(["too vague"], result.deficiencies)
        self.assertEqual(["add owner"], result.suggestions)

    async def test_verify_synthesis_defaults_to_indeterminate_failure_on_parse_error(self):
        with patch("server.board.verification.query_llm", new_callable=AsyncMock) as mock_query:
            with patch("server.board.verification.logger.warning"):
                mock_query.return_value = LLMResponse(
                    content="not json",
                    model="verifier",
                    input_tokens=1,
                    output_tokens=1,
                    latency_seconds=0.1,
                )

                result = await verify_synthesis("summary", "peer review", "query")

        self.assertEqual(0, result.score)
        self.assertFalse(result.passed)
        self.assertEqual("indeterminate", result.status)
        self.assertIn("Verification error", result.deficiencies[0])

    async def test_deliberate_failed_verification_triggers_one_revision_and_persists_result(self):
        orchestrator = BoardOrchestrator()
        first_synthesis = MemberResponse(
            member_id="chairperson",
            stage=3,
            content="### Executive Summary\nToo vague.",
            model="chair",
            elapsed_seconds=0.1,
        )

        with patch.object(orchestrator, "stage1", new=AsyncMock(return_value=[])):
            with patch.object(orchestrator, "stage2", new=AsyncMock(return_value=[])):
                with patch.object(orchestrator, "stage3", new=AsyncMock(return_value=first_synthesis)):
                    with patch("server.board.verification.verify_synthesis", new_callable=AsyncMock) as mock_verify:
                        with patch("server.board.orchestrator.query_llm", new_callable=AsyncMock) as mock_query:
                            with patch.object(BoardSession, "save", return_value=Path("data/sessions/board_verify.json")):
                                mock_verify.side_effect = [
                                    VerificationResult(
                                        score=5,
                                        passed=False,
                                        deficiencies=["missing next steps"],
                                        suggestions=["add concrete steps"],
                                    ),
                                    VerificationResult(
                                        score=8,
                                        passed=True,
                                        deficiencies=[],
                                        suggestions=[],
                                    ),
                                ]
                                mock_query.return_value = LLMResponse(
                                    content="### Executive Summary\nRevised with next steps.\n\n### SOTB Update\n- None.",
                                    model="chair",
                                    input_tokens=10,
                                    output_tokens=10,
                                    latency_seconds=0.1,
                                )

                                session = await orchestrator.deliberate(
                                    "Should we pivot?",
                                    skip_classify=True,
                                    verify=True,
                                    session_id="board_verify",
                                )

        self.assertEqual(2, mock_verify.await_count)
        self.assertEqual(1, mock_query.await_count)
        self.assertEqual(8, session.verification["score"])
        self.assertIn("Revised with next steps", session.stage3_synthesis.content)


if __name__ == "__main__":
    unittest.main()
