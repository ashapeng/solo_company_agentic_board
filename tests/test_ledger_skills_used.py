"""Tests for the `skills_used` column on `session_outcomes`."""

from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace


def _make_session_stub(session_id: str, skills_used: dict[str, list[str]]):
    """Build the minimum-shape session that `record_session` reads."""
    from server.board.metrics import SessionMetrics

    metrics = SessionMetrics()

    session = SimpleNamespace(
        session_id=session_id,
        classification={"query_type": "strategy", "complexity": "standard"},
        verification={},
        memory={},
        metrics=metrics,
        stage1_responses=[],
        stage2_responses=[],
        delegation_plan={},
        clarification={},
        skills={"used": skills_used, "missing": {}},
    )
    return session


class LedgerSkillsUsedColumnTest(unittest.TestCase):
    def test_ensure_columns_adds_skills_used(self):
        from server.harness.ledger import init_db

        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "ledger.db"
            init_db(db)
            conn = sqlite3.connect(str(db))
            try:
                cols = {row[1] for row in conn.execute("PRAGMA table_info(session_outcomes)")}
            finally:
                conn.close()
            self.assertIn("skills_used", cols)

    def test_record_session_persists_skills_used_json(self):
        from server.harness.ledger import record_session

        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "ledger.db"
            session = _make_session_stub(
                "s-001",
                {"strategist": ["pricing_research"], "researcher": ["jtbd_interview"]},
            )

            record_session(session, config_version=1, db_path=db)

            conn = sqlite3.connect(str(db))
            try:
                row = conn.execute(
                    "SELECT skills_used FROM session_outcomes WHERE session_id = ?",
                    ("s-001",),
                ).fetchone()
            finally:
                conn.close()

            self.assertIsNotNone(row)
            parsed = json.loads(row[0])
            self.assertEqual(
                parsed,
                {"strategist": ["pricing_research"], "researcher": ["jtbd_interview"]},
            )

    def test_record_session_empty_skills_used_is_empty_json_object(self):
        from server.harness.ledger import record_session

        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "ledger.db"
            session = _make_session_stub("s-002", {})

            record_session(session, config_version=1, db_path=db)

            conn = sqlite3.connect(str(db))
            try:
                row = conn.execute(
                    "SELECT skills_used FROM session_outcomes WHERE session_id = ?",
                    ("s-002",),
                ).fetchone()
            finally:
                conn.close()

            self.assertEqual(json.loads(row[0]), {})

    def test_record_session_missing_skills_attr_writes_empty_json(self):
        """A session WITHOUT a `skills` attribute (legacy code path) must
        not crash record_session; it writes an empty JSON object."""
        from server.harness.ledger import record_session
        from server.board.metrics import SessionMetrics

        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "ledger.db"
            session = SimpleNamespace(
                session_id="s-003",
                classification={},
                verification={},
                memory={},
                metrics=SessionMetrics(),
                stage1_responses=[],
                stage2_responses=[],
                delegation_plan={},
                clarification={},
                # No `skills` attr at all.
            )

            record_session(session, config_version=1, db_path=db)

            conn = sqlite3.connect(str(db))
            try:
                row = conn.execute(
                    "SELECT skills_used FROM session_outcomes WHERE session_id = ?",
                    ("s-003",),
                ).fetchone()
            finally:
                conn.close()

            self.assertEqual(json.loads(row[0]), {})


if __name__ == "__main__":
    unittest.main()
