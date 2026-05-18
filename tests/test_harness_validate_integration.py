"""Integration tests: validator wired into reviews, CLI, and HTTP."""

from __future__ import annotations

import json
import subprocess
import sys
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


def test_apply_harness_review_refuses_blocked_snapshot(tmp_path, monkeypatch):
    """Spec §4.3: apply must raise HarnessReviewError when blocked."""
    monkeypatch.chdir(tmp_path)

    review = run_harness_review(dry_run=True)
    approved = approve_harness_review(review["id"], approve=True)

    # Inject a snapshot whose model_assignments changes reference a bogus model.
    approved["snapshot"]["model_assignments"] = {
        "changes": [
            {
                "query_type": "strategic",
                "member_id": "strategist",
                "previous_model": "deepseek/deepseek-v4-pro",
                "new_model": "fakeprovider/x",
            }
        ],
    }
    review_path = Path("data/harness_reviews") / f"{approved['id']}.json"
    review_path.write_text(json.dumps(approved, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(HarnessReviewError) as excinfo:
        apply_harness_review(approved["id"])
    assert "validation blocked" in str(excinfo.value)
    assert "xref.model_unknown" in str(excinfo.value)


def test_apply_harness_review_allows_clean_snapshot(tmp_path, monkeypatch):
    """A snapshot that validates as 'ready' or 'warning' must apply."""
    monkeypatch.chdir(tmp_path)

    review = run_harness_review(dry_run=True)
    approved = approve_harness_review(review["id"], approve=True)

    # Default snapshot is clean; apply must succeed.
    result = apply_harness_review(approved["id"])
    assert result["status"] == "applied"


def test_cli_harness_validate_clean_config_exits_zero(tmp_path):
    """uv run python -m server.cli --harness-validate on default config → exit 0."""
    result = subprocess.run(
        [sys.executable, "-m", "server.cli", "--harness-validate"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=30,
    )
    # On a fresh tmpdir (no harness_config.json), defaults apply → ready.
    assert result.returncode == 0
    assert "ready" in result.stdout.lower()


def test_cli_harness_validate_bad_config_exits_nonzero(tmp_path):
    """A blocked config JSON file → exit code non-zero."""
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps({
        "stage1_max_tokens": -1,
    }))
    result = subprocess.run(
        [sys.executable, "-m", "server.cli", "--harness-validate", str(bad_path)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=30,
    )
    assert result.returncode != 0
    combined = (result.stdout + result.stderr).lower()
    assert "blocked" in combined
