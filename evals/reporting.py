"""Render markdown reports from the eval ledger."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from evals.ledger import get_run, get_signals_for_run
from evals.metrics import CategoryStats, aggregate_run, diff_runs


def _fmt_pct(rate: float) -> str:
    return f"{rate * 100:.1f}%"


def _fmt_signed_pp(delta_pp: float) -> str:
    sign = "+" if delta_pp >= 0 else ""
    return f"{sign}{delta_pp:.1f}pp"


def _category_table(stats: dict[str, CategoryStats]) -> str:
    lines = [
        "| Category | Pass rate | Passed | Total | Avg latency (s) | Avg cost ($) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for category in sorted(stats):
        s = stats[category]
        lines.append(
            f"| {category} | {_fmt_pct(s.pass_rate)} | {s.passed} | {s.total} "
            f"| {s.avg_latency_ms / 1000:.1f} | {s.avg_cost_usd:.3f} |"
        )
    return "\n".join(lines)


def _diff_table(diff_per_category: dict[str, dict]) -> str:
    lines = [
        "| Category | Baseline | New | Δ |",
        "|---|---:|---:|---:|",
    ]
    for category in sorted(diff_per_category):
        d = diff_per_category[category]
        lines.append(
            f"| {category} | {_fmt_pct(d['baseline_pass_rate'])} "
            f"| {_fmt_pct(d['new_pass_rate'])} "
            f"| {_fmt_signed_pp(d['delta_pp'])} |"
        )
    return "\n".join(lines)


def _failures_section(rows: list[dict]) -> str:
    failed = [r for r in rows if r["passed"] == 0]
    if not failed:
        return "_no failures_\n"
    lines = []
    for row in failed:
        session_ref = row.get("raw_session_id") or "—"
        err_line = f" — error: {row['error']}" if row.get("error") else ""
        lines.append(
            f"- **{row['prompt_id']}** ({row['category']}) "
            f"→ session `{session_ref}`{err_line}"
        )
    return "\n".join(lines) + "\n"


def render_report(
    run_id: str, *, diff_against: str | None = None, db_path: Path | None = None,
) -> str:
    run = get_run(run_id, db_path=db_path)
    if run is None:
        raise ValueError(f"unknown run_id: {run_id}")
    stats = aggregate_run(run_id, db_path=db_path)
    rows = get_signals_for_run(run_id, db_path=db_path)

    overall_total = sum(s.total for s in stats.values()) or 0
    overall_passed = sum(s.passed for s in stats.values()) or 0
    overall_rate = overall_passed / overall_total if overall_total else 0.0

    parts = [
        f"# Eval Run Report — {run['label']}",
        "",
        f"_Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}_",
        "",
        f"- run_id: `{run['run_id']}`",
        f"- label: {run['label']}",
        f"- tier: {run['tier']}",
        f"- config_version: {run['config_version']}",
        f"- started_at: {run['started_at']}",
        f"- completed_at: {run['completed_at'] or '—'}",
        f"- prompts: {overall_total}",
        f"- passed: {overall_passed} ({_fmt_pct(overall_rate)})",
        f"- total cost: ${run['total_cost_usd'] or 0.0:.2f}",
        "",
        "## Per-category pass rates",
        "",
        _category_table(stats),
        "",
    ]

    if diff_against:
        baseline = get_run(diff_against, db_path=db_path)
        if baseline is None:
            parts.extend([
                f"## Diff vs baseline (`{diff_against}` not found)",
                "",
            ])
        else:
            d = diff_runs(diff_against, run_id, db_path=db_path)
            parts.extend([
                f"## Diff vs baseline (`{baseline['label']}` → `{run['label']}`)",
                "",
                _diff_table(d.per_category),
                "",
            ])

    parts.extend([
        "## Failures",
        "",
        _failures_section(rows),
    ])

    return "\n".join(parts)
