# tests/test_clarification_gate_contract.py
from __future__ import annotations

import unittest


class ClarificationGateContract(unittest.TestCase):
    def test_gate_config_has_expected_shape(self):
        from server.board.roster import get_clarification_gate

        gate = get_clarification_gate()
        self.assertIsInstance(gate, dict)
        self.assertIn("ambiguous_terms", gate)
        self.assertIn("min_terms_present", gate)
        self.assertIn("max_query_words", gate)
        self.assertIn("gating_capabilities", gate)

        self.assertIsInstance(gate["ambiguous_terms"], list)
        self.assertGreater(len(gate["ambiguous_terms"]), 0)
        self.assertIsInstance(gate["min_terms_present"], int)
        self.assertGreaterEqual(gate["min_terms_present"], 1)
        self.assertIsInstance(gate["max_query_words"], int)
        self.assertGreaterEqual(gate["max_query_words"], 1)
        self.assertIsInstance(gate["gating_capabilities"], list)
        self.assertGreater(len(gate["gating_capabilities"]), 0)

    def test_gating_capabilities_exist_on_at_least_one_member(self):
        from server.board.config import get_board_members
        from server.board.roster import get_clarification_gate, load_roster

        gate_caps = set(get_clarification_gate()["gating_capabilities"])
        roster_members = load_roster().get("members", {})

        for cap in gate_caps:
            matching = [
                mid for mid, cfg in roster_members.items()
                if cap in cfg.get("capabilities", [])
            ]
            self.assertGreater(
                len(matching), 0,
                f"gating_capability {cap!r} is not declared on any member",
            )


if __name__ == "__main__":
    unittest.main()
