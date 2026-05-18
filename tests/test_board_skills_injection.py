"""Stage 1 / Stage 2 skill injection — orchestrator + helper tests."""

from __future__ import annotations

import unittest


class ComposeSystemPromptHelperTest(unittest.TestCase):
    def test_empty_skill_bodies_returns_base_unchanged(self):
        from server.board.deliberation.prompts import compose_system_prompt

        out = compose_system_prompt("BASE", [])

        self.assertEqual(out, "BASE")

    def test_single_skill_appended_with_divider(self):
        from server.board.deliberation.prompts import compose_system_prompt

        out = compose_system_prompt("BASE", ["SKILL_BODY"])

        self.assertEqual(out, "BASE\n\n---\n\nSKILL_BODY")

    def test_multiple_skills_appended_with_divider_between(self):
        from server.board.deliberation.prompts import compose_system_prompt

        out = compose_system_prompt("BASE", ["A", "B", "C"])

        self.assertEqual(out, "BASE\n\n---\n\nA\n\n---\n\nB\n\n---\n\nC")

    def test_divider_is_exactly_two_newlines_dashes_two_newlines(self):
        from server.board.deliberation.prompts import compose_system_prompt

        out = compose_system_prompt("X", ["Y"])

        self.assertIn("\n\n---\n\n", out)
        # No double-divider, no extra blank lines:
        self.assertNotIn("\n\n\n---", out)
        self.assertNotIn("---\n\n\n", out)

    def test_empty_base_with_skill_yields_divider_then_skill(self):
        from server.board.deliberation.prompts import compose_system_prompt

        out = compose_system_prompt("", ["BODY"])

        # Edge case: empty base prompt is unusual but mustn't crash.
        # The helper appends with the standard divider; downstream consumers
        # never pass empty base in practice (every member has a system_prompt).
        self.assertEqual(out, "\n\n---\n\nBODY")


if __name__ == "__main__":
    unittest.main()
