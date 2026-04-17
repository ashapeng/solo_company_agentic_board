import json
import sqlite3
import unittest
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from server.board.harness_config import HarnessConfig, load_config
from server.board.ledger import init_db
from server.board.tuner import (
    TOKEN_BUDGET_CEILINGS,
    TOKEN_BUDGET_FLOORS,
    VERIFICATION_THRESHOLD_CEILING,
    VERIFICATION_THRESHOLD_FLOOR,
    tune_token_budgets,
    tune_verification_thresholds,
)


def _insert_outcome(
    db_path: Path,
    session_id: str,
    *,
    query_type: str | None = "strategic",
    complexity: str | None = "moderate",
    stage1_tokens: int = 600,
    stage2_tokens: int = 500,
    stage3_tokens: int = 2500,
    verification_score: int | None = None,
    verification_passed: bool | None = None,
    feedback_rating: str | None = None,
) -> None:
    passed = None
    if verification_passed is not None:
        passed = 1 if verification_passed else 0

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """INSERT INTO session_outcomes (
                session_id, timestamp, query_type, complexity,
                stage1_tokens, stage2_tokens, stage3_tokens,
                verification_score, verification_passed, feedback_rating,
                harness_config_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                f"2026-04-15T00:00:{session_id[-2:]}+00:00",
                query_type,
                complexity,
                stage1_tokens,
                stage2_tokens,
                stage3_tokens,
                verification_score,
                passed,
                feedback_rating,
                1,
            ),
        )
        conn.commit()
    finally:
        conn.close()


class TokenBudgetTunerContractTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "ledger.db"
        self.config_path = Path(self.tmpdir.name) / "harness_config.json"
        init_db(self.db_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_skips_segments_with_fewer_than_three_sessions(self):
        _insert_outcome(self.db_path, "s01", stage1_tokens=200)
        _insert_outcome(self.db_path, "s02", stage1_tokens=220)

        report = tune_token_budgets(db_path=self.db_path, config_path=self.config_path)

        self.assertEqual(report.examined_segments, 1)
        self.assertEqual(report.eligible_segments, 0)
        self.assertEqual(report.changes, [])
        self.assertFalse(report.saved)
        self.assertFalse(self.config_path.exists())

    def test_writes_shrink_and_expand_overrides_per_query_complexity(self):
        for idx, stage1, stage3 in (
            (1, 390, 3600),
            (2, 400, 3700),
            (3, 410, 3800),
        ):
            _insert_outcome(
                self.db_path,
                f"s{idx:02d}",
                query_type="strategic",
                complexity="simple",
                stage1_tokens=stage1,
                stage2_tokens=500,
                stage3_tokens=stage3,
            )

        report = tune_token_budgets(db_path=self.db_path, config_path=self.config_path)
        loaded = load_config(self.config_path)
        budgets = loaded.per_query_type["strategic"]["token_budgets"]["simple"]

        self.assertTrue(report.saved)
        self.assertEqual(loaded.version, 2)
        self.assertEqual(budgets["stage1_max_tokens"], 520)
        self.assertEqual(budgets["stage3_max_tokens"], 4440)
        self.assertNotIn("stage2_max_tokens", budgets)
        self.assertEqual(
            {(c.query_type, c.complexity, c.field, c.direction) for c in report.changes},
            {
                ("strategic", "simple", "stage1_max_tokens", "shrink"),
                ("strategic", "simple", "stage3_max_tokens", "expand"),
            },
        )

    def test_respects_floor_and_ceiling_guards(self):
        for idx in range(1, 4):
            _insert_outcome(
                self.db_path,
                f"s{idx:02d}",
                query_type="product",
                complexity="complex",
                stage1_tokens=1,
                stage2_tokens=1,
                stage3_tokens=50_000,
            )

        tune_token_budgets(db_path=self.db_path, config_path=self.config_path)
        loaded = load_config(self.config_path)
        budgets = loaded.per_query_type["product"]["token_budgets"]["complex"]

        self.assertEqual(budgets["stage1_max_tokens"], TOKEN_BUDGET_FLOORS["stage1_max_tokens"])
        self.assertEqual(budgets["stage2_max_tokens"], TOKEN_BUDGET_FLOORS["stage2_max_tokens"])
        self.assertEqual(budgets["stage3_max_tokens"], TOKEN_BUDGET_CEILINGS["stage3_max_tokens"])

    def test_preserves_existing_query_type_metadata(self):
        cfg = HarnessConfig(
            per_query_type={
                "strategic": {
                    "verification_threshold": 8.0,
                    "model_preferences": {"strategist": "model-a"},
                    "token_budgets": {
                        "moderate": {"stage1_max_tokens": 1000},
                    },
                },
            },
        )
        self.config_path.write_text(
            json.dumps(asdict(cfg), indent=2) + "\n",
            encoding="utf-8",
        )
        for idx, stage1 in ((1, 940), (2, 950), (3, 960)):
            _insert_outcome(
                self.db_path,
                f"s{idx:02d}",
                query_type="strategic",
                complexity="moderate",
                stage1_tokens=stage1,
                stage2_tokens=500,
                stage3_tokens=2500,
            )

        tune_token_budgets(db_path=self.db_path, config_path=self.config_path)
        loaded = load_config(self.config_path)
        qcfg = loaded.per_query_type["strategic"]

        self.assertEqual(qcfg["verification_threshold"], 8.0)
        self.assertEqual(qcfg["model_preferences"], {"strategist": "model-a"})
        self.assertEqual(qcfg["token_budgets"]["moderate"]["stage1_max_tokens"], 1140)

    def test_dry_run_reports_changes_without_saving(self):
        for idx in range(1, 4):
            _insert_outcome(
                self.db_path,
                f"s{idx:02d}",
                query_type="strategic",
                complexity="simple",
                stage1_tokens=300,
            )

        report = tune_token_budgets(
            db_path=self.db_path,
            config_path=self.config_path,
            dry_run=True,
        )

        self.assertFalse(report.saved)
        self.assertTrue(report.dry_run)
        self.assertGreater(len(report.changes), 0)
        self.assertFalse(self.config_path.exists())

    def test_ignores_unclassified_sessions(self):
        for idx in range(1, 4):
            _insert_outcome(
                self.db_path,
                f"s{idx:02d}",
                query_type=None,
                complexity=None,
                stage1_tokens=100,
            )

        report = tune_token_budgets(db_path=self.db_path, config_path=self.config_path)

        self.assertEqual(report.examined_segments, 0)
        self.assertEqual(report.changes, [])
        self.assertFalse(report.saved)


class VerificationThresholdTunerContractTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "ledger.db"
        self.config_path = Path(self.tmpdir.name) / "harness_config.json"
        init_db(self.db_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_skips_query_types_with_fewer_than_twenty_feedback_sessions(self):
        for idx in range(1, 20):
            _insert_outcome(
                self.db_path,
                f"s{idx:02d}",
                verification_score=8,
                verification_passed=True,
                feedback_rating="negative",
            )

        report = tune_verification_thresholds(
            db_path=self.db_path,
            config_path=self.config_path,
        )

        self.assertEqual(report.examined_query_types, 1)
        self.assertEqual(report.eligible_query_types, 0)
        self.assertEqual(report.changes, [])
        self.assertFalse(report.saved)
        self.assertFalse(self.config_path.exists())

    def test_increases_threshold_when_passed_sessions_get_negative_feedback(self):
        for idx in range(1, 21):
            _insert_outcome(
                self.db_path,
                f"s{idx:02d}",
                query_type="strategic",
                verification_score=8,
                verification_passed=True,
                feedback_rating="negative",
            )

        report = tune_verification_thresholds(
            db_path=self.db_path,
            config_path=self.config_path,
        )
        loaded = load_config(self.config_path)

        self.assertTrue(report.saved)
        self.assertEqual(loaded.per_query_type["strategic"]["verification_threshold"], 7.5)
        self.assertEqual(report.changes[0].direction, "increase")
        self.assertEqual(report.changes[0].false_passes, 20)
        self.assertEqual(report.changes[0].false_fails, 0)

    def test_decreases_threshold_when_failed_sessions_get_positive_feedback(self):
        cfg = HarnessConfig(per_query_type={
            "product": {
                "verification_threshold": 7.5,
                "token_budgets": {
                    "simple": {"stage1_max_tokens": 600},
                },
            },
        })
        self.config_path.write_text(
            json.dumps(asdict(cfg), indent=2) + "\n",
            encoding="utf-8",
        )
        for idx in range(1, 21):
            _insert_outcome(
                self.db_path,
                f"s{idx:02d}",
                query_type="product",
                verification_score=6,
                verification_passed=False,
                feedback_rating="positive",
            )

        report = tune_verification_thresholds(
            db_path=self.db_path,
            config_path=self.config_path,
        )
        loaded = load_config(self.config_path)

        self.assertTrue(report.saved)
        self.assertEqual(loaded.per_query_type["product"]["verification_threshold"], 7.0)
        self.assertEqual(
            loaded.per_query_type["product"]["token_budgets"]["simple"]["stage1_max_tokens"],
            600,
        )
        self.assertEqual(report.changes[0].direction, "decrease")

    def test_tie_between_mismatch_types_does_not_change_threshold(self):
        for idx in range(1, 11):
            _insert_outcome(
                self.db_path,
                f"n{idx:02d}",
                verification_score=8,
                verification_passed=True,
                feedback_rating="negative",
            )
            _insert_outcome(
                self.db_path,
                f"p{idx:02d}",
                verification_score=6,
                verification_passed=False,
                feedback_rating="positive",
            )

        report = tune_verification_thresholds(
            db_path=self.db_path,
            config_path=self.config_path,
        )

        self.assertEqual(report.eligible_query_types, 1)
        self.assertEqual(report.changes, [])
        self.assertFalse(report.saved)

    def test_dry_run_reports_threshold_changes_without_saving(self):
        for idx in range(1, 21):
            _insert_outcome(
                self.db_path,
                f"s{idx:02d}",
                verification_score=8,
                verification_passed=True,
                feedback_rating="negative",
            )

        report = tune_verification_thresholds(
            db_path=self.db_path,
            config_path=self.config_path,
            dry_run=True,
        )

        self.assertFalse(report.saved)
        self.assertTrue(report.dry_run)
        self.assertEqual(1, len(report.changes))
        self.assertFalse(self.config_path.exists())

    def test_threshold_changes_respect_floor_and_ceiling(self):
        cfg = HarnessConfig(per_query_type={
            "strategic": {"verification_threshold": VERIFICATION_THRESHOLD_CEILING},
            "product": {"verification_threshold": VERIFICATION_THRESHOLD_FLOOR},
        })
        self.config_path.write_text(
            json.dumps(asdict(cfg), indent=2) + "\n",
            encoding="utf-8",
        )
        for idx in range(1, 21):
            _insert_outcome(
                self.db_path,
                f"n{idx:02d}",
                query_type="strategic",
                verification_score=8,
                verification_passed=True,
                feedback_rating="negative",
            )
            _insert_outcome(
                self.db_path,
                f"p{idx:02d}",
                query_type="product",
                verification_score=6,
                verification_passed=False,
                feedback_rating="positive",
            )

        report = tune_verification_thresholds(
            db_path=self.db_path,
            config_path=self.config_path,
        )

        self.assertEqual(report.changes, [])
        self.assertFalse(report.saved)

    def test_ignores_feedback_without_verification_result(self):
        for idx in range(1, 21):
            _insert_outcome(
                self.db_path,
                f"s{idx:02d}",
                verification_score=None,
                verification_passed=None,
                feedback_rating="negative",
            )

        report = tune_verification_thresholds(
            db_path=self.db_path,
            config_path=self.config_path,
        )

        self.assertEqual(report.examined_query_types, 0)
        self.assertEqual(report.changes, [])
        self.assertFalse(report.saved)


if __name__ == "__main__":
    unittest.main()
