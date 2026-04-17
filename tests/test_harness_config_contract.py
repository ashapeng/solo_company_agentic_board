import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from server.board.harness_config import (
    HarnessConfig,
    load_config,
    resolve_stage_max_tokens,
    resolve_verification_threshold,
    save_config,
)


class HarnessConfigContractTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = TemporaryDirectory()
        self.config_path = Path(self.tmpdir.name) / "harness_config.json"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_defaults_match_current_hardcoded_values(self):
        """Non-breaking migration: defaults must equal existing constants."""
        cfg = HarnessConfig()

        self.assertEqual(cfg.stage1_max_tokens, 1200)
        self.assertEqual(cfg.stage2_max_tokens, 800)
        self.assertEqual(cfg.stage3_max_tokens, 4000)
        self.assertEqual(cfg.revision_max_tokens, 2500)
        self.assertEqual(cfg.min_stage1_responses, 3)
        self.assertEqual(cfg.min_stage2_responses, 2)
        self.assertEqual(cfg.verification_threshold, 7.0)
        self.assertEqual(cfg.max_revision_attempts, 1)
        self.assertEqual(cfg.version, 1)
        self.assertEqual(cfg.per_query_type, {})
        self.assertEqual(cfg.complexity_multipliers, {
            "simple": 0.6,
            "moderate": 1.0,
            "complex": 1.5,
        })

    def test_falls_back_to_defaults_when_file_missing(self):
        missing = Path(self.tmpdir.name) / "nonexistent.json"
        cfg = load_config(missing)

        self.assertEqual(cfg.stage1_max_tokens, 1200)
        self.assertEqual(cfg.version, 1)

    def test_loads_from_json_when_file_exists(self):
        self.config_path.write_text(json.dumps({
            "stage1_max_tokens": 1500,
            "verification_threshold": 8.0,
            "version": 3,
        }))

        cfg = load_config(self.config_path)

        self.assertEqual(cfg.stage1_max_tokens, 1500)
        self.assertEqual(cfg.verification_threshold, 8.0)
        self.assertEqual(cfg.version, 3)

    def test_missing_fields_in_json_use_defaults(self):
        self.config_path.write_text(json.dumps({
            "stage1_max_tokens": 1500,
        }))

        cfg = load_config(self.config_path)

        self.assertEqual(cfg.stage1_max_tokens, 1500)
        self.assertEqual(cfg.stage2_max_tokens, 800)  # default
        self.assertEqual(cfg.verification_threshold, 7.0)  # default

    def test_unknown_fields_in_json_are_ignored(self):
        self.config_path.write_text(json.dumps({
            "stage1_max_tokens": 1200,
            "future_field_xyz": True,
        }))

        cfg = load_config(self.config_path)

        self.assertEqual(cfg.stage1_max_tokens, 1200)
        self.assertFalse(hasattr(cfg, "future_field_xyz"))

    def test_round_trip_save_then_load(self):
        cfg = HarnessConfig(stage1_max_tokens=1600, verification_threshold=8.5)
        save_config(cfg, self.config_path)
        loaded = load_config(self.config_path)

        self.assertEqual(loaded.stage1_max_tokens, 1600)
        self.assertEqual(loaded.verification_threshold, 8.5)

    def test_save_increments_version(self):
        cfg = HarnessConfig(version=3)
        save_config(cfg, self.config_path)
        loaded = load_config(self.config_path)

        self.assertEqual(loaded.version, 4)

    def test_save_sets_last_modified(self):
        cfg = HarnessConfig()
        save_config(cfg, self.config_path)
        loaded = load_config(self.config_path)

        self.assertNotEqual(loaded.last_modified, "")
        self.assertIn("T", loaded.last_modified)  # ISO 8601

    def test_resolve_stage_max_tokens_uses_defaults_without_override(self):
        cfg = HarnessConfig()

        self.assertEqual(resolve_stage_max_tokens(1, config=cfg), 1200)
        self.assertEqual(resolve_stage_max_tokens(2, config=cfg), 800)
        self.assertEqual(resolve_stage_max_tokens(3, config=cfg), 4000)

    def test_resolve_stage_max_tokens_prefers_query_complexity_override(self):
        cfg = HarnessConfig(per_query_type={
            "strategic": {
                "stage1_max_tokens": 1000,
                "token_budgets": {
                    "complex": {"stage1_max_tokens": 1800},
                },
            },
        })

        self.assertEqual(
            resolve_stage_max_tokens(
                1,
                query_type="strategic",
                complexity="complex",
                config=cfg,
            ),
            1800,
        )

    def test_resolve_stage_max_tokens_supports_query_type_override(self):
        cfg = HarnessConfig(per_query_type={
            "product": {"stage2_max_tokens": 900},
        })

        self.assertEqual(
            resolve_stage_max_tokens(
                2,
                query_type="product",
                complexity="simple",
                config=cfg,
            ),
            900,
        )

    def test_resolve_verification_threshold_uses_global_default(self):
        cfg = HarnessConfig(verification_threshold=7.5)

        self.assertEqual(resolve_verification_threshold(config=cfg), 7.5)
        self.assertEqual(
            resolve_verification_threshold(query_type="strategic", config=cfg),
            7.5,
        )

    def test_resolve_verification_threshold_prefers_query_type_override(self):
        cfg = HarnessConfig(
            verification_threshold=7.0,
            per_query_type={
                "strategic": {"verification_threshold": 8.5},
            },
        )

        self.assertEqual(
            resolve_verification_threshold(query_type="strategic", config=cfg),
            8.5,
        )


if __name__ == "__main__":
    unittest.main()
