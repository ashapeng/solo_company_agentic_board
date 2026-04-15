import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from server.board.ledger import (
    LedgerError,
    aggregate,
    init_db,
    query_outcomes,
    record_feedback,
    record_session,
)
from server.board.metrics import CallMetrics, SessionMetrics
from server.board.orchestrator import BoardSession, MemberResponse


def _make_session(
    session_id: str = "board_test",
    query_type: str | None = "strategic",
    complexity: str | None = "moderate",
    verification_score: int | None = None,
    verification_passed: bool | None = None,
) -> BoardSession:
    """Build a minimal BoardSession for ledger tests."""
    metrics = SessionMetrics()
    metrics.record(CallMetrics(
        member_id="strategist", stage=1, model="claude-sonnet-4",
        input_tokens=500, output_tokens=300, latency_seconds=2.1,
    ))
    metrics.record(CallMetrics(
        member_id="product", stage=1, model="gemini-2.5-pro",
        input_tokens=500, output_tokens=250, latency_seconds=1.8,
    ))
    metrics.record(CallMetrics(
        member_id="strategist", stage=2, model="claude-sonnet-4",
        input_tokens=400, output_tokens=200, latency_seconds=1.5,
    ))
    metrics.record(CallMetrics(
        member_id="chairperson", stage=3, model="claude-opus-4",
        input_tokens=1200, output_tokens=800, latency_seconds=5.0,
    ))

    session = BoardSession(
        session_id=session_id,
        user_query="Should we launch?",
        stage1_responses=[
            MemberResponse(member_id="strategist", stage=1, content="Analysis.", model="claude-sonnet-4", elapsed_seconds=2.1),
            MemberResponse(member_id="product", stage=1, content="Analysis.", model="gemini-2.5-pro", elapsed_seconds=1.8),
        ],
        stage2_responses=[
            MemberResponse(member_id="strategist", stage=2, content="Review.", model="claude-sonnet-4", elapsed_seconds=1.5),
        ],
        stage3_synthesis=MemberResponse(
            member_id="chairperson", stage=3, content="Decision.", model="claude-opus-4", elapsed_seconds=5.0,
        ),
        metrics=metrics,
        memory={"proposed_sotb_update": "Launch approved.", "requires_approval": True},
    )

    if query_type:
        session.classification = {
            "query_type": query_type,
            "complexity": complexity,
            "relevant_member_ids": ["strategist", "product"],
            "reasoning": "test",
            "required_capabilities": [],
            "unavailable_capabilities": [],
            "stage_profile": "pre_pmf",
            "role_gap_memo": "",
        }

    if verification_score is not None:
        session.verification = {
            "score": verification_score,
            "passed": verification_passed,
            "deficiencies": [],
            "suggestions": [],
        }

    return session


class LedgerContractTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "test_ledger.db"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_db_created_automatically_if_missing(self):
        self.assertFalse(self.db_path.exists())
        init_db(self.db_path)
        self.assertTrue(self.db_path.exists())

    def test_record_session_inserts_complete_row(self):
        init_db(self.db_path)
        session = _make_session()
        record_session(session, config_version=1, db_path=self.db_path)

        rows = query_outcomes(db_path=self.db_path)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["session_id"], "board_test")
        self.assertEqual(row["query_type"], "strategic")
        self.assertEqual(row["complexity"], "moderate")
        self.assertEqual(json.loads(row["members_routed"]), ["strategist", "product"])
        self.assertEqual(json.loads(row["members_responded"]), ["strategist", "product"])
        self.assertGreater(row["stage1_tokens"], 0)
        self.assertGreater(row["stage3_tokens"], 0)
        self.assertGreater(row["total_cost_usd"], 0)
        self.assertEqual(row["sotb_update_proposed"], 1)
        self.assertEqual(row["harness_config_version"], 1)

    def test_duplicate_session_id_raises(self):
        init_db(self.db_path)
        session = _make_session()
        record_session(session, config_version=1, db_path=self.db_path)

        with self.assertRaises(LedgerError):
            record_session(session, config_version=1, db_path=self.db_path)

    def test_session_without_classification_has_null_query_type(self):
        init_db(self.db_path)
        session = _make_session(query_type=None)
        record_session(session, config_version=1, db_path=self.db_path)

        rows = query_outcomes(db_path=self.db_path)
        self.assertIsNone(rows[0]["query_type"])
        self.assertIsNone(rows[0]["complexity"])

    def test_record_feedback_updates_existing_session(self):
        init_db(self.db_path)
        session = _make_session()
        record_session(session, config_version=1, db_path=self.db_path)

        record_feedback("board_test", "positive", note="Good decision", db_path=self.db_path)

        rows = query_outcomes(db_path=self.db_path)
        self.assertEqual(rows[0]["feedback_rating"], "positive")
        self.assertEqual(rows[0]["feedback_note"], "Good decision")

    def test_record_feedback_on_nonexistent_session_raises(self):
        init_db(self.db_path)

        with self.assertRaises(LedgerError):
            record_feedback("no_such_session", "positive", db_path=self.db_path)

    def test_query_outcomes_filters_by_query_type(self):
        init_db(self.db_path)
        record_session(_make_session("s1", query_type="strategic"), config_version=1, db_path=self.db_path)
        record_session(_make_session("s2", query_type="product"), config_version=1, db_path=self.db_path)
        record_session(_make_session("s3", query_type="strategic"), config_version=1, db_path=self.db_path)

        rows = query_outcomes(query_type="strategic", db_path=self.db_path)
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(r["query_type"] == "strategic" for r in rows))

    def test_query_outcomes_no_filters_returns_all(self):
        init_db(self.db_path)
        record_session(_make_session("s1"), config_version=1, db_path=self.db_path)
        record_session(_make_session("s2"), config_version=1, db_path=self.db_path)

        rows = query_outcomes(db_path=self.db_path)
        self.assertEqual(len(rows), 2)

    def test_aggregate_returns_correct_averages(self):
        init_db(self.db_path)
        record_session(_make_session("s1", query_type="strategic"), config_version=1, db_path=self.db_path)
        record_session(_make_session("s2", query_type="product"), config_version=1, db_path=self.db_path)
        record_session(_make_session("s3", query_type="strategic"), config_version=1, db_path=self.db_path)

        result = aggregate("stage1_tokens", group_by="query_type", db_path=self.db_path)

        self.assertIn("strategic", result)
        self.assertIn("product", result)
        self.assertIsInstance(result["strategic"], float)

    def test_session_with_verification_stores_score(self):
        init_db(self.db_path)
        session = _make_session(verification_score=8, verification_passed=True)
        record_session(session, config_version=1, db_path=self.db_path)

        rows = query_outcomes(db_path=self.db_path)
        self.assertEqual(rows[0]["verification_score"], 8)
        self.assertEqual(rows[0]["verification_passed"], 1)

    def test_session_without_verification_has_null_fields(self):
        init_db(self.db_path)
        session = _make_session()
        record_session(session, config_version=1, db_path=self.db_path)

        rows = query_outcomes(db_path=self.db_path)
        self.assertIsNone(rows[0]["verification_score"])
        self.assertIsNone(rows[0]["verification_passed"])


if __name__ == "__main__":
    unittest.main()
