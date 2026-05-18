"""Tests for SOTB governance (spec §8) — sidecar, freshness, conflict logging."""
from __future__ import annotations

import json
import unittest
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


if __name__ == "__main__":
    unittest.main()
