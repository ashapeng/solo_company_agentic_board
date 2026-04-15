import unittest

from server.board.memory_review import review_sotb_update


CURRENT_SOTB = """# State of the Board
> Last updated: [never] | Sessions: 0

## Active Decisions
- Keep existing decision.

## Risk Register
- Keep existing risk.

## Established Positions
- Keep existing position.

## Open Questions
- Keep existing question.

## Last Session
[No previous sessions.]
"""


class MemoryContractTest(unittest.TestCase):
    def test_sotb_review_preserves_unrelated_sections_with_last_session_fallback(self):
        review = review_sotb_update(
            "- Decision: validate with concierge MVP.",
            session_id="board_memory_test",
            current_sotb=CURRENT_SOTB,
        )

        self.assertTrue(review["requires_approval"])
        self.assertIn("Keep existing decision.", review["candidate_sotb"])
        self.assertIn("Keep existing risk.", review["candidate_sotb"])
        self.assertIn("Session: board_memory_test", review["candidate_sotb"])
        self.assertIn("candidate_sotb.md", review["diff"])
        self.assertEqual([], review["warnings"])

    def test_sotb_review_applies_section_aware_updates_without_writing(self):
        review = review_sotb_update(
            """## Active Decisions
- Validate pricing manually before building billing.

## Risk Register
- Pricing signal may be too weak for self-serve.
""",
            session_id="board_section_test",
            current_sotb=CURRENT_SOTB,
        )

        candidate = review["candidate_sotb"]

        self.assertIn("Keep existing decision.", candidate)
        self.assertIn("Validate pricing manually", candidate)
        self.assertIn("_Source: session:board_section_test_", candidate)
        self.assertIn("Keep existing risk.", candidate)
        self.assertIn("Pricing signal may be too weak", candidate)
        self.assertIn("Keep existing position.", candidate)
        self.assertIn("Keep existing question.", candidate)
        self.assertIn("[No previous sessions.]", candidate)

    def test_sotb_review_empty_update_is_noop_with_warning(self):
        review = review_sotb_update("", session_id="board_empty", current_sotb=CURRENT_SOTB)

        self.assertEqual(CURRENT_SOTB, review["candidate_sotb"])
        self.assertIn("No proposed SOTB update was provided.", review["warnings"])
        self.assertIsNone(review["proposed_sotb_update"])


if __name__ == "__main__":
    unittest.main()
