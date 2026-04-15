import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from server.board.config import BoardMember
from server.board.loader import load_members
from server.board.llm import LLMResponse, _native_provider_for_model, _send_llm_request, query_llm
from server.board.metrics import CallMetrics, SessionMetrics
from server.board.orchestrator import BoardOrchestrator


class InfrastructureContractTest(unittest.TestCase):
    def test_loader_parses_markdown_members_and_shelved_members(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            members_dir = Path(tmpdir)
            (members_dir / "_template.md").write_text("template without frontmatter", encoding="utf-8")
            (members_dir / "strategist.md").write_text(
                """---
id: strategist
title: Chief Strategist
role: CSO
expertise: market, evidence
priority: 90
tags: [strategy, market]
model_override: null
---

# Chief Strategist

## Identity
Owns market evidence.

## Stage 2 Behavior
Challenge unsupported market claims.

## Anti-Patterns
Do not drift into implementation planning.
""",
                encoding="utf-8",
            )
            (members_dir / "_guardian.md").write_text(
                """---
id: guardian
title: Security Guardian
role: CISO
expertise: [security]
priority: 80
tags: security
model_override: null
---

# Security Guardian

## Identity
Owns security risk.
""",
                encoding="utf-8",
            )

            default_members = load_members(members_dir)
            self.assertEqual(["strategist"], [member.id for member in default_members])
            self.assertEqual(["market", "evidence"], default_members[0].expertise)
            self.assertEqual(["strategy", "market"], default_members[0].tags)
            self.assertEqual("Challenge unsupported market claims.", default_members[0].stage2_behavior)

            with_shelved = load_members(members_dir, include_shelved_ids={"guardian"})
            self.assertEqual(["strategist", "guardian"], [member.id for member in with_shelved])
            guardian = next(member for member in with_shelved if member.id == "guardian")
            self.assertEqual(["security"], guardian.expertise)
            self.assertEqual(["security"], guardian.tags)

    def test_session_metrics_count_tokens_and_ignore_unknowns(self):
        metrics = SessionMetrics()
        metrics.record(CallMetrics(
            member_id="strategist",
            stage=1,
            model="openai/gpt-4.1",
            input_tokens=1000,
            output_tokens=500,
            latency_seconds=0.2,
        ))
        metrics.record(CallMetrics(
            member_id="critic",
            stage=2,
            model="unknown/model",
            input_tokens=-1,
            output_tokens=250,
            latency_seconds=0.3,
        ))

        summary = metrics.summary()

        self.assertEqual(1750, metrics.total_tokens())
        self.assertEqual(2, summary["total_calls"])
        self.assertEqual(1500, summary["by_stage"][1]["tokens"])
        self.assertEqual(250, summary["by_stage"][2]["tokens"])
        self.assertGreater(metrics.total_cost_estimate(), 0)


class InfrastructureAsyncContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_query_member_sends_system_prompt_and_records_metrics(self):
        member = BoardMember(
            id="test_member",
            title="Test Member",
            role="Test Role",
            expertise=[],
            system_prompt="SYSTEM PROMPT",
        )
        orchestrator = BoardOrchestrator(members=[member])

        with patch("server.board.orchestrator.query_llm", new_callable=AsyncMock) as mock_query:
            mock_query.return_value = LLMResponse(
                content="member response",
                model="test-model",
                input_tokens=11,
                output_tokens=7,
                latency_seconds=0.25,
            )

            response = await orchestrator._query_member(member, "USER PROMPT", stage=1)

        mock_query.assert_awaited_once()
        args, kwargs = mock_query.call_args
        self.assertEqual("SYSTEM PROMPT", kwargs["system"])
        self.assertEqual(1200, kwargs["max_tokens"])
        self.assertEqual([{"role": "user", "content": "USER PROMPT"}], args[1])
        self.assertEqual("test-model", response.model)
        self.assertEqual(18, orchestrator.metrics.total_tokens())

    async def test_send_llm_request_requires_actionable_api_key_error(self):
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "OPENROUTER_API_KEY not set"):
                await _send_llm_request(
                    "anthropic/claude-sonnet-4",
                    [{"role": "user", "content": "hello"}],
                )

    async def test_query_llm_uses_configured_single_fallback(self):
        fallback_response = LLMResponse(
            content="fallback response",
            model="google/gemini-2.5-pro",
            input_tokens=5,
            output_tokens=3,
            latency_seconds=0.1,
        )

        with patch("server.board.llm._send_llm_request", new_callable=AsyncMock) as mock_send:
            with patch("server.board.llm.logger.warning"):
                mock_send.side_effect = [
                    httpx.TimeoutException("primary failed"),
                    fallback_response,
                ]

                response = await query_llm(
                    "anthropic/claude-sonnet-4",
                    [{"role": "user", "content": "hello"}],
                    system="system prompt",
                )

        self.assertEqual(fallback_response, response)
        self.assertEqual(2, mock_send.await_count)
        first_call = mock_send.await_args_list[0]
        fallback_call = mock_send.await_args_list[1]
        self.assertEqual("anthropic/claude-sonnet-4", first_call.args[0])
        self.assertEqual("google/gemini-2.5-pro", fallback_call.args[0])
        self.assertEqual("system prompt", fallback_call.kwargs["system"])

    async def test_query_llm_routes_native_provider_prefixes_to_sdk_adapter(self):
        native_response = LLMResponse(
            content="native response",
            model="deepseek/deepseek-chat",
            input_tokens=5,
            output_tokens=3,
            latency_seconds=0.1,
        )

        with patch("server.board.llm._send_native_request", new_callable=AsyncMock) as mock_native:
            mock_native.return_value = native_response

            response = await query_llm(
                "deepseek/deepseek-chat",
                [{"role": "user", "content": "hello"}],
                system="system prompt",
            )

        self.assertEqual(native_response, response)
        mock_native.assert_awaited_once()
        self.assertEqual("deepseek/deepseek-chat", mock_native.await_args.args[0])
        self.assertEqual("system prompt", mock_native.await_args.kwargs["system"])

    async def test_query_llm_can_force_openrouter_for_provider_shaped_model_ids(self):
        openrouter_response = LLMResponse(
            content="openrouter response",
            model="deepseek/deepseek-chat",
            input_tokens=5,
            output_tokens=3,
            latency_seconds=0.1,
        )

        with patch("server.board.llm._send_llm_request", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = openrouter_response

            response = await query_llm(
                "openrouter:deepseek/deepseek-chat",
                [{"role": "user", "content": "hello"}],
                fallback=False,
            )

        self.assertEqual(openrouter_response, response)
        mock_send.assert_awaited_once()
        self.assertEqual("deepseek/deepseek-chat", mock_send.await_args.args[0])

    def test_native_provider_model_prefixes_are_explicit(self):
        self.assertEqual(("zai", "glm-5.1"), _native_provider_for_model("glm/glm-5.1"))
        self.assertEqual(("qwen", "qwen3-max"), _native_provider_for_model("qwen/qwen3-max"))
        self.assertEqual(("kimi", "kimi-k2.5"), _native_provider_for_model("kimi/kimi-k2.5"))
        self.assertIsNone(_native_provider_for_model("openrouter:deepseek/deepseek-chat"))


if __name__ == "__main__":
    unittest.main()
