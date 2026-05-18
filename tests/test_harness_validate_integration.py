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


def test_http_harness_validate_default_returns_report(tmp_path, monkeypatch):
    """POST /harness/validate with empty body returns the active-config report."""
    from fastapi.testclient import TestClient
    from server.api.app import app

    # Set up harness config in tmp_path but don't chdir
    monkeypatch.setenv("AGENTIC_BOARD_ALLOW_REMOTE", "1")
    client = TestClient(app)
    response = client.post("/harness/validate", json={})
    assert response.status_code == 200
    payload = response.json()
    assert "readiness" in payload
    assert payload["readiness"] in {"ready", "warning", "blocked"}


def test_http_harness_validate_bad_candidate_returns_blocked(tmp_path, monkeypatch):
    """POST /harness/validate with a broken candidate body returns blocked."""
    from fastapi.testclient import TestClient
    from server.api.app import app

    # Set up harness config in tmp_path but don't chdir
    monkeypatch.setenv("AGENTIC_BOARD_ALLOW_REMOTE", "1")
    client = TestClient(app)
    response = client.post(
        "/harness/validate",
        json={"candidate": {"stage1_max_tokens": -1}},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["readiness"] == "blocked"
    codes = [issue["code"] for issue in payload["errors"]]
    assert "schema.stage_tokens_non_positive" in codes


def test_run_harness_review_validates_proposed_not_live(tmp_path, monkeypatch):
    """Spec §4.3: validation reflects the merged proposed snapshot.

    A snapshot containing a bad model_preferences change should be flagged
    by the validation field in the review JSON, even though the live config
    is clean.
    """
    monkeypatch.chdir(tmp_path)
    from server.harness.model_assignment import ModelAssignmentTuningReport, ModelPreferenceChange

    # Mock tune_model_assignments to inject a bogus model change.
    bogus_change = ModelPreferenceChange(
        query_type="strategic",
        member_id="strategist",
        previous_model="deepseek/deepseek-v4-pro",
        new_model="fakeprovider/x",
        previous_score=5.0,
        new_score=7.0,
        sample_count=5,
        runner_up_model=None,
        runner_up_score=None,
    )
    bogus_report = ModelAssignmentTuningReport(
        examined_assignments=1,
        eligible_assignments=1,
        changes=[bogus_change],
        saved=False,
        dry_run=True,
        config_version=1,
    )

    with patch(
        "server.harness.reviews.tune_model_assignments",
        return_value=bogus_report,
    ):
        review = run_harness_review(dry_run=True)

    assert review["validation"]["readiness"] == "blocked"
    codes = [issue["code"] for issue in review["validation"]["errors"]]
    assert "xref.model_unknown" in codes
