# tests/test_board_core_contracts.py
"""Phase 0 repro: board core contracts (member IDs hardcoded; drift breaks compaction)."""

from __future__ import annotations

import pathlib
import re
import unittest


class OrchestratorHardcodedIdsTest(unittest.TestCase):
    def test_no_literal_council_member_ids(self):
        text = pathlib.Path("server/board/deliberation/orchestrator.py").read_text()
        for mid in ("strategist", "product", "researcher",
                    "critic", "architect", "builder"):
            pattern = rf"""["']{mid}["']"""
            self.assertIsNone(
                re.search(pattern, text),
                f"orchestrator still hardcodes member id literal: {mid!r}",
            )


class DriftedMarkdownCompactionTest(unittest.TestCase):
    def test_drifted_stage1_header_still_compacts(self):
        from server.board.deliberation.compaction import _compact_single_stage1
        drifted = "**TL;DR:** alpha wins\n\n**Recommendation:** ship it\n"
        out = _compact_single_stage1(drifted)
        self.assertIn("alpha", out)
        self.assertIn("ship", out)


class Stage1JsonPreferredTest(unittest.TestCase):
    def test_json_block_is_parsed_first(self):
        from server.board.deliberation.compaction import _compact_single_stage1
        payload = (
            "Some preamble.\n\n"
            "```json\n"
            '{"confidence":"High","tldr":"alpha","analysis":"a","recommendation":"beta",'
            '"risks":[{"severity":"High","description":"r1"}],"open_questions":[]}\n'
            "```\n"
            "Some trailer."
        )
        out = _compact_single_stage1(payload)
        self.assertIn("alpha", out)
        self.assertIn("beta", out)


if __name__ == "__main__":
    unittest.main()
