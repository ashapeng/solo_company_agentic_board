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


if __name__ == "__main__":
    unittest.main()
