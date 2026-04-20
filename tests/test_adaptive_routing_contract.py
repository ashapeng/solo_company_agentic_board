import unittest
from unittest.mock import AsyncMock, patch

from server.board.classifier import classify_query, parse_classification
from server.board.llm import LLMResponse
from server.board.roster import (
    active_member_ids,
    decision_capabilities,
    load_roster,
    select_members_for_decision_type,
)


class AdaptiveRoutingContractTest(unittest.TestCase):
    def test_decision_capabilities_live_in_roster(self):
        roster = load_roster()

        self.assertEqual(
            [
                "market_strategy",
                "customer_research",
                "product_strategy",
                "technical_feasibility",
                "evidence_assessment",
                "risk_challenge",
                "synthesis",
            ],
            decision_capabilities("strategic", roster=roster),
        )
        self.assertIn("technical_feasibility", decision_capabilities("technical", roster=roster))
        self.assertEqual(
            decision_capabilities("full-board", roster=roster),
            decision_capabilities("unknown", roster=roster),
        )

    def test_focused_routing_is_smaller_than_full_board(self):
        product = select_members_for_decision_type("product", stage_profile="pre_pmf")
        full_board = select_members_for_decision_type("full-board", stage_profile="pre_pmf")

        self.assertIn("chairperson", product.member_ids)
        self.assertLess(len(product.member_ids), len(full_board.member_ids))
        self.assertEqual(active_member_ids(stage_profile="pre_pmf"), full_board.member_ids)

    def test_parser_accepts_market_alias_and_default_capabilities(self):
        decision_types = list(load_roster()["decision_types"].keys())
        parsed = parse_classification(
            "decision_type: market\n"
            "complexity: simple\n"
            "capabilities: default\n"
            "reasoning: Market framing question.",
            valid_decision_types=decision_types,
        )

        self.assertEqual("strategic", parsed[0])
        self.assertEqual("simple", parsed[1])
        self.assertEqual([], parsed[2])
        self.assertEqual("Market framing question.", parsed[3])


class AdaptiveRoutingAsyncContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_classifier_filters_invalid_capabilities_and_falls_back_to_decision_defaults(self):
        with patch("server.board.classifier.query_llm", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = LLMResponse(
                content=(
                    "decision_type: product\n"
                    "complexity: moderate\n"
                    "capabilities: made_up_capability\n"
                    "reasoning: Needs product review."
                ),
                model="classifier",
                input_tokens=1,
                output_tokens=1,
                latency_seconds=0.1,
            )

            classification = await classify_query("What is the MVP?")

        self.assertEqual("deepseek/deepseek-chat", mock_query.await_args.kwargs["model"])
        self.assertEqual("product", classification.query_type)
        self.assertEqual("moderate", classification.complexity)
        self.assertEqual(
            [
                "product_strategy",
                "customer_research",
                "market_strategy",
                "technical_feasibility",
                "risk_challenge",
                "synthesis",
            ],
            classification.required_capabilities,
        )
        self.assertIn("chairperson", classification.relevant_member_ids)
        self.assertIn("product", classification.relevant_member_ids)

    async def test_classifier_surfaces_unavailable_capabilities_as_role_gap(self):
        with patch("server.board.classifier.query_llm", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = LLMResponse(
                content=(
                    "decision_type: security\n"
                    "complexity: complex\n"
                    "capabilities: default\n"
                    "reasoning: Public API security question."
                ),
                model="classifier",
                input_tokens=1,
                output_tokens=1,
                latency_seconds=0.1,
            )

            classification = await classify_query("Is our public API safe?")

        self.assertEqual("security", classification.query_type)
        self.assertIn("threat_modeling", classification.unavailable_capabilities)
        self.assertIn("role-gap review", classification.role_gap_memo)

    async def test_classifier_failure_falls_back_to_full_board(self):
        with patch("server.board.classifier.query_llm", new_callable=AsyncMock) as mock_query:
            with patch("server.board.classifier.logger.warning"):
                mock_query.side_effect = RuntimeError("classifier unavailable")

                classification = await classify_query("Ambiguous company decision")

        self.assertEqual("full-board", classification.query_type)
        self.assertEqual("complex", classification.complexity)
        self.assertEqual(active_member_ids(stage_profile="pre_pmf"), classification.relevant_member_ids)
        self.assertIn("defaulting to full board", classification.reasoning)


if __name__ == "__main__":
    unittest.main()
