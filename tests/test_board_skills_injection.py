"""Stage 1 / Stage 2 skill injection — orchestrator + helper tests."""

from __future__ import annotations

import unittest


class ComposeSystemPromptHelperTest(unittest.TestCase):
    def test_empty_skill_bodies_returns_base_unchanged(self):
        from server.board.deliberation.prompts import compose_system_prompt

        out = compose_system_prompt("BASE", [])

        self.assertEqual(out, "BASE")

    def test_single_skill_appended_with_divider(self):
        from server.board.deliberation.prompts import compose_system_prompt

        out = compose_system_prompt("BASE", ["SKILL_BODY"])

        self.assertEqual(out, "BASE\n\n---\n\nSKILL_BODY")

    def test_multiple_skills_appended_with_divider_between(self):
        from server.board.deliberation.prompts import compose_system_prompt

        out = compose_system_prompt("BASE", ["A", "B", "C"])

        self.assertEqual(out, "BASE\n\n---\n\nA\n\n---\n\nB\n\n---\n\nC")

    def test_divider_is_exactly_two_newlines_dashes_two_newlines(self):
        from server.board.deliberation.prompts import compose_system_prompt

        out = compose_system_prompt("X", ["Y"])

        self.assertIn("\n\n---\n\n", out)
        # No double-divider, no extra blank lines:
        self.assertNotIn("\n\n\n---", out)
        self.assertNotIn("---\n\n\n", out)

    def test_empty_base_with_skill_yields_divider_then_skill(self):
        from server.board.deliberation.prompts import compose_system_prompt

        out = compose_system_prompt("", ["BODY"])

        # Edge case: empty base prompt is unusual but mustn't crash.
        # The helper appends with the standard divider; downstream consumers
        # never pass empty base in practice (every member has a system_prompt).
        self.assertEqual(out, "\n\n---\n\nBODY")


def _make_fake_llm_resp():
    return type(
        "Resp",
        (),
        {
            "content": "ok",
            "model": "test/model",
            "latency_seconds": 0.01,
            "input_tokens": 1,
            "output_tokens": 1,
            "cost_estimate": 0.0,
            "finish_reason": "stop",
            "response_id": None,
        },
    )()


def _make_orchestrator(member):
    """Instantiate BoardOrchestrator with a controlled single-member setup."""
    from unittest.mock import patch as _patch

    from server.board.deliberation.orchestrator import BoardOrchestrator

    chairman = member  # use same member as chairman to simplify fixture

    with _patch("server.board.deliberation.orchestrator.get_board_members", return_value=[member]), \
         _patch("server.board.deliberation.orchestrator.get_members_by_id", return_value={member.id: member}), \
         _patch("server.board.deliberation.orchestrator.get_chairman_model", return_value="test/model"), \
         _patch("server.board.deliberation.orchestrator._assign_models", return_value={member.id: "test/model"}):
        board = BoardOrchestrator(members=[member], chairman_id=member.id)

    return board


class Stage1SkillInjectionTest(unittest.TestCase):
    def test_query_member_appends_skill_body_to_system_prompt_at_stage_1(self):
        import asyncio
        from unittest.mock import AsyncMock, patch

        from server.board.config import BoardMember

        member = BoardMember(
            id="strategist",
            title="Strategist",
            role="CSO",
            expertise=[],
            system_prompt="STRATEGIST BASE PROMPT",
            skills=["pricing_research"],
        )

        board = _make_orchestrator(member)

        with patch(
            "server.board.deliberation.orchestrator.query_llm",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = _make_fake_llm_resp()
            asyncio.run(board._query_member(member, prompt="PROMPT", stage=1))

            self.assertTrue(mock_llm.called)
            kwargs = mock_llm.call_args.kwargs
            system_prompt = kwargs["system"]
            self.assertIn("STRATEGIST BASE PROMPT", system_prompt)
            self.assertIn("\n\n---\n\n", system_prompt)
            self.assertIn("Van Westendorp", system_prompt,
                          "pricing_research body must be appended at Stage 1")

    def test_member_without_skills_sends_base_prompt_unchanged_at_stage_1(self):
        import asyncio
        from unittest.mock import AsyncMock, patch

        from server.board.config import BoardMember

        member = BoardMember(
            id="critic",
            title="Critic",
            role="Red Team",
            expertise=[],
            system_prompt="CRITIC BASE PROMPT",
            skills=[],
        )

        board = _make_orchestrator(member)

        with patch(
            "server.board.deliberation.orchestrator.query_llm",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = _make_fake_llm_resp()
            asyncio.run(board._query_member(member, prompt="PROMPT", stage=1))

            kwargs = mock_llm.call_args.kwargs
            system_prompt = kwargs["system"]
            self.assertEqual(system_prompt, "CRITIC BASE PROMPT")
            self.assertNotIn("---", system_prompt)


if __name__ == "__main__":
    unittest.main()
