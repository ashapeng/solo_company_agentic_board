"""Tests for SOTB governance (spec §8) — sidecar, freshness, conflict logging."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from server.harness.config import HarnessConfig, get_config


class HarnessConfigSotbKeysTest(unittest.TestCase):
    def test_hardening_defaults_include_sotb_judge_enabled_false(self):
        cfg = HarnessConfig()
        self.assertIn("sotb_judge_enabled", cfg.hardening)
        self.assertEqual(cfg.hardening["sotb_judge_enabled"], False)

    def test_hardening_defaults_include_sotb_judge_model_none(self):
        cfg = HarnessConfig()
        self.assertIn("sotb_judge_model", cfg.hardening)
        self.assertIsNone(cfg.hardening["sotb_judge_model"])

    def test_hardening_defaults_include_sotb_stale_days_90(self):
        cfg = HarnessConfig()
        self.assertIn("sotb_stale_days", cfg.hardening)
        self.assertEqual(cfg.hardening["sotb_stale_days"], 90)


from datetime import datetime, timezone


class SotbEntryTest(unittest.TestCase):
    def test_compute_entry_id_is_deterministic_12_char_hex(self):
        from server.memory.sotb_governance import SotbEntry
        eid_a = SotbEntry.compute_entry_id("Active Decisions", "ship MVP friday")
        eid_b = SotbEntry.compute_entry_id("Active Decisions", "ship MVP friday")
        self.assertEqual(eid_a, eid_b)
        self.assertEqual(len(eid_a), 12)
        self.assertTrue(all(c in "0123456789abcdef" for c in eid_a))

    def test_compute_entry_id_differs_by_section(self):
        from server.memory.sotb_governance import SotbEntry
        a = SotbEntry.compute_entry_id("Active Decisions", "X")
        b = SotbEntry.compute_entry_id("Risk Register", "X")
        self.assertNotEqual(a, b)

    def test_entry_to_dict_roundtrips_via_from_dict(self):
        from server.memory.sotb_governance import SotbEntry
        e = SotbEntry(
            entry_id="abc123def456", section="Active Decisions", text="ship X",
            created_at="2026-05-17T00:00:00+00:00",
            updated_at="2026-05-17T00:00:00+00:00",
            confidence=0.8, expires_at=None,
            provenance={"session_id": "s1", "source_member": "chairperson"},
        )
        d = e.to_dict()
        e2 = SotbEntry.from_dict(d)
        self.assertEqual(e, e2)


class SectionDefaultsTest(unittest.TestCase):
    def test_section_defaults_match_spec_table_8_4(self):
        from server.memory.sotb_governance import SECTION_DEFAULTS
        self.assertIsNone(SECTION_DEFAULTS["Active Decisions"])
        self.assertEqual(SECTION_DEFAULTS["Risk Register"], 180)
        self.assertEqual(SECTION_DEFAULTS["Established Positions"], 365)
        self.assertEqual(SECTION_DEFAULTS["Open Questions"], 90)
        self.assertEqual(SECTION_DEFAULTS["Last Session"], 30)
        self.assertIsNone(SECTION_DEFAULTS["Resolved"])


class ParseEntriesFromUpdateTest(unittest.TestCase):
    def test_parse_extracts_section_bullets_with_default_confidence(self):
        from server.memory.sotb_governance import parse_entries_from_update
        update = (
            "## Active Decisions\n"
            "- Ship the MVP on Friday.\n"
            "- Defer billing to v2.\n"
        )
        entries = parse_entries_from_update(update, session_id="s1", source_member="chairperson")
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].section, "Active Decisions")
        self.assertEqual(entries[0].text, "Ship the MVP on Friday.")
        self.assertEqual(entries[0].confidence, 0.5)  # DC3 default
        self.assertIsNone(entries[0].expires_at)       # §8.4 Active Decisions has no default
        self.assertEqual(entries[0].provenance, {"session_id": "s1", "source_member": "chairperson"})

    def test_parse_confidence_suffix_overrides_default(self):
        from server.memory.sotb_governance import parse_entries_from_update
        update = "## Active Decisions\n- Ship MVP. (confidence: 0.9)\n"
        entries = parse_entries_from_update(update, session_id="s1", source_member="chair")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].confidence, 0.9)
        # Text strips the (confidence: ...) suffix.
        self.assertEqual(entries[0].text, "Ship MVP.")

    def test_parse_confidence_clamps_to_unit_interval(self):
        from server.memory.sotb_governance import parse_entries_from_update
        u_high = "## Active Decisions\n- X. (confidence: 1.5)\n"
        u_low = "## Active Decisions\n- X. (confidence: -0.2)\n"
        self.assertEqual(parse_entries_from_update(u_high, session_id="s", source_member="m")[0].confidence, 1.0)
        self.assertEqual(parse_entries_from_update(u_low, session_id="s", source_member="m")[0].confidence, 0.0)

    def test_parse_expires_suffix_overrides_section_default(self):
        from server.memory.sotb_governance import parse_entries_from_update
        update = "## Risk Register\n- Q3 churn spike. (expires: 2026-12-31)\n"
        entries = parse_entries_from_update(update, session_id="s", source_member="m")
        self.assertEqual(entries[0].expires_at, "2026-12-31T00:00:00+00:00")

    def test_parse_section_default_expiry_applies_when_no_suffix(self):
        """Risk Register entries default to 180d (§8.4) when no expires_at suffix."""
        from server.memory.sotb_governance import parse_entries_from_update
        update = "## Risk Register\n- Some risk.\n"
        entries = parse_entries_from_update(update, session_id="s", source_member="m")
        # Just assert that expires_at is set (some ISO string), not the exact value
        # — exact value depends on now() and is hard to pin in a unit test.
        self.assertIsNotNone(entries[0].expires_at)
        self.assertTrue(entries[0].expires_at.endswith("+00:00"))

    def test_parse_ignores_unknown_sections(self):
        """Defensive: chair-provided update with a typo section is skipped."""
        from server.memory.sotb_governance import parse_entries_from_update
        update = "## Random Section\n- not a valid section.\n## Active Decisions\n- valid.\n"
        entries = parse_entries_from_update(update, session_id="s", source_member="m")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].text, "valid.")

    def test_parse_empty_update_returns_empty_list(self):
        from server.memory.sotb_governance import parse_entries_from_update
        self.assertEqual(parse_entries_from_update("", session_id="s", source_member="m"), [])
        self.assertEqual(parse_entries_from_update("   \n  ", session_id="s", source_member="m"), [])

    def test_parse_handles_both_confidence_and_expires_suffixes(self):
        from server.memory.sotb_governance import parse_entries_from_update
        update = "## Active Decisions\n- Ship X. (confidence: 0.7) (expires: 2026-06-30)\n"
        e = parse_entries_from_update(update, session_id="s", source_member="m")[0]
        self.assertEqual(e.confidence, 0.7)
        self.assertEqual(e.expires_at, "2026-06-30T00:00:00+00:00")
        self.assertEqual(e.text, "Ship X.")


class SotbIndexIOTest(unittest.TestCase):
    def test_write_then_read_roundtrips(self):
        from server.memory.sotb_governance import (
            SotbEntry, read_sotb_index, write_sotb_index,
        )
        with tempfile.TemporaryDirectory() as td:
            idx_path = Path(td) / "sotb_index.jsonl"
            md_path = Path(td) / "sotb.md"
            md_path.write_text("# SOTB\n", encoding="utf-8")  # empty-ish md
            entries = [
                SotbEntry(entry_id="aaa111bbb222", section="Active Decisions",
                          text="ship", created_at="2026-05-17T00:00:00+00:00",
                          updated_at="2026-05-17T00:00:00+00:00", confidence=0.8,
                          expires_at=None, provenance={"session_id": "s", "source_member": "m"}),
            ]
            write_sotb_index(entries, path=idx_path)
            read_back = read_sotb_index(md_path=md_path, index_path=idx_path)
            self.assertEqual(len(read_back), 1)
            self.assertEqual(read_back[0].entry_id, "aaa111bbb222")
            self.assertEqual(read_back[0].text, "ship")
            self.assertEqual(read_back[0].confidence, 0.8)

    def test_read_with_missing_sidecar_bootstraps_from_markdown(self):
        """First-time read on a real sotb.md with no sidecar creates one."""
        from server.memory.sotb_governance import read_sotb_index
        with tempfile.TemporaryDirectory() as td:
            md_path = Path(td) / "sotb.md"
            idx_path = Path(td) / "sotb_index.jsonl"
            md_path.write_text(
                "# State of the Board\n"
                "## Active Decisions\n"
                "- ship MVP friday.\n"
                "## Risk Register\n"
                "- supplier risk.\n",
                encoding="utf-8",
            )
            entries = read_sotb_index(md_path=md_path, index_path=idx_path)
            self.assertTrue(idx_path.exists())
            sections = sorted(e.section for e in entries)
            self.assertEqual(sections, ["Active Decisions", "Risk Register"])
            texts = sorted(e.text for e in entries)
            self.assertEqual(texts, ["ship MVP friday.", "supplier risk."])
            for e in entries:
                self.assertEqual(e.provenance["source_member"], "manual")
                self.assertEqual(e.provenance["session_id"], "bootstrap")
                self.assertEqual(e.confidence, 0.5)

    def test_read_with_empty_markdown_bootstraps_to_empty_index(self):
        """sotb.md exists but has no entries — index is empty, no crash."""
        from server.memory.sotb_governance import read_sotb_index
        with tempfile.TemporaryDirectory() as td:
            md_path = Path(td) / "sotb.md"
            idx_path = Path(td) / "sotb_index.jsonl"
            md_path.write_text(
                "# State of the Board\n"
                "## Active Decisions\n"
                "[No decisions yet.]\n",  # placeholder, no `- ` bullet
                encoding="utf-8",
            )
            entries = read_sotb_index(md_path=md_path, index_path=idx_path)
            self.assertEqual(entries, [])

    def test_read_reconciles_drift_markdown_edit_creates_new_sidecar_row(self):
        """§8.6: hand-edit to sotb.md → next read creates a sidecar row for the
        new entry with provenance.source_member='manual'."""
        from server.memory.sotb_governance import (
            SotbEntry, read_sotb_index, write_sotb_index,
        )
        with tempfile.TemporaryDirectory() as td:
            md_path = Path(td) / "sotb.md"
            idx_path = Path(td) / "sotb_index.jsonl"

            # Sidecar knows about "X" only.
            write_sotb_index([SotbEntry(
                entry_id=SotbEntry.compute_entry_id("Active Decisions", "X"),
                section="Active Decisions", text="X",
                created_at="2026-05-17T00:00:00+00:00",
                updated_at="2026-05-17T00:00:00+00:00", confidence=0.7,
                expires_at=None, provenance={"session_id": "s1", "source_member": "chair"},
            )], path=idx_path)

            # Markdown has X AND a hand-added Y.
            md_path.write_text(
                "## Active Decisions\n- X\n- Y\n", encoding="utf-8",
            )
            entries = read_sotb_index(md_path=md_path, index_path=idx_path)
            texts = sorted(e.text for e in entries)
            self.assertEqual(texts, ["X", "Y"])
            y_entry = next(e for e in entries if e.text == "Y")
            self.assertEqual(y_entry.provenance["source_member"], "manual")
            x_entry = next(e for e in entries if e.text == "X")
            self.assertEqual(x_entry.confidence, 0.7)  # sidecar metadata preserved

    def test_read_reconciles_drift_markdown_deletion_drops_sidecar_row(self):
        """§8.6 corollary: hand-delete from sotb.md → next read drops the
        orphaned sidecar row (markdown is truth)."""
        from server.memory.sotb_governance import (
            SotbEntry, read_sotb_index, write_sotb_index,
        )
        with tempfile.TemporaryDirectory() as td:
            md_path = Path(td) / "sotb.md"
            idx_path = Path(td) / "sotb_index.jsonl"
            write_sotb_index([
                SotbEntry(entry_id=SotbEntry.compute_entry_id("Active Decisions", "X"),
                          section="Active Decisions", text="X",
                          created_at="t", updated_at="t", confidence=0.5,
                          expires_at=None, provenance={}),
                SotbEntry(entry_id=SotbEntry.compute_entry_id("Active Decisions", "Y"),
                          section="Active Decisions", text="Y",
                          created_at="t", updated_at="t", confidence=0.5,
                          expires_at=None, provenance={}),
            ], path=idx_path)
            # Markdown only has X now.
            md_path.write_text("## Active Decisions\n- X\n", encoding="utf-8")
            entries = read_sotb_index(md_path=md_path, index_path=idx_path)
            self.assertEqual([e.text for e in entries], ["X"])

    def test_write_is_atomic_via_tmp_rename(self):
        """The writer should write to *.tmp and rename, not write in place.
        Approximated by checking the file content is valid JSON-per-line
        after write."""
        from server.memory.sotb_governance import SotbEntry, write_sotb_index
        with tempfile.TemporaryDirectory() as td:
            idx_path = Path(td) / "sotb_index.jsonl"
            entries = [SotbEntry(
                entry_id="x" * 12, section="Active Decisions", text="t",
                created_at="t", updated_at="t", confidence=0.5,
                expires_at=None, provenance={},
            )]
            write_sotb_index(entries, path=idx_path)
            # Each line is a valid JSON object.
            for line in idx_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    json.loads(line)
            # No leftover tmp file.
            self.assertFalse((idx_path.parent / (idx_path.name + ".tmp")).exists())


from datetime import datetime, timedelta, timezone


class SotbHealthTest(unittest.TestCase):
    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _past_iso(self, days_ago: int) -> str:
        return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()

    def _future_iso(self, days_ahead: int) -> str:
        return (datetime.now(timezone.utc) + timedelta(days=days_ahead)).isoformat()

    def test_health_empty_when_all_entries_fresh(self):
        from server.memory.sotb_governance import SotbEntry, compute_freshness
        entries = [SotbEntry(
            entry_id="a" * 12, section="Active Decisions", text="X",
            created_at=self._now_iso(), updated_at=self._now_iso(),
            confidence=0.9, expires_at=self._future_iso(30), provenance={},
        )]
        md = "## Active Decisions\n- X\n"
        new_md, health = compute_freshness(md=md, entries=entries, stale_days=90)
        self.assertEqual(health.expired, [])
        self.assertEqual(health.low_confidence, [])
        self.assertEqual(health.stale, [])
        self.assertEqual(new_md, md)

    def test_expired_entry_is_dropped_from_md_and_recorded(self):
        from server.memory.sotb_governance import SotbEntry, compute_freshness
        entries = [SotbEntry(
            entry_id="b" * 12, section="Active Decisions", text="OLD",
            created_at=self._past_iso(400), updated_at=self._past_iso(400),
            confidence=0.9, expires_at=self._past_iso(1), provenance={},
        )]
        md = "## Active Decisions\n- OLD\n- KEEP\n"
        new_md, health = compute_freshness(md=md, entries=entries, stale_days=90)
        self.assertEqual(len(health.expired), 1)
        self.assertEqual(health.expired[0].text, "OLD")
        self.assertNotIn("- OLD", new_md)
        self.assertIn("- KEEP", new_md)

    def test_low_confidence_entry_is_flagged_not_dropped(self):
        from server.memory.sotb_governance import SotbEntry, compute_freshness
        entries = [SotbEntry(
            entry_id="c" * 12, section="Active Decisions", text="MEH",
            created_at=self._now_iso(), updated_at=self._now_iso(),
            confidence=0.3, expires_at=None, provenance={},
        )]
        md = "## Active Decisions\n- MEH\n"
        new_md, health = compute_freshness(md=md, entries=entries, stale_days=90)
        self.assertEqual(len(health.low_confidence), 1)
        self.assertEqual(health.low_confidence[0].text, "MEH")
        self.assertIn("- MEH", new_md)  # NOT dropped

    def test_stale_warning_on_risk_register_after_threshold(self):
        from server.memory.sotb_governance import SotbEntry, compute_freshness
        entries = [SotbEntry(
            entry_id="d" * 12, section="Risk Register", text="STALE_RISK",
            created_at=self._past_iso(120), updated_at=self._past_iso(120),
            confidence=0.8, expires_at=self._future_iso(60), provenance={},
        )]
        md = "## Risk Register\n- STALE_RISK\n"
        new_md, health = compute_freshness(md=md, entries=entries, stale_days=90)
        self.assertEqual(len(health.stale), 1)
        self.assertEqual(health.stale[0].text, "STALE_RISK")
        self.assertIn("- STALE_RISK", new_md)  # NOT dropped, just flagged

    def test_stale_warning_only_for_risk_and_open_sections(self):
        """Active Decisions / Established Positions are not staleness-flagged."""
        from server.memory.sotb_governance import SotbEntry, compute_freshness
        entries = [SotbEntry(
            entry_id="e" * 12, section="Active Decisions", text="OLD_DEC",
            created_at=self._past_iso(200), updated_at=self._past_iso(200),
            confidence=0.8, expires_at=None, provenance={},
        )]
        md = "## Active Decisions\n- OLD_DEC\n"
        _, health = compute_freshness(md=md, entries=entries, stale_days=90)
        self.assertEqual(health.stale, [])

    def test_health_to_dict_serializes_lists_of_dicts(self):
        from server.memory.sotb_governance import SotbEntry, SotbHealth
        h = SotbHealth(
            expired=[SotbEntry(entry_id="x" * 12, section="Active Decisions",
                               text="t", created_at="t", updated_at="t",
                               confidence=0.5, expires_at=None, provenance={})],
            low_confidence=[], stale=[], query_conflicts=[], conflicts_logged=[],
        )
        d = h.to_dict()
        self.assertEqual(len(d["expired"]), 1)
        self.assertEqual(d["expired"][0]["entry_id"], "x" * 12)
        self.assertEqual(d["low_confidence"], [])
        self.assertEqual(d["warnings_count"], 1)

    def test_warnings_count_sums_all_four_lists(self):
        from server.memory.sotb_governance import SotbEntry, SotbHealth
        def _e(t):
            return SotbEntry(entry_id=SotbEntry.compute_entry_id("Active Decisions", t),
                              section="Active Decisions", text=t,
                              created_at="t", updated_at="t", confidence=0.5,
                              expires_at=None, provenance={})
        h = SotbHealth(
            expired=[_e("a")],
            low_confidence=[_e("b"), _e("c")],
            stale=[_e("d")],
            query_conflicts=[{"note": "x"}, {"note": "y"}],
            conflicts_logged=[{"note": "z"}],
        )
        self.assertEqual(h.to_dict()["warnings_count"], 1 + 2 + 1 + 2 + 1)


import asyncio


def _llm_resp(content: str):
    """Build a minimal LLMResponse-like object the judge can consume."""
    from server.board.llm import LLMResponse
    return LLMResponse(
        content=content, model="qwen/qwen3.6-max-preview",
        input_tokens=1, output_tokens=1, latency_seconds=0.1,
        finish_reason="stop", tool_calls=[],
    )


class DetectQueryConflictsTest(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_judge_says_contradicts_returns_one_conflict_entry(self):
        from server.memory.sotb_governance import (
            SotbEntry, _detect_query_conflicts,
        )
        entries = [SotbEntry(
            entry_id="a" * 12, section="Active Decisions",
            text="We decided to sunset feature X.",
            created_at="t", updated_at="t", confidence=0.9,
            expires_at=None, provenance={},
        )]
        judge_resp = _llm_resp(
            'JSON:\n{"conflicts": [{"entry_id": "aaaaaaaaaaaa", '
            '"rationale": "query proposes building X; SOTB says X is sunset."}]}'
        )
        with patch(
            "server.memory.sotb_governance.query_llm",
            new=AsyncMock(return_value=judge_resp),
        ):
            conflicts = self._run(_detect_query_conflicts(
                query="should we invest more in feature X?",
                entries=entries,
                model="qwen/qwen3.6-max-preview",
            ))
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["entry_id"], "aaaaaaaaaaaa")
        self.assertIn("X is sunset", conflicts[0]["rationale"])

    def test_judge_says_compatible_returns_empty_list(self):
        from server.memory.sotb_governance import (
            SotbEntry, _detect_query_conflicts,
        )
        entries = [SotbEntry(
            entry_id="b" * 12, section="Active Decisions",
            text="Ship MVP friday.", created_at="t", updated_at="t",
            confidence=0.9, expires_at=None, provenance={},
        )]
        judge_resp = _llm_resp('JSON:\n{"conflicts": []}')
        with patch(
            "server.memory.sotb_governance.query_llm",
            new=AsyncMock(return_value=judge_resp),
        ):
            conflicts = self._run(_detect_query_conflicts(
                query="what marketing channel should we test next?",
                entries=entries,
                model="qwen/qwen3.6-max-preview",
            ))
        self.assertEqual(conflicts, [])

    def test_judge_returns_empty_on_malformed_json_no_crash(self):
        """Defensive: judge returned freeform text without JSON -> []."""
        from server.memory.sotb_governance import (
            SotbEntry, _detect_query_conflicts,
        )
        entries = [SotbEntry(entry_id="c" * 12, section="Active Decisions",
                             text="X", created_at="t", updated_at="t",
                             confidence=0.5, expires_at=None, provenance={})]
        with patch(
            "server.memory.sotb_governance.query_llm",
            new=AsyncMock(return_value=_llm_resp("freeform with no json")),
        ):
            conflicts = self._run(_detect_query_conflicts(
                query="q", entries=entries, model="m",
            ))
        self.assertEqual(conflicts, [])

    def test_judge_returns_empty_on_provider_error(self):
        """Provider error -> log + return [] (never raise into orchestrator)."""
        from server.memory.sotb_governance import (
            SotbEntry, _detect_query_conflicts,
        )
        entries = [SotbEntry(entry_id="d" * 12, section="Active Decisions",
                             text="X", created_at="t", updated_at="t",
                             confidence=0.5, expires_at=None, provenance={})]
        with patch(
            "server.memory.sotb_governance.query_llm",
            new=AsyncMock(side_effect=RuntimeError("provider down")),
        ):
            conflicts = self._run(_detect_query_conflicts(
                query="q", entries=entries, model="m",
            ))
        self.assertEqual(conflicts, [])

    def test_judge_skipped_when_index_empty(self):
        """No entries -> no LLM call at all (return [] without invoking the mock)."""
        from server.memory.sotb_governance import _detect_query_conflicts
        mock = AsyncMock()
        with patch("server.memory.sotb_governance.query_llm", new=mock):
            conflicts = self._run(_detect_query_conflicts(
                query="q", entries=[], model="m",
            ))
        self.assertEqual(conflicts, [])
        mock.assert_not_awaited()


class ReadSotbGovernedTest(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_returns_md_and_empty_health_for_empty_index(self):
        from server.memory.sotb_governance import read_sotb_governed
        with tempfile.TemporaryDirectory() as td:
            md_path = Path(td) / "sotb.md"
            idx_path = Path(td) / "sotb_index.jsonl"
            md_path.write_text("# SOTB\n## Active Decisions\n[No decisions yet.]\n",
                               encoding="utf-8")
            md, health = self._run(read_sotb_governed(
                query="q", verify=True, md_path=md_path, index_path=idx_path,
            ))
            self.assertIn("SOTB", md)
            self.assertEqual(health.warnings_count if hasattr(health, "warnings_count")
                             else health.to_dict()["warnings_count"], 0)

    def test_judge_not_called_when_verify_false(self):
        from server.memory.sotb_governance import read_sotb_governed
        with tempfile.TemporaryDirectory() as td:
            md_path = Path(td) / "sotb.md"
            idx_path = Path(td) / "sotb_index.jsonl"
            md_path.write_text("## Active Decisions\n- X\n", encoding="utf-8")
            mock = AsyncMock()
            with patch("server.memory.sotb_governance.query_llm", new=mock), \
                 patch("server.memory.sotb_governance.get_config",
                       return_value=_cfg(sotb_judge_enabled=True)):
                self._run(read_sotb_governed(
                    query="q", verify=False, md_path=md_path, index_path=idx_path,
                ))
            mock.assert_not_awaited()

    def test_judge_not_called_when_flag_disabled(self):
        from server.memory.sotb_governance import read_sotb_governed
        with tempfile.TemporaryDirectory() as td:
            md_path = Path(td) / "sotb.md"
            idx_path = Path(td) / "sotb_index.jsonl"
            md_path.write_text("## Active Decisions\n- X\n", encoding="utf-8")
            mock = AsyncMock()
            with patch("server.memory.sotb_governance.query_llm", new=mock), \
                 patch("server.memory.sotb_governance.get_config",
                       return_value=_cfg(sotb_judge_enabled=False)):
                self._run(read_sotb_governed(
                    query="q", verify=True, md_path=md_path, index_path=idx_path,
                ))
            mock.assert_not_awaited()

    def test_judge_called_when_heavy_and_flag_enabled(self):
        from server.memory.sotb_governance import read_sotb_governed
        with tempfile.TemporaryDirectory() as td:
            md_path = Path(td) / "sotb.md"
            idx_path = Path(td) / "sotb_index.jsonl"
            md_path.write_text("## Active Decisions\n- X\n", encoding="utf-8")
            judge_resp = _llm_resp('{"conflicts": []}')
            with patch("server.memory.sotb_governance.query_llm",
                       new=AsyncMock(return_value=judge_resp)) as mock, \
                 patch("server.memory.sotb_governance.get_config",
                       return_value=_cfg(sotb_judge_enabled=True,
                                         sotb_judge_model="qwen/test")):
                _, health = self._run(read_sotb_governed(
                    query="q", verify=True, md_path=md_path, index_path=idx_path,
                ))
            mock.assert_awaited_once()
            self.assertEqual(health.query_conflicts, [])

    def test_expired_entries_dropped_from_returned_md(self):
        """Wires T4's compute_freshness through the governed read path."""
        from server.memory.sotb_governance import (
            SotbEntry, read_sotb_governed, write_sotb_index,
        )
        with tempfile.TemporaryDirectory() as td:
            md_path = Path(td) / "sotb.md"
            idx_path = Path(td) / "sotb_index.jsonl"
            md_path.write_text("## Active Decisions\n- OLD\n- KEEP\n",
                               encoding="utf-8")
            now = datetime.now(timezone.utc)
            past = (now - timedelta(days=1)).isoformat()
            write_sotb_index([
                SotbEntry(entry_id=SotbEntry.compute_entry_id("Active Decisions", "OLD"),
                          section="Active Decisions", text="OLD",
                          created_at="2026-01-01T00:00:00+00:00",
                          updated_at="2026-01-01T00:00:00+00:00",
                          confidence=0.9, expires_at=past, provenance={}),
                SotbEntry(entry_id=SotbEntry.compute_entry_id("Active Decisions", "KEEP"),
                          section="Active Decisions", text="KEEP",
                          created_at="2026-05-01T00:00:00+00:00",
                          updated_at="2026-05-01T00:00:00+00:00",
                          confidence=0.9, expires_at=None, provenance={}),
            ], path=idx_path)
            with patch("server.memory.sotb_governance.get_config",
                       return_value=_cfg(sotb_judge_enabled=False)):
                md, health = self._run(read_sotb_governed(
                    query="q", verify=True, md_path=md_path, index_path=idx_path,
                ))
            self.assertNotIn("- OLD", md)
            self.assertIn("- KEEP", md)
            self.assertEqual(len(health.expired), 1)


def _cfg(**overrides):
    """Build a minimal HarnessConfig-like object for governance tests."""
    from server.harness.config import HarnessConfig
    cfg = HarnessConfig()
    cfg.hardening = {**cfg.hardening, **overrides}
    return cfg


class ApplySotbUpdateGovernedTest(unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def _setup(self, td: str, *, existing_md: str = "", existing_entries: list | None = None):
        from server.memory.sotb_governance import write_sotb_index
        md_path = Path(td) / "sotb.md"
        idx_path = Path(td) / "sotb_index.jsonl"
        md_path.write_text(existing_md, encoding="utf-8")
        if existing_entries:
            write_sotb_index(existing_entries, path=idx_path)
        return md_path, idx_path

    def test_new_entries_appended_to_index(self):
        from server.memory.sotb_governance import (
            apply_sotb_update_governed, read_sotb_index,
        )
        with tempfile.TemporaryDirectory() as td:
            md_path, idx_path = self._setup(td, existing_md="## Active Decisions\n")
            update = "## Active Decisions\n- ship MVP friday.\n"
            with patch("server.memory.sotb_governance.get_config",
                       return_value=_cfg(sotb_judge_enabled=False)):
                health = self._run(apply_sotb_update_governed(
                    update_text=update, session_id="s1", verify=False,
                    source_member="chairperson",
                    md_path=md_path, index_path=idx_path,
                ))
            entries = read_sotb_index(md_path=md_path, index_path=idx_path)
            texts = [e.text for e in entries]
            self.assertIn("ship MVP friday.", texts)
            self.assertEqual(health.conflicts_logged, [])

    def test_judge_says_contradicts_logs_conflict_keeps_both_entries(self):
        """DC2: log-only — both entries persist; no markdown rewrite."""
        from server.memory.sotb_governance import (
            SotbEntry, apply_sotb_update_governed, read_sotb_index,
        )
        with tempfile.TemporaryDirectory() as td:
            existing = SotbEntry(
                entry_id=SotbEntry.compute_entry_id("Active Decisions",
                                                   "sunset feature X"),
                section="Active Decisions", text="sunset feature X",
                created_at="t", updated_at="t", confidence=0.9,
                expires_at=None, provenance={},
            )
            md_path, idx_path = self._setup(
                td,
                existing_md="## Active Decisions\n- sunset feature X\n",
                existing_entries=[existing],
            )
            update = "## Active Decisions\n- invest in feature X next quarter.\n"
            judge_resp = _llm_resp(
                '{"verdict": "CONTRADICTORY", "rationale": '
                '"new says invest; old says sunset."}'
            )
            with patch("server.memory.sotb_governance.query_llm",
                       new=AsyncMock(return_value=judge_resp)), \
                 patch("server.memory.sotb_governance.get_config",
                       return_value=_cfg(sotb_judge_enabled=True,
                                         sotb_judge_model="qwen/test")):
                health = self._run(apply_sotb_update_governed(
                    update_text=update, session_id="s2", verify=True,
                    source_member="chairperson",
                    md_path=md_path, index_path=idx_path,
                ))
            self.assertEqual(len(health.conflicts_logged), 1)
            log = health.conflicts_logged[0]
            self.assertEqual(log["existing_entry_id"], existing.entry_id)
            self.assertIn("invest", log["new_text"])
            self.assertIn("sunset", log["rationale"])
            # Both entries persist — DC2 log-only.
            entries = read_sotb_index(md_path=md_path, index_path=idx_path)
            texts = sorted(e.text for e in entries)
            self.assertEqual(
                texts,
                ["invest in feature X next quarter.", "sunset feature X"],
            )

    def test_judge_says_compatible_no_conflict_logged(self):
        """When the judge says compatible, both entries persist with no log."""
        from server.memory.sotb_governance import (
            SotbEntry, apply_sotb_update_governed,
        )
        with tempfile.TemporaryDirectory() as td:
            existing = SotbEntry(
                entry_id=SotbEntry.compute_entry_id("Active Decisions", "ship MVP"),
                section="Active Decisions", text="ship MVP",
                created_at="t", updated_at="t", confidence=0.9,
                expires_at=None, provenance={},
            )
            md_path, idx_path = self._setup(
                td, existing_md="## Active Decisions\n- ship MVP\n",
                existing_entries=[existing],
            )
            update = "## Active Decisions\n- focus marketing on enterprise.\n"
            judge_resp = _llm_resp('{"verdict": "CONSISTENT", "rationale": "unrelated."}')
            with patch("server.memory.sotb_governance.query_llm",
                       new=AsyncMock(return_value=judge_resp)), \
                 patch("server.memory.sotb_governance.get_config",
                       return_value=_cfg(sotb_judge_enabled=True,
                                         sotb_judge_model="qwen/test")):
                health = self._run(apply_sotb_update_governed(
                    update_text=update, session_id="s3", verify=True,
                    source_member="chairperson",
                    md_path=md_path, index_path=idx_path,
                ))
            self.assertEqual(health.conflicts_logged, [])

    def test_judge_not_called_when_flag_disabled_or_light_tier(self):
        """DC6 gate: judge gated on verify AND flag. New entries added unconditionally."""
        from server.memory.sotb_governance import apply_sotb_update_governed
        with tempfile.TemporaryDirectory() as td:
            md_path, idx_path = self._setup(td, existing_md="## Active Decisions\n")
            update = "## Active Decisions\n- something.\n"
            mock = AsyncMock()
            # Case A: verify=False
            with patch("server.memory.sotb_governance.query_llm", new=mock), \
                 patch("server.memory.sotb_governance.get_config",
                       return_value=_cfg(sotb_judge_enabled=True)):
                self._run(apply_sotb_update_governed(
                    update_text=update, session_id="s", verify=False,
                    source_member="m", md_path=md_path, index_path=idx_path,
                ))
            mock.assert_not_awaited()

            # Case B: verify=True but flag=False
            with patch("server.memory.sotb_governance.query_llm", new=mock), \
                 patch("server.memory.sotb_governance.get_config",
                       return_value=_cfg(sotb_judge_enabled=False)):
                self._run(apply_sotb_update_governed(
                    update_text=update, session_id="s", verify=True,
                    source_member="m", md_path=md_path, index_path=idx_path,
                ))
            mock.assert_not_awaited()

    def test_empty_update_is_noop(self):
        from server.memory.sotb_governance import (
            apply_sotb_update_governed, read_sotb_index,
        )
        with tempfile.TemporaryDirectory() as td:
            md_path, idx_path = self._setup(td, existing_md="## Active Decisions\n")
            with patch("server.memory.sotb_governance.get_config",
                       return_value=_cfg(sotb_judge_enabled=False)):
                health = self._run(apply_sotb_update_governed(
                    update_text="", session_id="s", verify=True,
                    source_member="m", md_path=md_path, index_path=idx_path,
                ))
            self.assertEqual(health.conflicts_logged, [])
            self.assertEqual(read_sotb_index(md_path=md_path, index_path=idx_path), [])

    def test_judge_provider_error_does_not_block_write(self):
        """Defensive: if the judge LLM call fails, the new entry is still
        added (silent log of judge failure; chair sees both entries next read)."""
        from server.memory.sotb_governance import (
            SotbEntry, apply_sotb_update_governed, read_sotb_index,
        )
        with tempfile.TemporaryDirectory() as td:
            existing = SotbEntry(
                entry_id=SotbEntry.compute_entry_id("Active Decisions", "X"),
                section="Active Decisions", text="X",
                created_at="t", updated_at="t", confidence=0.9,
                expires_at=None, provenance={},
            )
            md_path, idx_path = self._setup(
                td, existing_md="## Active Decisions\n- X\n",
                existing_entries=[existing],
            )
            update = "## Active Decisions\n- Y\n"
            with patch("server.memory.sotb_governance.query_llm",
                       new=AsyncMock(side_effect=RuntimeError("provider down"))), \
                 patch("server.memory.sotb_governance.get_config",
                       return_value=_cfg(sotb_judge_enabled=True,
                                         sotb_judge_model="qwen/test")):
                health = self._run(apply_sotb_update_governed(
                    update_text=update, session_id="s", verify=True,
                    source_member="m", md_path=md_path, index_path=idx_path,
                ))
            self.assertEqual(health.conflicts_logged, [])
            entries = read_sotb_index(md_path=md_path, index_path=idx_path)
            self.assertIn("Y", [e.text for e in entries])


if __name__ == "__main__":
    unittest.main()
