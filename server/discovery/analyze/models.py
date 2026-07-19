from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any


PAIN_CLASSES = frozenset(
    {"hair_on_fire", "important", "nice_to_solve", "opportunity"}
)
COMPETITION_LEVELS = frozenset({"low", "moderate", "high", "saturated"})
RESOURCE_KINDS = frozenset(
    {"discussion", "video", "issue", "opportunity", "article", "other"}
)
PRODUCER_KIND = "ide_coding_agent"
BUNDLE_SCHEMA_VERSION = 1
CANDIDATE_SCHEMA_VERSION = 1
REPORT_SCHEMA_VERSION = 1


class ContractError(ValueError):
    """A portable discovery file does not match its declared contract."""


def _object(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{path} must be an object")
    return value


def _exact_fields(
    data: dict[str, Any], required: set[str], optional: set[str], path: str
) -> None:
    missing = required - data.keys()
    unknown = data.keys() - required - optional
    if missing:
        raise ContractError(f"{path} missing required field: {sorted(missing)[0]}")
    if unknown:
        raise ContractError(f"{path} has unknown field: {sorted(unknown)[0]}")


def _string(value: Any, path: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ContractError(f"{path} must be a non-empty string")
    return value


def _integer(value: Any, path: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContractError(f"{path} must be an integer >= {minimum}")
    return value


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{path} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ContractError(f"{path} must be finite")
    return result


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContractError(f"{path} must be a list")
    return value


def topic_slug(value: str) -> str:
    """Return stable ASCII topic identifier derived from a title."""
    slug = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return slug[:80].rstrip("-")


@dataclass(frozen=True)
class Producer:
    kind: str
    name: str
    run_id: str

    def __post_init__(self) -> None:
        if self.kind != PRODUCER_KIND:
            raise ContractError(f"producer.kind must equal {PRODUCER_KIND!r}")
        _string(self.name, "producer.name")
        _string(self.run_id, "producer.run_id", allow_empty=True)

    @classmethod
    def from_dict(cls, value: Any, path: str = "producer") -> Producer:
        data = _object(value, path)
        _exact_fields(data, {"kind", "name", "run_id"}, set(), path)
        return cls(
            kind=_string(data["kind"], f"{path}.kind"),
            name=_string(data["name"], f"{path}.name"),
            run_id=_string(data["run_id"], f"{path}.run_id", allow_empty=True),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AgentBundle:
    schema_version: int
    week: str
    generated_at: str
    post_count: int
    selected_post_count: int
    records_digest: str
    records: list[dict[str, Any]]
    constraints: dict[str, Any]

    @classmethod
    def from_dict(cls, value: Any) -> AgentBundle:
        data = _object(value, "bundle")
        required = {
            "schema_version", "week", "generated_at", "post_count",
            "selected_post_count", "records_digest", "records", "constraints",
        }
        _exact_fields(data, required, set(), "bundle")
        version = _integer(data["schema_version"], "bundle.schema_version", minimum=1)
        if version != BUNDLE_SCHEMA_VERSION:
            raise ContractError(f"unsupported bundle.schema_version: {version}")
        records = _list(data["records"], "bundle.records")
        record_fields = {
            "post_key", "channel", "source", "title", "body", "url", "author",
            "score", "comments", "normalized_engagement", "created_at", "retrieved_at",
        }
        for index, item in enumerate(records):
            record = _object(item, f"bundle.records[{index}]")
            _exact_fields(record, record_fields, set(), f"bundle.records[{index}]")
            for field in (
                "post_key", "channel", "source", "title", "body", "url", "author",
                "created_at", "retrieved_at",
            ):
                _string(
                    record[field],
                    f"bundle.records[{index}].{field}",
                    allow_empty=field not in {"post_key", "channel", "url"},
                )
            _integer(record["score"], f"bundle.records[{index}].score")
            _integer(record["comments"], f"bundle.records[{index}].comments")
            normalized = _number(
                record["normalized_engagement"],
                f"bundle.records[{index}].normalized_engagement",
            )
            if not 0 <= normalized <= 1:
                raise ContractError(
                    f"bundle.records[{index}].normalized_engagement must be between 0 and 1"
                )
        selected = _integer(data["selected_post_count"], "bundle.selected_post_count")
        if selected != len(records):
            raise ContractError("bundle.selected_post_count does not match records")
        post_count = _integer(data["post_count"], "bundle.post_count")
        if post_count < selected:
            raise ContractError("bundle.post_count cannot be smaller than selected_post_count")
        constraints = _object(data["constraints"], "bundle.constraints")
        return cls(
            schema_version=version,
            week=_string(data["week"], "bundle.week"),
            generated_at=_string(data["generated_at"], "bundle.generated_at"),
            post_count=post_count,
            selected_post_count=selected,
            records_digest=_string(data["records_digest"], "bundle.records_digest"),
            records=records,
            constraints=constraints,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateEvidence:
    post_key: str
    quote: str

    @classmethod
    def from_dict(cls, value: Any, path: str) -> CandidateEvidence:
        data = _object(value, path)
        _exact_fields(data, {"post_key", "quote"}, set(), path)
        return cls(
            post_key=_string(data["post_key"], f"{path}.post_key"),
            quote=_string(data["quote"], f"{path}.quote"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateTopic:
    id: str
    title: str
    summary: str
    who: str
    pain_class: str
    signal_strength: float
    competition_level: str
    existing_solutions: str
    competition_rationale: str
    evidence: list[CandidateEvidence]

    @classmethod
    def from_dict(cls, value: Any, path: str = "topic") -> CandidateTopic:
        data = _object(value, path)
        required = {
            "id",
            "title",
            "summary",
            "who",
            "pain_class",
            "signal_strength",
            "competition_level",
            "existing_solutions",
            "competition_rationale",
            "evidence",
        }
        _exact_fields(data, required, set(), path)
        pain_class = _string(data["pain_class"], f"{path}.pain_class")
        if pain_class not in PAIN_CLASSES:
            raise ContractError(f"{path}.pain_class is unknown: {pain_class}")
        competition_level = _string(data["competition_level"], f"{path}.competition_level")
        if competition_level not in COMPETITION_LEVELS:
            raise ContractError(f"{path}.competition_level is unknown: {competition_level}")
        strength = _number(data["signal_strength"], f"{path}.signal_strength")
        if not 0 <= strength <= 1:
            raise ContractError(f"{path}.signal_strength must be between 0 and 1")
        raw_evidence = _list(data["evidence"], f"{path}.evidence")
        return cls(
            id=_string(data["id"], f"{path}.id"),
            title=_string(data["title"], f"{path}.title"),
            summary=_string(data["summary"], f"{path}.summary"),
            who=_string(data["who"], f"{path}.who"),
            pain_class=pain_class,
            signal_strength=strength,
            competition_level=competition_level,
            existing_solutions=_string(
                data["existing_solutions"], f"{path}.existing_solutions"
            ),
            competition_rationale=_string(
                data["competition_rationale"], f"{path}.competition_rationale"
            ),
            evidence=[CandidateEvidence.from_dict(e, f"{path}.evidence[{i}]") for i, e in enumerate(raw_evidence)],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Evidence:
    post_key: str
    channel: str
    title: str
    url: str
    author: str
    score: int
    comments: int
    normalized_engagement: float
    created_at: str
    retrieved_at: str
    quote: str

    @classmethod
    def from_dict(cls, value: Any, path: str = "evidence") -> Evidence:
        data = _object(value, path)
        required = {
            "post_key", "channel", "title", "url", "author", "score", "comments",
            "normalized_engagement", "created_at", "retrieved_at", "quote",
        }
        _exact_fields(data, required, set(), path)
        normalized = _number(data["normalized_engagement"], f"{path}.normalized_engagement")
        if not 0 <= normalized <= 1:
            raise ContractError(f"{path}.normalized_engagement must be between 0 and 1")
        return cls(
            post_key=_string(data["post_key"], f"{path}.post_key"),
            channel=_string(data["channel"], f"{path}.channel"),
            title=_string(data["title"], f"{path}.title", allow_empty=True),
            url=_string(data["url"], f"{path}.url"),
            author=_string(data["author"], f"{path}.author", allow_empty=True),
            score=_integer(data["score"], f"{path}.score"),
            comments=_integer(data["comments"], f"{path}.comments"),
            normalized_engagement=normalized,
            created_at=_string(data["created_at"], f"{path}.created_at", allow_empty=True),
            retrieved_at=_string(data["retrieved_at"], f"{path}.retrieved_at", allow_empty=True),
            quote=_string(data["quote"], f"{path}.quote"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Resource:
    label: str
    url: str
    kind: str

    def __post_init__(self) -> None:
        if self.kind not in RESOURCE_KINDS:
            raise ContractError(f"resource.kind is unknown: {self.kind}")

    @classmethod
    def from_dict(cls, value: Any, path: str = "resource") -> Resource:
        data = _object(value, path)
        _exact_fields(data, {"label", "url", "kind"}, set(), path)
        return cls(
            label=_string(data["label"], f"{path}.label"),
            url=_string(data["url"], f"{path}.url"),
            kind=_string(data["kind"], f"{path}.kind"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Topic:
    id: str
    title: str
    summary: str
    who: str
    pain_class: str
    signal_strength: float
    competition_level: str
    existing_solutions: str
    competition_rationale: str
    engagement_score: float
    evidence: list[Evidence] = field(default_factory=list)
    resources: list[Resource] = field(default_factory=list)

    @classmethod
    def from_dict(cls, value: Any, path: str = "topic") -> Topic:
        data = _object(value, path)
        required = {
            "id", "title", "summary", "who", "pain_class", "signal_strength",
            "competition_level", "existing_solutions", "competition_rationale",
            "engagement_score", "evidence", "resources",
        }
        _exact_fields(data, required, set(), path)
        pain = _string(data["pain_class"], f"{path}.pain_class")
        if pain not in PAIN_CLASSES:
            raise ContractError(f"{path}.pain_class is unknown: {pain}")
        competition = _string(data["competition_level"], f"{path}.competition_level")
        if competition not in COMPETITION_LEVELS:
            raise ContractError(f"{path}.competition_level is unknown: {competition}")
        evidence = _list(data["evidence"], f"{path}.evidence")
        resources = _list(data["resources"], f"{path}.resources")
        strength = _number(data["signal_strength"], f"{path}.signal_strength")
        if not 0 <= strength <= 1:
            raise ContractError(f"{path}.signal_strength must be between 0 and 1")
        engagement_score = _number(data["engagement_score"], f"{path}.engagement_score")
        if engagement_score < 0:
            raise ContractError(f"{path}.engagement_score must be non-negative")
        return cls(
            id=_string(data["id"], f"{path}.id"),
            title=_string(data["title"], f"{path}.title"),
            summary=_string(data["summary"], f"{path}.summary"),
            who=_string(data["who"], f"{path}.who"),
            pain_class=pain,
            signal_strength=strength,
            competition_level=competition,
            existing_solutions=_string(
                data["existing_solutions"], f"{path}.existing_solutions"
            ),
            competition_rationale=_string(
                data["competition_rationale"], f"{path}.competition_rationale"
            ),
            engagement_score=engagement_score,
            evidence=[Evidence.from_dict(e, f"{path}.evidence[{i}]") for i, e in enumerate(evidence)],
            resources=[Resource.from_dict(r, f"{path}.resources[{i}]") for i, r in enumerate(resources)],
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TopicReport:
    schema_version: int
    week: str
    generated_at: str
    producer: Producer
    bundle_digest: str
    post_count: int
    selected_post_count: int
    topics: list[Topic]
    discarded_noise_notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Any) -> TopicReport:
        data = _object(value, "report")
        required = {
            "schema_version", "week", "generated_at", "producer", "bundle_digest",
            "post_count", "selected_post_count", "topics", "discarded_noise_notes",
        }
        _exact_fields(data, required, set(), "report")
        version = _integer(data["schema_version"], "report.schema_version", minimum=1)
        if version != REPORT_SCHEMA_VERSION:
            raise ContractError(f"unsupported report.schema_version: {version}")
        topics = _list(data["topics"], "report.topics")
        return cls(
            schema_version=version,
            week=_string(data["week"], "report.week"),
            generated_at=_string(data["generated_at"], "report.generated_at"),
            producer=Producer.from_dict(data["producer"]),
            bundle_digest=_string(data["bundle_digest"], "report.bundle_digest"),
            post_count=_integer(data["post_count"], "report.post_count"),
            selected_post_count=_integer(data["selected_post_count"], "report.selected_post_count"),
            topics=[Topic.from_dict(t, f"report.topics[{i}]") for i, t in enumerate(topics)],
            discarded_noise_notes=_string(data["discarded_noise_notes"], "report.discarded_noise_notes", allow_empty=True),
        )
