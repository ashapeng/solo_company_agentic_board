from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from server.discovery.analyze.models import REPORT_SCHEMA_VERSION, TopicReport
from server.discovery.analyze.render import render_markdown
from server.discovery.analyze.validate import (
    enrich_topics,
    parse_candidate_file,
)
from server.discovery.store import DiscoveryStore
from server.discovery.lifecycle.models import Candidate
from server.discovery.lifecycle.store import CandidateStore


@dataclass(frozen=True)
class ImportResult:
    report: TopicReport
    markdown: str
    paths: dict[str, Path] | None
    candidates: list[Candidate] | None = None


def import_topics(
    store: DiscoveryStore,
    week: str,
    candidate_path: Path,
    *,
    max_topics: int = 8,
    dry_run: bool = False,
    producer_run_id: str | None = None,
) -> ImportResult:
    if max_topics < 1 or max_topics > 100:
        raise ValueError("max_topics must be between 1 and 100")
    bundle = store.read_prepared(week)
    if bundle is None:
        raise ValueError(f"no prepared bundle found for week {week}; run prepare first")
    candidate = parse_candidate_file(Path(candidate_path), max_topics=max_topics)
    topics = enrich_topics(candidate, bundle)
    producer = candidate.producer
    if producer_run_id is not None:
        producer = replace(producer, run_id=producer_run_id)
    report = TopicReport(
        schema_version=REPORT_SCHEMA_VERSION,
        week=week,
        generated_at=datetime.now(tz=timezone.utc).isoformat(),
        producer=producer,
        bundle_digest=bundle.records_digest,
        post_count=bundle.post_count,
        selected_post_count=bundle.selected_post_count,
        topics=topics,
        discarded_noise_notes=candidate.discarded_noise_notes,
    )
    markdown = render_markdown(report)
    paths = None
    candidates = None
    if not dry_run:
        paths = store.write_analyzed(week, report, markdown)
        candidates = list(CandidateStore(store.root).import_report(report))
    return ImportResult(report, markdown, paths, candidates)
