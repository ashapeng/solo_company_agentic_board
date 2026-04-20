import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.execution import web_search


class WebSearchContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_provider_returns_unavailable_warning(self):
        with patch.dict(os.environ, {}, clear=True):
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


if __name__ == "__main__":
    unittest.main()
