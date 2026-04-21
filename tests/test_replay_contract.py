# tests/test_replay_contract.py
"""Phase 0 repro for Plan 5 (offline replay + drift observability)."""

from __future__ import annotations

import subprocess
import unittest


class ReplayModuleExistsTest(unittest.TestCase):
    def test_replay_module_importable(self):
        from server.harness import replay  # noqa: F401

        self.assertTrue(hasattr(replay, "replay_session"))


class CliFlagExistsTest(unittest.TestCase):
    def test_cli_accepts_replay_flag(self):
        result = subprocess.run(
            ["/home/apeng/projects/solo_company_agentic_board/.venv/bin/python",
             "-m", "server.cli", "--help"],
            capture_output=True, text=True, timeout=30,
        )
        self.assertIn("--replay", result.stdout)


class ReplayReportShapeTest(unittest.TestCase):
    def test_replay_report_fields_present(self):
        from server.harness.replay import ReplayReport

        report = ReplayReport(
            replay_id="r1",
            source_session_id="board_1",
            candidate_config_path=None,
            baseline={"verification_score": 8, "synthesis_len": 100},
            candidate={"verification_score": 7, "synthesis_len": 80},
            delta={"verification_score": -1, "synthesis_len": -20},
        )
        d = report.to_dict()
        self.assertEqual(d["replay_id"], "r1")
        self.assertEqual(d["source_session_id"], "board_1")
        self.assertEqual(d["baseline"]["synthesis_len"], 100)
        self.assertEqual(d["delta"]["verification_score"], -1)

    def test_replay_session_rejects_session_without_stage3(self):
        import json
        import tempfile
        from pathlib import Path
        from server.harness.replay import replay_session

        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False,
        ) as tmp:
            json.dump(
                {
                    "session_id": "board_missing_stage3",
                    "user_query": "q",
                    "stage1": [],
                    "stage2": [],
                    "stage3": None,
                },
                tmp,
            )
            path = Path(tmp.name)
        try:
            with self.assertRaises(ValueError) as ctx:
                replay_session(path, verify=False)
            self.assertIn("stage3", str(ctx.exception).lower())
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
