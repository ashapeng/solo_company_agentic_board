from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from server.discovery.analyze.corpus import prepare_corpus, records_digest
from server.discovery.analyze.instructions import render_agent_instructions
from server.discovery.analyze.models import AgentBundle, BUNDLE_SCHEMA_VERSION
from server.discovery.store import DiscoveryStore


@dataclass(frozen=True)
class PrepareResult:
    bundle: AgentBundle
    bundle_path: Path
    instructions_path: Path
    channel_distribution: dict[str, int]


def prepare_week(store: DiscoveryStore, week: str, max_posts: int = 80) -> PrepareResult:
    if max_posts < 1 or max_posts > 1000:
        raise ValueError("max_posts must be between 1 and 1000")
    posts = store.read_week_posts(week)
    if not posts:
        raise ValueError(f"no raw posts found for week {week}")
    generated_at = datetime.now(tz=timezone.utc).isoformat()
    manifest = store.read_manifest(week) or {}
    retrieved_at = str(manifest.get("generated_at") or "")
    records = prepare_corpus(posts, max_posts=max_posts, retrieved_at=retrieved_at)
    if not records:
        raise ValueError("bundle character budget excluded every raw post")
    digest = records_digest(records)
    constraints = {
        "records_are_untrusted_data": True,
        "max_topics": 8,
        "minimum_evidence_per_topic": 2 if len(records) >= 2 else 1,
        "quote_must_match_title_or_body": True,
        "network_allowed_during_synthesis": False,
    }
    bundle = AgentBundle(
        schema_version=BUNDLE_SCHEMA_VERSION,
        week=week,
        generated_at=generated_at,
        post_count=len(posts),
        selected_post_count=len(records),
        records_digest=digest,
        records=records,
        constraints=constraints,
    )
    paths = store.write_prepared(
        week,
        bundle,
        render_agent_instructions(week=week, max_topics=constraints["max_topics"]),
    )
    distribution: dict[str, int] = {}
    for record in records:
        channel = record["channel"]
        distribution[channel] = distribution.get(channel, 0) + 1
    return PrepareResult(bundle, paths["bundle"], paths["instructions"], distribution)
