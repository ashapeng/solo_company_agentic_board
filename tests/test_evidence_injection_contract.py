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
    def setUp(self):
        os.environ["WEB_SEARCH_PROVIDER"] = "fake"

    def tearDown(self):
        os.environ.pop("WEB_SEARCH_PROVIDER", None)
        try:
            import server.execution.web_search as ws
            if hasattr(ws, "_SESSION_BUCKETS"):
                ws._SESSION_BUCKETS.clear()
            if hasattr(ws, "_cache"):
                ws._cache.clear()
        except Exception:
            pass

    async def test_orchestrator_exposes_evidence_collection(self):
        from server.board.deliberation.orchestrator import BoardOrchestrator

        orch = BoardOrchestrator()
        self.assertTrue(
            hasattr(orch, "_collect_member_evidence"),
            "BoardOrchestrator should expose _collect_member_evidence "
            "to inject retrieved evidence for members with evidence_required=True",
        )
        result = await orch._collect_member_evidence("What is the foo market?")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        addenda, packet_ids = result
        self.assertIsInstance(addenda, dict)
        self.assertIsInstance(packet_ids, dict)

    async def test_researcher_receives_retrieved_evidence(self):
        from server.board.deliberation.orchestrator import BoardOrchestrator

        orch = BoardOrchestrator()
        orch._current_session_id = "board_1700000123"
        addenda, packet_ids = await orch._collect_member_evidence(
            "How big is the indie app developer market?"
        )
        # Researcher has evidence_required=true; fake provider always returns 1 result.
        self.assertIn("researcher", addenda)
        self.assertIn("Retrieved Evidence", addenda["researcher"])

    async def test_non_flagged_member_receives_no_addendum(self):
        from server.board.deliberation.orchestrator import BoardOrchestrator

        orch = BoardOrchestrator()
        addenda, packet_ids = await orch._collect_member_evidence("random query")
        self.assertNotIn("builder", addenda)
        self.assertNotIn("critic", addenda)


class EvidencePacketIdsAreRealTest(unittest.IsolatedAsyncioTestCase):
    async def test_session_evidence_packets_reference_existing_packets(self):
        os.environ["WEB_SEARCH_PROVIDER"] = "fake"
        try:
            from server.board.deliberation.orchestrator import BoardOrchestrator
            from server.execution.evidence import get_evidence_packet

            orch = BoardOrchestrator()
            addenda, packet_ids = await orch._collect_member_evidence(
                "What market should we enter?"
            )
            # At least one evidence-required member should produce a real packet id.
            self.assertTrue(packet_ids, "expected at least one evidence packet id")
            for member_id, pid in packet_ids.items():
                self.assertIsInstance(pid, str)
                self.assertTrue(pid, "packet id must be non-empty")
                # The packet should be retrievable from the evidence store.
                packet = get_evidence_packet(pid)
                self.assertIsNotNone(
                    packet,
                    f"packet id {pid!r} for {member_id!r} was not found in the evidence store",
                )
        finally:
            os.environ.pop("WEB_SEARCH_PROVIDER", None)


class SessionBucketSweepTest(unittest.TestCase):
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
        import importlib
        ws = importlib.import_module("server.execution.web_search")
        ws._SESSION_BUCKETS.clear()
        ws._cache.clear()

    def test_empty_bucket_is_evicted_on_next_call(self):
        import asyncio, importlib
        from collections import deque

        ws = importlib.import_module("server.execution.web_search")
        ws._SESSION_BUCKETS["stale_session"] = deque()

        async def run():
            return await ws.web_search("x", session_id="fresh_session")

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(run())
        finally:
            loop.close()
        self.assertNotIn("stale_session", ws._SESSION_BUCKETS)
        self.assertIn("fresh_session", ws._SESSION_BUCKETS)


class CacheBeforeRateLimitTest(unittest.TestCase):
    def setUp(self):
        os.environ["WEB_SEARCH_PROVIDER"] = "fake"
        os.environ["AGENTIC_BOARD_WEB_SEARCH_RATE_LIMIT"] = "1"
        os.environ["AGENTIC_BOARD_WEB_SEARCH_RATE_WINDOW_SECONDS"] = "60"

    def tearDown(self):
        for k in (
            "WEB_SEARCH_PROVIDER",
            "AGENTIC_BOARD_WEB_SEARCH_RATE_LIMIT",
            "AGENTIC_BOARD_WEB_SEARCH_RATE_WINDOW_SECONDS",
        ):
            os.environ.pop(k, None)
        import importlib
        ws = importlib.import_module("server.execution.web_search")
        ws._SESSION_BUCKETS.clear()
        ws._cache.clear()

    def test_cached_query_bypasses_rate_limit(self):
        import asyncio, importlib

        ws = importlib.import_module("server.execution.web_search")

        async def run():
            first = await ws.web_search("cached-q", session_id="s1")
            # s1 is now at its 1-req/60s quota. Same query should still serve
            # from cache, WITHOUT emitting a rate-limit warning.
            second = await ws.web_search("cached-q", session_id="s1")
            return first, second

        loop = asyncio.new_event_loop()
        try:
            first, second = loop.run_until_complete(run())
        finally:
            loop.close()

        self.assertEqual(first.get("warnings") or [], [])
        self.assertEqual(
            second.get("warnings") or [],
            [],
            "cached hit must not emit a rate-limit warning",
        )
        self.assertEqual(first["results"], second["results"])


if __name__ == "__main__":
    unittest.main()
