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
