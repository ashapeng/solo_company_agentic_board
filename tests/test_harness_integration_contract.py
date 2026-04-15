import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from server.board.harness_config import HarnessConfig, get_config
from server.board.ledger import init_db, query_outcomes, LedgerError
from server.board.llm import LLMResponse
from server.board.orchestrator import BoardOrchestrator, BoardSession, MemberResponse
from server.board.verification import verify_synthesis
from server.api import feedback, FeedbackRequest


class ConfigWiringContractTest(unittest.TestCase):
    def test_orchestrator_no_longer_has_hardcoded_stage_max_tokens(self):
        """After migration, STAGE_MAX_TOKENS should not exist in orchestrator."""
        import server.board.orchestrator as orch_module
        self.assertFalse(
            hasattr(orch_module, "STAGE_MAX_TOKENS"),
            "STAGE_MAX_TOKENS should be deleted from orchestrator — now in harness_config",
        )

    def test_orchestrator_no_longer_has_hardcoded_response_thresholds(self):
        import server.board.orchestrator as orch_module
        self.assertFalse(hasattr(orch_module, "MAX_STAGE1_REQUIRED_RESPONSES"))
        self.assertFalse(hasattr(orch_module, "MAX_STAGE2_REQUIRED_RESPONSES"))


class ConfigWiringAsyncContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_orchestrator_uses_config_token_budget(self):
        """Orchestrator should pass config's max_tokens to query_llm."""
        with patch("server.board.orchestrator.get_config") as mock_cfg:
            mock_cfg.return_value = HarnessConfig(stage1_max_tokens=999)
            with patch("server.board.orchestrator.query_llm", new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = LLMResponse(
                    content="Analysis.", model="test", input_tokens=1,
                    output_tokens=1, latency_seconds=0.1,
                )
                orchestrator = BoardOrchestrator()
                if orchestrator.council:
                    member = orchestrator.council[0]
                    await orchestrator._query_member(member, "test prompt", stage=1)

                    call_kwargs = mock_llm.call_args
                    self.assertEqual(call_kwargs.kwargs.get("max_tokens"), 999)

    async def test_verification_uses_config_threshold(self):
        """verify_synthesis should use config's verification_threshold."""
        with patch("server.board.verification.get_config") as mock_cfg:
            mock_cfg.return_value = HarnessConfig(verification_threshold=9.0)
            with patch("server.board.verification.query_llm", new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = LLMResponse(
                    content='{"score": 8, "deficiencies": [], "suggestions": []}',
                    model="verifier", input_tokens=1, output_tokens=1,
                    latency_seconds=0.1,
                )

                result = await verify_synthesis("summary", "peer review", "query")

                # Score 8 < threshold 9 → should NOT pass
                self.assertFalse(result.passed)


class LedgerWiringAsyncContractTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test_ledger.db"
        init_db(self.db_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    async def test_deliberate_records_ledger_entry(self):
        """After deliberate() completes, a ledger row should exist."""
        orchestrator = BoardOrchestrator()
        synthesis = MemberResponse(
            member_id="chairperson", stage=3,
            content="### Executive Summary\nLaunch.\n\n### SOTB Update\n- None.",
            model="chair", elapsed_seconds=0.1,
        )

        with patch.object(orchestrator, "stage1", new=AsyncMock(return_value=[
            MemberResponse(member_id="strategist", stage=1, content="A.", model="m", elapsed_seconds=0.1),
        ])):
            with patch.object(orchestrator, "stage2", new=AsyncMock(return_value=[])):
                with patch.object(orchestrator, "stage3", new=AsyncMock(return_value=synthesis)):
                    with patch.object(BoardSession, "save", return_value=Path("/tmp/s.json")):
                        with patch("server.board.orchestrator._LEDGER_DB_PATH", self.db_path):
                            session = await orchestrator.deliberate(
                                "Should we launch?",
                                skip_classify=True,
                                session_id="ledger_test",
                            )

        rows = query_outcomes(db_path=self.db_path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["session_id"], "ledger_test")
        self.assertEqual(rows[0]["harness_config_version"], get_config().version)

    async def test_ledger_entry_has_null_query_type_when_classifier_skipped(self):
        orchestrator = BoardOrchestrator()
        synthesis = MemberResponse(
            member_id="chairperson", stage=3,
            content="### Executive Summary\nDecision.\n\n### SOTB Update\n- None.",
            model="chair", elapsed_seconds=0.1,
        )

        with patch.object(orchestrator, "stage1", new=AsyncMock(return_value=[])):
            with patch.object(orchestrator, "stage2", new=AsyncMock(return_value=[])):
                with patch.object(orchestrator, "stage3", new=AsyncMock(return_value=synthesis)):
                    with patch.object(BoardSession, "save", return_value=Path("/tmp/s.json")):
                        with patch("server.board.orchestrator._LEDGER_DB_PATH", self.db_path):
                            session = await orchestrator.deliberate(
                                "Test query",
                                skip_classify=True,
                                session_id="no_classify_test",
                            )

        rows = query_outcomes(db_path=self.db_path)
        self.assertIsNone(rows[0]["query_type"])


class FeedbackEndpointContractTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test_ledger.db"
        init_db(self.db_path)
        self._old_remote = os.environ.get("AGENTIC_BOARD_ALLOW_REMOTE")
        os.environ["AGENTIC_BOARD_ALLOW_REMOTE"] = "1"

    def tearDown(self):
        self.tmpdir.cleanup()
        if self._old_remote is None:
            os.environ.pop("AGENTIC_BOARD_ALLOW_REMOTE", None)
        else:
            os.environ["AGENTIC_BOARD_ALLOW_REMOTE"] = self._old_remote

    async def test_valid_feedback_returns_200(self):
        from server.board.ledger import record_session
        from tests.test_ledger_contract import _make_session

        record_session(_make_session("fb_test"), config_version=1, db_path=self.db_path)

        with patch("server.api._FEEDBACK_DB_PATH", self.db_path):
            result = await feedback("fb_test", FeedbackRequest(rating="positive", note="Good"))

        self.assertEqual(result["status"], "recorded")
        self.assertEqual(result["session_id"], "fb_test")

    async def test_invalid_rating_raises_422(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            with patch("server.api._FEEDBACK_DB_PATH", self.db_path):
                await feedback("any_id", FeedbackRequest(rating="meh"))

        self.assertEqual(ctx.exception.status_code, 422)

    async def test_nonexistent_session_raises_404(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            with patch("server.api._FEEDBACK_DB_PATH", self.db_path):
                await feedback("no_such", FeedbackRequest(rating="positive"))

        self.assertEqual(ctx.exception.status_code, 404)

    async def test_note_exceeding_500_chars_raises_422(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            with patch("server.api._FEEDBACK_DB_PATH", self.db_path):
                await feedback("any_id", FeedbackRequest(rating="positive", note="x" * 501))

        self.assertEqual(ctx.exception.status_code, 422)

    async def test_second_feedback_overwrites_first(self):
        from server.board.ledger import record_session
        from tests.test_ledger_contract import _make_session

        record_session(_make_session("fb_overwrite"), config_version=1, db_path=self.db_path)

        with patch("server.api._FEEDBACK_DB_PATH", self.db_path):
            await feedback("fb_overwrite", FeedbackRequest(rating="negative", note="Bad"))
            await feedback("fb_overwrite", FeedbackRequest(rating="positive", note="Changed mind"))

        rows = query_outcomes(db_path=self.db_path)
        row = next(r for r in rows if r["session_id"] == "fb_overwrite")
        self.assertEqual(row["feedback_rating"], "positive")
        self.assertEqual(row["feedback_note"], "Changed mind")


if __name__ == "__main__":
    unittest.main()
