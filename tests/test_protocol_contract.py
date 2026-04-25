from pathlib import Path
import unittest

from server.board.deliberation.compaction import compact_stage1_responses, compact_stage2_responses
from server.board.deliberation.orchestrator import MemberResponse
from server.board.deliberation.prompts import format_stage1, format_stage2


PROTOCOLS = Path("server/protocols")


class ProtocolContractTest(unittest.TestCase):
    def test_stage1_output_format_has_only_stage1_compaction_headings(self):
        output_format = (PROTOCOLS / "stage1_output_format.md").read_text(encoding="utf-8")

        for heading in (
            "## TL;DR",
            "## Risks",
            "## Recommendation",
        ):
            self.assertIn(heading, output_format)

        self.assertNotIn("### Peer Challenges", output_format)
        self.assertNotIn("### Updated Position", output_format)
        self.assertNotIn("### Ranking", output_format)

    def test_stage2_output_format_is_delta_only(self):
        output_format = (PROTOCOLS / "stage2_delta_format.md").read_text(encoding="utf-8")

        for heading in (
            "### Peer Challenges",
            "### Updated Position",
            "### Ranking",
        ):
            self.assertIn(heading, output_format)

        self.assertNotIn("## TL;DR", output_format)
        self.assertNotIn("## Analysis", output_format)
        self.assertNotIn("## Risks", output_format)
        self.assertNotIn("## Recommendation", output_format)

    def test_rendered_stage_prompts_are_stage_specific(self):
        stage1 = format_stage1(role="Test Role", user_query="Should we build this?")
        stage2 = format_stage2(
            role="Test Role",
            user_query="Should we build this?",
            anonymized_responses="### Member A\n## TL;DR\n- Signal.",
            stage2_behavior="Challenge missing evidence.",
        )

        self.assertIn("## TL;DR", stage1)
        self.assertNotIn("### Peer Challenges", stage1)
        self.assertIn("### Peer Challenges", stage2)
        self.assertNotIn("## Evidence Ledger", stage2)

    def test_stage3_protocol_has_projected_decision_headings(self):
        stage3 = (PROTOCOLS / "stage3_synthesis.md").read_text(encoding="utf-8")

        for heading in (
            "### Executive Summary",
            "### Critical Findings",
            "### Strategic Direction",
            "### Architecture & Design",
            "### Security Posture",
            "### Implementation Plan",
            "### Risk Register",
            "### Dissenting Views",
            "### Next Steps",
            "### SOTB Update",
        ):
            self.assertIn(heading, stage3)

    def test_stage1_compaction_extracts_contract_sections(self):
        response = MemberResponse(
            member_id="strategist",
            stage=1,
            model="test-model",
            elapsed_seconds=0.1,
            content="""> Member: Chief Strategist | Stage: 1 | Confidence: High

## TL;DR
- Focus on customer evidence before scaling.

## Analysis
- This section should stay out of compacted peer context.

## Risks
- **High**: Weak customer pull - Probability: H, Impact: H
- **Low**: Naming churn - Probability: L, Impact: L

## Recommendation
- **Do this:** Run five customer interviews this week.
- **Because:** Evidence is currently thin.
""",
        )

        compacted = compact_stage1_responses([response])[0].content

        self.assertIn("> Confidence: High", compacted)
        self.assertIn("## TL;DR", compacted)
        self.assertIn("Focus on customer evidence", compacted)
        self.assertIn("## Recommendation", compacted)
        self.assertIn("Run five customer interviews", compacted)
        self.assertIn("## Top Risk", compacted)
        self.assertIn("Weak customer pull", compacted)
        self.assertNotIn("This section should stay out", compacted)

    def test_stage2_compaction_extracts_contract_sections(self):
        response = MemberResponse(
            member_id="critic",
            stage=2,
            model="test-model",
            elapsed_seconds=0.1,
            content="""> Member: Devil's Advocate | Stage: 2 | Confidence: Medium

## Analysis
- This section should stay out of compacted chair context.

### Peer Challenges
- **Member A:** Challenge - evidence threshold is too low.

### Updated Position
I now believe the MVP is viable only as a concierge test.

### Ranking
1. Member B - strongest evidence.
""",
        )

        compacted = compact_stage2_responses([response])[0].content

        self.assertIn("> Confidence: Medium", compacted)
        self.assertIn("### Peer Challenges", compacted)
        self.assertIn("evidence threshold is too low", compacted)
        self.assertIn("### Updated Position", compacted)
        self.assertIn("concierge test", compacted)
        self.assertIn("### Ranking", compacted)
        self.assertIn("Member B", compacted)
        self.assertNotIn("This section should stay out", compacted)


if __name__ == "__main__":
    unittest.main()
