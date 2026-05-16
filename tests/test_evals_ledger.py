"""Eval ledger tests."""
from __future__ import annotations

import json

import pytest

from evals.ledger import (
    LedgerError,
    complete_run,
    create_run,
    find_run_by_label,
    get_run,
    get_signals_for_run,
    init_db,
    record_signal,
)


def test_init_db_idempotent(tmp_path):
    db = tmp_path / "eval.db"
    init_db(db)
    init_db(db)  # second call must not error
    assert db.exists()


def test_create_and_complete_run(tmp_path):
    db = tmp_path / "eval.db"
    init_db(db)
    run_id = create_run(
        label="baseline",
        tier="heavy",
        config_version=2,
        prompt_count=25,
        db_path=db,
    )
    assert isinstance(run_id, str) and len(run_id) > 0
    run = get_run(run_id, db_path=db)
    assert run["label"] == "baseline"
    assert run["tier"] == "heavy"
    assert run["prompt_count"] == 25
    assert run["completed_at"] is None

    complete_run(run_id, total_passed=12, total_cost_usd=4.56, db_path=db)
    run = get_run(run_id, db_path=db)
    assert run["total_passed"] == 12
    assert run["total_cost_usd"] == pytest.approx(4.56)
    assert run["completed_at"] is not None


def test_record_signal_roundtrip(tmp_path):
    db = tmp_path / "eval.db"
    init_db(db)
    run_id = create_run(
        label="baseline", tier="heavy", config_version=2, prompt_count=1, db_path=db,
    )
    record_signal(
        run_id=run_id,
        prompt_id="hall-001",
        category="hallucination_planted",
        expected_outcome={"verifier_passed": False, "deficiency_contains": ["growth rate"]},
        observed_signals={"verifier_passed": True, "verifier_score": 8},
        passed=False,
        latency_ms=12500,
        tokens=4200,
        cost_usd=0.18,
        raw_session_id="board_1700000001",
        error=None,
        db_path=db,
    )
    rows = get_signals_for_run(run_id, db_path=db)
    assert len(rows) == 1
    row = rows[0]
    assert row["prompt_id"] == "hall-001"
    assert row["category"] == "hallucination_planted"
    assert json.loads(row["expected_outcome_json"]) == {
        "verifier_passed": False,
        "deficiency_contains": ["growth rate"],
    }
    assert json.loads(row["observed_signals_json"])["verifier_score"] == 8
    assert row["passed"] == 0
    assert row["raw_session_id"] == "board_1700000001"


def test_find_run_by_label(tmp_path):
    db = tmp_path / "eval.db"
    init_db(db)
    rid1 = create_run(label="baseline", tier="heavy", config_version=2, prompt_count=25, db_path=db)
    rid2 = create_run(label="after-P1", tier="heavy", config_version=3, prompt_count=25, db_path=db)
    assert find_run_by_label("baseline", db_path=db) == rid1
    assert find_run_by_label("after-P1", db_path=db) == rid2
    assert find_run_by_label("nonexistent", db_path=db) is None


def test_find_run_by_label_returns_most_recent(tmp_path):
    db = tmp_path / "eval.db"
    init_db(db)
    create_run(label="baseline", tier="heavy", config_version=1, prompt_count=25, db_path=db)
    rid_latest = create_run(label="baseline", tier="heavy", config_version=2, prompt_count=25, db_path=db)
    assert find_run_by_label("baseline", db_path=db) == rid_latest


def test_record_signal_unknown_run_errors(tmp_path):
    db = tmp_path / "eval.db"
    init_db(db)
    with pytest.raises(LedgerError, match="unknown run"):
        record_signal(
            run_id="does-not-exist",
            prompt_id="x", category="hallucination_planted",
            expected_outcome={}, observed_signals={}, passed=False,
            latency_ms=0, tokens=0, cost_usd=0.0, raw_session_id=None, error=None,
            db_path=db,
        )
