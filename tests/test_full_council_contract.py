from pathlib import Path
import re
import unittest

from server.board.loader import load_members
from server.board.roster import active_member_ids, load_roster, select_members_for_decision_type


MEMBERS_DIR = Path("server/members")
REQUIRED_SECTIONS = (
    "## Identity",
    "## Core Question",
    "## Operating Procedures",
    "## Domain Boundaries",
    "## Anti-Patterns",
    "## Evidence Standards",
    "## Stage 2 Behavior",
)
DEFAULT_PRE_PMF = [
    "chairperson",
    "strategist",
    "product",
    "researcher",
    "critic",
    "architect",
    "builder",
    "secretary",
]


class FullCouncilContractTest(unittest.TestCase):
    def test_pre_pmf_active_board_is_small_governance_roster(self):
        self.assertCountEqual(DEFAULT_PRE_PMF, active_member_ids(stage_profile="pre_pmf"))

        loaded_ids = [member.id for member in load_members()]
        self.assertCountEqual(DEFAULT_PRE_PMF, loaded_ids)

    def test_live_product_profile_activates_shelved_members(self):
        live_product_ids = active_member_ids(stage_profile="live_product")
        loaded_ids = [member.id for member in load_members(include_shelved_ids=set(live_product_ids))]

        expected = DEFAULT_PRE_PMF + ["guardian", "operator"]
        self.assertCountEqual(expected, live_product_ids)
        self.assertIn("guardian", loaded_ids)
        self.assertIn("operator", loaded_ids)

    def test_no_unimplemented_member_is_active_in_stage_profiles(self):
        roster = load_roster()
        implemented_ids = {
            path.stem.lstrip("_")
            for path in MEMBERS_DIR.glob("*.md")
            if path.stem != "_template"
        }

        for profile_name, profile in roster["stage_profiles"].items():
            with self.subTest(profile=profile_name):
                active_ids = set(profile.get("active", []))
                self.assertTrue(active_ids.issubset(implemented_ids))

        self.assertIn("finance", roster["stage_profiles"]["revenue"]["optional"])
        self.assertIn("legal", roster["stage_profiles"]["revenue"]["optional"])

    def test_active_and_shelved_member_prompts_follow_council_template(self):
        for path in sorted(MEMBERS_DIR.glob("*.md")):
            if path.name == "_template.md":
                continue

            text = path.read_text(encoding="utf-8")
            with self.subTest(member_file=path.name):
                for section in REQUIRED_SECTIONS:
                    self.assertIn(section, text)

                procedure_count = len(re.findall(r"^### Procedure \d+:", text, flags=re.MULTILINE))
                self.assertGreaterEqual(procedure_count, 3)
                self.assertLessEqual(procedure_count, 6)
                self.assertIn("[UNVERIFIED]", text)
                self.assertIn("| I Own | I Do NOT Own", text)

    def test_all_loaded_members_have_stage2_behavior(self):
        member_ids = set(active_member_ids(stage_profile="live_product"))
        members = load_members(include_shelved_ids=member_ids)

        for member in members:
            with self.subTest(member=member.id):
                self.assertTrue(member.stage2_behavior.strip())

    def test_finance_and_legal_route_as_role_gaps_until_implemented(self):
        finance = select_members_for_decision_type("finance", stage_profile="revenue")
        legal = select_members_for_decision_type("legal", stage_profile="revenue")

        self.assertIn("chairperson", finance.member_ids)
        self.assertIn("secretary", finance.member_ids)
        self.assertNotIn("finance_lead", [m for m in finance.member_ids])
        self.assertIn("financial_analysis", finance.unavailable_capabilities)
        self.assertIn("pricing", finance.unavailable_capabilities)
        self.assertIn("runway", finance.unavailable_capabilities)
        self.assertIn("role-gap review", finance.role_gap_memo)

        self.assertIn("chairperson", legal.member_ids)
        self.assertIn("secretary", legal.member_ids)
        self.assertIn("guardian", legal.member_ids)
        self.assertIn("critic", legal.member_ids)
        self.assertIn("legal_review", legal.unavailable_capabilities)
        self.assertIn("role-gap review", legal.role_gap_memo)


if __name__ == "__main__":
    unittest.main()
