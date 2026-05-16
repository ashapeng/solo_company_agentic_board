"""Eval runner CLI.

Usage:
    uv run python -m evals.runner --baseline --tier heavy
    uv run python -m evals.runner --tier heavy --label after-P1
    uv run python -m evals.runner --tier heavy --label after-P1 --diff-against baseline
    uv run python -m evals.runner --tier heavy --category clean_baseline --label smoke
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from server.board.deliberation.orchestrator import (
    BoardDeliberationError,
    BoardOrchestrator,
)
from server.harness.config import get_config

from evals import corpus as corpus_mod
from evals.corpus import EvalPrompt
from evals.ledger import (
    complete_run,
    create_run,
    find_run_by_label,
    init_db,
    record_signal,
)
from evals.metrics import check_signal_for_prompt
from evals.signals import ObservedSignals, extract_signals

logger = logging.getLogger("evals.runner")

_SESSIONS_DIR = Path("data/sessions")


def _tier_to_verify(tier: str) -> bool:
    """At P0, --tier maps only to the existing verify= flag."""
    return tier == "heavy"


async def _run_one_prompt(
    prompt: EvalPrompt,
    *,
    tier: str,
    sessions_dir: Path,
) -> tuple[dict, str | None, str | None]:
    """Run a single prompt. Returns (observed_signals_json_dict, raw_session_id, error)."""
    orchestrator = BoardOrchestrator()
    session_id = f"board_eval_{prompt.id}_{int(time.time())}"
    try:
        session = await orchestrator.deliberate(
            prompt.query,
            verify=_tier_to_verify(tier),
            session_id=session_id,
        )
    except BoardDeliberationError as e:
        logger.warning("deliberate failed for %s: %s", prompt.id, e)
        return ({}, None, str(e))
    except Exception as e:
        # Any other deliberation error (provider 4xx/5xx, network, parsing,
        # etc.) records as a failed prompt rather than killing the whole run.
        logger.exception("deliberate raised %s for %s", type(e).__name__, prompt.id)
        return ({}, None, f"{type(e).__name__}: {e}")

    try:
        session.save(directory=str(sessions_dir))
    except Exception as e:
        logger.warning("failed to save session %s: %s", session.session_id, e)

    signals = extract_signals(session)
    return (signals.to_json(), session.session_id, None)


async def run_corpus(
    prompts: list[EvalPrompt],
    *,
    tier: str,
    label: str,
    config_version: int,
    db_path: Path | None = None,
    sessions_dir: Path = _SESSIONS_DIR,
) -> str:
    """Run all prompts sequentially, record per-prompt signals, return run_id."""
    sessions_dir.mkdir(parents=True, exist_ok=True)
    if db_path is not None:
        init_db(db_path)

    run_id = create_run(
        label=label, tier=tier, config_version=config_version,
        prompt_count=len(prompts), db_path=db_path,
    )

    total_passed = 0
    total_cost = 0.0

    for i, prompt in enumerate(prompts, 1):
        logger.info("[%d/%d] running %s (%s)", i, len(prompts), prompt.id, prompt.category)
        observed_json, raw_session_id, error = await _run_one_prompt(
            prompt, tier=tier, sessions_dir=sessions_dir,
        )

        if observed_json:
            signals = ObservedSignals.from_dict(observed_json)
            passed = check_signal_for_prompt(prompt, signals)
            latency_ms = int(signals.total_latency_seconds * 1000)
            tokens = signals.total_tokens
            cost_usd = signals.total_cost_usd
        else:
            passed = False
            latency_ms = 0
            tokens = 0
            cost_usd = 0.0

        record_signal(
            run_id=run_id, prompt_id=prompt.id, category=prompt.category,
            expected_outcome=prompt.expected_outcome,
            observed_signals=observed_json,
            passed=passed, latency_ms=latency_ms, tokens=tokens, cost_usd=cost_usd,
            raw_session_id=raw_session_id, error=error, db_path=db_path,
        )
        if passed:
            total_passed += 1
        total_cost += cost_usd

    complete_run(run_id, total_passed=total_passed, total_cost_usd=total_cost, db_path=db_path)
    return run_id


def _select_prompts(category: str | None, limit: int | None) -> list[EvalPrompt]:
    prompts = (
        corpus_mod.load_category(category) if category else corpus_mod.load_all()
    )
    if limit is not None:
        prompts = prompts[:limit]
    return prompts


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(
        prog="evals",
        description="Eval harness for board hardening (P0).",
    )
    parser.add_argument("--tier", choices=("light", "standard", "heavy"),
                        default="heavy",
                        help="Tier (P0: only changes verify=). Default: heavy.")
    parser.add_argument("--label", type=str, default=None,
                        help="Run label (e.g. 'baseline', 'after-P1').")
    parser.add_argument("--baseline", action="store_true",
                        help="Shortcut for --label baseline.")
    parser.add_argument("--category", choices=corpus_mod.CATEGORIES, default=None,
                        help="Restrict to one category (default: all).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Only run the first N prompts (for dev/smoke).")
    parser.add_argument("--diff-against", type=str, default=None,
                        help="After running, render a diff vs this baseline label.")
    parser.add_argument("--no-report", action="store_true",
                        help="Skip markdown report rendering.")
    parser.add_argument("--reports-dir", type=Path, default=Path("evals/reports"),
                        help="Where to write the markdown report.")
    parser.add_argument("--db", type=Path, default=None,
                        help="Override eval ledger path.")

    args = parser.parse_args(argv)

    if args.baseline and args.label:
        parser.error("--baseline and --label are mutually exclusive")
    label = args.label or ("baseline" if args.baseline else "ad-hoc")

    prompts = _select_prompts(args.category, args.limit)
    if not prompts:
        print("no prompts selected", file=sys.stderr)
        return 2

    cfg = get_config()
    config_version = getattr(cfg, "version", 0) or 0

    run_id = asyncio.run(
        run_corpus(
            prompts, tier=args.tier, label=label,
            config_version=config_version,
            db_path=args.db,
        )
    )
    print(f"run_id: {run_id}")

    if not args.no_report:
        from evals.reporting import render_report
        diff_run_id = None
        if args.diff_against:
            diff_run_id = find_run_by_label(args.diff_against, db_path=args.db)
            if diff_run_id is None:
                print(f"warning: no run found with label '{args.diff_against}'",
                      file=sys.stderr)
        report = render_report(run_id, diff_against=diff_run_id, db_path=args.db)
        args.reports_dir.mkdir(parents=True, exist_ok=True)
        out_path = args.reports_dir / f"{run_id}.md"
        out_path.write_text(report)
        print(f"report: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
