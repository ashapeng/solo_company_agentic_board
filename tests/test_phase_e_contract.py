import json
import sqlite3
import unittest
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from server.board.deliberation.classifier import QueryClassification
from server.board.config import BoardMember
from server.harness.config import HarnessConfig, load_config
from server.harness.ledger import init_db
from server.board.deliberation.orchestrator import BoardOrchestrator, BoardSession, MemberResponse, _assign_models
from server.harness.model_assignment import tune_model_assignments


def _member(member_id: str, *, override: str | None = None) -> BoardMember:
    return BoardMember(
        id=member_id,
        title=f"{member_id.title()} Member",
        role="Test Role",
        expertise=[],
        system_prompt=f"{member_id} system prompt",
        model_override=override,
    )


def _insert_outcome(
    db_path: Path,
    session_id: str,
    *,
    query_type: str | None = "strategic",
    models_used: dict[str, str] | None = None,
    verification_score: int | None = None,
    feedback_rating: str | None = None,
) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """INSERT INTO session_outcomes (
                session_id, timestamp, query_type, complexity,
                models_used, verification_score, feedback_rating,
                harness_config_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                f"2026-04-15T00:00:{session_id[-2:]}+00:00",
                query_type,
                "moderate",
                json.dumps(models_used or {}),
                verification_score,
                feedback_rating,
                1,
            ),
        )
        conn.commit()
    finally:
        conn.close()


class PhaseEModelAssignmentContractTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        root = Path(self.tmpdir.name)
        self.db_path = root / "ledger.db"
        self.config_path = root / "harness_config.json"
        init_db(self.db_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_tuner_writes_best_model_per_query_type_member(self):
        for idx in range(1, 7):
            _insert_outcome(
                self.db_path,
                f"a{idx:02d}",
                models_used={"strategist": "model-a"},
                verification_score=6,
                feedback_rating="negative",
            )
            _insert_outcome(
                self.db_path,
                f"b{idx:02d}",
                models_used={"strategist": "model-b"},
                verification_score=9,
                feedback_rating="positive",
            )

        report = tune_model_assignments(
            db_path=self.db_path,
            config_path=self.config_path,
        )
        loaded = load_config(self.config_path)

        self.assertTrue(report.saved)
        self.assertEqual(
            "model-b",
            loaded.per_query_type["strategic"]["model_preferences"]["strategist"],
        )
        self.assertEqual(1, len(report.changes))
        self.assertEqual("strategist", report.changes[0].member_id)
        self.assertEqual("model-b", report.changes[0].new_model)

    def test_tuner_requires_multiple_models_for_a_member(self):
        for idx in range(1, 8):
            _insert_outcome(
                self.db_path,
                f"s{idx:02d}",
                models_used={"product": "model-a"},
                verification_score=9,
                feedback_rating="positive",
            )

        report = tune_model_assignments(
            db_path=self.db_path,
            config_path=self.config_path,
        )

        self.assertEqual(report.changes, [])
        self.assertFalse(report.saved)
        self.assertFalse(self.config_path.exists())

    def test_tuner_requires_minimum_samples_per_candidate_model(self):
        for idx in range(1, 7):
            _insert_outcome(
                self.db_path,
                f"a{idx:02d}",
                models_used={"product": "model-a"},
                verification_score=7,
            )
        _insert_outcome(
            self.db_path,
            "b01",
            models_used={"product": "model-b"},
            verification_score=10,
            feedback_rating="positive",
        )

        report = tune_model_assignments(
            db_path=self.db_path,
            config_path=self.config_path,
        )

        self.assertEqual(report.changes, [])
        self.assertFalse(report.saved)

    def test_dry_run_reports_model_preferences_without_saving(self):
        for idx in range(1, 7):
            _insert_outcome(
                self.db_path,
                f"a{idx:02d}",
                models_used={"critic": "model-a"},
                verification_score=5,
                feedback_rating="negative",
            )
            _insert_outcome(
                self.db_path,
                f"b{idx:02d}",
                models_used={"critic": "model-b"},
                verification_score=9,
                feedback_rating="positive",
            )

        report = tune_model_assignments(
            db_path=self.db_path,
            config_path=self.config_path,
            dry_run=True,
        )

        self.assertTrue(report.dry_run)
        self.assertFalse(report.saved)
        self.assertEqual(1, len(report.changes))
        self.assertFalse(self.config_path.exists())

    def test_tuner_preserves_existing_query_type_metadata(self):
        cfg = HarnessConfig(per_query_type={
            "strategic": {
                "verification_threshold": 8.0,
                "token_budgets": {"moderate": {"stage1_max_tokens": 900}},
                "routing": {"suppressed_member_ids": ["critic"]},
                "model_preferences": {"product": "existing-model"},
            },
        })
        self.config_path.write_text(
            json.dumps(asdict(cfg), indent=2) + "\n",
            encoding="utf-8",
        )
        for idx in range(1, 7):
            _insert_outcome(
                self.db_path,
                f"a{idx:02d}",
                models_used={"strategist": "model-a"},
                verification_score=6,
            )
            _insert_outcome(
                self.db_path,
                f"b{idx:02d}",
                models_used={"strategist": "model-b"},
                verification_score=9,
            )

        tune_model_assignments(
            db_path=self.db_path,
            config_path=self.config_path,
        )
        loaded = load_config(self.config_path)
        qcfg = loaded.per_query_type["strategic"]

        self.assertEqual(8.0, qcfg["verification_threshold"])
        self.assertEqual(900, qcfg["token_budgets"]["moderate"]["stage1_max_tokens"])
        self.assertEqual(["critic"], qcfg["routing"]["suppressed_member_ids"])
        self.assertEqual("existing-model", qcfg["model_preferences"]["product"])
        self.assertEqual("model-b", qcfg["model_preferences"]["strategist"])

    def test_tuner_ignores_unclassified_or_unscored_rows(self):
        for idx in range(1, 7):
            _insert_outcome(
                self.db_path,
                f"u{idx:02d}",
                query_type=None,
                models_used={"strategist": "model-a"},
                verification_score=10,
            )
            _insert_outcome(
                self.db_path,
                f"x{idx:02d}",
                models_used={"strategist": "model-b"},
                verification_score=None,
                feedback_rating=None,
            )

        report = tune_model_assignments(
            db_path=self.db_path,
            config_path=self.config_path,
        )

        self.assertEqual(report.examined_assignments, 0)
        self.assertEqual(report.changes, [])
        self.assertFalse(report.saved)

    def test_assign_models_uses_query_type_model_preference(self):
        cfg = HarnessConfig(per_query_type={
            "strategic": {
                "model_preferences": {"strategist": "model-b"},
            },
        })

        assignments = _assign_models(
            [_member("strategist"), _member("product")],
            query_type="strategic",
            config=cfg,
        )

        self.assertEqual("model-b", assignments["strategist"])

    def test_assign_models_keeps_explicit_member_override(self):
        cfg = HarnessConfig(per_query_type={
            "strategic": {
                "model_preferences": {"strategist": "model-b"},
            },
        })

        assignments = _assign_models(
            [_member("strategist", override="member-override")],
            query_type="strategic",
            config=cfg,
        )

        self.assertEqual("member-override", assignments["strategist"])

    async def test_deliberate_uses_model_preference_after_classification(self):
        cfg = HarnessConfig(per_query_type={
            "strategic": {
                "model_preferences": {"strategist": "model-b"},
            },
        })
        classification = QueryClassification(
            query_type="strategic",
            complexity="moderate",
            relevant_member_ids=["strategist", "chairperson"],
            reasoning="Strategic decision.",
        )
        orchestrator = BoardOrchestrator()
        synthesis = MemberResponse(
            member_id="chairperson",
            stage=3,
            content="### Executive Summary\nLaunch.\n\n### SOTB Update\n- None.",
            model="m",
            elapsed_seconds=0.1,
        )

        with patch("server.board.deliberation.orchestrator.get_config", return_value=cfg):
            with patch("server.board.deliberation.classifier.classify_query", new_callable=AsyncMock) as mock_classify:
                with patch.object(orchestrator, "stage1", new=AsyncMock(return_value=[])):
                    with patch.object(orchestrator, "stage2", new=AsyncMock(return_value=[])):
                        with patch.object(orchestrator, "stage3", new=AsyncMock(return_value=synthesis)):
                            with patch.object(BoardSession, "save", return_value=Path("/tmp/s.json")):
                                with patch("server.board.deliberation.orchestrator._record_to_ledger"):
                                    with patch.object(
                                        orchestrator,
                                        "_collect_member_evidence",
                                        new=AsyncMock(return_value=("", {})),
                                    ):
                                        with patch.object(
                                            orchestrator,
                                            "stage4_secretary_brief",
                                            new=AsyncMock(return_value=None),
                                        ):
                                            mock_classify.return_value = classification
                                            await orchestrator.deliberate(
                                                "Should we launch?",
                                                session_id="model_preference",
                                            )

        self.assertEqual("model-b", orchestrator.model_assignments["strategist"])


if __name__ == "__main__":
    unittest.main()
