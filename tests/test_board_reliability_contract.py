import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from server.board.deliberation.classifier import classify_query
from server.board.deliberation.orchestrator import BoardOrchestrator, BoardSession, MemberResponse
from server.board.llm import LLMResponse
from server.execution import parse_delegation_plan
from server.harness.ledger import init_db, query_outcomes, record_session


TRUNCATED_SYNTHESIS = """### Executive Summary
Validate first.

### Delegation Plan
```json
{
  "tasks": [
    {
      "title": "Technical Feasibility",
      "objective": "Assess the build",
      "execution_unit_id": "engineering",
      "manager_agent_id": "technical_lead",
      "accountable_board_member_id": "technical_lead"
"""


VALID_DELEGATION_JSON = """{
  "tasks": [
    {
      "title": "Customer Discovery",
      "objective": "Interview ecommerce sellers.",
      "execution_unit_id": "research",
      "manager_agent_id": "research_lead",
      "accountable_board_member_id": "researcher",
      "priority": "p0",
      "acceptance_criteria": ["Interview plan exists"],
      "dependencies": [],
      "approval_required": true
    }
  ]
}"""


class DelegationReliabilityContractTest(unittest.IsolatedAsyncioTestCase):
    def test_truncated_delegation_section_records_structured_warning(self):
        plan = parse_delegation_plan(TRUNCATED_SYNTHESIS, session_id="truncated_session")

        self.assertEqual([], plan["tasks"])
        self.assertIn("parseable JSON", plan["warnings"][0])
        self.assertTrue(plan["structured_output_failed"])
        self.assertTrue(plan["truncated"])

    async def test_dedicated_delegation_pass_retries_after_malformed_json(self):
        orchestrator = BoardOrchestrator()
        responses = [
            LLMResponse("not json", "test-model", 10, 2, 0.1),
            LLMResponse(VALID_DELEGATION_JSON, "test-model", 10, 20, 0.1),
        ]

        with patch("server.board.deliberation.orchestrator.query_llm", new_callable=AsyncMock) as mock_query:
            mock_query.side_effect = responses

            plan = await orchestrator.build_delegation_plan(
                user_query="Build an AI photo product",
                synthesis_content="### Executive Summary\nValidate first.",
                session_id="delegation_retry",
                query_type="product",
                complexity="moderate",
            )

        self.assertEqual(2, mock_query.await_count)
        self.assertEqual(1, len(plan["tasks"]))
        self.assertEqual("research_lead", plan["tasks"][0]["manager_agent_id"])
        self.assertIn("retry", " ".join(plan["warnings"]).lower())


class RoutingAndClarificationContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_classifier_unions_explicit_capabilities_with_decision_defaults(self):
        with patch("server.board.deliberation.classifier.query_llm", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = LLMResponse(
                content=(
                    "decision_type: product\n"
                    "complexity: moderate\n"
                    "capabilities: technical_feasibility, value_proposition\n"
                    "reasoning: Product concept needs validation and feasibility."
                ),
                model="test",
                input_tokens=1,
                output_tokens=1,
                latency_seconds=0.1,
            )

            classification = await classify_query(
                "search business on e-commerce with ai enhanced photo from actual product"
            )

        self.assertEqual("product", classification.query_type)
        self.assertIn("product", classification.relevant_member_ids)
        self.assertIn("researcher", classification.relevant_member_ids)
        self.assertIn("strategist", classification.relevant_member_ids)
        self.assertIn("architect", classification.relevant_member_ids)

    async def test_ambiguous_prompt_returns_clarification_required_before_stage1(self):
        orchestrator = BoardOrchestrator()

        with patch("server.board.deliberation.orchestrator.BoardOrchestrator.stage1") as mock_stage1:
            with patch.object(BoardSession, "save", return_value=Path("/tmp/clarify.json")):
                with patch("server.board.deliberation.orchestrator._record_to_ledger"):
                    session = await orchestrator.deliberate(
                        "search business on e-commerce with ai enhanced photo from actual product",
                        session_id="clarify_required",
                        member_ids=["product", "researcher", "architect"],
                    )

        mock_stage1.assert_not_called()
        self.assertEqual("clarification_required", session.status)
        self.assertEqual("required", session.clarification["status"])
        self.assertTrue(session.intake_cards)
        self.assertTrue(session.clarification["questions"])


class LedgerReliabilityContractTest(unittest.TestCase):
    def test_ledger_records_parse_warning_truncation_and_blank_member_response(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "ledger.db"
            init_db(db_path)
            session = BoardSession(session_id="ledger_reliability", user_query="question")
            session.classification = {
                "query_type": "product",
                "complexity": "moderate",
                "relevant_member_ids": ["chairperson", "product", "architect"],
            }
            session.stage1_responses = [
                MemberResponse("product", 1, "Useful analysis", "model-a", 0.1),
                MemberResponse("architect", 1, "", "model-b", 0.1),
            ]
            session.stage3_synthesis = MemberResponse(
                "chairperson",
                3,
                TRUNCATED_SYNTHESIS,
                "model-c",
                0.1,
            )
            session.delegation_plan = parse_delegation_plan(
                TRUNCATED_SYNTHESIS,
                session_id=session.session_id,
            )
            session.clarification = {
                "status": "answered",
                "questions": [{"member_id": "product", "question": "Who is the buyer?"}],
                "answers": {"buyer": "SMB sellers"},
            }

            record_session(session, config_version=1, db_path=db_path)
            rows = query_outcomes(db_path=db_path)

        self.assertEqual(1, rows[0]["structured_output_failed"])
        self.assertEqual(1, rows[0]["truncation_detected"])
        self.assertIn("parseable JSON", rows[0]["parse_warnings"])
        self.assertIn("architect", rows[0]["blank_member_responses"])
        self.assertEqual(1, rows[0]["clarification_questions_count"])
        self.assertEqual(1, rows[0]["clarification_answers_count"])


if __name__ == "__main__":
    unittest.main()
