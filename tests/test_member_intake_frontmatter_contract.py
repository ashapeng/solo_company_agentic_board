# tests/test_member_intake_frontmatter_contract.py
from __future__ import annotations

import unittest


class MemberIntakeContract(unittest.TestCase):
    def test_all_council_members_have_intake_frontmatter(self):
        from server.board.config import get_board_members

        members = [m for m in get_board_members() if m.id != "chairperson"]
        self.assertGreaterEqual(
            len(members), 6,
            "expected at least 6 council members after chairperson excluded",
        )
        for m in members:
            self.assertIsNotNone(
                m.intake,
                f"member {m.id!r} is missing intake frontmatter",
            )
            for attr in (
                "clarifying_question",
                "immediate_concern",
                "proposed_path",
                "required_execution_unit",
            ):
                value = getattr(m.intake, attr)
                self.assertTrue(value, f"member {m.id!r} has empty intake.{attr}")


if __name__ == "__main__":
    unittest.main()
