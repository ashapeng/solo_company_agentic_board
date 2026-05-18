"""Unit tests for server.harness.validate."""

from __future__ import annotations

from server.harness.config import HarnessConfig
from server.harness.validate import (
    ValidationIssue,
    ValidationReport,
    validate_config,
)


def test_default_config_is_ready():
    """A freshly constructed HarnessConfig must validate cleanly."""
    report = validate_config(HarnessConfig())
    assert report.ok is True
    assert report.readiness == "ready"
    assert report.errors == []


def test_validation_report_ok_field_mirrors_readiness():
    """ValidationReport.ok must equal (readiness == 'ready')."""
    ready = ValidationReport(ok=True, errors=[], warnings=[], readiness="ready")
    warn = ValidationReport(
        ok=False,
        errors=[],
        warnings=[ValidationIssue(
            code="x", path="y", message="z", severity="warning",
        )],
        readiness="warning",
    )
    blocked = ValidationReport(
        ok=False,
        errors=[ValidationIssue(
            code="x", path="y", message="z", severity="error",
        )],
        warnings=[],
        readiness="blocked",
    )
    assert ready.ok is True
    assert warn.ok is False
    assert blocked.ok is False


def test_validate_config_accepts_dict_input():
    """validate_config must accept a plain-dict input (per spec §4.1 signature)."""
    report = validate_config({})
    # Empty dict → defaults applied → ready
    assert report.readiness in {"ready", "warning"}


def test_schema_rejects_negative_stage_tokens():
    """Negative stage budgets are structurally broken."""
    cfg = HarnessConfig(stage1_max_tokens=-100)
    report = validate_config(cfg)
    assert report.readiness == "blocked"
    codes = [issue.code for issue in report.errors]
    assert "schema.stage_tokens_non_positive" in codes


def test_schema_rejects_min_responses_below_one():
    """min_stage1_responses must be >= 1."""
    cfg = HarnessConfig(min_stage1_responses=0)
    report = validate_config(cfg)
    assert report.readiness == "blocked"
    codes = [issue.code for issue in report.errors]
    assert "schema.min_responses_below_one" in codes


def test_schema_rejects_verification_threshold_out_of_range():
    """verification_threshold ranges to floor/ceiling — error if outside."""
    cfg = HarnessConfig(verification_threshold=0.0)
    report = validate_config(cfg)
    codes = [issue.code for issue in report.errors]
    assert "schema.verification_threshold_out_of_range" in codes


def test_schema_complexity_multipliers_required_keys():
    """complexity_multipliers must contain simple/moderate/complex."""
    cfg = HarnessConfig(complexity_multipliers={"simple": 1.0})
    report = validate_config(cfg)
    codes = [issue.code for issue in report.errors]
    assert "schema.complexity_multipliers_missing_keys" in codes


def test_schema_rejects_bool_max_revision_attempts():
    """max_revision_attempts=True must be rejected even though isinstance(True, int) is True."""
    cfg = HarnessConfig(max_revision_attempts=True)  # type: ignore[arg-type]
    report = validate_config(cfg)
    codes = [issue.code for issue in report.errors]
    assert "schema.max_revision_attempts_negative" in codes


def test_xref_model_pref_matching_known_model_passes():
    """A model preference using a default chairman/council model is allowed."""
    cfg = HarnessConfig()
    cfg.per_query_type = {
        "strategic": {"model_preferences": {"strategist": "deepseek/deepseek-v4-pro"}},
    }
    report = validate_config(cfg)
    codes = [issue.code for issue in report.errors]
    assert "xref.model_unknown" not in codes


def test_xref_model_pref_with_known_prefix_passes():
    """Any model with a known provider prefix is allowed (e.g. qwen/foo)."""
    cfg = HarnessConfig()
    cfg.per_query_type = {
        "strategic": {"model_preferences": {"strategist": "qwen/qwen-mythical"}},
    }
    report = validate_config(cfg)
    codes = [issue.code for issue in report.errors]
    assert "xref.model_unknown" not in codes


def test_xref_model_pref_unknown_prefix_fails():
    """A model with no recognised prefix is rejected."""
    cfg = HarnessConfig()
    cfg.per_query_type = {
        "strategic": {"model_preferences": {"strategist": "fakeprovider/x"}},
    }
    report = validate_config(cfg)
    codes = [issue.code for issue in report.errors]
    assert "xref.model_unknown" in codes


def test_xref_openrouter_colon_prefix_allowed():
    """openrouter:<id> with a colon, not slash, is a valid escape hatch."""
    cfg = HarnessConfig()
    cfg.per_query_type = {
        "strategic": {"model_preferences": {"strategist": "openrouter:anthropic/foo"}},
    }
    report = validate_config(cfg)
    codes = [issue.code for issue in report.errors]
    assert "xref.model_unknown" not in codes
