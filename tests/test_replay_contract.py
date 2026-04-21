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


if __name__ == "__main__":
    unittest.main()
