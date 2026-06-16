"""Tests for counterfactual baseline cost + savings reporting (Plan 4a/4b)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from server.board.config import get_chairman_model
from server.board.metrics import CallMetrics, SessionMetrics

# A free / zero-rate model present in COST_RATES — cheaper than the flagship.
CHEAP_MODEL = "gemini/gemini-2.5-flash"


def _cheap_metrics() -> SessionMetrics:
    m = SessionMetrics()
    m.record(CallMetrics("strategist", 1, CHEAP_MODEL, 1000, 500, 1.0))
    m.record(CallMetrics("product", 1, CHEAP_MODEL, 2000, 800, 1.5))
    return m


# ── savings math ─────────────────────────────────────────────────────────

def test_savings_cheap_vs_flagship_baseline():
    m = _cheap_metrics()
    baseline_model = get_chairman_model()
    s = m.savings(baseline_model)

    assert s["baseline_cost_usd"] >= s["actual_cost_usd"]
    assert s["cost_saved_usd"] >= 0
    # Cheap model is free, flagship is paid → strictly positive savings.
    assert s["baseline_cost_usd"] > 0
    assert s["cost_saved_usd"] > 0
    assert 0 < s["saved_pct"] <= 100


def test_baseline_cost_estimate_matches_per_call_sum():
    from server.board.metrics import _estimate_cost

    m = _cheap_metrics()
    baseline_model = get_chairman_model()
    expected = sum(
        _estimate_cost(baseline_model, c.input_tokens, c.output_tokens)
        for c in m.calls
    )
    assert m.baseline_cost_estimate(baseline_model) == expected


def test_savings_zero_when_all_calls_use_chairman_model():
    chairman = get_chairman_model()
    m = SessionMetrics()
    m.record(CallMetrics("chairperson", 3, chairman, 1000, 500, 1.0))
    m.record(CallMetrics("chairperson", 3, chairman, 2000, 800, 1.2))

    s = m.savings(chairman)
    assert s["cost_saved_usd"] == 0
    assert s["baseline_cost_usd"] == s["actual_cost_usd"]


def test_savings_pct_zero_when_baseline_free():
    """If the baseline model itself is free, baseline==0 → saved_pct 0.0."""
    m = _cheap_metrics()
    s = m.savings(CHEAP_MODEL)
    assert s["baseline_cost_usd"] == 0.0
    assert s["saved_pct"] == 0.0


# ── summary() exposes baseline keys ──────────────────────────────────────

def test_summary_includes_baseline_keys():
    m = _cheap_metrics()
    summary = m.summary()
    assert "baseline_cost_estimate_usd" in summary
    assert "cost_saved_usd" in summary
    # Existing keys must remain.
    for key in (
        "total_calls",
        "total_tokens",
        "total_cost_estimate_usd",
        "calls",
        "by_stage",
        "by_provider",
    ):
        assert key in summary
    assert summary["baseline_cost_estimate_usd"] >= summary["total_cost_estimate_usd"]
    assert summary["cost_saved_usd"] >= 0


# ── ledger persistence ───────────────────────────────────────────────────

def _make_session_stub(session_id: str, metrics: SessionMetrics):
    return SimpleNamespace(
        session_id=session_id,
        classification={"query_type": "strategy", "complexity": "standard"},
        verification={},
        memory={},
        metrics=metrics,
        stage1_responses=[],
        stage2_responses=[],
        delegation_plan={},
        clarification={},
        skills={"used": {}, "missing": {}},
    )


def test_ledger_persists_baseline_and_saved():
    from server.harness.ledger import cumulative_savings, query_outcomes, record_session

    with TemporaryDirectory() as tmp:
        db = Path(tmp) / "ledger.db"
        m = _cheap_metrics()
        record_session(_make_session_stub("s-baseline-1", m), config_version=1, db_path=db)

        rows = query_outcomes(db_path=db)
        assert len(rows) == 1
        row = rows[0]
        assert row["baseline_cost_usd"] is not None
        assert row["cost_saved_usd"] is not None
        assert row["baseline_cost_usd"] > 0
        assert row["cost_saved_usd"] > 0
        # actual stored cost should be (essentially) zero for the free model.
        assert row["baseline_cost_usd"] >= row["total_cost_usd"]

        cum = cumulative_savings(db_path=db)
        assert cum["total_baseline_usd"] == round(row["baseline_cost_usd"], 6)
        assert cum["total_saved_usd"] == round(row["cost_saved_usd"], 6)
        assert cum["total_actual_usd"] == round(row["total_cost_usd"], 6)
        assert cum["saved_pct"] > 0


def test_cumulative_savings_sums_multiple_sessions():
    from server.harness.ledger import cumulative_savings, query_outcomes, record_session

    with TemporaryDirectory() as tmp:
        db = Path(tmp) / "ledger.db"
        record_session(_make_session_stub("s-1", _cheap_metrics()), config_version=1, db_path=db)
        record_session(_make_session_stub("s-2", _cheap_metrics()), config_version=1, db_path=db)

        rows = query_outcomes(db_path=db)
        total_baseline = round(sum(r["baseline_cost_usd"] for r in rows), 6)
        total_saved = round(sum(r["cost_saved_usd"] for r in rows), 6)

        cum = cumulative_savings(db_path=db)
        assert cum["total_baseline_usd"] == total_baseline
        assert cum["total_saved_usd"] == total_saved


def test_cumulative_savings_empty_db():
    from server.harness.ledger import cumulative_savings, init_db

    with TemporaryDirectory() as tmp:
        db = Path(tmp) / "ledger.db"
        init_db(db)
        cum = cumulative_savings(db_path=db)
        assert cum["total_baseline_usd"] == 0
        assert cum["total_saved_usd"] == 0
        assert cum["saved_pct"] == 0.0


def test_ensure_columns_adds_baseline_columns():
    from server.harness.ledger import init_db

    with TemporaryDirectory() as tmp:
        db = Path(tmp) / "ledger.db"
        init_db(db)
        conn = sqlite3.connect(str(db))
        try:
            cols = {row[1] for row in conn.execute("PRAGMA table_info(session_outcomes)")}
        finally:
            conn.close()
        assert "baseline_cost_usd" in cols
        assert "cost_saved_usd" in cols
