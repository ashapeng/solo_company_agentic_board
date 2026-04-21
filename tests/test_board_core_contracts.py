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


class StructuredParseTest(unittest.TestCase):
    def test_parse_stage1_from_fenced_json(self):
        from server.board.deliberation.structured import parse_stage1

        payload = (
            '```json\n'
            '{"confidence":"High","tldr":"t","analysis":"a","recommendation":"r",'
            '"risks":[],"open_questions":[]}\n'
            '```'
        )
        out = parse_stage1(payload)
        self.assertIsNotNone(out)
        self.assertEqual(out.confidence, "High")
        self.assertEqual(out.tldr, "t")

    def test_parse_stage1_returns_none_on_non_json(self):
        from server.board.deliberation.structured import parse_stage1

        self.assertIsNone(parse_stage1("no json here, only prose"))

    def test_parse_stage1_bare_json_without_fence(self):
        from server.board.deliberation.structured import parse_stage1

        payload = (
            'Preamble text.\n'
            '{"confidence":"Medium","tldr":"x","analysis":"y","recommendation":"z",'
            '"risks":[{"severity":"High","description":"r"}],"open_questions":["q1"]}\n'
            'Trailing text.'
        )
        out = parse_stage1(payload)
        self.assertIsNotNone(out)
        self.assertEqual(out.confidence, "Medium")
        self.assertEqual(out.risks[0].severity, "High")

    def test_parse_stage2_from_fenced_json(self):
        from server.board.deliberation.structured import parse_stage2

        payload = (
            '```json\n'
            '{"confidence":"Low","updated_position":"p",'
            '"peer_challenges":["c1"],"ranking":["r1","r2"]}\n'
            '```'
        )
        out = parse_stage2(payload)
        self.assertIsNotNone(out)
        self.assertEqual(out.peer_challenges, ["c1"])
        self.assertEqual(out.ranking, ["r1", "r2"])

    def test_parse_stage1_walks_past_invalid_first_fence(self):
        from server.board.deliberation.structured import parse_stage1

        payload = (
            '```json\n'
            '{"some_other_key": "commentary", "not_a_stage1_response": true}\n'
            '```\n'
            'Then the real answer:\n'
            '```json\n'
            '{"confidence":"High","tldr":"t","analysis":"a","recommendation":"r",'
            '"risks":[],"open_questions":[]}\n'
            '```'
        )
        out = parse_stage1(payload)
        self.assertIsNotNone(out)
        self.assertEqual(out.tldr, "t")


if __name__ == "__main__":
    unittest.main()
