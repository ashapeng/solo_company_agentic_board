import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from server.board.deliberation.classifier import QueryClassification
from server.harness.config import HarnessConfig, get_config
from server.harness.ledger import init_db, query_outcomes, LedgerError
from server.board.llm import LLMResponse
from server.board.deliberation.orchestrator import BoardOrchestrator, BoardSession, MemberResponse
from server.board.deliberation.verification import VerificationResult, verify_synthesis
from server.api import feedback, FeedbackRequest


class ConfigWiringContractTest(unittest.TestCase):
    def test_orchestrator_no_longer_has_hardcoded_stage_max_tokens(self):
        """After migration, STAGE_MAX_TOKENS should not exist in orchestrator."""
        import server.board.deliberation.orchestrator as orch_module
        self.assertFalse(
            hasattr(orch_module, "STAGE_MAX_TOKENS"),
            "STAGE_MAX_TOKENS should be deleted from orchestrator — now in harness_config",
        )

    def test_orchestrator_no_longer_has_hardcoded_response_thresholds(self):
        import server.board.deliberation.orchestrator as orch_module
        self.assertFalse(hasattr(orch_module, "MAX_STAGE1_REQUIRED_RESPONSES"))
        self.assertFalse(hasattr(orch_module, "MAX_STAGE2_REQUIRED_RESPONSES"))


class ConfigWiringAsyncContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_orchestrator_uses_config_token_budget(self):
        """Orchestrator should pass config's max_tokens to query_llm."""
        with patch("server.board.deliberation.orchestrator.get_config") as mock_cfg:
            mock_cfg.return_value = HarnessConfig(stage1_max_tokens=999)
            with patch("server.board.deliberation.orchestrator.query_llm", new_callable=AsyncMock) as mock_llm:
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

    async def test_orchestrator_uses_tuned_query_complexity_token_budget(self):
        with patch("server.board.deliberation.orchestrator.get_config") as mock_cfg:
            mock_cfg.return_value = HarnessConfig(per_query_type={
                "strategic": {
                    "token_budgets": {
                        "complex": {"stage1_max_tokens": 1777},
                    },
                },
            })
            with patch("server.board.deliberation.orchestrator.query_llm", new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = LLMResponse(
                    content="Analysis.", model="test", input_tokens=1,
                    output_tokens=1, latency_seconds=0.1,
                )
                orchestrator = BoardOrchestrator()
                if orchestrator.council:
                    member = orchestrator.council[0]
                    await orchestrator._query_member(
                        member,
                        "test prompt",
                        stage=1,
                        query_type="strategic",
                        complexity="complex",
                    )

                    call_kwargs = mock_llm.call_args
                    self.assertEqual(call_kwargs.kwargs.get("max_tokens"), 1777)

    async def test_verification_uses_config_threshold(self):
        """verify_synthesis should use config's verification_threshold."""
        with patch("server.board.deliberation.verification.get_config") as mock_cfg:
            mock_cfg.return_value = HarnessConfig(verification_threshold=9.0)
            with patch("server.board.deliberation.verification.query_llm", new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = LLMResponse(
                    content='{"score": 8, "deficiencies": [], "suggestions": []}',
                    model="verifier", input_tokens=1, output_tokens=1,
                    latency_seconds=0.1,
                )

                result = await verify_synthesis("summary", "peer review", "query")

                # Score 8 < threshold 9 → should NOT pass
                self.assertFalse(result.passed)

    async def test_verification_uses_tuned_query_type_threshold(self):
        with patch("server.board.deliberation.verification.get_config") as mock_cfg:
            mock_cfg.return_value = HarnessConfig(
                verification_threshold=7.0,
                per_query_type={"strategic": {"verification_threshold": 9.0}},
            )
            with patch("server.board.deliberation.verification.query_llm", new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = LLMResponse(
                    content='{"score": 8, "deficiencies": [], "suggestions": []}',
                    model="verifier", input_tokens=1, output_tokens=1,
                    latency_seconds=0.1,
                )

                result = await verify_synthesis(
                    "summary",
                    "peer review",
                    "query",
                    query_type="strategic",
                )

        self.assertFalse(result.passed)

    async def test_deliberate_passes_query_type_to_verification(self):
        orchestrator = BoardOrchestrator()
        synthesis = MemberResponse(
            member_id="chairperson", stage=3,
            content="### Executive Summary\nLaunch.\n\n### SOTB Update\n- None.",
            model="chair", elapsed_seconds=0.1,
        )
        classification = QueryClassification(
            query_type="strategic",
            complexity="complex",
            relevant_member_ids=["strategist", "chairperson"],
            reasoning="Strategic launch decision.",
        )

        with patch("server.board.deliberation.classifier.classify_query", new_callable=AsyncMock) as mock_classify:
            with patch.object(orchestrator, "stage1", new=AsyncMock(return_value=[])):
                with patch.object(orchestrator, "stage2", new=AsyncMock(return_value=[])):
                    with patch.object(orchestrator, "stage3", new=AsyncMock(return_value=synthesis)):
                        with patch("server.board.deliberation.verification.verify_synthesis", new_callable=AsyncMock) as mock_verify:
                            with patch.object(BoardSession, "save", return_value=Path("/tmp/s.json")):
                                with patch("server.board.deliberation.orchestrator._record_to_ledger"):
                                    mock_classify.return_value = classification
                                    mock_verify.return_value = VerificationResult(
                                        score=8,
                                        passed=True,
                                        deficiencies=[],
                                        suggestions=[],
                                    )

                                    await orchestrator.deliberate(
                                        "Should we launch?",
                                        verify=True,
                                        session_id="verification_query_type",
                                    )

        self.assertEqual("strategic", mock_verify.await_args.kwargs["query_type"])


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
                        with patch("server.board.deliberation.orchestrator._LEDGER_DB_PATH", self.db_path):
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
                        with patch("server.board.deliberation.orchestrator._LEDGER_DB_PATH", self.db_path):
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
        from server.harness.ledger import record_session
        from tests.test_ledger_contract import _make_session

        record_session(_make_session("board_1700000010"), config_version=1, db_path=self.db_path)

        with patch("server.api._FEEDBACK_DB_PATH", self.db_path):
            result = await feedback("board_1700000010", FeedbackRequest(rating="positive", note="Good"))

        self.assertEqual(result["status"], "recorded")
        self.assertEqual(result["session_id"], "board_1700000010")

    async def test_invalid_rating_raises_422(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            with patch("server.api._FEEDBACK_DB_PATH", self.db_path):
                await feedback("board_1700000011", FeedbackRequest(rating="meh"))

        self.assertEqual(ctx.exception.status_code, 422)

    async def test_nonexistent_session_raises_404(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            with patch("server.api._FEEDBACK_DB_PATH", self.db_path):
                await feedback("board_1700000012", FeedbackRequest(rating="positive"))

        self.assertEqual(ctx.exception.status_code, 404)

    async def test_note_exceeding_500_chars_raises_422(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            with patch("server.api._FEEDBACK_DB_PATH", self.db_path):
                await feedback("board_1700000011", FeedbackRequest(rating="positive", note="x" * 501))

        self.assertEqual(ctx.exception.status_code, 422)

    async def test_second_feedback_overwrites_first(self):
        from server.harness.ledger import record_session
        from tests.test_ledger_contract import _make_session

        record_session(_make_session("board_1700000013"), config_version=1, db_path=self.db_path)

        with patch("server.api._FEEDBACK_DB_PATH", self.db_path):
            await feedback("board_1700000013", FeedbackRequest(rating="negative", note="Bad"))
            await feedback("board_1700000013", FeedbackRequest(rating="positive", note="Changed mind"))

        rows = query_outcomes(db_path=self.db_path)
        row = next(r for r in rows if r["session_id"] == "board_1700000013")
        self.assertEqual(row["feedback_rating"], "positive")
        self.assertEqual(row["feedback_note"], "Changed mind")


class DriftRecommendationTest(unittest.TestCase):
    def test_drift_fires_when_recent_sessions_regress(self):
        import tempfile
        from pathlib import Path

        from server.harness import ledger as ledger_mod
        from server.harness.reviews import run_harness_review

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "ledger.db"
            ledger_mod.init_db(db_path)
            conn = ledger_mod._connect(db_path)
            try:
                # 100 baseline rows at score 8 (older timestamps).
                for i in range(100):
                    conn.execute(
                        "INSERT INTO session_outcomes (session_id, timestamp, "
                        "query_type, verification_score, harness_config_version) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (f"board_b{i}", f"2026-04-10T{i % 24:02d}:00:{i % 60:02d}Z",
                         "product", 8, 1),
                    )
                # 10 recent rows at score 3 (newer timestamps).
                for i in range(10):
                    conn.execute(
                        "INSERT INTO session_outcomes (session_id, timestamp, "
                        "query_type, verification_score, harness_config_version) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (f"board_r{i}", f"2026-04-20T{i:02d}:00:00Z",
                         "product", 3, 1),
                    )
                conn.commit()
            finally:
                conn.close()

            # Patch the ledger's default DB path for the duration of the call.
            original = ledger_mod._DEFAULT_DB_PATH
            ledger_mod._DEFAULT_DB_PATH = db_path
            try:
                review = run_harness_review(dry_run=True)
            finally:
                ledger_mod._DEFAULT_DB_PATH = original

        categories = {r["category"] for r in review.get("recommendations", [])}
        self.assertIn("drift", categories)


def test_harness_config_hardening_defaults(tmp_path, monkeypatch):
    """hardening block ships with P1 defaults; load preserves them on empty JSON."""
    from server.harness.config import HarnessConfig, get_config, load_config

    cfg = HarnessConfig()
    assert isinstance(cfg.hardening, dict)
    assert cfg.hardening["atomizer_model"] == "qwen/qwen3.6-plus-2026-04-02"
    assert cfg.hardening["blinded_verifier_pass_threshold"] == 0.80
    assert cfg.hardening["blinded_verifier_evidence_max_chars"] == 4000


def test_harness_config_hardening_overrides_from_json(tmp_path):
    """Custom hardening values in harness_config.json override defaults."""
    from server.harness.config import load_config

    path = tmp_path / "harness_config.json"
    path.write_text(json.dumps({
        "stage1_max_tokens": 1200,
        "stage2_max_tokens": 800,
        "stage3_max_tokens": 4000,
        "stage4_max_tokens": 3000,
        "revision_max_tokens": 2500,
        "min_stage1_responses": 3,
        "min_stage2_responses": 2,
        "verification_threshold": 7.0,
        "max_revision_attempts": 1,
        "complexity_multipliers": {"simple": 0.6, "moderate": 1.0, "complex": 1.5},
        "per_query_type": {},
        "hardening": {
            "atomizer_model": "qwen/qwen3.6-max-preview",
            "blinded_verifier_pass_threshold": 0.7,
            "blinded_verifier_evidence_max_chars": 6000,
        },
        "version": 5,
        "last_modified": "2026-05-16T00:00:00+00:00",
    }))

    cfg = load_config(path)
    assert cfg.hardening["blinded_verifier_pass_threshold"] == 0.7
    assert cfg.hardening["blinded_verifier_evidence_max_chars"] == 6000


if __name__ == "__main__":
    unittest.main()
