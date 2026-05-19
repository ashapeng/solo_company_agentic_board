import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.execution import web_search


class WebSearchContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_provider_returns_unavailable_warning(self):
        with patch.dict(os.environ, {"AGENTIC_BOARD_WEB_SEARCH_SESSION_CAP": "1000"}, clear=True):
            result = await web_search("ai product photography", provider="disabled")

        self.assertEqual([], result["results"])
        self.assertIn("unavailable", result["warnings"][0].lower())

    async def test_fake_provider_creates_evidence_packet_with_sources(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from server.execution import evidence

            old_dir = evidence._EVIDENCE_DIR
            evidence._EVIDENCE_DIR = Path(tmpdir)
            try:
                result = await web_search("ai product photography", provider="fake")
            finally:
                evidence._EVIDENCE_DIR = old_dir

        self.assertEqual("current", result["evidence_packet"]["freshness"])
        self.assertGreaterEqual(len(result["results"]), 1)
        source = result["evidence_packet"]["sources"][0]
        self.assertTrue(source["url"].startswith("https://example.com/search"))
        self.assertTrue(source["retrieved_at"])


class SearchCacheTest(unittest.TestCase):
    def test_put_then_get_returns_value(self):
        from server.execution.search_cache import SearchCache

        cache = SearchCache(maxsize=4, ttl_seconds=60)
        cache.put(("a", "b"), {"x": 1})
        self.assertEqual(cache.get(("a", "b")), {"x": 1})

    def test_get_returns_none_for_missing(self):
        from server.execution.search_cache import SearchCache

        cache = SearchCache()
        self.assertIsNone(cache.get(("missing",)))

    def test_lru_eviction(self):
        from server.execution.search_cache import SearchCache

        cache = SearchCache(maxsize=2, ttl_seconds=60)
        cache.put(("a",), {"v": 1})
        cache.put(("b",), {"v": 2})
        cache.put(("c",), {"v": 3})
        self.assertIsNone(cache.get(("a",)))
        self.assertEqual(cache.get(("b",)), {"v": 2})
        self.assertEqual(cache.get(("c",)), {"v": 3})

    def test_ttl_expiration(self):
        import time as _time
        from server.execution.search_cache import SearchCache

        cache = SearchCache(maxsize=4, ttl_seconds=0)
        cache.put(("a",), {"v": 1})
        # ttl=0 means ALL entries are considered expired.
        # Ensure the wall-clock monotonic delta is > 0.
        _time.sleep(0.001)
        self.assertIsNone(cache.get(("a",)))

    def test_clear_empties_cache(self):
        from server.execution.search_cache import SearchCache

        cache = SearchCache()
        cache.put(("a",), {"v": 1})
        cache.put(("b",), {"v": 2})
        cache.clear()
        self.assertIsNone(cache.get(("a",)))
        self.assertIsNone(cache.get(("b",)))


if __name__ == "__main__":
    unittest.main()
