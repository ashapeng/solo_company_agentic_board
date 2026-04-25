import unittest

from server.board.deliberation.classifier import parse_classification
from server.board.loader import load_members
from server.board.roster import load_roster, select_members_for_decision_type


class RosterRoutingTest(unittest.TestCase):
    def test_security_routes_to_active_fallbacks_in_pre_pmf(self):
        selection = select_members_for_decision_type("security", stage_profile="pre_pmf")

        self.assertIn("chairperson", selection.member_ids)
        self.assertIn("architect", selection.member_ids)
        self.assertIn("critic", selection.member_ids)
        self.assertNotIn("guardian", selection.member_ids)
        self.assertIn("threat_modeling", selection.unavailable_capabilities)
        self.assertIn("threat_modeling", selection.role_gap_memo)

    def test_security_routes_to_guardian_in_live_product(self):
        selection = select_members_for_decision_type("security", stage_profile="live_product")

        self.assertIn("guardian", selection.member_ids)
        self.assertEqual([], selection.unavailable_capabilities)

    def test_full_board_uses_active_profile(self):
        selection = select_members_for_decision_type("full-board", stage_profile="pre_pmf")

        self.assertEqual(
            ["chairperson", "strategist", "product", "researcher", "critic", "architect", "builder"],
            selection.member_ids,
        )

    def test_loader_can_activate_shelved_member(self):
        members = load_members(include_shelved_ids={"guardian"})
        member_ids = [member.id for member in members]

        self.assertIn("guardian", member_ids)
        self.assertNotIn("operator", member_ids)

    def test_classifier_parser_accepts_capabilities(self):
        roster = load_roster()
        decision_types = list(roster["decision_types"].keys())
        parsed = parse_classification(
            "decision_type: technical\n"
            "complexity: moderate\n"
            "capabilities: technical_feasibility, execution_feasibility\n"
            "reasoning: Needs technical tradeoff review.",
            valid_decision_types=decision_types,
        )

        self.assertEqual("technical", parsed[0])
        self.assertEqual("moderate", parsed[1])
        self.assertEqual(["technical_feasibility", "execution_feasibility"], parsed[2])


if __name__ == "__main__":
    unittest.main()
