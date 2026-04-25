import os
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from server.board.config import (
    BoardMember,
    get_chairman_model,
    get_classifier_model,
    get_council_models,
    get_verification_model,
)
from server.board.loader import load_members
from server.board.llm import LLMResponse
from server.board.metrics import CallMetrics, SessionMetrics
from server.board.deliberation.orchestrator import BoardOrchestrator


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
intake:
  clarifying_question: "Which seller segment and market wedge should this target first?"
  immediate_concern: "Market and competitive assumptions are not yet grounded."
  proposed_path: "Define the wedge and evidence threshold before spend."
  required_execution_unit: "strategy"
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
intake:
  clarifying_question: "What security risks does this expose?"
  immediate_concern: "Security implications have not been assessed."
  proposed_path: "Run security review before rollout."
  required_execution_unit: "legal"
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

    def test_default_models_use_available_native_providers(self):
        with patch.dict(
            os.environ,
            {
                "CHAIRMAN_MODEL": "",
                "COUNCIL_MODELS": "",
                "CLASSIFIER_MODEL": "",
                "VERIFICATION_MODEL": "",
            },
            clear=False,
        ):
            os.environ.pop("CHAIRMAN_MODEL", None)
            os.environ.pop("COUNCIL_MODELS", None)
            os.environ.pop("CLASSIFIER_MODEL", None)
            os.environ.pop("VERIFICATION_MODEL", None)

            self.assertEqual("kimi/kimi-k2.5", get_chairman_model())
            self.assertEqual(
                ["deepseek/deepseek-chat", "kimi/kimi-k2.5"],
                get_council_models(),
            )
            self.assertEqual("deepseek/deepseek-chat", get_classifier_model())
            self.assertEqual("deepseek/deepseek-chat", get_verification_model())

    def test_runtime_lockfile_pins_project_dependencies(self):
        pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        direct_deps = {
            item.split(">=", 1)[0].split("==", 1)[0].lower()
            for item in pyproject["project"]["dependencies"]
        }
        lock_lines = Path("requirements.lock").read_text(encoding="utf-8").splitlines()
        locked = {
            line.split("==", 1)[0].lower()
            for line in lock_lines
            if line and not line.startswith("#") and "==" in line
        }

        self.assertTrue(direct_deps <= locked)
        self.assertTrue(all("==" in line for line in lock_lines if line and not line.startswith("#")))


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

        with patch("server.board.deliberation.orchestrator.query_llm", new_callable=AsyncMock) as mock_query:
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


if __name__ == "__main__":
    unittest.main()
