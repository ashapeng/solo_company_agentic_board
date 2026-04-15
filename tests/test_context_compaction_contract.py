import unittest
from unittest.mock import AsyncMock, patch

from server.board.compaction import compact_stage1_responses
from server.board.config import BoardMember
from server.board.llm import LLMResponse
from server.board.orchestrator import BoardOrchestrator, MemberResponse


def _member(member_id: str) -> BoardMember:
    return BoardMember(
        id=member_id,
        title=f"{member_id.title()} Member",
        role="Test Role",
        expertise=[],
        system_prompt=f"{member_id} system prompt",
        stage2_behavior="Review peers for missing evidence.",
    )


def _stage1_response(member_id: str) -> MemberResponse:
    return MemberResponse(
        member_id=member_id,
        stage=1,
        model="test-model",
        elapsed_seconds=0.1,
        content=f"""> Member: {member_id} | Stage: 1 | Confidence: High

## TL;DR
- {member_id} compact finding.

## Analysis
- VERBOSE STAGE1 ANALYSIS {member_id} should not reach Stage 2.

## Risks
- **High**: {member_id} top risk - Probability: H, Impact: H

## Recommendation
- **Do this:** {member_id} action.
""",
    )


def _stage2_response(member_id: str) -> MemberResponse:
    return MemberResponse(
        member_id=member_id,
        stage=2,
        model="test-model",
        elapsed_seconds=0.1,
        content=f"""> Member: {member_id} | Stage: 2 | Confidence: Medium

## Analysis
- VERBOSE STAGE2 ANALYSIS {member_id} should not reach Stage 3.

### Peer Challenges
- **Member A:** Challenge - {member_id} peer challenge.

### Updated Position
{member_id} updated position.

### Ranking
1. Member A - strongest evidence for {member_id}.
""",
    )


class ContextCompactionContractTest(unittest.TestCase):
    def test_compaction_returns_new_responses_without_mutating_raw_stage1(self):
        raw = [_stage1_response("alpha")]
        original_content = raw[0].content

        compacted = compact_stage1_responses(raw)

        self.assertIsNot(raw[0], compacted[0])
        self.assertEqual(original_content, raw[0].content)
        self.assertIn("VERBOSE STAGE1 ANALYSIS alpha", raw[0].content)
        self.assertNotIn("VERBOSE STAGE1 ANALYSIS alpha", compacted[0].content)
        self.assertIn("## Top Risk", compacted[0].content)


class ContextCompactionAsyncContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_stage2_receives_compacted_stage1_context(self):
        orchestrator = BoardOrchestrator(members=[
            _member("alpha"),
            _member("beta"),
            _member("gamma"),
        ])
        prompts: list[str] = []

        async def fake_query(member: BoardMember, prompt: str, stage: int) -> MemberResponse:
            prompts.append(prompt)
            return MemberResponse(
                member_id=member.id,
                stage=stage,
                content=f"{member.id} stage {stage}",
                model="test-model",
                elapsed_seconds=0.1,
            )

        with patch.object(orchestrator, "_query_member", side_effect=fake_query):
            responses = await orchestrator.stage2(
                "Should we build this?",
                [_stage1_response("alpha"), _stage1_response("beta"), _stage1_response("gamma")],
            )

        self.assertEqual(3, len(responses))
        self.assertEqual(3, len(prompts))
        for prompt in prompts:
            self.assertIn("## TL;DR", prompt)
            self.assertIn("## Recommendation", prompt)
            self.assertIn("## Top Risk", prompt)
            self.assertNotIn("VERBOSE STAGE1 ANALYSIS", prompt)

    async def test_stage3_receives_compacted_stage1_and_stage2_context(self):
        orchestrator = BoardOrchestrator(members=[_member("alpha"), _member("beta")])
        captured: dict[str, str] = {}

        async def fake_query_llm(*args, **kwargs) -> LLMResponse:
            captured["prompt"] = args[1][0]["content"]
            return LLMResponse(
                content="chair synthesis",
                model="chair-model",
                input_tokens=10,
                output_tokens=5,
                latency_seconds=0.1,
            )

        with patch("server.board.orchestrator.query_llm", new=AsyncMock(side_effect=fake_query_llm)):
            synthesis = await orchestrator.stage3(
                "Should we build this?",
                [_stage1_response("alpha"), _stage1_response("beta")],
                [_stage2_response("alpha"), _stage2_response("beta")],
                sotb="SOTB memory",
            )

        prompt = captured["prompt"]
        self.assertEqual("chairperson", synthesis.member_id)
        self.assertIn("## TL;DR", prompt)
        self.assertIn("## Top Risk", prompt)
        self.assertNotIn("VERBOSE STAGE1 ANALYSIS", prompt)
        self.assertIn("### Peer Challenges", prompt)
        self.assertIn("alpha peer challenge", prompt)
        self.assertIn("### Updated Position", prompt)
        self.assertIn("beta updated position", prompt)
        self.assertIn("### Ranking", prompt)
        self.assertNotIn("VERBOSE STAGE2 ANALYSIS", prompt)


if __name__ == "__main__":
    unittest.main()
