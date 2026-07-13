from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import math
from typing import Any
from uuid import UUID

from server.discovery.analyze.models import Evidence, PAIN_CLASSES, Resource, topic_slug


CANDIDATE_SCHEMA_VERSION = 2


class LifecycleContractError(ValueError):
    """A durable candidate file does not match its declared contract."""


class DiscoveryStatus(StrEnum):
    NEW = "new"
    READY_FOR_BOARD = "ready_for_board"
    UNDER_BOARD_REVIEW = "under_board_review"
    REVIEWED = "reviewed"


class BoardLabel(StrEnum):
    PRIORITIZE = "prioritize"
    INVESTIGATE = "investigate"
    DEFER = "defer"
    REJECT = "reject"


class FounderDisposition(StrEnum):
    ACTIVE = "active"
    OVERRIDDEN = "overridden"
    DISPOSED = "disposed"


class ValidationState(StrEnum):
    NOT_SELECTED = "not_selected"
    QUEUED = "queued"
    VALIDATING = "validating"
    VALIDATED = "validated"
    ITERATE = "iterate"
    INCONCLUSIVE = "inconclusive"
    REJECTED = "rejected"


# Legacy enum retained for explicit compatibility commands and migration only.
class CandidateStatus(StrEnum):
    NEW = "new"
    SHORTLISTED = "shortlisted"
    REJECTED = "rejected"
    PROMOTED = "promoted"
    BOARD_STARTED = "board_started"


_LEGACY_TRANSITIONS = {
    CandidateStatus.NEW: {CandidateStatus.SHORTLISTED, CandidateStatus.REJECTED, CandidateStatus.PROMOTED},
    CandidateStatus.SHORTLISTED: {CandidateStatus.REJECTED, CandidateStatus.PROMOTED},
    CandidateStatus.REJECTED: set(), CandidateStatus.PROMOTED: {CandidateStatus.BOARD_STARTED},
    CandidateStatus.BOARD_STARTED: set(),
}


def allowed_transition(current: CandidateStatus, target: CandidateStatus) -> bool:
    return target in _LEGACY_TRANSITIONS[current]


@dataclass(frozen=True)
class AuditEvent:
    actor: str
    field: str
    previous_value: Any
    new_value: Any
    reason: str
    occurred_at: str
    related_session_id: str | None = None
    related_experiment_id: str | None = None

    @classmethod
    def from_dict(cls, value: Any, path: str = "audit_event") -> AuditEvent:
        data = _mapping(value, path)
        required = {
            "actor", "field", "previous_value", "new_value", "reason",
            "occurred_at", "related_session_id", "related_experiment_id",
        }
        _exact_fields(data, required, path)
        for key in ("actor", "field", "reason", "occurred_at"):
            _nonempty(data[key], f"{path}.{key}")
        for key in ("related_session_id", "related_experiment_id"):
            if data[key] is not None and not isinstance(data[key], str):
                raise LifecycleContractError(f"{path}.{key} must be a string or null")
        return cls(**data)


def _nonempty(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LifecycleContractError(f"{path} must be a non-empty string")
    return value


def _mapping(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LifecycleContractError(f"{path} must be an object")
    return value


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise LifecycleContractError(f"{path} must be a list")
    return value


def _exact_fields(data: dict[str, Any], required: set[str], path: str) -> None:
    missing = required - data.keys()
    unknown = data.keys() - required
    if missing:
        raise LifecycleContractError(f"{path} missing required field: {sorted(missing)[0]}")
    if unknown:
        raise LifecycleContractError(f"{path} has unknown field: {sorted(unknown)[0]}")


@dataclass(frozen=True)
class Candidate:
    schema_version: int
    id: str
    title_slug: str
    report_week: str
    report_digest: str
    producer_run_id: str
    title: str
    summary: str
    audience: str
    pain_class: str
    signal_strength: float
    engagement_score: float
    evidence: list[Evidence]
    resources: list[Resource]
    # Compatibility projection for pre-v2 local callers. The four fields below
    # are authoritative; new flow code never makes decisions from this value.
    status: CandidateStatus = CandidateStatus.SHORTLISTED
    discovery_status: DiscoveryStatus = DiscoveryStatus.READY_FOR_BOARD
    board_label: BoardLabel | None = None
    founder_disposition: FounderDisposition = FounderDisposition.ACTIVE
    validation_state: ValidationState = ValidationState.NOT_SELECTED
    board_rank: int | None = None
    board_rationale: str | None = None
    audit_events: list[AuditEvent] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    founder_decisions: list[dict[str, Any]] = field(default_factory=list)
    promotion: dict[str, Any] | None = None
    board_sessions: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if self.schema_version != CANDIDATE_SCHEMA_VERSION:
            raise LifecycleContractError(
                f"unsupported candidate.schema_version: {self.schema_version}"
            )
        if not self.id.startswith("cand_"):
            raise LifecycleContractError("candidate.id must start with 'cand_'")
        try:
            UUID(hex=self.id.removeprefix("cand_"))
        except (ValueError, AttributeError) as exc:
            raise LifecycleContractError("candidate.id must contain a UUID") from exc
        for name in (
            "id", "title_slug", "report_week", "report_digest", "producer_run_id",
            "title", "summary", "audience", "pain_class", "created_at", "updated_at",
        ):
            _nonempty(getattr(self, name), f"candidate.{name}")
        if self.title_slug != topic_slug(self.title_slug):
            raise LifecycleContractError("candidate.title_slug must be a normalized slug")
        if self.pain_class not in PAIN_CLASSES:
            raise LifecycleContractError(f"candidate.pain_class is unknown: {self.pain_class}")
        for name in ("signal_strength", "engagement_score"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise LifecycleContractError(f"candidate.{name} must be a non-negative number")
        if self.signal_strength > 1:
            raise LifecycleContractError("candidate.signal_strength must be between 0 and 1")
        if not isinstance(self.status, CandidateStatus):
            raise LifecycleContractError("candidate.status compatibility projection is invalid")
        if not isinstance(self.discovery_status, DiscoveryStatus):
            raise LifecycleContractError("candidate.discovery_status is invalid")
        if self.board_label is not None and not isinstance(self.board_label, BoardLabel):
            raise LifecycleContractError("candidate.board_label is invalid")
        if not isinstance(self.founder_disposition, FounderDisposition):
            raise LifecycleContractError("candidate.founder_disposition is invalid")
        if not isinstance(self.validation_state, ValidationState):
            raise LifecycleContractError("candidate.validation_state is invalid")
        if self.board_rank is not None and (isinstance(self.board_rank, bool) or self.board_rank < 1):
            raise LifecycleContractError("candidate.board_rank must be a positive integer or null")
        if self.board_rationale is not None and not isinstance(self.board_rationale, str):
            raise LifecycleContractError("candidate.board_rationale must be a string or null")
        _mapping(self.provenance, "candidate.provenance")
        for name in ("founder_decisions", "board_sessions"):
            for index, item in enumerate(_list(getattr(self, name), f"candidate.{name}")):
                _mapping(item, f"candidate.{name}[{index}]")
        if self.promotion is not None:
            _mapping(self.promotion, "candidate.promotion")

    @classmethod
    def from_dict(cls, value: Any) -> Candidate:
        data = _mapping(value, "candidate")
        required = {
            "schema_version", "id", "title_slug", "report_week", "report_digest",
            "producer_run_id", "title", "summary", "audience", "pain_class",
            "signal_strength", "engagement_score", "evidence", "resources",
            "status",
            "discovery_status", "board_label", "founder_disposition", "validation_state",
            "board_rank", "board_rationale", "audit_events", "provenance",
            "founder_decisions", "promotion", "board_sessions", "created_at", "updated_at",
        }
        _exact_fields(data, required, "candidate")
        evidence = _list(data["evidence"], "candidate.evidence")
        resources = _list(data["resources"], "candidate.resources")
        events = _list(data["audit_events"], "candidate.audit_events")
        try:
            return cls(
                **{key: data[key] for key in required - {
                    "evidence", "resources", "discovery_status", "board_label",
                    "founder_disposition", "validation_state", "audit_events", "status",
                }},
                evidence=[Evidence.from_dict(item, f"candidate.evidence[{i}]") for i, item in enumerate(evidence)],
                resources=[Resource.from_dict(item, f"candidate.resources[{i}]") for i, item in enumerate(resources)],
                status=CandidateStatus(data["status"]),
                discovery_status=DiscoveryStatus(data["discovery_status"]),
                board_label=BoardLabel(data["board_label"]) if data["board_label"] is not None else None,
                founder_disposition=FounderDisposition(data["founder_disposition"]),
                validation_state=ValidationState(data["validation_state"]),
                audit_events=[AuditEvent.from_dict(item, f"candidate.audit_events[{i}]") for i, item in enumerate(events)],
            )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, LifecycleContractError):
                raise
            raise LifecycleContractError(f"invalid candidate: {exc}") from exc

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["discovery_status"] = self.discovery_status.value
        data["board_label"] = self.board_label.value if self.board_label else None
        data["founder_disposition"] = self.founder_disposition.value
        data["validation_state"] = self.validation_state.value
        return data
