import json
import sqlite3
import unittest
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from server.board.deliberation.classifier import QueryClassification
from server.board.deliberation.compaction import compact_stage1_responses
from server.harness.config import HarnessConfig, load_config
from server.harness.ledger import init_db
from server.board.deliberation.orchestrator import BoardOrchestrator, BoardSession, MemberResponse
from server.harness.routing_compaction import extract_cited_member_ids, tune_routing_and_compaction


def _insert_outcome(
    db_path: Path,
    session_id: str,
    *,
    query_type: str = "strategic",
    complexity: str = "moderate",
    members_routed: list[str] | None = None,
) -> None:
    routed = members_routed or ["strategist", "product", "critic", "chairperson"]
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            """INSERT INTO session_outcomes (
                session_id, timestamp, query_type, complexity,
                members_routed, harness_config_version
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                f"2026-04-15T00:00:{session_id[-2:]}+00:00",
                query_type,
                complexity,
                json.dumps(routed),
                1,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _stage1_content(prefix: str) -> str:
    return f"""> Member: Product Lead | Stage: 1 | Confidence: High

## TL;DR
- {prefix} market finding.

## Analysis
- {prefix} long analysis should usually stay out of compacted context.

## Risks
- **High**: {prefix} pricing collapse risk - Probability: H, Impact: H
- **Medium**: {prefix} onboarding drift risk - Probability: M, Impact: M

## Recommendation
- **Do this:** {prefix} ship a narrow wedge.
"""


def _write_session(
    sessions_dir: Path,
    session_id: str,
    *,
    synthesis: str,
    query_type: str = "strategic",
) -> None:
    sessions_dir.mkdir(parents=True, exist_ok=True)
    prefix = session_id
    payload = {
        "session_id": session_id,
        "classification": {"query_type": query_type, "complexity": "moderate"},
        "stage1": [
            {
                "member_id": "strategist",
                "stage": 1,
                "content": _stage1_content(prefix),
                "model": "m",
                "elapsed_seconds": 0.1,
            },
            {
                "member_id": "product",
                "stage": 1,
                "content": _stage1_content(prefix),
                "model": "m",
                "elapsed_seconds": 0.1,
            },
            {
                "member_id": "critic",
                "stage": 1,
                "content": _stage1_content(prefix),
                "model": "m",
                "elapsed_seconds": 0.1,
            },
        ],
        "stage3": {"content": synthesis},
    }
    (sessions_dir / f"{session_id}.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


class PhaseDRoutingContractTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        root = Path(self.tmpdir.name)
        self.db_path = root / "ledger.db"
        self.config_path = root / "harness_config.json"
        self.sessions_dir = root / "sessions"
        init_db(self.db_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_extract_cited_member_ids_matches_member_titles_and_ids(self):
        synthesis = (
            "The Chief Strategist's segmentation wins. "
            "Product Lead should scope the MVP. The critic concern is noted."
        )

        cited = extract_cited_member_ids(synthesis)

        self.assertIn("strategist", cited)
        self.assertIn("product", cited)
        self.assertIn("critic", cited)

    def test_tuner_suppresses_consistently_uncited_routed_member(self):
        for idx in range(1, 51):
            session_id = f"s{idx:02d}"
            _insert_outcome(self.db_path, session_id)
            _write_session(
                self.sessions_dir,
                session_id,
                synthesis=(
                    f"Chief Strategist and Product Lead drive the decision. "
                    f"The {session_id} pricing collapse risk must be handled."
                ),
            )

        report = tune_routing_and_compaction(
            db_path=self.db_path,
            config_path=self.config_path,
            sessions_dir=self.sessions_dir,
        )
        loaded = load_config(self.config_path)

        self.assertTrue(report.saved)
        self.assertEqual(50, report.analyzed_sessions)
        self.assertIn("critic", loaded.per_query_type["strategic"]["routing"]["suppressed_member_ids"])
        self.assertNotIn("strategist", loaded.per_query_type["strategic"]["routing"]["suppressed_member_ids"])
        self.assertEqual("suppress", report.routing_changes[0].action)

    def test_tuner_does_not_suppress_when_member_is_cited_often_enough(self):
        for idx in range(1, 51):
            session_id = f"s{idx:02d}"
            _insert_outcome(self.db_path, session_id)
            synthesis = "Chief Strategist and Product Lead drive the decision."
            if idx <= 10:
                synthesis += " Critic flags the decisive risk."
            _write_session(self.sessions_dir, session_id, synthesis=synthesis)

        report = tune_routing_and_compaction(
            db_path=self.db_path,
            config_path=self.config_path,
            sessions_dir=self.sessions_dir,
        )

        suppressed = [
            change.member_id
            for change in report.routing_changes
            if change.action == "suppress"
        ]
        self.assertNotIn("critic", suppressed)

    def test_dry_run_reports_phase_d_changes_without_saving(self):
        for idx in range(1, 51):
            session_id = f"s{idx:02d}"
            _insert_outcome(self.db_path, session_id)
            _write_session(
                self.sessions_dir,
                session_id,
                synthesis="Chief Strategist and Product Lead drive the decision.",
            )

        report = tune_routing_and_compaction(
            db_path=self.db_path,
            config_path=self.config_path,
            sessions_dir=self.sessions_dir,
            dry_run=True,
        )

        self.assertTrue(report.dry_run)
        self.assertFalse(report.saved)
        self.assertGreater(len(report.routing_changes), 0)
        self.assertFalse(self.config_path.exists())

    async def test_orchestrator_applies_routing_suppression_after_classification(self):
        cfg = HarnessConfig(per_query_type={
            "strategic": {
                "routing": {"suppressed_member_ids": ["critic"]},
            },
        })
        classification = QueryClassification(
            query_type="strategic",
            complexity="moderate",
            relevant_member_ids=["strategist", "critic", "chairperson"],
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
                                            session = await orchestrator.deliberate(
                                                "Should we launch?",
                                                session_id="route_suppressed",
                                            )

        self.assertEqual(["strategist", "chairperson"], session.classification["relevant_member_ids"])
        self.assertEqual(["strategist"], [member.id for member in orchestrator.council])


class PhaseDCompactionContractTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        root = Path(self.tmpdir.name)
        self.db_path = root / "ledger.db"
        self.config_path = root / "harness_config.json"
        self.sessions_dir = root / "sessions"
        init_db(self.db_path)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_tuner_drops_unused_stage1_sections_and_preserves_used_risk_detail(self):
        for idx in range(1, 51):
            session_id = f"s{idx:02d}"
            _insert_outcome(self.db_path, session_id)
            _write_session(
                self.sessions_dir,
                session_id,
                synthesis=(
                    f"Chief Strategist supports this. "
                    f"The {session_id} pricing collapse risk is the deciding factor."
                ),
            )

        report = tune_routing_and_compaction(
            db_path=self.db_path,
            config_path=self.config_path,
            sessions_dir=self.sessions_dir,
        )
        loaded = load_config(self.config_path)
        policy = loaded.per_query_type["strategic"]["compaction"]

        self.assertTrue(report.saved)
        self.assertEqual(["confidence", "top_risk"], policy["stage1_sections"])
        self.assertEqual(["top_risk"], policy["stage1_detail_sections"])
        self.assertIn(
            ("strategic", "tldr", "drop"),
            {(c.query_type, c.section, c.action) for c in report.compaction_changes},
        )

    def test_compaction_uses_query_type_policy(self):
        cfg = HarnessConfig(per_query_type={
            "strategic": {
                "compaction": {
                    "stage1_sections": ["confidence", "top_risk"],
                    "stage1_detail_sections": ["top_risk"],
                },
            },
        })
        response = MemberResponse(
            member_id="product",
            stage=1,
            content=_stage1_content("test"),
            model="m",
            elapsed_seconds=0.1,
        )

        compacted = compact_stage1_responses(
            [response],
            query_type="strategic",
            config=cfg,
        )

        self.assertIn("> Confidence: High", compacted[0].content)
        self.assertIn("## Risks", compacted[0].content)
        self.assertIn("onboarding drift risk", compacted[0].content)
        self.assertNotIn("## TL;DR", compacted[0].content)
        self.assertNotIn("## Recommendation", compacted[0].content)

    def test_phase_d_preserves_existing_query_type_metadata(self):
        cfg = HarnessConfig(per_query_type={
            "strategic": {
                "verification_threshold": 8.0,
                "token_budgets": {
                    "moderate": {"stage1_max_tokens": 900},
                },
            },
        })
        self.config_path.write_text(
            json.dumps(asdict(cfg), indent=2) + "\n",
            encoding="utf-8",
        )
        for idx in range(1, 51):
            session_id = f"s{idx:02d}"
            _insert_outcome(self.db_path, session_id)
            _write_session(
                self.sessions_dir,
                session_id,
                synthesis="Chief Strategist and Product Lead drive the decision.",
            )

        tune_routing_and_compaction(
            db_path=self.db_path,
            config_path=self.config_path,
            sessions_dir=self.sessions_dir,
        )
        loaded = load_config(self.config_path)

        self.assertEqual(8.0, loaded.per_query_type["strategic"]["verification_threshold"])
        self.assertEqual(
            900,
            loaded.per_query_type["strategic"]["token_budgets"]["moderate"]["stage1_max_tokens"],
        )


if __name__ == "__main__":
    unittest.main()
