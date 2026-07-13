from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class ExperimentContractError(ValueError):
    pass


class ExperimentStatus(StrEnum):
    DRAFT = "draft"
    GENERATING = "generating"
    READY_TO_PUBLISH = "ready_to_publish"
    PUBLISHED = "published"
    COLLECTING = "collecting"
    REVIEW_DUE = "review_due"
    VALIDATED = "validated"
    ITERATE = "iterate"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"
    EXTENDED = "extended"


ACTIVE_EXPERIMENT_STATUSES = frozenset({
    ExperimentStatus.DRAFT, ExperimentStatus.GENERATING, ExperimentStatus.READY_TO_PUBLISH,
    ExperimentStatus.PUBLISHED, ExperimentStatus.COLLECTING, ExperimentStatus.REVIEW_DUE,
    ExperimentStatus.INCONCLUSIVE, ExperimentStatus.EXTENDED,
})

TRANSITIONS = {
    ExperimentStatus.DRAFT: {ExperimentStatus.GENERATING},
    ExperimentStatus.GENERATING: {ExperimentStatus.READY_TO_PUBLISH, ExperimentStatus.DRAFT},
    ExperimentStatus.READY_TO_PUBLISH: {ExperimentStatus.PUBLISHED, ExperimentStatus.DRAFT},
    ExperimentStatus.PUBLISHED: {ExperimentStatus.COLLECTING},
    ExperimentStatus.COLLECTING: {ExperimentStatus.REVIEW_DUE},
    ExperimentStatus.REVIEW_DUE: {ExperimentStatus.VALIDATED, ExperimentStatus.ITERATE,
                                  ExperimentStatus.REJECTED, ExperimentStatus.INCONCLUSIVE},
    ExperimentStatus.INCONCLUSIVE: {ExperimentStatus.EXTENDED},
    ExperimentStatus.EXTENDED: {ExperimentStatus.REVIEW_DUE},
    ExperimentStatus.VALIDATED: set(), ExperimentStatus.ITERATE: set(), ExperimentStatus.REJECTED: set(),
}


@dataclass(frozen=True)
class ValidationExperiment:
    id: str
    candidate_id: str
    portfolio_review_id: str
    board_session_id: str
    venture_id: str
    initiative_id: str
    hypothesis: str
    critical_assumption: str
    experiment_type: str
    success_signals: list[str]
    stop_conditions: list[str]
    minimum_exposure: int
    starts_at: str
    review_at: str
    expires_at: str
    status: ExperimentStatus = ExperimentStatus.DRAFT
    landing_page_deployment: dict[str, Any] | None = None
    distribution_packet_ids: list[str] = field(default_factory=list)
    latest_metrics: dict[str, Any] = field(default_factory=dict)
    decision_history: list[dict[str, Any]] = field(default_factory=list)
    extension_count: int = 0
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        for name in ("id", "candidate_id", "portfolio_review_id", "board_session_id", "venture_id",
                     "initiative_id", "hypothesis", "critical_assumption", "experiment_type",
                     "starts_at", "review_at", "expires_at", "created_at", "updated_at"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ExperimentContractError(f"experiment.{name} must be a non-empty string")
        if not self.id.startswith("exp_"):
            raise ExperimentContractError("experiment.id must start with exp_")
        if not isinstance(self.status, ExperimentStatus):
            raise ExperimentContractError("experiment.status is invalid")
        if not self.success_signals or not all(isinstance(x, str) and x.strip() for x in self.success_signals):
            raise ExperimentContractError("experiment.success_signals must contain strings")
        if not self.stop_conditions or not all(isinstance(x, str) and x.strip() for x in self.stop_conditions):
            raise ExperimentContractError("experiment.stop_conditions must contain strings")
        if isinstance(self.minimum_exposure, bool) or self.minimum_exposure < 1:
            raise ExperimentContractError("experiment.minimum_exposure must be positive")
        if self.extension_count not in {0, 1}:
            raise ExperimentContractError("experiment.extension_count must be zero or one")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> ValidationExperiment:
        data = dict(value)
        data["status"] = ExperimentStatus(data["status"])
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data
