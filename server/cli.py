"""
Agentic Board — CLI entry point.

Usage:
    uv run python -m server.cli "Should we build a SaaS or open-source this?"
    uv run python -m server.cli --interactive
    uv run python -m server.cli --list-members
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
from server.board.memory import read_sotb
from server.board.metrics import SessionMetrics, _estimate_cost
from server.board.orchestrator import BoardOrchestrator, BoardDeliberationError, BoardSession, MemberResponse

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
    args = parser.parse_args()

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
