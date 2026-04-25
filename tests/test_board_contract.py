import unittest

from server.memory.review import propose_memory_update
from server.memory.review import review_sotb_update
from server.board.role_gap import review_role_gap
from server.board.projection import adapt_session_record, project_board_decision


SYNTHESIS = """### Executive Summary
Ship a concierge MVP before building the full platform.

### Critical Findings
- Customer evidence is still thin.
- Scope is the main schedule risk.

### Strategic Direction
Validate the workflow manually first.

### Architecture & Design
Use existing APIs and local session artifacts.

### Security Posture
Avoid storing external user data in v0.

### Implementation Plan
1. Draft the interview guide.
2. Run five calls.

### Risk Register
- High: No strong customer pull.

### Dissenting Views
- Critic: The evidence threshold may be too low.

### Next Steps
1. Prepare the evidence packet.
2. Schedule customer calls.

### SOTB Update
- Decision: validate with concierge MVP before platform build.
"""


class BoardContractTest(unittest.TestCase):
    def test_projects_chairman_markdown(self):
        decision = project_board_decision(SYNTHESIS)

        self.assertEqual(
            decision["executive_summary"],
            "Ship a concierge MVP before building the full platform.",
        )
        self.assertEqual(decision["next_steps"][0], "Prepare the evidence packet.")
        self.assertIn("No strong customer pull.", decision["risk_register"][0])

    def test_memory_proposal_requires_approval(self):
        proposal = propose_memory_update(SYNTHESIS, session_id="board_test")

        self.assertTrue(proposal["requires_approval"])
        self.assertEqual(proposal["source"], "session:board_test")
        self.assertIn("concierge MVP", proposal["proposed_sotb_update"])

    def test_sotb_review_returns_diff_without_write(self):
        review = review_sotb_update(
            "- Decision: validate with concierge MVP before platform build.",
            session_id="board_test",
            current_sotb="# State of the Board\n\n## Last Session\n[No previous sessions.]\n",
        )

        self.assertTrue(review["requires_approval"])
        self.assertIn("candidate_sotb.md", review["diff"])
        self.assertIn("board_test", review["candidate_sotb"])

    def test_adapts_saved_session_record(self):
        adapted = adapt_session_record({
            "session_id": "board_test",
            "user_query": "What should we build?",
            "stage3": {"content": SYNTHESIS},
        })

        self.assertEqual("board_test", adapted["session_id"])
        self.assertIn("concierge MVP", adapted["decision"]["executive_summary"])
        self.assertIn("concierge MVP", adapted["memory"]["proposed_sotb_update"])
        self.assertTrue(adapted["memory"]["requires_approval"])

    def test_role_gap_review_prefers_shelved_member_when_repeated(self):
        review = review_role_gap(
            ["threat_modeling"],
            query="Should we expose a public API?",
            stage_profile="pre_pmf",
            recurrence_count=2,
        )

        self.assertEqual("activate_shelved_member", review["recommendation"])
        self.assertIn("guardian", review["candidate_shelved_members"])


if __name__ == "__main__":
    unittest.main()
