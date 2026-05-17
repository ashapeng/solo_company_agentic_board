"""End-to-end smoke for evals runner. Opt-in via `pytest -m live`.

This test hits real LLM providers. It loads the clean_baseline category
(2 prompts), runs the runner against the actual board pipeline, and
asserts the eval ledger is populated and a report can be rendered.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from evals import corpus
from evals.ledger import get_run, get_signals_for_run
from evals.reporting import render_report
from evals.runner import run_corpus


@pytest.mark.live
@pytest.mark.asyncio
async def test_clean_baseline_end_to_end(tmp_path):
    prompts = corpus.load_category("clean_baseline")
    assert len(prompts) == 2

    db = tmp_path / "eval.db"
    sessions_dir = tmp_path / "sessions"

    run_id = await run_corpus(
        prompts, tier="heavy", label="smoke",
        config_version=0, db_path=db, sessions_dir=sessions_dir,
    )

    run = get_run(run_id, db_path=db)
    assert run is not None
    assert run["prompt_count"] == 2
    assert run["completed_at"] is not None

    rows = get_signals_for_run(run_id, db_path=db)
    assert len(rows) == 2
    # On clean_baseline, both prompts should produce a session file
    for row in rows:
        if row["raw_session_id"]:
            assert (sessions_dir / f"{row['raw_session_id']}.json").exists()

    report = render_report(run_id, db_path=db)
    assert "smoke" in report
    assert "clean_baseline" in report


@pytest.mark.live
@pytest.mark.asyncio
async def test_hallucination_planted_end_to_end(tmp_path):
    """Live smoke for the P1 atomizer + blinded verifier path.

    Runs hall-001 through the real pipeline and asserts the verification
    output contains the post-P1 `per_claim` field. Verifier verdict is
    non-deterministic so we don't assert pass/fail, only that the blinded
    protocol ran (per_claim is non-empty or fallback used)."""
    prompts = [p for p in corpus.load_category("hallucination_planted") if p.id == "hall-001"]
    assert len(prompts) == 1

    db = tmp_path / "eval.db"
    sessions_dir = tmp_path / "sessions"

    run_id = await run_corpus(
        prompts, tier="heavy", label="smoke-p1",
        config_version=0, db_path=db, sessions_dir=sessions_dir,
    )

    rows = get_signals_for_run(run_id, db_path=db)
    assert len(rows) == 1
    observed = rows[0]["observed_signals_json"]
    import json as _json
    obs = _json.loads(observed)
    # If the blinded path ran (any cited claims existed), per_claim is non-empty.
    # If atomization yielded zero cited claims, checklist fallback ran and
    # per_claim is empty - both are valid post-P1 behaviors.
    assert "blinded_verifier_per_claim" in obs
