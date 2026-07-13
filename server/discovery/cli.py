from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from server.discovery.channels import build_channel
from server.discovery.analyze.importer import import_topics
from server.discovery.analyze.prepare import prepare_week
from server.discovery.analyze.validate import CandidateValidationError
from server.discovery.board_start import BoardStartError, start_board
from server.discovery.doctor import run_doctor
from server.discovery.lifecycle import (
    BoardLabel, Candidate, CandidateStatus, CandidateStore, DiscoveryStatus,
    FounderDisposition, ValidationState,
)
from server.discovery.lifecycle.migrate import migrate_candidates
from server.discovery.policy import fetch_allowed
from server.discovery.producers import (
    CANDIDATE_SCHEMA_PATH,
    CodexCliProducer,
    ManualHandoffProducer,
    ProducerConfig,
    ProducerRunStore,
)
from server.discovery.promotion import PromotionError, promote_candidate
from server.discovery.store import DiscoveryStore, iso_week
from server.discovery.watchlist import load_watchlist

DEFAULT_DATA_DIR = Path("data/discovery")


def _redact(text: str) -> str:
    """Error strings can embed full request URLs; strip credential query params
    before they reach stdout or the manifest (later read by LLM sessions)."""
    return re.sub(r"(api_key|apikey|token|key)=[^&'\"\s]+", r"\1=REDACTED", text)


def _cmd_fetch(args: argparse.Namespace) -> int:
    week = args.week or iso_week()
    watchlist = load_watchlist(Path(args.watchlist) if args.watchlist else None)
    store = DiscoveryStore(Path(args.data_dir))
    runs = []
    for channel_name, items in watchlist.items():
        if not items:
            continue
        allowed, policy = fetch_allowed(
            channel_name, explicit_watchlist=args.watchlist is not None
        )
        channel = build_channel(channel_name) if allowed else None
        for item in items:
            label = item["label"]
            entry = {
                "channel": channel_name,
                "label": label,
                "fetched": 0,
                "new": 0,
                "file": None,
                "error": None,
                "policy": policy.posture,
                "policy_reason": policy.reason,
                "state": "ready" if allowed else policy.posture,
            }
            if not allowed:
                runs.append(entry)
                print(f"{channel_name}/{label}: SKIPPED {policy.posture}: {policy.reason}")
                continue
            try:
                assert channel is not None
                posts = channel.fetch(item)
                new_posts = store.filter_new(posts)
                path = store.write_raw(week, channel_name, label, new_posts)
                store.mark_seen(new_posts)
                entry.update(fetched=len(posts), new=len(new_posts), file=path.name)
            except Exception as exc:
                entry["error"] = _redact(str(exc))
            runs.append(entry)
            print(f"{channel_name}/{label}: fetched={entry['fetched']} new={entry['new']}"
                  + (f" ERROR: {entry['error']}" if entry["error"] else ""))
    manifest = {
        "week": week,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "runs": runs,
        "doctor": [asdict(h) for h in run_doctor(sorted({r["channel"] for r in runs}))],
    }
    store.write_manifest(week, manifest)
    print(f"manifest: {store.root / 'raw' / week / 'manifest.json'}")
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    names = args.channels.split(",") if args.channels else None
    for h in run_doctor(names):
        configured = "yes" if h.configured else "no"
        detail = h.detail or h.policy_reason
        print(
            f"{h.channel:12} posture={h.posture:8} configured={configured:3} "
            f"health={h.status:12} {detail}"
        )
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    store = DiscoveryStore(Path(args.data_dir))
    latest = store.latest_manifest()
    if latest is None:
        print("no fetch runs recorded yet")
        return 0
    week, manifest = latest
    total_new = sum(r.get("new", 0) for r in manifest.get("runs", []))
    errors = [r for r in manifest.get("runs", []) if r.get("error")]
    held = [r for r in manifest.get("runs", []) if r.get("state") in {"held", "disabled"}]
    print(f"latest run: {week} ({manifest.get('generated_at', 'unknown')})")
    print(f"items: {len(manifest['runs'])}, new posts: {total_new}, errors: {len(errors)}")
    try:
        raw_count = len(store.read_week_posts(week))
    except ValueError as exc:
        print(f"raw: invalid ({exc})")
        return 2
    prepared = store.read_prepared(week) if store.prepared_exists(week) else None
    analyzed = store.read_analyzed(week) if store.analyzed_exists(week) else None
    print(f"raw: ready ({raw_count} posts)" if raw_count else "raw: empty")
    print(
        f"prepared: ready ({prepared.selected_post_count} selected)"
        if prepared else "prepared: missing"
    )
    print(
        f"analyzed: ready ({len(analyzed.topics)} topics)"
        if analyzed else "analyzed: missing"
    )
    if held:
        print(f"policy-skipped: {len(held)}")
    for r in errors:
        print(f"  ERROR {r['channel']}/{r['label']}: {r['error']}")
    return 0


def _resolve_week(store: DiscoveryStore, requested: str | None) -> str:
    if requested:
        return requested
    week = store.latest_week_with_posts()
    if week is None:
        raise ValueError("no week with raw posts found; pass --week after fetch")
    return week


def _cmd_prepare(args: argparse.Namespace) -> int:
    store = DiscoveryStore(Path(args.data_dir))
    try:
        week = _resolve_week(store, args.week)
        result = prepare_week(store, week, max_posts=args.max_posts)
    except ValueError as exc:
        print(f"prepare failed: {exc}")
        return 2
    distribution = ", ".join(
        f"{channel}={count}" for channel, count in sorted(result.channel_distribution.items())
    )
    print(
        f"prepared {week}: raw={result.bundle.post_count} "
        f"selected={result.bundle.selected_post_count} channels={distribution}"
    )
    print(f"digest: {result.bundle.records_digest}")
    print(f"bundle: {result.bundle_path}")
    print(f"instructions: {result.instructions_path}")
    return 0


def _cmd_import_topics(args: argparse.Namespace) -> int:
    store = DiscoveryStore(Path(args.data_dir))
    try:
        week = _resolve_week(store, args.week)
        result = import_topics(
            store,
            week,
            Path(args.candidate),
            max_topics=args.max_topics,
            dry_run=args.dry_run,
        )
    except (ValueError, CandidateValidationError) as exc:
        print(f"import-topics failed: {exc}")
        return 2
    if args.dry_run:
        print(result.markdown, end="")
        print(
            f"validated: topics={len(result.report.topics)} "
            f"bundle_digest={result.report.bundle_digest} dry_run=true"
        )
    else:
        assert result.paths is not None
        print(
            f"imported {len(result.report.topics)} topics: "
            f"{result.paths['json']} and {result.paths['md']}"
        )
    return 0


def _candidate_store(args: argparse.Namespace) -> CandidateStore:
    return CandidateStore(Path(args.data_dir))


def _cmd_candidates(args: argparse.Namespace) -> int:
    try:
        candidates = _candidate_store(args).list(
            discovery_status=args.discovery_status, status=args.status, week=args.week
        )
    except (ValueError, KeyError) as exc:
        print(f"candidates failed: {exc}")
        return 2
    for candidate in candidates:
        print(
            f"{candidate.id}  {candidate.discovery_status.value:18}  "
            f"{(candidate.board_label.value if candidate.board_label else '-'):11}  "
            f"{candidate.validation_state.value:12}  {candidate.report_week}  "
            f"{candidate.signal_strength:.2f}  {candidate.title}"
        )
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    try:
        candidate = _candidate_store(args).get(args.candidate_id)
    except (ValueError, KeyError) as exc:
        print(f"show failed: {exc}")
        return 2
    print(json.dumps(candidate.to_dict(), indent=2, ensure_ascii=False))
    return 0


def _cmd_decide(args: argparse.Namespace) -> int:
    try:
        store = _candidate_store(args)
        if args.command == "shortlist":
            candidate = store.update(args.candidate_id, actor="founder",
                                     reason=args.note or "legacy shortlist compatibility",
                                     discovery_status=DiscoveryStatus.READY_FOR_BOARD)
        else:
            candidate = store.dispose(args.candidate_id, reason=args.reason)
    except (ValueError, KeyError) as exc:
        print(f"{args.command} failed: {exc}")
        return 2
    print(f"{candidate.id}: {candidate.discovery_status.value}/{candidate.founder_disposition.value}")
    return 0


def _cmd_disposition(args: argparse.Namespace) -> int:
    try:
        store = _candidate_store(args)
        candidate = (store.dispose(args.candidate_id, reason=args.reason) if args.command == "dispose"
                     else store.restore(args.candidate_id, reason=args.reason))
    except (ValueError, KeyError) as exc:
        print(f"{args.command} failed: {exc}")
        return 2
    print(f"{candidate.id}: {candidate.founder_disposition.value}")
    return 0


def _cmd_migrate_candidates(args: argparse.Namespace) -> int:
    try:
        result = migrate_candidates(Path(args.data_dir), dry_run=not args.apply)
    except ValueError as exc:
        print(f"migrate-candidates failed: {exc}")
        return 2
    print(f"inspected={result.inspected} migrated={result.migrated} unchanged={result.unchanged} dry_run={str(result.dry_run).lower()}")
    if result.backup_directory:
        print(f"backup: {result.backup_directory}")
    return 0


def _cmd_review_portfolio(args: argparse.Namespace) -> int:
    from server.board.deliberation.orchestrator import BoardOrchestrator
    from server.discovery.portfolio_review import PortfolioReviewService
    from server.experiments.service import ExperimentService
    from server.experiments.store import ExperimentStore

    candidate_store = _candidate_store(args)
    db_path = Path(args.db_path)
    experiment_store = ExperimentStore(db_path)
    service = PortfolioReviewService(candidate_store=candidate_store,
                                     experiment_store=experiment_store,
                                     orchestrator=BoardOrchestrator())
    try:
        result = asyncio.run(service.review(week=args.week, default_select=args.default_select,
                                            maximum_active=args.max_active, verify=args.verify))
        experiments = ExperimentService(store=experiment_store, candidate_store=candidate_store,
                                        db_path=db_path).create_selected(
                                            result, maximum_active=args.max_active)
    except (ValueError, KeyError) as exc:
        print(f"review-portfolio failed: {exc}")
        return 2
    print(f"portfolio review {result.review_id}: decisions={len(result.decisions)} selected={sum(d.selected_for_validation for d in result.decisions)} experiments={len(experiments)}")
    return 0


def _cmd_runs(args: argparse.Namespace) -> int:
    try:
        runs = ProducerRunStore(Path(args.data_dir)).list(week=args.week)
    except ValueError as exc:
        print(f"runs failed: {exc}")
        return 2
    for run in runs:
        valid = "" if run.validation is None else f" valid={run.validation.get('valid')}"
        print(f"{run.id}  {run.status:14}  {run.week}  {run.producer_name}{valid}")
    return 0


def _producer_config(args: argparse.Namespace) -> ProducerConfig:
    return ProducerConfig(
        executable=args.codex_executable,
        model=args.model,
        timeout_seconds=args.timeout,
        profile=args.profile,
    )


def _validate_and_import_run(
    run_store: ProducerRunStore, run, candidate_path: Path, data_dir: Path
) -> tuple[bool, str | None, object | None]:
    try:
        result = import_topics(
            DiscoveryStore(data_dir), run.week, candidate_path, producer_run_id=run.id
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError, CandidateValidationError) as exc:
        run_store.record_validation(run, valid=False, error=str(exc))
        return False, str(exc), None
    run_store.record_validation(run, valid=True)
    return True, None, result


def _cmd_synthesize(args: argparse.Namespace) -> int:
    data_dir = Path(args.data_dir)
    store = DiscoveryStore(data_dir)
    try:
        week = _resolve_week(store, args.week)
        if not store.prepared_exists(week):
            raise ValueError(f"no prepared bundle found for week {week}; run prepare first")
        producer = (
            CodexCliProducer(_producer_config(args))
            if args.producer == "codex"
            else ManualHandoffProducer(_producer_config(args))
        )
        run_store = ProducerRunStore(data_dir)
        run = run_store.create(
            week=week,
            producer_name=producer.name,
            producer_version=producer.version,
            prepared_bundle=data_dir / "prepared" / week / "agent_bundle.json",
            instructions=data_dir / "prepared" / week / "AGENT_INSTRUCTIONS.md",
            schema=CANDIDATE_SCHEMA_PATH,
        )
        request = run_store.request(run, Path.cwd())
        run_store.mark_started(run, producer.command(request))
        result = producer.produce(request)
        run_store.apply_result(run, result)
        if result.message:
            print(result.message, end="" if result.message.endswith("\n") else "\n")
        if result.status == "pending":
            print(f"pending producer run: {run.id}")
            return 0
        if result.status != "completed":
            print(f"producer run {run.id} failed: {result.message or result.status}")
            return 3
        valid, error, imported = _validate_and_import_run(
            run_store, run, request.output_path, data_dir
        )
        if not valid:
            print(f"producer run {run.id} produced invalid output: {error}")
            return 3
        count = len(imported.candidates or [])
        print(f"completed producer run {run.id}: candidates={count}")
        return 0
    except (ValueError, OSError) as exc:
        print(f"synthesize failed: {exc}")
        return 2


def _cmd_resume_run(args: argparse.Namespace) -> int:
    run_store = ProducerRunStore(Path(args.data_dir))
    try:
        run = run_store.get(args.run_id)
        if run is None:
            raise ValueError(f"producer run not found: {args.run_id}")
        if not run_store.resumable(run):
            raise ValueError(f"producer run is not resumable: {run.status}")
        valid, error, imported = _validate_and_import_run(
            run_store, run, Path(args.candidate), Path(args.data_dir)
        )
        if not valid:
            raise ValueError(error)
        print(f"resumed {run.id}: candidates={len(imported.candidates or [])}")
        return 0
    except (ValueError, OSError) as exc:
        print(f"resume-run failed: {exc}")
        return 2


def _save_candidate_mapping(store: CandidateStore, value: dict) -> None:
    store.save(Candidate.from_dict(value))


def _cmd_promote(args: argparse.Namespace) -> int:
    store = _candidate_store(args)
    try:
        candidate = store.get(args.candidate_id).to_dict()
        promotion = promote_candidate(
            candidate,
            save_candidate=lambda value: _save_candidate_mapping(store, value),
            venture_id=args.venture,
            new_venture_name=args.new_venture,
        )
    except (ValueError, KeyError, PromotionError) as exc:
        print(f"promote failed: {exc}")
        return 2
    print(
        f"promoted {args.candidate_id}: venture={promotion['venture_id']} "
        f"evidence={promotion['evidence_packet_id']} promotion={promotion['id']}"
    )
    return 0


def _cmd_start_board(args: argparse.Namespace) -> int:
    from server.board.deliberation.orchestrator import BoardOrchestrator

    store = _candidate_store(args)
    try:
        candidate = store.get(args.candidate_id).to_dict()
        result = asyncio.run(
            start_board(
                candidate,
                orchestrator=BoardOrchestrator(),
                save_candidate=lambda value: _save_candidate_mapping(store, value),
                verify=args.verify,
                mode=args.mode,
                new_session=args.new_session,
            )
        )
    except (ValueError, KeyError, BoardStartError) as exc:
        print(f"start-board failed: {exc}")
        return 2
    except Exception as exc:
        print(f"start-board deliberation failed: {exc}")
        return 4
    session_id = result.get("session_id") if isinstance(result, dict) else result.session_id
    print(f"board session: {session_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m server.discovery")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="fetch all watchlist items for the week")
    fetch.add_argument("--watchlist", default=None)
    fetch.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    fetch.add_argument("--week", default=None)
    fetch.set_defaults(func=_cmd_fetch)

    doctor = sub.add_parser("doctor", help="probe channel health")
    doctor.add_argument("--channels", default=None)
    doctor.set_defaults(func=_cmd_doctor)

    status = sub.add_parser("status", help="summarize the latest fetch run")
    status.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    status.set_defaults(func=_cmd_status)

    prepare = sub.add_parser("prepare", help="prepare bounded IDE-agent input bundle")
    prepare.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    prepare.add_argument("--week", default=None)
    prepare.add_argument("--max-posts", type=int, default=80)
    prepare.set_defaults(func=_cmd_prepare)

    importer = sub.add_parser(
        "import-topics", help="validate and persist IDE-agent candidate topics"
    )
    importer.add_argument("candidate")
    importer.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    importer.add_argument("--week", default=None)
    importer.add_argument("--max-topics", type=int, default=8)
    importer.add_argument("--dry-run", action="store_true")
    importer.set_defaults(func=_cmd_import_topics)

    synthesize = sub.add_parser("synthesize", help="synthesize and import prepared records")
    synthesize.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    synthesize.add_argument("--week", default=None)
    synthesize.add_argument("--producer", choices=("codex", "manual"), required=True)
    synthesize.add_argument("--codex-executable", default="codex")
    synthesize.add_argument("--model", default=None)
    synthesize.add_argument("--profile", default=None)
    synthesize.add_argument("--timeout", type=float, default=600)
    synthesize.set_defaults(func=_cmd_synthesize)

    runs = sub.add_parser("runs", help="list synthesis producer runs")
    runs.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    runs.add_argument("--week", default=None)
    runs.set_defaults(func=_cmd_runs)

    resume = sub.add_parser("resume-run", help="validate and import a resumable producer run")
    resume.add_argument("run_id")
    resume.add_argument("--candidate", required=True)
    resume.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    resume.set_defaults(func=_cmd_resume_run)

    candidates = sub.add_parser("candidates", help="list durable discovery candidates")
    candidates.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    candidates.add_argument("--status", choices=tuple(status.value for status in CandidateStatus))
    candidates.add_argument("--discovery-status", choices=tuple(status.value for status in DiscoveryStatus))
    candidates.add_argument("--week", default=None)
    candidates.set_defaults(func=_cmd_candidates)

    show = sub.add_parser("show", help="show one durable discovery candidate")
    show.add_argument("candidate_id")
    show.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    show.set_defaults(func=_cmd_show)

    shortlist = sub.add_parser("shortlist", help="shortlist a discovery candidate")
    shortlist.add_argument("candidate_id")
    shortlist.add_argument("--note", default=None)
    shortlist.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    shortlist.set_defaults(func=_cmd_decide)

    reject = sub.add_parser("reject", help="reject a discovery candidate")
    reject.add_argument("candidate_id")
    reject.add_argument("--reason", required=True)
    reject.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    reject.set_defaults(func=_cmd_decide)

    dispose = sub.add_parser("dispose", help="soft-dispose a candidate while retaining history")
    dispose.add_argument("candidate_id")
    dispose.add_argument("--reason", required=True)
    dispose.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    dispose.set_defaults(func=_cmd_disposition)

    restore = sub.add_parser("restore", help="restore a soft-disposed candidate")
    restore.add_argument("candidate_id")
    restore.add_argument("--reason", required=True)
    restore.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    restore.set_defaults(func=_cmd_disposition)

    migrate = sub.add_parser("migrate-candidates", help="migrate candidate files to schema v2")
    migrate.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    migrate.add_argument("--dry-run", action="store_true", help="accepted for explicitness; dry-run is the default")
    migrate.add_argument("--apply", action="store_true")
    migrate.set_defaults(func=_cmd_migrate_candidates)

    review = sub.add_parser("review-portfolio", help="run one bounded board portfolio review")
    review.add_argument("--week", required=True)
    review.add_argument("--default-select", type=int, default=3)
    review.add_argument("--max-active", type=int, default=5)
    review.add_argument("--verify", action="store_true")
    review.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    review.add_argument("--db-path", default="data/harness_ledger.db")
    review.set_defaults(func=_cmd_review_portfolio)

    promote = sub.add_parser("legacy-promote", help="compatibility: link one candidate to a venture")
    promote.add_argument("candidate_id")
    venture_choice = promote.add_mutually_exclusive_group(required=True)
    venture_choice.add_argument("--venture")
    venture_choice.add_argument("--new-venture")
    promote.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    promote.set_defaults(func=_cmd_promote)

    board = sub.add_parser("legacy-start-board", help="compatibility: start one promoted candidate board")
    board.add_argument("candidate_id")
    board.add_argument("--verify", action="store_true")
    board.add_argument("--mode", choices=("fast", "standard", "deep"), default=None)
    board.add_argument("--new-session", action="store_true")
    board.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    board.set_defaults(func=_cmd_start_board)

    args = parser.parse_args(argv)
    return args.func(args)
