import unittest

from hermes.plugins.agentic_board.plugin import tool_schemas
from server.board.role_gap import review_role_gap
from server.board.roster import load_roster


class GrowthExtensionsContractTest(unittest.TestCase):
    def test_role_gap_no_missing_capabilities_means_no_change(self):
        review = review_role_gap([], query="No gap")

        self.assertEqual("no_change", review["recommendation"])

    def test_one_off_missing_capability_prefers_hermes_skill(self):
        review = review_role_gap(
            ["threat_modeling"],
            query="Should we expose a public API?",
            stage_profile="pre_pmf",
            recurrence_count=1,
        )

        self.assertEqual("create_hermes_skill", review["recommendation"])
        self.assertIn("threat_modeling", review["missing_capabilities"])

    def test_repeated_shelved_capability_activates_shelved_member(self):
        review = review_role_gap(
            ["threat_modeling"],
            query="Should we expose a public API?",
            stage_profile="pre_pmf",
            recurrence_count=2,
        )

        self.assertEqual("activate_shelved_member", review["recommendation"])
        self.assertEqual(["guardian"], review["candidate_shelved_members"])

    def test_repeated_uncovered_capability_can_create_new_member(self):
        roster = load_roster()
        roster["stage_profiles"]["pre_pmf"]["optional"] = []

        review = review_role_gap(
            ["partnership_sales"],
            query="Should we sell through partners?",
            stage_profile="pre_pmf",
            recurrence_count=3,
            roster=roster,
        )

        self.assertEqual("create_new_board_member", review["recommendation"])
        self.assertEqual([], review["candidate_shelved_members"])
        self.assertEqual("Should we sell through partners?", review["benchmark_query"])

    def test_plugin_schema_keeps_memory_writes_absent(self):
        names = {schema["name"] for schema in tool_schemas()}

        self.assertIn("agentic_board_deliberate", names)
        self.assertIn("agentic_board_propose_sotb_update", names)
        self.assertNotIn("agentic_board_apply_sotb_update", names)
        self.assertNotIn("agentic_board_update_sotb", names)


if __name__ == "__main__":
    unittest.main()
