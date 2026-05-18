"""Integration tests: validator wired into reviews, CLI, and HTTP."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from server.harness.config import HarnessConfig
from server.harness.reviews import (
    HarnessReviewError,
    apply_harness_review,
    approve_harness_review,
    run_harness_review,
)


def test_run_harness_review_attaches_validation_field(tmp_path, monkeypatch):
    """run_harness_review must produce a top-level 'validation' field."""
    monkeypatch.chdir(tmp_path)
    review = run_harness_review(dry_run=True)
    assert "validation" in review
    validation = review["validation"]
    assert isinstance(validation, dict)
    assert "readiness" in validation
    assert validation["readiness"] in {"ready", "warning", "blocked"}


def test_run_harness_review_swallows_validator_crash(tmp_path, monkeypatch):
    """Spec §4.4: validator crash must not abort the review."""
    monkeypatch.chdir(tmp_path)

    def boom(_candidate):
        raise RuntimeError("simulated validator crash")

    with patch("server.harness.reviews.validate_config", side_effect=boom):
        review = run_harness_review(dry_run=True)

    categories = [r["category"] for r in review["recommendations"]]
    assert "validation" in categories
    validation_rec = next(r for r in review["recommendations"] if r["category"] == "validation")
    assert "validation check failed" in validation_rec["summary"]
    assert "simulated validator crash" in validation_rec["details"]["error"]
