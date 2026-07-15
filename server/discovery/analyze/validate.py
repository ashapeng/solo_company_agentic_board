from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from server.discovery.analyze.models import (
    CANDIDATE_SCHEMA_VERSION,
    AgentBundle,
    CandidateTopic,
    ContractError,
    Evidence,
    Producer,
    Resource,
    Topic,
    topic_slug,
)


MAX_CANDIDATE_BYTES = 1_000_000
MAX_NESTING_DEPTH = 8
MAX_TITLE_CHARS = 200
MAX_SUMMARY_CHARS = 2_000
MAX_WHO_CHARS = 500
MAX_QUOTE_CHARS = 500
MAX_NOTES_CHARS = 2_000
MAX_EVIDENCE_PER_TOPIC = 12
MAX_PRODUCER_CHARS = 100


class CandidateValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedCandidate:
    week: str
    bundle_digest: str
    producer: Producer
    topics: list[CandidateTopic]
    discarded_noise_notes: str


def _depth(value: Any, current: int = 0) -> int:
    if isinstance(value, dict):
        return max([current, *(_depth(v, current + 1) for v in value.values())])
    if isinstance(value, list):
        return max([current, *(_depth(v, current + 1) for v in value)])
    return current


def _bounded(value: str, limit: int, path: str) -> None:
    if len(value) > limit:
        raise CandidateValidationError(f"{path} exceeds {limit} characters")


def parse_candidate_file(path: Path, *, max_topics: int = 8) -> ParsedCandidate:
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise CandidateValidationError(f"cannot read candidate file {path}: {exc}") from exc
    if size > MAX_CANDIDATE_BYTES:
        raise CandidateValidationError(
            f"candidate file exceeds {MAX_CANDIDATE_BYTES} byte limit"
        )
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_reject_duplicate_fields
        )
    except CandidateValidationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise CandidateValidationError(f"candidate must be plain valid JSON: {exc}") from exc
    return parse_candidate(value, max_topics=max_topics)


def _reject_duplicate_fields(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CandidateValidationError(f"candidate JSON has duplicate field: {key}")
        result[key] = value
    return result


def parse_candidate(value: Any, *, max_topics: int = 8) -> ParsedCandidate:
    if not isinstance(value, dict):
        raise CandidateValidationError("candidate root must be an object")
    if _depth(value) > MAX_NESTING_DEPTH:
        raise CandidateValidationError(
            f"candidate nesting exceeds depth {MAX_NESTING_DEPTH}"
        )
    required = {
        "schema_version", "week", "bundle_digest", "producer", "topics",
        "discarded_noise_notes",
    }
    missing = required - value.keys()
    unknown = value.keys() - required
    if missing:
        raise CandidateValidationError(f"candidate missing required field: {sorted(missing)[0]}")
    if unknown:
        raise CandidateValidationError(f"candidate has unknown field: {sorted(unknown)[0]}")
    version = value["schema_version"]
    if isinstance(version, bool) or version != CANDIDATE_SCHEMA_VERSION:
        raise CandidateValidationError(
            f"candidate.schema_version must equal {CANDIDATE_SCHEMA_VERSION}"
        )
    if not isinstance(value["week"], str) or not value["week"]:
        raise CandidateValidationError("candidate.week must be a non-empty string")
    if not isinstance(value["bundle_digest"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", value["bundle_digest"]
    ):
        raise CandidateValidationError("candidate.bundle_digest must be a SHA-256 hex digest")
    if not isinstance(value["topics"], list):
        raise CandidateValidationError("candidate.topics must be a list")
    if not value["topics"]:
        raise CandidateValidationError("candidate.topics must contain at least one topic")
    if len(value["topics"]) > max_topics:
        raise CandidateValidationError(f"candidate.topics exceeds maximum of {max_topics}")
    if not isinstance(value["discarded_noise_notes"], str):
        raise CandidateValidationError("candidate.discarded_noise_notes must be a string")
    _bounded(value["discarded_noise_notes"], MAX_NOTES_CHARS, "candidate.discarded_noise_notes")
    try:
        producer = Producer.from_dict(value["producer"])
        topics = [
            CandidateTopic.from_dict(topic, f"topics[{index}]")
            for index, topic in enumerate(value["topics"])
        ]
    except ContractError as exc:
        raise CandidateValidationError(str(exc)) from exc
    _bounded(producer.name, MAX_PRODUCER_CHARS, "producer.name")
    _bounded(producer.run_id, MAX_PRODUCER_CHARS, "producer.run_id")
    for index, topic in enumerate(topics):
        prefix = f"topics[{index}]({topic.id})"
        _bounded(topic.id, 80, f"{prefix}.id")
        _bounded(topic.title, MAX_TITLE_CHARS, f"{prefix}.title")
        _bounded(topic.summary, MAX_SUMMARY_CHARS, f"{prefix}.summary")
        _bounded(topic.who, MAX_WHO_CHARS, f"{prefix}.who")
        if len(topic.evidence) > MAX_EVIDENCE_PER_TOPIC:
            raise CandidateValidationError(
                f"{prefix}.evidence exceeds maximum of {MAX_EVIDENCE_PER_TOPIC}"
            )
        for evidence_index, evidence in enumerate(topic.evidence):
            _bounded(
                evidence.post_key,
                200,
                f"{prefix}.evidence[{evidence_index}].post_key",
            )
            _bounded(
                evidence.quote,
                MAX_QUOTE_CHARS,
                f"{prefix}.evidence[{evidence_index}].quote",
            )
    return ParsedCandidate(
        week=value["week"],
        bundle_digest=value["bundle_digest"],
        producer=producer,
        topics=topics,
        discarded_noise_notes=value["discarded_noise_notes"],
    )


def normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def _validate_url(url: str, path: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise CandidateValidationError(f"{path} trusted source URL must use http/https")
    if parts.username is not None or parts.password is not None:
        raise CandidateValidationError(f"{path} trusted source URL contains credentials")


def resource_kind(record: dict[str, Any]) -> str:
    channel = str(record["channel"])
    url = str(record["url"])
    if channel == "youtube":
        return "video"
    if channel == "github" and ("/issues/" in url or "/pull/" in url):
        return "issue"
    if channel in {"sam_gov", "grants_gov", "canadabuys"}:
        return "opportunity"
    if channel in {"reddit", "hackernews", "producthunt", "fake"}:
        return "discussion"
    if channel == "rss":
        return "article"
    return "other"


def enrich_topics(candidate: ParsedCandidate, bundle: AgentBundle) -> list[Topic]:
    if candidate.week != bundle.week:
        raise CandidateValidationError(
            f"candidate.week {candidate.week!r} does not match prepared week {bundle.week!r}"
        )
    if candidate.bundle_digest != bundle.records_digest:
        raise CandidateValidationError("candidate.bundle_digest does not match prepared bundle")
    records = {record.get("post_key"): record for record in bundle.records}
    if None in records or len(records) != len(bundle.records):
        raise CandidateValidationError("prepared bundle has invalid or duplicate post_key values")
    required_evidence = 2 if len(bundle.records) >= 2 else 1
    ids: set[str] = set()
    topics: list[Topic] = []
    for index, candidate_topic in enumerate(candidate.topics):
        prefix = f"topics[{index}]({candidate_topic.id})"
        expected_id = topic_slug(candidate_topic.title)
        if not expected_id or candidate_topic.id != expected_id:
            raise CandidateValidationError(
                f"{prefix}.id must equal deterministic title slug {expected_id!r}"
            )
        if candidate_topic.id in ids:
            raise CandidateValidationError(f"{prefix}.id duplicates an earlier topic")
        ids.add(candidate_topic.id)
        if len(candidate_topic.evidence) < required_evidence:
            raise CandidateValidationError(
                f"{prefix}.evidence requires at least {required_evidence} distinct posts"
            )
        evidence_keys: set[str] = set()
        evidence: list[Evidence] = []
        resources: list[Resource] = []
        resource_urls: set[str] = set()
        for evidence_index, candidate_evidence in enumerate(candidate_topic.evidence):
            evidence_path = f"{prefix}.evidence[{evidence_index}]"
            key = candidate_evidence.post_key
            if key in evidence_keys:
                raise CandidateValidationError(f"{evidence_path}.post_key is duplicated")
            evidence_keys.add(key)
            record = records.get(key)
            if record is None:
                raise CandidateValidationError(
                    f"{evidence_path}.post_key {key!r} is not in prepared bundle"
                )
            quote = normalize_whitespace(candidate_evidence.quote)
            haystacks = (
                normalize_whitespace(str(record.get("title", ""))),
                normalize_whitespace(str(record.get("body", ""))),
            )
            if not quote or not any(quote in text for text in haystacks):
                raise CandidateValidationError(
                    f"{evidence_path}.quote is not an exact normalized-whitespace substring"
                )
            url = str(record.get("url", ""))
            _validate_url(url, f"{evidence_path}.url")
            enriched = Evidence(
                post_key=key,
                channel=str(record["channel"]),
                title=str(record.get("title", "")),
                url=url,
                author=str(record.get("author", "")),
                score=int(record.get("score", 0)),
                comments=int(record.get("comments", 0)),
                normalized_engagement=float(record.get("normalized_engagement", 0)),
                created_at=str(record.get("created_at", "")),
                retrieved_at=str(record.get("retrieved_at", "")),
                quote=candidate_evidence.quote,
            )
            evidence.append(enriched)
            if url not in resource_urls:
                resource_urls.add(url)
                resources.append(
                    Resource(
                        label=str(record.get("title") or f"{record['channel']} source"),
                        url=url,
                        kind=resource_kind(record),
                    )
                )
        engagement_score = round(
            sum(item.normalized_engagement for item in evidence), 6
        )
        topics.append(
            Topic(
                id=candidate_topic.id,
                title=candidate_topic.title,
                summary=candidate_topic.summary,
                who=candidate_topic.who,
                pain_class=candidate_topic.pain_class,
                signal_strength=candidate_topic.signal_strength,
                competition_level=candidate_topic.competition_level,
                existing_solutions=candidate_topic.existing_solutions,
                competition_rationale=candidate_topic.competition_rationale,
                engagement_score=engagement_score,
                evidence=evidence,
                resources=resources,
            )
        )
    return sorted(
        topics,
        key=lambda topic: (-topic.signal_strength, -topic.engagement_score, topic.id),
    )
