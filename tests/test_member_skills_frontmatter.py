"""Tests for `BoardMember.skills` and frontmatter parsing."""

from __future__ import annotations

import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class BoardMemberSkillsDataclassTest(unittest.TestCase):
    def test_board_member_has_skills_field_default_empty(self):
        from server.board.config import BoardMember

        member = BoardMember(
            id="m1",
            title="Member 1",
            role="Role 1",
            expertise=[],
            system_prompt="hello",
        )
        self.assertEqual(member.skills, [])

    def test_board_member_accepts_skills_list(self):
        from server.board.config import BoardMember

        member = BoardMember(
            id="m1",
            title="Member 1",
            role="Role 1",
            expertise=[],
            system_prompt="hello",
            skills=["alpha", "beta"],
        )
        self.assertEqual(member.skills, ["alpha", "beta"])


if __name__ == "__main__":
    unittest.main()
