from pathlib import Path
import re
import unittest

from server.board.loader import load_members


STRATEGIST_PATH = Path("server/members/strategist.md")


class FirstMemberContractTest(unittest.TestCase):
    def test_strategist_is_reference_member_with_expected_metadata(self):
        strategist = next(member for member in load_members() if member.id == "strategist")

        self.assertEqual("Chief Strategist", strategist.title)
        self.assertEqual("CSO / Market Strategy & Evidence", strategist.role)
        self.assertIn("market analysis", strategist.expertise)
        self.assertIn("evidence assessment", strategist.expertise)
        self.assertIn("strategy", strategist.tags)
        self.assertEqual(90, strategist.priority)
        self.assertIn("Unexamined market assumptions", strategist.stage2_behavior)

    def test_strategist_prompt_has_member_template_sections(self):
        text = STRATEGIST_PATH.read_text(encoding="utf-8")

        for section in (
            "## Identity",
            "## Core Question",
            "## Operating Procedures",
            "## Domain Boundaries",
            "## Anti-Patterns",
            "## Evidence Standards",
            "## Stage 2 Behavior",
        ):
            self.assertIn(section, text)

        procedure_count = len(re.findall(r"^### Procedure \d+:", text, flags=re.MULTILINE))
        self.assertGreaterEqual(procedure_count, 3)
        self.assertLessEqual(procedure_count, 5)

    def test_strategist_prompt_enforces_evidence_and_confidence_calibration(self):
        text = STRATEGIST_PATH.read_text(encoding="utf-8")

        self.assertIn("[UNVERIFIED]", text)
        self.assertIn("Customer interview data > Behavioral/usage data", text)
        self.assertIn("Use High confidence only when multiple evidence types agree", text)
        self.assertIn("use Medium when evidence is partial", text)
        self.assertIn("use Low when the recommendation depends mainly on inference", text)

    def test_strategist_prompt_keeps_strategy_boundary(self):
        text = STRATEGIST_PATH.read_text(encoding="utf-8")

        self.assertIn("Do NOT propose features or technical solutions", text)
        self.assertIn("Product Lead", text)
        self.assertIn("Researcher", text)
        self.assertIn("Architect", text)
        self.assertIn("Builder", text)
        self.assertIn("Critic", text)

    def test_strategist_stage2_behavior_targets_market_review(self):
        text = STRATEGIST_PATH.read_text(encoding="utf-8")

        for review_target in (
            "Unexamined market assumptions",
            "Missing segmentation",
            "Competitive blind spots",
            "Channel assumptions",
            "Evidence quality gaps",
        ):
            self.assertIn(review_target, text)


if __name__ == "__main__":
    unittest.main()
