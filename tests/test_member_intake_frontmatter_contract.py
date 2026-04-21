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


    def test_activated_shelved_without_intake_raises(self):
        import tempfile
        import textwrap
        from pathlib import Path
        from server.board.loader import load_members

        # Create a temporary member directory with one shelved file that has no intake.
        # This verifies the enforcement path without relying on real shelved files.
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            shelved_file = tmp / "_testmember.md"
            shelved_file.write_text(textwrap.dedent("""\
                ---
                id: testmember
                title: Test Member
                role: Test Role
                expertise: [testing]
                priority: 50
                tags: []
                model_override: null
                ---

                ## Identity
                Test member without intake.

                ## Stage 2 Behavior
                Review peers.
            """), encoding="utf-8")
            with self.assertRaises(ValueError) as ctx:
                load_members(directory=tmpdir, include_shelved_ids={"testmember"})
            self.assertIn("testmember", str(ctx.exception))
            self.assertIn("intake", str(ctx.exception).lower())


class EvidenceRequiredFlagTest(unittest.TestCase):
    def test_researcher_and_strategist_require_evidence(self):
        from server.board.config import get_board_members

        by_id = {m.id: m for m in get_board_members()}
        self.assertTrue(
            by_id["researcher"].evidence_required,
            "researcher should have evidence_required=True",
        )
        self.assertTrue(
            by_id["strategist"].evidence_required,
            "strategist should have evidence_required=True",
        )

    def test_other_members_do_not_require_evidence(self):
        from server.board.config import get_board_members

        by_id = {m.id: m for m in get_board_members()}
        for mid in ("chairperson", "product", "critic", "architect", "builder"):
            self.assertFalse(
                by_id[mid].evidence_required,
                f"{mid!r} should default to evidence_required=False",
            )


if __name__ == "__main__":
    unittest.main()
