"""Per-category checkers, run aggregation, and run-vs-run diffs.

Each category has one pass condition (see spec §4.3). At P0 baseline,
post-P1/P2 signals are absent and many prompts will fail by design —
that gap is exactly what subsequent phases will close.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from evals.corpus import EvalPrompt
from evals.ledger import get_signals_for_run
from evals.signals import ObservedSignals


@dataclass
class CategoryStats:
    category: str
    total: int
    passed: int
    pass_rate: float
    avg_latency_ms: float
    avg_cost_usd: float


@dataclass
class RunDiff:
    baseline_run_id: str
    new_run_id: str
    per_category: dict[str, dict[str, float]] = field(default_factory=dict)


# ── per-category checkers ────────────────────────────────────────────────

def _check_hallucination(prompt: EvalPrompt, signals: ObservedSignals) -> bool:
    if signals.verifier_passed is None:
        return False
    if signals.verifier_passed:
        return False
    needles = [s.lower() for s in prompt.expected_outcome.get("deficiency_contains", [])]
    if not needles:
        return True  # any verifier failure counts
    haystack = " ".join(signals.verifier_deficiencies).lower()
    # post-P1: also check blinded verifier rationales
    for entry in signals.blinded_verifier_per_claim:
        haystack += " " + str(entry.get("rationale", "")).lower()
    return any(needle in haystack for needle in needles)


def _check_cross_member_conflict(prompt: EvalPrompt, signals: ObservedSignals) -> bool:
    if not prompt.expected_outcome.get("contradiction_surfaced"):
        return signals.contradictions_surfaced == 0
    return signals.contradictions_surfaced >= 1


def _check_ambiguous_query(prompt: EvalPrompt, signals: ObservedSignals) -> bool:
    return bool(prompt.expected_outcome.get("clarification_required")) == signals.clarification_required


def _check_source_quality_trap(prompt: EvalPrompt, signals: ObservedSignals) -> bool:
    needle = (prompt.expected_outcome.get("claim_substring") or "").lower()
    if not needle:
        return False  # corpus must specify which claim is the trap
    relevant = [
        v for v in signals.validate_claim_verdicts
        if needle in str(v.get("claim", "")).lower()
    ]
    if not relevant:
        # Trap not exercised — the member did not call validate_claim on it.
        return False
    # Pass when at least one matching verdict is NOT SUPPORTED.
    return any(v.get("verdict") != "SUPPORTED" for v in relevant)


def _check_sycophantic_verifier(prompt: EvalPrompt, signals: ObservedSignals) -> bool:
    expected_passed = prompt.expected_outcome.get("verifier_passed")
    if signals.verifier_passed is None:
        return False
    return signals.verifier_passed == bool(expected_passed)


def _check_clean_baseline(prompt: EvalPrompt, signals: ObservedSignals) -> bool:
    if signals.verifier_passed is None:
        # Stage 4 didn't run — can't confirm "passes cleanly"
        return False
    if not signals.verifier_passed:
        return False
    if signals.contradictions_surfaced != 0:
        return False
    return True


_CHECKERS = {
    "hallucination_planted": _check_hallucination,
    "cross_member_conflict": _check_cross_member_conflict,
    "ambiguous_query": _check_ambiguous_query,
    "source_quality_trap": _check_source_quality_trap,
    "sycophantic_verifier": _check_sycophantic_verifier,
    "clean_baseline": _check_clean_baseline,
}


def check_signal_for_prompt(prompt: EvalPrompt, signals: ObservedSignals) -> bool:
    checker = _CHECKERS.get(prompt.category)
    if checker is None:
        raise ValueError(f"no checker registered for category '{prompt.category}'")
    return checker(prompt, signals)


# ── aggregator + diff ────────────────────────────────────────────────────

def aggregate_run(run_id: str, *, db_path: Path | None = None) -> dict[str, CategoryStats]:
    """Group signal rows by category and compute pass rate, mean latency, mean cost."""
    rows = get_signals_for_run(run_id, db_path=db_path)
    by_category: dict[str, list[dict]] = {}
    for row in rows:
        by_category.setdefault(row["category"], []).append(row)

    stats: dict[str, CategoryStats] = {}
    for category, group in by_category.items():
        total = len(group)
        passed = sum(1 for r in group if r["passed"] == 1)
        avg_latency = sum((r["latency_ms"] or 0) for r in group) / total if total else 0.0
        avg_cost = sum((r["cost_usd"] or 0.0) for r in group) / total if total else 0.0
        stats[category] = CategoryStats(
            category=category,
            total=total,
            passed=passed,
            pass_rate=passed / total if total else 0.0,
            avg_latency_ms=avg_latency,
            avg_cost_usd=avg_cost,
        )
    return stats


def diff_runs(
    baseline_run_id: str, new_run_id: str, *, db_path: Path | None = None
) -> RunDiff:
    baseline = aggregate_run(baseline_run_id, db_path=db_path)
    new = aggregate_run(new_run_id, db_path=db_path)
    categories = set(baseline) | set(new)
    diff = RunDiff(baseline_run_id=baseline_run_id, new_run_id=new_run_id)
    for category in categories:
        b = baseline.get(category)
        n = new.get(category)
        b_rate = b.pass_rate if b else 0.0
        n_rate = n.pass_rate if n else 0.0
        diff.per_category[category] = {
            "baseline_pass_rate": b_rate,
            "new_pass_rate": n_rate,
            "delta_pp": (n_rate - b_rate) * 100,
            "baseline_total": b.total if b else 0,
            "new_total": n.total if n else 0,
        }
    return diff
