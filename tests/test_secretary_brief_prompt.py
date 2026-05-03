"""Contract tests for the live Secretary brief prompt template."""

import unittest

from server.board.deliberation.prompts import format_live_secretary_brief


class SecretaryBriefPromptTest(unittest.TestCase):
    def test_signature_accepts_round_index_and_no_brief_mode(self) -> None:
        # New signature: only user_query, transcript, round_index. No brief_mode/is_final.
        prompt = format_live_secretary_brief(
            user_query="Should we ship feature X?",
            transcript="[Strategist] Validate demand first.\n[Architect] Spike feasibility.",
            round_index=0,
        )
        self.assertIsInstance(prompt, str)
        self.assertGreater(len(prompt), 0)

    def test_prompt_lists_the_four_required_sections(self) -> None:
        prompt = format_live_secretary_brief(
            user_query="Q",
            transcript="t",
            round_index=0,
        )
        for header in ("## Agreements", "## Conflicts", "## Open Questions", "## Decision Needed From CEO"):
            self.assertIn(header, prompt, f"prompt must reference required section: {header}")

    def test_prompt_forbids_deprecated_sections(self) -> None:
        prompt = format_live_secretary_brief(
            user_query="Q",
            transcript="t",
            round_index=0,
        )
        for forbidden in ("Risk Snapshot", "Action Items", "Detail Index", "Decision Options", "One-liner"):
            self.assertNotIn(forbidden, prompt, f"deprecated section name leaked into prompt: {forbidden}")

    def test_prompt_announces_round_index_for_continuations(self) -> None:
        prompt_round_0 = format_live_secretary_brief(user_query="Q", transcript="t", round_index=0)
        prompt_round_2 = format_live_secretary_brief(user_query="Q", transcript="t", round_index=2)
        # Round 0 prompt should not mention "follow-up"; round 2 should.
        self.assertIn("Round 0", prompt_round_0)
        self.assertIn("Round 2", prompt_round_2)
        self.assertIn("follow-up", prompt_round_2.lower())

    def test_prompt_caps_brief_to_eighty_lines(self) -> None:
        prompt = format_live_secretary_brief(user_query="Q", transcript="t", round_index=0)
        # The instruction must explicitly mention the 80-line cap.
        self.assertIn("80 lines", prompt)


if __name__ == "__main__":
    unittest.main()
