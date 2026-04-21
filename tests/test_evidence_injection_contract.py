# tests/test_evidence_injection_contract.py
"""Phase 0 repro for Plan 4 (web search integration)."""

from __future__ import annotations

import asyncio
import os
import unittest


class RateLimitPerSessionTest(unittest.TestCase):
    def setUp(self):
        os.environ["WEB_SEARCH_PROVIDER"] = "fake"
        os.environ["AGENTIC_BOARD_WEB_SEARCH_RATE_LIMIT"] = "2"
        os.environ["AGENTIC_BOARD_WEB_SEARCH_RATE_WINDOW_SECONDS"] = "60"

    def tearDown(self):
        for k in (
            "WEB_SEARCH_PROVIDER",
            "AGENTIC_BOARD_WEB_SEARCH_RATE_LIMIT",
            "AGENTIC_BOARD_WEB_SEARCH_RATE_WINDOW_SECONDS",
        ):
            os.environ.pop(k, None)
        try:
            import server.execution.web_search as ws
            if hasattr(ws, "_SESSION_BUCKETS"):
                ws._SESSION_BUCKETS.clear()
        except Exception:
            pass

    def test_per_session_bucket_is_isolated(self):
        from server.execution.web_search import web_search

        async def run():
            # Session A exhausts its quota.
            await web_search("q", session_id="s1")
            await web_search("q", session_id="s1")
            # Session B should still go through.
            return await web_search("q", session_id="s2")

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(run())
        finally:
            loop.close()
        warnings = " ".join(result.get("warnings", []))
        self.assertNotIn(
            "rate limit",
            warnings.lower(),
            "session s2 should NOT be rate-limited when s1 is; "
            "current global deque treats them as one bucket. "
            f"warnings={warnings!r}",
        )


class CacheHitTest(unittest.TestCase):
    def setUp(self):
        os.environ["WEB_SEARCH_PROVIDER"] = "fake"

    def tearDown(self):
        os.environ.pop("WEB_SEARCH_PROVIDER", None)
        try:
            import importlib
            ws = importlib.import_module("server.execution.web_search")
            if hasattr(ws, "_cache"):
                ws._cache.clear()
        except Exception:
            pass

    def test_repeat_query_reuses_cached_result(self):
        import importlib
        ws = importlib.import_module("server.execution.web_search")

        async def run():
            first = await ws.web_search("cache-me")
            second = await ws.web_search("cache-me")
            return first, second

        loop = asyncio.new_event_loop()
        try:
            first, second = loop.run_until_complete(run())
        finally:
            loop.close()

        # Evidence packet IDs should be identical for a cache hit.
        first_packet = first.get("evidence_packet") or {}
        second_packet = second.get("evidence_packet") or {}
        first_id = first_packet.get("packet_id") or first_packet.get("id")
        second_id = second_packet.get("packet_id") or second_packet.get("id")
        self.assertEqual(
            first_id,
            second_id,
            f"expected identical packet IDs on cache hit; "
            f"got {first_id!r} vs {second_id!r}",
        )


class EvidenceHookTest(unittest.IsolatedAsyncioTestCase):
    async def test_orchestrator_exposes_evidence_collection(self):
        os.environ["WEB_SEARCH_PROVIDER"] = "fake"
        try:
            from server.board.deliberation.orchestrator import BoardOrchestrator

            orch = BoardOrchestrator()
            self.assertTrue(
                hasattr(orch, "_collect_member_evidence"),
                "BoardOrchestrator should expose _collect_member_evidence "
                "to inject retrieved evidence for members with evidence_required=True",
            )
            addenda = await orch._collect_member_evidence("What is the foo market?")
            self.assertIsInstance(addenda, dict)
        finally:
            os.environ.pop("WEB_SEARCH_PROVIDER", None)


if __name__ == "__main__":
    unittest.main()
