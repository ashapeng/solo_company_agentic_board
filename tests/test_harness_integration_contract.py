import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

from server.board.harness_config import HarnessConfig
from server.board.llm import LLMResponse
from server.board.orchestrator import BoardOrchestrator, BoardSession, MemberResponse
from server.board.verification import verify_synthesis


class ConfigWiringContractTest(unittest.TestCase):
    def test_orchestrator_no_longer_has_hardcoded_stage_max_tokens(self):
        """After migration, STAGE_MAX_TOKENS should not exist in orchestrator."""
        import server.board.orchestrator as orch_module
        self.assertFalse(
            hasattr(orch_module, "STAGE_MAX_TOKENS"),
            "STAGE_MAX_TOKENS should be deleted from orchestrator — now in harness_config",
        )

    def test_orchestrator_no_longer_has_hardcoded_response_thresholds(self):
        import server.board.orchestrator as orch_module
        self.assertFalse(hasattr(orch_module, "MAX_STAGE1_REQUIRED_RESPONSES"))
        self.assertFalse(hasattr(orch_module, "MAX_STAGE2_REQUIRED_RESPONSES"))


class ConfigWiringAsyncContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_orchestrator_uses_config_token_budget(self):
        """Orchestrator should pass config's max_tokens to query_llm."""
        with patch("server.board.orchestrator.get_config") as mock_cfg:
            mock_cfg.return_value = HarnessConfig(stage1_max_tokens=999)
            with patch("server.board.orchestrator.query_llm", new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = LLMResponse(
                    content="Analysis.", model="test", input_tokens=1,
                    output_tokens=1, latency_seconds=0.1,
                )
                orchestrator = BoardOrchestrator()
                if orchestrator.council:
                    member = orchestrator.council[0]
                    await orchestrator._query_member(member, "test prompt", stage=1)

                    call_kwargs = mock_llm.call_args
                    self.assertEqual(call_kwargs.kwargs.get("max_tokens"), 999)

    async def test_verification_uses_config_threshold(self):
        """verify_synthesis should use config's verification_threshold."""
        with patch("server.board.verification.get_config") as mock_cfg:
            mock_cfg.return_value = HarnessConfig(verification_threshold=9.0)
            with patch("server.board.verification.query_llm", new_callable=AsyncMock) as mock_llm:
                mock_llm.return_value = LLMResponse(
                    content='{"score": 8, "deficiencies": [], "suggestions": []}',
                    model="verifier", input_tokens=1, output_tokens=1,
                    latency_seconds=0.1,
                )

                result = await verify_synthesis("summary", "peer review", "query")

                # Score 8 < threshold 9 → should NOT pass
                self.assertFalse(result.passed)


if __name__ == "__main__":
    unittest.main()
