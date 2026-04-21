# tests/test_harness_trust_contract.py
"""Phase 0 reproduction tests for the Harness Trust plan.

Every test in this module MUST fail on current main.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path


class VerifierDecouplingTest(unittest.TestCase):
    def test_default_verifier_provider_differs_from_chairman(self):
        os.environ.pop("AGENTIC_BOARD_ALLOW_SAME_VERIFIER", None)
        os.environ.pop("CHAIRMAN_MODEL", None)
        os.environ.pop("VERIFICATION_MODEL", None)
        from server.board.config import get_chairman_model, get_verification_model
        from server.harness.config_provider import provider_of

        self.assertNotEqual(
            provider_of(get_chairman_model()),
            provider_of(get_verification_model()),
            "verifier and chairman must use distinct providers",
        )


class ApplyUsesSnapshotTest(unittest.TestCase):
    def test_apply_uses_snapshot_not_live_ledger(self):
        from server.harness.reviews import (
            run_harness_review,
            approve_harness_review,
            apply_harness_review,
        )

        # run + approve captures a snapshot
        review = run_harness_review(dry_run=True)
        approved = approve_harness_review(review["id"], approve=True)
        self.assertIn("snapshot", approved, "approved review must carry a diff snapshot")

        # applying uses snapshot; applied_reports equals snapshot
        applied = apply_harness_review(review["id"])
        self.assertEqual(applied.get("status"), "applied")
        self.assertEqual(
            applied.get("applied_reports"),
            approved["snapshot"],
            "apply must write the approved snapshot, not re-run tuners",
        )
        self.assertIn("applied_at", applied)


class ShadowRollbackTest(unittest.TestCase):
    def test_shadow_reverts_after_regression(self):
        from server.harness.shadow import watch_after_apply
        from server.harness import ledger as ledger_module

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "ledger.db"
            ledger_module.init_db(db_path)

            # seed baseline: 20 sessions, verification_score=8
            self._seed(db_path, scores=[8] * 20)

            # synthetic activation row + post-apply regression: scores=4
            self._activate(db_path, review_id="rev1", snapshot={"token_budgets": {"changes": []}})
            self._seed(db_path, scores=[4] * 10)

            outcome = watch_after_apply(
                review_id="rev1", db_path=db_path, window=10, regression_threshold=1.0,
            )

            self.assertTrue(outcome["reverted"], "must flip reverted=True on regression")
            self.assertIn("reason", outcome)

    def _seed(self, db_path: Path, scores):
        from server.harness.ledger import record_session

        class _Metrics:
            def by_stage(self, _):
                return []

            def total_cost_estimate(self):
                return 0.0

        class _Session:
            def __init__(self, sid, score):
                self.session_id = sid
                self.classification = {
                    "query_type": "strategic",
                    "complexity": "moderate",
                    "relevant_member_ids": [],
                }
                self.verification = {"score": score, "passed": score >= 7}
                self.memory = {}
                self.metrics = _Metrics()
                self.stage1_responses = []
                self.stage2_responses = []
                self.delegation_plan = {}
                self.clarification = {}

        import itertools
        counter = itertools.count(int.from_bytes(os.urandom(2), "big"))
        for score in scores:
            sid = f"board_{next(counter)}"
            try:
                record_session(_Session(sid, score), config_version=1, db_path=db_path)
            except Exception:
                pass

    def _activate(self, db_path: Path, review_id: str, snapshot):
        import json

        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS harness_config_activations (
                    review_id TEXT PRIMARY KEY,
                    activated_at TEXT,
                    reverted_at TEXT,
                    snapshot TEXT,
                    previous_snapshot TEXT
                )"""
            )
            conn.execute(
                "INSERT OR REPLACE INTO harness_config_activations "
                "(review_id, activated_at, snapshot, previous_snapshot) VALUES (?, ?, ?, ?)",
                (review_id, "2026-04-20T00:00:00Z", json.dumps(snapshot), json.dumps({})),
            )
            conn.commit()
        finally:
            conn.close()


class SplitQualitySignalTest(unittest.TestCase):
    def test_negative_feedback_blocks_promotion_despite_high_verifier_score(self):
        from server.harness.model_assignment import _apply_model_assignment_tuning
        from server.harness.config import HarnessConfig

        outcomes = [
            # kimi dominates verifier score but has universally negative feedback
            {"query_type": "product", "verification_score": 10,
             "feedback_rating": "negative",
             "models_used": '{"researcher": "kimi/kimi-k2.5"}'},
            {"query_type": "product", "verification_score": 10,
             "feedback_rating": "negative",
             "models_used": '{"researcher": "kimi/kimi-k2.5"}'},
            {"query_type": "product", "verification_score": 10,
             "feedback_rating": "negative",
             "models_used": '{"researcher": "kimi/kimi-k2.5"}'},
            # deepseek has weaker verifier but universally positive feedback
            {"query_type": "product", "verification_score": 5,
             "feedback_rating": "positive",
             "models_used": '{"researcher": "deepseek/deepseek-chat"}'},
            {"query_type": "product", "verification_score": 5,
             "feedback_rating": "positive",
             "models_used": '{"researcher": "deepseek/deepseek-chat"}'},
            {"query_type": "product", "verification_score": 5,
             "feedback_rating": "positive",
             "models_used": '{"researcher": "deepseek/deepseek-chat"}'},
        ]
        config = HarnessConfig()
        changes, _, _ = _apply_model_assignment_tuning(
            config, outcomes, min_samples=3, min_score_delta=0.0,
        )
        promoted = [c.new_model for c in changes if c.member_id == "researcher"]
        self.assertNotIn(
            "kimi/kimi-k2.5",
            promoted,
            "model with only negative feedback must not be promoted",
        )


class MetaAccuracyTest(unittest.TestCase):
    def test_meta_reports_accuracy_per_tuner(self):
        import json as _json

        from server.harness.ledger import init_db, _connect
        from server.harness.meta import tuner_accuracy

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "l.db"
            init_db(path)
            conn = _connect(path)
            try:
                conn.execute(
                    "INSERT INTO harness_config_activations "
                    "(review_id, activated_at, snapshot) VALUES (?, ?, ?)",
                    (
                        "r1",
                        "2026-04-20T00:00:00Z",
                        _json.dumps({
                            "model_assignments": {"changes": [{"member_id": "x"}]},
                        }),
                    ),
                )
                conn.execute(
                    "INSERT INTO harness_config_activations "
                    "(review_id, activated_at, snapshot, reverted_at) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        "r2",
                        "2026-04-21T00:00:00Z",
                        _json.dumps({
                            "model_assignments": {"changes": [{"member_id": "y"}]},
                        }),
                        "2026-04-21T01:00:00Z",
                    ),
                )
                conn.commit()
            finally:
                conn.close()
            result = tuner_accuracy(db_path=path)
        self.assertEqual(result["model_assignments"]["applied"], 2)
        self.assertEqual(result["model_assignments"]["reverted"], 1)
        self.assertAlmostEqual(result["model_assignments"]["accuracy"], 0.5, places=2)


if __name__ == "__main__":
    unittest.main()
