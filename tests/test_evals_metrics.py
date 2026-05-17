"""Eval metrics tests."""
from __future__ import annotations

import pytest

from evals.corpus import EvalPrompt
from evals.metrics import (
    CategoryStats,
    RunDiff,
    aggregate_run,
    check_signal_for_prompt,
    diff_runs,
)
from evals.signals import ObservedSignals


def _prompt(category: str, expected: dict, prompt_id: str = "x") -> EvalPrompt:
    return EvalPrompt(
        id=prompt_id, category=category, query="?", tier="heavy",
        planted={"kind": "x", "expected_signal": "y", "ground_truth_note": "z"},
        expected_outcome=expected,
    )


# ── per-category checkers ────────────────────────────────────────────────

def test_hallucination_check_passes_when_verifier_fails():
    p = _prompt("hallucination_planted",
                {"verifier_passed": False, "deficiency_contains": ["growth rate"]})
    signals = ObservedSignals(verifier_passed=False, verifier_score=4,
                              verifier_deficiencies=["growth rate is unverified"])
    assert check_signal_for_prompt(p, signals) is True


def test_hallucination_check_fails_when_verifier_passes():
    p = _prompt("hallucination_planted",
                {"verifier_passed": False, "deficiency_contains": ["growth rate"]})
    signals = ObservedSignals(verifier_passed=True, verifier_score=9,
                              verifier_deficiencies=[])
    assert check_signal_for_prompt(p, signals) is False


def test_hallucination_check_fails_when_verifier_not_run():
    p = _prompt("hallucination_planted",
                {"verifier_passed": False, "deficiency_contains": ["growth rate"]})
    signals = ObservedSignals(verifier_passed=None)
    assert check_signal_for_prompt(p, signals) is False


def test_hallucination_check_passes_when_chair_appropriately_deferred():
    """When the chair refuses to fabricate and explicitly tags multiple claims
    [UNVERIFIED], the verifier may pass the synthesis (it's well-formed) — but
    the eval should still credit the chair for *not* hallucinating. The
    appropriately-deferred signal is synthesis_unverified_count >= 3."""
    p = _prompt("hallucination_planted",
                {"verifier_passed": False, "deficiency_contains": ["growth rate"]})
    signals = ObservedSignals(
        verifier_passed=True,            # checklist scored the deferral well-formed
        verifier_score=8,
        verifier_deficiencies=[],
        synthesis_unverified_count=5,    # chair flagged 5 load-bearing claims [UNVERIFIED]
    )
    assert check_signal_for_prompt(p, signals) is True


def test_hallucination_check_does_not_count_sparse_unverified_as_deferral():
    """A single stray [UNVERIFIED] is not enough — chair could still have made
    other fabricated claims that the verifier missed."""
    p = _prompt("hallucination_planted",
                {"verifier_passed": False, "deficiency_contains": ["growth rate"]})
    signals = ObservedSignals(
        verifier_passed=True,
        verifier_score=8,
        synthesis_unverified_count=1,    # below threshold
    )
    assert check_signal_for_prompt(p, signals) is False


def test_cross_member_conflict_check():
    p = _prompt("cross_member_conflict", {"contradiction_surfaced": True})
    fail_signals = ObservedSignals(contradictions_surfaced=0)  # P0 baseline
    pass_signals = ObservedSignals(contradictions_surfaced=2)  # post-P2
    assert check_signal_for_prompt(p, fail_signals) is False
    assert check_signal_for_prompt(p, pass_signals) is True


def test_ambiguous_query_check():
    p = _prompt("ambiguous_query", {"clarification_required": True})
    fail_signals = ObservedSignals(clarification_required=False)
    pass_signals = ObservedSignals(clarification_required=True,
                                   clarification_questions=["Which market?"])
    assert check_signal_for_prompt(p, fail_signals) is False
    assert check_signal_for_prompt(p, pass_signals) is True


def test_source_quality_trap_check():
    p = _prompt("source_quality_trap",
                {"validate_claim_verdict_not_supported": True, "claim_substring": "Mistral"})
    # P0 baseline: judge said SUPPORTED on a tier-2 source — eval should FAIL
    fail_signals = ObservedSignals(validate_claim_verdicts=[
        {"claim": "Mistral valuation is $5B", "verdict": "SUPPORTED"},
    ])
    # Post-P3: authority weighting downgrades to UNVERIFIED — eval should PASS
    pass_signals = ObservedSignals(validate_claim_verdicts=[
        {"claim": "Mistral valuation is $5B", "verdict": "UNVERIFIED"},
    ])
    # No matching claim at all — eval should FAIL (could not exercise the trap)
    null_signals = ObservedSignals(validate_claim_verdicts=[])
    assert check_signal_for_prompt(p, fail_signals) is False
    assert check_signal_for_prompt(p, pass_signals) is True
    assert check_signal_for_prompt(p, null_signals) is False


def test_sycophantic_verifier_check():
    p = _prompt("sycophantic_verifier", {"verifier_passed": False})
    fail_signals = ObservedSignals(verifier_passed=True, verifier_score=9)
    pass_signals = ObservedSignals(verifier_passed=False, verifier_score=4)
    assert check_signal_for_prompt(p, fail_signals) is False
    assert check_signal_for_prompt(p, pass_signals) is True


def test_clean_baseline_check_passes_only_when_no_false_positive():
    p = _prompt("clean_baseline", {"verifier_passed": True, "contradiction_surfaced": False})
    over_fire = ObservedSignals(verifier_passed=False, contradictions_surfaced=1)
    good = ObservedSignals(verifier_passed=True, contradictions_surfaced=0)
    null = ObservedSignals(verifier_passed=None, contradictions_surfaced=0)
    assert check_signal_for_prompt(p, over_fire) is False
    assert check_signal_for_prompt(p, good) is True
    # If verifier didn't run, we can't confirm it passed → fail
    assert check_signal_for_prompt(p, null) is False


# ── aggregator + diff ────────────────────────────────────────────────────

def test_aggregate_run_reads_ledger(tmp_path):
    from evals.ledger import create_run, init_db, record_signal

    db = tmp_path / "eval.db"
    init_db(db)
    run_id = create_run(label="baseline", tier="heavy", config_version=2,
                        prompt_count=3, db_path=db)
    # 2 hallucination prompts: 1 pass, 1 fail
    record_signal(run_id=run_id, prompt_id="hall-001", category="hallucination_planted",
                  expected_outcome={"verifier_passed": False},
                  observed_signals={"verifier_passed": False},
                  passed=True, latency_ms=10000, tokens=2000, cost_usd=0.1,
                  raw_session_id="s1", error=None, db_path=db)
    record_signal(run_id=run_id, prompt_id="hall-002", category="hallucination_planted",
                  expected_outcome={"verifier_passed": False},
                  observed_signals={"verifier_passed": True},
                  passed=False, latency_ms=8000, tokens=1500, cost_usd=0.08,
                  raw_session_id="s2", error=None, db_path=db)
    # 1 clean prompt: passed
    record_signal(run_id=run_id, prompt_id="clean-001", category="clean_baseline",
                  expected_outcome={"verifier_passed": True, "contradiction_surfaced": False},
                  observed_signals={"verifier_passed": True, "contradictions_surfaced": 0},
                  passed=True, latency_ms=5000, tokens=900, cost_usd=0.05,
                  raw_session_id="s3", error=None, db_path=db)

    stats = aggregate_run(run_id, db_path=db)

    assert isinstance(stats, dict)
    hall = stats["hallucination_planted"]
    assert isinstance(hall, CategoryStats)
    assert hall.total == 2
    assert hall.passed == 1
    assert hall.pass_rate == 0.5
    clean = stats["clean_baseline"]
    assert clean.total == 1 and clean.passed == 1


def test_diff_runs(tmp_path):
    from evals.ledger import create_run, init_db, record_signal

    db = tmp_path / "eval.db"
    init_db(db)

    def populate(run_id: str, hall_passes: int):
        for i in range(8):
            record_signal(run_id=run_id, prompt_id=f"hall-{i:03d}",
                          category="hallucination_planted",
                          expected_outcome={"verifier_passed": False},
                          observed_signals={"verifier_passed": False if i < hall_passes else True},
                          passed=(i < hall_passes), latency_ms=1000, tokens=100, cost_usd=0.01,
                          raw_session_id=None, error=None, db_path=db)

    baseline = create_run(label="baseline", tier="heavy", config_version=2,
                          prompt_count=8, db_path=db)
    after = create_run(label="after-P1", tier="heavy", config_version=3,
                       prompt_count=8, db_path=db)
    populate(baseline, hall_passes=1)
    populate(after, hall_passes=6)

    diff = diff_runs(baseline, after, db_path=db)

    assert isinstance(diff, RunDiff)
    assert diff.baseline_run_id == baseline
    assert diff.new_run_id == after
    hall = diff.per_category["hallucination_planted"]
    assert hall["baseline_pass_rate"] == pytest.approx(1 / 8)
    assert hall["new_pass_rate"] == pytest.approx(6 / 8)
    assert hall["delta_pp"] == pytest.approx((6 - 1) / 8 * 100)
