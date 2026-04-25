"""
Agentic Board — CLI entry point.

Usage:
    uv run python -m server.cli "Should we build a SaaS or open-source this?"
    uv run python -m server.cli --interactive
    uv run python -m server.cli --list-members
    uv run python -m server.cli --tune
    uv run python -m server.cli --tune-verification
    uv run python -m server.cli --tune-routing
    uv run python -m server.cli --tune-models
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from dotenv import load_dotenv
load_dotenv()

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from server.board.config import BOARD_MEMBERS, BoardMember
from server.memory.sotb import read_sotb
from server.board.metrics import SessionMetrics, _estimate_cost
from server.board.deliberation.orchestrator import BoardOrchestrator, BoardDeliberationError, BoardSession, MemberResponse
from server.harness.routing_compaction import (
    MIN_PHASE_D_SESSIONS_PER_QUERY_TYPE,
    tune_routing_and_compaction,
)
from server.harness.model_assignment import MIN_MODEL_SAMPLES, tune_model_assignments
from server.harness.tuning import (
    MIN_FEEDBACK_SESSIONS_PER_QUERY_TYPE,
    tune_token_budgets,
    tune_verification_thresholds,
)

console = Console()


# ---------------------------------------------------------------------------
# Progress callbacks
# ---------------------------------------------------------------------------

_progress: Progress | None = None
_task_ids: dict[str, int] = {}


def on_stage_start(stage: int, name: str):
    console.print()
    console.rule(f"[bold cyan]Stage {stage}: {name}[/bold cyan]")


def on_member_done(stage: int, member: BoardMember, resp: MemberResponse | None, error: str | None = None):
    if error:
        console.print(
            f"  [red]✗ {member.title} — FAILED: {error}[/red]"
        )
    else:
        console.print(
            f"  [{_color_for(member.id)}]{member.title}[/] "
            f"({resp.model}) — {resp.elapsed_seconds}s"
        )


def on_stage_done(stage: int, responses):
    if isinstance(responses, list):
        console.print(f"  [dim]{len(responses)} responses collected[/dim]")


def _color_for(member_id: str) -> str:
    colors = [
        "bright_red", "bright_green", "bright_yellow", "bright_blue",
        "bright_magenta", "bright_cyan", "orange1", "spring_green1",
        "deep_pink1", "dodger_blue1",
    ]
    idx = list(m.id for m in BOARD_MEMBERS).index(member_id) if member_id in [m.id for m in BOARD_MEMBERS] else 0
    return colors[idx % len(colors)]


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

def show_members():
    table = Table(title="Board Members", show_lines=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("ID", style="cyan")
    table.add_column("Title", style="bold")
    table.add_column("Role", style="green")
    table.add_column("Expertise", style="yellow")
    table.add_column("Tags", style="dim")

    for i, m in enumerate(BOARD_MEMBERS, 1):
        table.add_row(
            str(i),
            m.id,
            m.title,
            m.role,
            ", ".join(m.expertise[:3]),
            ", ".join(m.tags),
        )
    console.print(table)


def show_budget(session: BoardSession):
    """Display token usage and cost breakdown."""
    metrics = session.metrics
    console.print()
    console.rule("[bold yellow]Session Metrics[/bold yellow]")

    for stage in (1, 2, 3):
        calls = metrics.by_stage(stage)
        if not calls:
            continue
        tokens = sum(max(c.input_tokens, 0) + max(c.output_tokens, 0) for c in calls)
        cost = sum(_estimate_cost(c.model, c.input_tokens, c.output_tokens) for c in calls)
        label = "1 chairman" if stage == 3 else f"{len(calls)} members"
        stage_names = {1: "Stage 1", 2: "Stage 2", 3: "Stage 3"}
        console.print(f"  {stage_names[stage]}: {label}, {tokens:,} tokens (${cost:.2f})")

    total_tokens = metrics.total_tokens()
    total_cost = metrics.total_cost_estimate()
    console.print(f"  [bold]Total: {total_tokens:,} tokens (${total_cost:.2f}) in {session.total_elapsed}s[/bold]")


def show_session(session: BoardSession, *, budget: bool = False):
    console.print()
    console.rule("[bold green]BOARD DECISION[/bold green]")
    console.print()

    if session.stage3_synthesis:
        console.print(Markdown(session.stage3_synthesis.content))

    console.print()
    console.rule("[dim]Session Details[/dim]")
    console.print(f"  Session ID: {session.session_id}")
    console.print(f"  Total time: {session.total_elapsed}s")
    console.print(f"  Saved to:   data/sessions/{session.session_id}.json")
    if session.memory and session.memory.get("proposed_sotb_update"):
        console.print("  SOTB update: proposed in session JSON; not applied automatically")

    if budget:
        show_budget(session)

    # Offer to show individual responses
    console.print()
    console.print("[dim]Tip: inspect individual member responses in the saved JSON file.[/dim]")


def show_stage1_detail(session: BoardSession):
    """Show all Stage 1 responses."""
    for resp in session.stage1_responses:
        member = next((m for m in BOARD_MEMBERS if m.id == resp.member_id), None)
        title = member.title if member else resp.member_id
        console.print()
        console.print(Panel(
            Markdown(resp.content),
            title=f"[bold]{title}[/bold] ({resp.model})",
            subtitle=f"{resp.elapsed_seconds}s",
            border_style=_color_for(resp.member_id),
        ))


def run_tuner(*, dry_run: bool = False, json_output: bool = False):
    """Run the Phase B token budget tuner."""
    report = tune_token_budgets(dry_run=dry_run)

    if json_output:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return report

    console.print()
    console.rule("[bold yellow]Token Budget Tuner[/bold yellow]")
    console.print(
        f"  Examined segments: {report.examined_segments} "
        f"({report.eligible_segments} eligible)"
    )

    if not report.changes:
        console.print("  [dim]No budget changes recommended.[/dim]")
        return report

    table = Table(show_lines=True)
    table.add_column("Query Type", style="cyan")
    table.add_column("Complexity", style="green")
    table.add_column("Stage", justify="right")
    table.add_column("Usage", justify="right")
    table.add_column("Previous", justify="right")
    table.add_column("New", justify="right")
    table.add_column("Direction", style="yellow")

    for change in report.changes:
        table.add_row(
            change.query_type,
            change.complexity,
            str(change.stage),
            f"{change.median_usage:.0f}",
            str(change.previous_budget),
            str(change.new_budget),
            change.direction,
        )

    console.print(table)
    if report.saved:
        console.print(f"  [green]Saved harness config version {report.config_version}.[/green]")
    elif report.dry_run:
        console.print("  [yellow]Dry run only; config was not changed.[/yellow]")
    return report


def run_verification_tuner(
    *,
    dry_run: bool = False,
    json_output: bool = False,
    min_feedback_sessions: int = MIN_FEEDBACK_SESSIONS_PER_QUERY_TYPE,
):
    """Run the Phase C verification threshold tuner."""
    report = tune_verification_thresholds(
        dry_run=dry_run,
        min_feedback_sessions=min_feedback_sessions,
    )

    if json_output:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return report

    console.print()
    console.rule("[bold yellow]Verification Threshold Tuner[/bold yellow]")
    console.print(
        f"  Examined query types: {report.examined_query_types} "
        f"({report.eligible_query_types} eligible)"
    )

    if not report.changes:
        console.print("  [dim]No threshold changes recommended.[/dim]")
        return report

    table = Table(show_lines=True)
    table.add_column("Query Type", style="cyan")
    table.add_column("Feedback", justify="right")
    table.add_column("False Passes", justify="right")
    table.add_column("False Fails", justify="right")
    table.add_column("Previous", justify="right")
    table.add_column("New", justify="right")
    table.add_column("Direction", style="yellow")

    for change in report.changes:
        table.add_row(
            change.query_type,
            str(change.feedback_count),
            str(change.false_passes),
            str(change.false_fails),
            f"{change.previous_threshold:.1f}",
            f"{change.new_threshold:.1f}",
            change.direction,
        )

    console.print(table)
    if report.saved:
        console.print(f"  [green]Saved harness config version {report.config_version}.[/green]")
    elif report.dry_run:
        console.print("  [yellow]Dry run only; config was not changed.[/yellow]")
    return report


def run_phase_d_tuner(
    *,
    dry_run: bool = False,
    json_output: bool = False,
    min_sessions: int = MIN_PHASE_D_SESSIONS_PER_QUERY_TYPE,
):
    """Run the Phase D routing and compaction tuner."""
    report = tune_routing_and_compaction(
        dry_run=dry_run,
        min_sessions=min_sessions,
    )

    if json_output:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return report

    console.print()
    console.rule("[bold yellow]Routing & Compaction Tuner[/bold yellow]")
    console.print(
        f"  Analyzed sessions: {report.analyzed_sessions}; "
        f"query types: {report.examined_query_types} "
        f"({report.eligible_query_types} eligible)"
    )

    if report.routing_changes:
        table = Table(title="Routing Changes", show_lines=True)
        table.add_column("Query Type", style="cyan")
        table.add_column("Member", style="green")
        table.add_column("Routed", justify="right")
        table.add_column("Cited", justify="right")
        table.add_column("Rate", justify="right")
        table.add_column("Action", style="yellow")
        for change in report.routing_changes:
            table.add_row(
                change.query_type,
                change.member_id,
                str(change.routed_count),
                str(change.cited_count),
                f"{change.citation_rate:.2f}",
                change.action,
            )
        console.print(table)

    if report.compaction_changes:
        table = Table(title="Compaction Changes", show_lines=True)
        table.add_column("Query Type", style="cyan")
        table.add_column("Section", style="green")
        table.add_column("Observed", justify="right")
        table.add_column("Used", justify="right")
        table.add_column("Rate", justify="right")
        table.add_column("Action", style="yellow")
        for change in report.compaction_changes:
            table.add_row(
                change.query_type,
                change.section,
                str(change.observed_count),
                str(change.used_count),
                f"{change.usage_rate:.2f}",
                change.action,
            )
        console.print(table)

    if not report.routing_changes and not report.compaction_changes:
        console.print("  [dim]No routing or compaction changes recommended.[/dim]")
        return report

    if report.saved:
        console.print(f"  [green]Saved harness config version {report.config_version}.[/green]")
    elif report.dry_run:
        console.print("  [yellow]Dry run only; config was not changed.[/yellow]")
    return report


def run_model_tuner(
    *,
    dry_run: bool = False,
    json_output: bool = False,
    min_samples: int = MIN_MODEL_SAMPLES,
):
    """Run the Phase E model assignment tuner."""
    report = tune_model_assignments(
        dry_run=dry_run,
        min_samples=min_samples,
    )

    if json_output:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
        return report

    console.print()
    console.rule("[bold yellow]Model Assignment Tuner[/bold yellow]")
    console.print(
        f"  Examined assignments: {report.examined_assignments} "
        f"({report.eligible_assignments} eligible)"
    )

    if not report.changes:
        console.print("  [dim]No model preference changes recommended.[/dim]")
        return report

    table = Table(show_lines=True)
    table.add_column("Query Type", style="cyan")
    table.add_column("Member", style="green")
    table.add_column("Previous")
    table.add_column("New", style="yellow")
    table.add_column("New Score", justify="right")
    table.add_column("Runner Up", justify="right")
    table.add_column("Samples", justify="right")

    for change in report.changes:
        runner = ""
        if change.runner_up_model and change.runner_up_score is not None:
            runner = f"{change.runner_up_model} ({change.runner_up_score:.2f})"
        table.add_row(
            change.query_type,
            change.member_id,
            change.previous_model or "",
            change.new_model,
            f"{change.new_score:.2f}",
            runner,
            str(change.sample_count),
        )

    console.print(table)
    if report.saved:
        console.print(f"  [green]Saved harness config version {report.config_version}.[/green]")
    elif report.dry_run:
        console.print("  [yellow]Dry run only; config was not changed.[/yellow]")
    return report


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_board(
    query: str,
    *,
    verbose: bool = False,
    member_ids: list[str] | None = None,
    full_board: bool = False,
    verify: bool = False,
    budget: bool = False,
    json_output: bool = False,
):
    orchestrator = BoardOrchestrator(
        on_stage_start=None if json_output else on_stage_start,
        on_member_done=None if json_output else on_member_done,
        on_stage_done=None if json_output else on_stage_done,
    )

    if not json_output:
        console.print(Panel(
            f"[bold]{query}[/bold]",
            title="[cyan]Board Query[/cyan]",
            border_style="cyan",
        ))

    try:
        session = await orchestrator.deliberate(
            query,
            member_ids=member_ids,
            skip_classify=full_board,
            verify=verify,
        )
    except BoardDeliberationError as e:
        if json_output:
            print(json.dumps({"error": "deliberation_failed", "message": str(e)}, indent=2))
            return None
        console.print(f"\n  [bold red]Board deliberation aborted:[/bold red] {e}")
        return None

    if json_output:
        print(json.dumps(session.to_dict(), indent=2, ensure_ascii=False))
        return session

    if verbose:
        show_stage1_detail(session)

    show_session(session, budget=budget)
    return session


async def interactive_mode():
    console.print(Panel(
        "[bold]Agentic Board — Interactive Mode[/bold]\n"
        "Type your question and the board will deliberate.\n"
        "Commands: [cyan]/members[/cyan] [cyan]/verbose[/cyan] [cyan]/verify[/cyan] "
        "[cyan]/budget[/cyan] [cyan]/sotb[/cyan] [cyan]/quit[/cyan]",
        border_style="cyan",
    ))

    verbose = False
    verify = False
    budget = False

    while True:
        console.print()
        query = console.input("[bold cyan]You > [/bold cyan]").strip()

        if not query:
            continue
        if query.lower() in ("/quit", "/exit", "/q"):
            console.print("[dim]Board adjourned.[/dim]")
            break
        if query.lower() == "/members":
            show_members()
            continue
        if query.lower() == "/verbose":
            verbose = not verbose
            console.print(f"[dim]Verbose mode: {'ON' if verbose else 'OFF'}[/dim]")
            continue
        if query.lower() == "/verify":
            verify = not verify
            console.print(f"[dim]Verification: {'ON' if verify else 'OFF'}[/dim]")
            continue
        if query.lower() == "/budget":
            budget = not budget
            console.print(f"[dim]Budget display: {'ON' if budget else 'OFF'}[/dim]")
            continue
        if query.lower() == "/sotb":
            sotb = read_sotb()
            if sotb:
                console.print(Panel(
                    Markdown(sotb),
                    title="[bold]State of the Board[/bold]",
                    border_style="yellow",
                ))
            else:
                console.print("[dim]No SOTB found. It will be created after the first deliberation.[/dim]")
            continue

        await run_board(query, verbose=verbose, verify=verify, budget=budget)


def cli():
    parser = argparse.ArgumentParser(description="Agentic Board — LLM Council")
    parser.add_argument("query", nargs="?", help="Question for the board")
    parser.add_argument("--interactive", "-i", action="store_true", help="Interactive mode")
    parser.add_argument("--list-members", "-l", action="store_true", help="List board members")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show individual responses")
    parser.add_argument("--members", "-m", type=str, help="Comma-separated member IDs to invoke")
    parser.add_argument("--full-board", "-f", action="store_true", help="Skip classifier, invoke all members")
    parser.add_argument("--verify", action="store_true", help="Enable Stage 4 verification on synthesis")
    parser.add_argument("--budget", action="store_true", help="Show token usage and cost breakdown")
    parser.add_argument("--json", action="store_true", help="Emit session JSON only")
    parser.add_argument("--tune", action="store_true", help="Run Phase B token budget tuner from the ledger")
    parser.add_argument("--tune-verification", action="store_true", help="Run Phase C verification threshold tuner")
    parser.add_argument(
        "--tune-routing",
        "--tune-routing-compaction",
        dest="tune_routing",
        action="store_true",
        help="Run Phase D routing and compaction tuner",
    )
    parser.add_argument("--tune-models", action="store_true", help="Run Phase E model assignment tuner")
    parser.add_argument("--dry-run", action="store_true", help="Preview tuner changes without saving config")
    parser.add_argument(
        "--min-feedback-sessions",
        type=int,
        default=MIN_FEEDBACK_SESSIONS_PER_QUERY_TYPE,
        help="Minimum feedback-bearing sessions per query type for --tune-verification",
    )
    parser.add_argument(
        "--min-phase-d-sessions",
        type=int,
        default=MIN_PHASE_D_SESSIONS_PER_QUERY_TYPE,
        help="Minimum saved sessions per query type for --tune-routing",
    )
    parser.add_argument(
        "--min-model-samples",
        type=int,
        default=MIN_MODEL_SAMPLES,
        help="Minimum sessions per candidate model for --tune-models",
    )
    parser.add_argument(
        "--replay",
        type=str,
        default=None,
        help="Path to a saved session JSON to replay Stage 3 under a candidate harness config",
    )
    parser.add_argument(
        "--candidate-config",
        type=str,
        default=None,
        help="Harness config JSON path to use during replay (default: active config)",
    )
    parser.add_argument(
        "--replay-verify",
        action="store_true",
        help="Also run Stage 4 verification during replay",
    )
    args = parser.parse_args()

    if args.replay:
        from pathlib import Path as _ReplayPath
        from server.harness.replay import replay_session
        import json as _replay_json

        report = replay_session(
            _ReplayPath(args.replay),
            _ReplayPath(args.candidate_config) if args.candidate_config else None,
            verify=args.replay_verify,
        )
        print(_replay_json.dumps(report.to_dict(), indent=2))
        return

    if args.tune:
        run_tuner(dry_run=args.dry_run, json_output=args.json)
        return

    if args.tune_verification:
        run_verification_tuner(
            dry_run=args.dry_run,
            json_output=args.json,
            min_feedback_sessions=args.min_feedback_sessions,
        )
        return

    if args.tune_routing:
        run_phase_d_tuner(
            dry_run=args.dry_run,
            json_output=args.json,
            min_sessions=args.min_phase_d_sessions,
        )
        return

    if args.tune_models:
        run_model_tuner(
            dry_run=args.dry_run,
            json_output=args.json,
            min_samples=args.min_model_samples,
        )
        return

    if args.list_members:
        show_members()
        return

    if args.interactive or not args.query:
        asyncio.run(interactive_mode())
        return

    # Parse manual member override
    member_ids = None
    if args.members:
        member_ids = [mid.strip() for mid in args.members.split(",") if mid.strip()]

    asyncio.run(run_board(
        args.query,
        verbose=args.verbose,
        member_ids=member_ids,
        full_board=args.full_board,
        verify=args.verify,
        budget=args.budget,
        json_output=args.json,
    ))


if __name__ == "__main__":
    cli()
