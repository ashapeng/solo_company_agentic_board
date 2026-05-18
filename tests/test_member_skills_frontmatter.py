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


def _write_member(path: Path, frontmatter_extra: str = "") -> None:
    body = textwrap.dedent(f"""\
        ---
        id: test_member
        title: Test Member
        role: Test Role
        expertise: [testing]
        priority: 10
        tags: [test]
        model_override: null
        intake:
          clarifying_question: "q?"
          immediate_concern: "c"
          proposed_path: "p"
          required_execution_unit: "strategy"
        {frontmatter_extra}
        ---

        ## Identity
        Test.

        ## Stage 2 Behavior
        Review peers.
    """)
    path.write_text(body, encoding="utf-8")


class LoaderSkillsParsingTest(unittest.TestCase):
    def test_member_with_skills_list_parses(self):
        from server.board.loader import load_members

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_member(
                tmp_path / "test_member.md",
                frontmatter_extra="skills: [pricing_research, jtbd_interview]",
            )

            members = load_members(directory=tmp_path)

            self.assertEqual(len(members), 1)
            self.assertEqual(
                members[0].skills,
                ["pricing_research", "jtbd_interview"],
            )

    def test_member_without_skills_defaults_empty(self):
        from server.board.loader import load_members

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_member(tmp_path / "test_member.md")

            members = load_members(directory=tmp_path)

            self.assertEqual(len(members), 1)
            self.assertEqual(members[0].skills, [])

    def test_member_with_empty_skills_list_defaults_empty(self):
        from server.board.loader import load_members

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_member(
                tmp_path / "test_member.md",
                frontmatter_extra="skills: []",
            )

            members = load_members(directory=tmp_path)

            self.assertEqual(len(members), 1)
            self.assertEqual(members[0].skills, [])

    def test_member_with_null_skills_defaults_empty(self):
        from server.board.loader import load_members

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_member(
                tmp_path / "test_member.md",
                frontmatter_extra="skills: null",
            )

            members = load_members(directory=tmp_path)

            self.assertEqual(len(members), 1)
            self.assertEqual(members[0].skills, [])

    def test_skills_string_is_coerced_to_single_element_list(self):
        from server.board.loader import load_members

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_member(
                tmp_path / "test_member.md",
                frontmatter_extra='skills: "pricing_research"',
            )

            members = load_members(directory=tmp_path)

            self.assertEqual(len(members), 1)
            self.assertEqual(members[0].skills, ["pricing_research"])
