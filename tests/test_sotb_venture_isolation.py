"""Tests for per-venture SOTB path isolation.

The default venture keeps the legacy global files (zero-migration back-compat);
other ventures get physically separate files under server/memory/ventures/<slug>/.
"""
from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _cfg(**overrides):
    from server.harness.config import HarnessConfig
    cfg = HarnessConfig()
    cfg.hardening = {**cfg.hardening, **overrides}
    return cfg


class VentureMemoryPathsTest(unittest.TestCase):
    def test_default_returns_legacy_paths(self):
        from server.memory.sotb_governance import (
            _SOTB_PATH, _INDEX_PATH, venture_memory_paths,
        )
        md, idx = venture_memory_paths("default")
        self.assertEqual(md, _SOTB_PATH)
        self.assertEqual(idx, _INDEX_PATH)

    def test_empty_or_none_returns_legacy_paths(self):
        from server.memory.sotb_governance import (
            _SOTB_PATH, _INDEX_PATH, venture_memory_paths,
        )
        self.assertEqual(venture_memory_paths(""), (_SOTB_PATH, _INDEX_PATH))
        self.assertEqual(venture_memory_paths(None), (_SOTB_PATH, _INDEX_PATH))

    def test_distinct_ventures_resolve_to_distinct_dirs(self):
        from server.memory.sotb_governance import venture_memory_paths
        md_a, idx_a = venture_memory_paths("acme")
        md_b, idx_b = venture_memory_paths("globex")
        self.assertNotEqual(md_a.parent, md_b.parent)
        self.assertEqual(md_a.name, "sotb.md")
        self.assertEqual(idx_a.name, "sotb_index.jsonl")
        self.assertEqual(md_a.parent, idx_a.parent)

    def test_messy_name_is_filesystem_safe_within_ventures_dir(self):
        from server.memory.sotb_governance import _VENTURES_DIR, venture_memory_paths
        md, idx = venture_memory_paths("../../etc/Pass Word!!")
        # Slug must be confined to the ventures dir (no escape via `..`/`/`).
        self.assertEqual(md.parent.parent, _VENTURES_DIR)
        slug = md.parent.name
        self.assertNotIn("/", slug)
        self.assertNotIn("..", slug)
        self.assertTrue(all(c.islower() or c.isdigit() or c == "-" for c in slug))
        self.assertTrue(slug)

    def test_paths_not_created_on_resolve(self):
        from server.memory.sotb_governance import venture_memory_paths
        md, _ = venture_memory_paths("never-written-resolve-only")
        self.assertFalse(md.parent.exists())


class VentureFunctionalIsolationTest(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_writes_are_isolated_per_venture(self):
        from server.memory import sotb_governance as gov

        with tempfile.TemporaryDirectory() as td, \
             patch.object(gov, "_VENTURES_DIR", Path(td) / "ventures"), \
             patch.object(gov, "_SOTB_PATH", Path(td) / "default_sotb.md"), \
             patch.object(gov, "_INDEX_PATH", Path(td) / "default_index.jsonl"), \
             patch("server.memory.sotb_governance.get_config",
                   return_value=_cfg(sotb_judge_enabled=False)):

            update_a = "## Active Decisions\n- ALPHA ships on monday.\n"
            update_b = "## Active Decisions\n- BETA pivots to enterprise.\n"

            self._run(gov.apply_sotb_update_governed(
                update_text=update_a, session_id="sA", verify=False,
                source_member="chairperson", venture_id="alpha-co",
            ))
            self._run(gov.apply_sotb_update_governed(
                update_text=update_b, session_id="sB", verify=False,
                source_member="chairperson", venture_id="beta-co",
            ))

            md_a, _ = self._run(gov.read_sotb_governed(
                query="q", verify=False, venture_id="alpha-co",
            ))
            md_b, _ = self._run(gov.read_sotb_governed(
                query="q", verify=False, venture_id="beta-co",
            ))

            self.assertIn("ALPHA ships on monday.", md_a)
            self.assertNotIn("BETA", md_a)

            self.assertIn("BETA pivots to enterprise.", md_b)
            self.assertNotIn("ALPHA", md_b)

            # The default venture is untouched by either write.
            self.assertFalse((Path(td) / "default_sotb.md").exists())

    def test_default_venture_uses_legacy_paths_end_to_end(self):
        from server.memory import sotb_governance as gov

        with tempfile.TemporaryDirectory() as td, \
             patch.object(gov, "_VENTURES_DIR", Path(td) / "ventures"), \
             patch.object(gov, "_SOTB_PATH", Path(td) / "default_sotb.md"), \
             patch.object(gov, "_INDEX_PATH", Path(td) / "default_index.jsonl"), \
             patch("server.memory.sotb_governance.get_config",
                   return_value=_cfg(sotb_judge_enabled=False)):

            self._run(gov.apply_sotb_update_governed(
                update_text="## Active Decisions\n- DEFAULT decision.\n",
                session_id="s0", verify=False, source_member="chairperson",
                venture_id="default",
            ))
            # Wrote to the (patched) legacy default path, not a ventures subdir.
            self.assertTrue((Path(td) / "default_sotb.md").exists())
            self.assertFalse((Path(td) / "ventures").exists())

            md, _ = self._run(gov.read_sotb_governed(
                query="q", verify=False, venture_id="default",
            ))
            self.assertIn("DEFAULT decision.", md)


if __name__ == "__main__":
    unittest.main()
