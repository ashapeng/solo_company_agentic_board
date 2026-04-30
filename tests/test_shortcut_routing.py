"""Tests for intent-based shortcut routing (secretary brief, etc.)."""

import unittest
from unittest.mock import AsyncMock, patch, MagicMock

from server.board.deliberation.orchestrator import BoardOrchestrator, BoardSession, MemberResponse
from server.board.deliberation.shortcut import ShortcutType, detect_shortcut, DetectedShortcut


class DetectShortcutTest(unittest.TestCase):
    """Rule-based shortcut detection — no LLM calls."""

    def _detect(self, query: str) -> DetectedShortcut | None:
        return detect_shortcut(query)

    # ── should match ──────────────────────────────────────────────

    def test_slash_summary(self):
        r = self._detect("/summary")
        self.assertIsNotNone(r)
        assert r is not None  # for type checker
        self.assertEqual(r.type, ShortcutType.SECRETARY_BRIEF)
        self.assertEqual(r.target_member_id, "secretary")

    def test_slash_brief(self):
        r = self._detect("/brief")
        self.assertEqual(r.type, ShortcutType.SECRETARY_BRIEF)

    def test_at_secretary(self):
        r = self._detect("@secretary summarize the last meeting")
        self.assertEqual(r.type, ShortcutType.SECRETARY_BRIEF)

    def test_secretary_summarize(self):
        r = self._detect("secretary summarize")
        self.assertEqual(r.type, ShortcutType.SECRETARY_BRIEF)

    def test_secretary_summary(self):
        r = self._detect("secretary summary")
        self.assertEqual(r.type, ShortcutType.SECRETARY_BRIEF)

    def test_secretary_give_me_brief(self):
        r = self._detect("secretary give me a brief")
        self.assertEqual(r.type, ShortcutType.SECRETARY_BRIEF)

    def test_summarize_this_discussion(self):
        r = self._detect("summarize this discussion")
        self.assertEqual(r.type, ShortcutType.SECRETARY_BRIEF)

    def test_summarize_with_session_id(self):
        r = self._detect("summarize the board meeting from session board_1742345678")
        self.assertEqual(r.type, ShortcutType.SECRETARY_BRIEF)
        assert r is not None
        self.assertEqual(r.source_session_id, "board_1742345678")

    def test_executive_summary(self):
        r = self._detect("give me an executive summary")
        self.assertEqual(r.type, ShortcutType.SECRETARY_BRIEF)

    # ── should NOT match (normal queries go through full pipeline) ───

    def test_normal_query_no_match(self):
        self.assertIsNone(self._detect("Should we pivot to enterprise?"))

    def test_market_size_query(self):
        self.assertIsNone(self._detect("What do you think about market size?"))

    def test_empty_query(self):
        self.assertIsNone(self._detect(""))

    def test_whitespace_only(self):
        self.assertIsNone(self._detect("   "))


class ShortcutIntegrationTest(unittest.TestCase):
    """Verify that the orchestrator short-circuits on a secretary shortcut."""

    @patch("server.board.deliberation.orchestrator.query_llm", new_callable=AsyncMock)
    @patch("server.board.deliberation.orchestrator.get_board_members", return_value=[])
    @patch("server.board.deliberation.orchestrator.get_members_by_id", return_value={})
    @patch("server.board.deliberation.orchestrator.get_council_models", return_value=["test-model"])
    @patch("server.board.deliberation.orchestrator.get_chairman_model", return_value="chair-model")
    @patch("server.board.deliberation.orchestrator.get_config")
    async def test_secretary_shortcut_skips_deliberation(
        self,
        mock_cfg,
        *_mocks,
    ):
        """When ``secretary summarize`` is sent, deliberate() returns immediately
        without running stages 1–3."""
        cfg = MagicMock()
        cfg.version = "0.1.0"
        cfg.stage4_max_tokens = 3000
        cfg.revision_max_tokens = 2000
        mock_cfg.return_value = cfg

        # Mock the standalone LLM call so we don't need a real model
        from server.board.deliberation import orchestrator as orch_module

        original_call = orch_module.query_llm

        async def _fake_llm(model, messages, **kw):
            from server.board.llm import LLMResponse
            return LLMResponse(content="# Secretary Brief\n\n## One-Liner\nTest brief.", latency_seconds=0.5, finish_reason="stop", model=model, id="fake")

        with patch.object(orch_module, "query_llm", side_effect=_fake_llm):
            orch = BoardOrchestrator()
            session = await orch.deliberate("secretary summarize this discussion")

        # Must have a secretary_brief set (not stage1/2/3 which should be empty)
        self.assertIsInstance(session, BoardSession)
        self.assertIsNotNone(session.secretary_brief, "Secretary brief must be populated after shortcut")
        self.assertEqual(len(session.stage1_responses), 0, "Stage 1 should be skipped in shortcut mode")
        self.assertEqual(len(session.stage2_responses), 0, "Stage 2 should be skipped in shortcut mode")
        self.assertIsNone(session.stage3_synthesis, "Stage 3 should be skipped in shortcut mode")
        self.assertIn("Secretary", session.secretary_brief.content or "")

    @patch("server.board.deliberation.orchestrator.query_llm", new_callable=AsyncMock)
    @patch("server.board.deliberation.orchestrator.get_board_members", return_value=[])
    @patch("server.board.deliberation.orchestrator.get_members_by_id", return_value={})
    @patch("server.board.deliberation.orchestrator.get_council_models", return_value=["test-model"])
    @patch("server.board.deliberation.orchestrator.get_chairman_model", return_value="chair-model")
    @patch("server.board.deliberation.orchestrator.get_config")
    async def test_normal_query_not_shortcut(
        self,
        mock_cfg,
        *_mocks,
        ):
        """A normal business query must NOT trigger shortcut detection."""
        cfg = MagicMock()
        cfg.version = "0.1.0"
        cfg.stage4_max_tokens = 3000
        cfg.revision_max_tokens = 2000
        mock_cfg.return_value = cfg

        orch = BoardOrchestrator()

        # Normal queries don't have shortcut matches, but they WILL fail at
        # classification because there are no members loaded. We just check that
        # the shortcut detector returns None.
        from server.board.deliberation.shortcut import detect_shortcut
        self.assertIsNone(detect_shortcut("Should we enter the Chinese market?"))


if __name__ == "__main__":
    unittest.main()
