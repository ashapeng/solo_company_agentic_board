"""Report rendering tests."""
from __future__ import annotations

from evals.ledger import create_run, init_db, record_signal
from evals.reports import render_report


def _populate(db, run_id: str, category_counts: dict[str, tuple[int, int]]):
    """category -> (total, passes)"""
    for category, (total, passes) in category_counts.items():
        for i in range(total):
            record_signal(
                run_id=run_id, prompt_id=f"{category}-{i:03d}", category=category,
                expected_outcome={"verifier_passed": False},
                observed_signals={"verifier_passed": False if i < passes else True},
                passed=(i < passes), latency_ms=1000, tokens=200, cost_usd=0.05,
                raw_session_id=f"s_{category}_{i}", error=None, db_path=db,
            )


def test_render_report_single_run(tmp_path):
    db = tmp_path / "eval.db"
    init_db(db)
    run_id = create_run(label="baseline", tier="heavy", config_version=2,
                        prompt_count=10, db_path=db)
    _populate(db, run_id, {
        "hallucination_planted": (8, 1),
        "clean_baseline": (2, 2),
    })

    md = render_report(run_id, db_path=db)

    assert "# Eval Run Report" in md
    assert "baseline" in md
    assert "tier: heavy" in md
    assert "hallucination_planted" in md
    assert "clean_baseline" in md
    # 1/8 = 12.5%, 2/2 = 100%
    assert "12.5%" in md or "1/8" in md
    assert "100.0%" in md or "2/2" in md


def test_render_report_with_diff(tmp_path):
    db = tmp_path / "eval.db"
    init_db(db)
    baseline = create_run(label="baseline", tier="heavy", config_version=2,
                          prompt_count=8, db_path=db)
    after = create_run(label="after-P1", tier="heavy", config_version=3,
                       prompt_count=8, db_path=db)
    _populate(db, baseline, {"hallucination_planted": (8, 1)})
    _populate(db, after, {"hallucination_planted": (8, 6)})

    md = render_report(after, diff_against=baseline, db_path=db)

    assert "Diff vs baseline" in md
    assert "hallucination_planted" in md
    # +62.5pp (from 1/8 to 6/8)
    assert "+62.5" in md or "+62.50" in md


def test_render_report_lists_failures(tmp_path):
    db = tmp_path / "eval.db"
    init_db(db)
    run_id = create_run(label="baseline", tier="heavy", config_version=2,
                        prompt_count=2, db_path=db)
    record_signal(
        run_id=run_id, prompt_id="hall-001", category="hallucination_planted",
        expected_outcome={"verifier_passed": False},
        observed_signals={"verifier_passed": True, "verifier_score": 9},
        passed=False, latency_ms=12000, tokens=4000, cost_usd=0.20,
        raw_session_id="board_x", error=None, db_path=db,
    )
    md = render_report(run_id, db_path=db)
    assert "hall-001" in md
    assert "board_x" in md
