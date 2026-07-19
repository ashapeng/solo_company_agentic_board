from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from server.board.portfolio import PortfolioDecision, PortfolioReviewResult
from server.discovery.lifecycle import CandidateStore, ValidationState
from server.initiatives import activate_initiative, create_initiative
from server.ventures import create_venture, get_venture

from .landing.models import LandingPageArtifact
from .landing.publisher import LandingPagePublisher
from .models import ExperimentStatus, ValidationExperiment
from .store import ExperimentStore


class ExperimentService:
    def __init__(self, *, store: ExperimentStore, candidate_store: CandidateStore,
                 db_path: Path | None = None,
                 create_venture_fn: Callable[..., dict[str, Any]] = create_venture,
                 get_venture_fn: Callable[..., dict[str, Any] | None] = get_venture,
                 create_initiative_fn: Callable[..., dict[str, Any]] = create_initiative,
                 activate_initiative_fn: Callable[..., dict[str, Any]] = activate_initiative):
        self.store = store
        self.candidate_store = candidate_store
        self.db_path = db_path or store.db_path
        self.create_venture_fn = create_venture_fn
        self.get_venture_fn = get_venture_fn
        self.create_initiative_fn = create_initiative_fn
        self.activate_initiative_fn = activate_initiative_fn

    def create_selected(self, result: PortfolioReviewResult, *, maximum_active: int = 5,
                        now: datetime | None = None) -> list[ValidationExperiment]:
        selected = sorted((item for item in result.decisions if item.selected_for_validation),
                          key=lambda item: item.rank)
        capacity = self.store.available_capacity(maximum_active)
        created: list[ValidationExperiment] = []
        for decision in selected:
            existing = self.store.get_for_candidate_review(decision.candidate_id, result.review_id)
            if existing:
                created.append(existing); continue
            if capacity <= 0:
                self.candidate_store.update(decision.candidate_id, actor="system",
                                            reason="validation capacity exhausted",
                                            validation_state=ValidationState.QUEUED,
                                            related_session_id=result.board_session_id)
                continue
            created.append(self._create_one(decision, result, now=now))
            capacity -= 1
        return created

    def _create_one(self, decision: PortfolioDecision, result: PortfolioReviewResult,
                    *, now: datetime | None) -> ValidationExperiment:
        candidate = self.candidate_store.get(decision.candidate_id)
        suffix = candidate.id.removeprefix("cand_")
        venture_id = f"venture_{suffix}"
        venture = self.get_venture_fn(venture_id, db_path=self.db_path)
        if venture is None:
            venture = self.create_venture_fn(candidate.title, venture_id=venture_id,
                                             slug=f"{candidate.title_slug[:25]}-{suffix[:8]}", db_path=self.db_path)
        initiative_id = f"init_validation_{suffix}_{result.review_id.removeprefix('review_')[:12]}"
        initiative = self.create_initiative_fn(
            title=f"Validate: {candidate.title}",
            objective=f"Falsify this critical assumption: {decision.critical_assumption}",
            success_criteria=["Minimal landing page is ready", f"At least {decision.minimum_exposure} qualified visits",
                              *decision.success_signals, "Day-7 decision is recorded"],
            departments=["validation"], created_from="board_suggestion",
            source_session_id=result.board_session_id, venture_id=venture["id"],
            initiative_id=initiative_id, db_path=self.db_path,
        )
        initiative = self.activate_initiative_fn(initiative["id"], db_path=self.db_path)
        start = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        experiment = ValidationExperiment(
            id=f"exp_{uuid4().hex}", candidate_id=candidate.id,
            portfolio_review_id=result.review_id, board_session_id=result.board_session_id,
            venture_id=venture["id"], initiative_id=initiative["id"],
            hypothesis=f"{candidate.audience} will take a measurable validation action because {candidate.summary}",
            critical_assumption=decision.critical_assumption, experiment_type="landing_page",
            success_signals=decision.success_signals, stop_conditions=decision.stop_conditions,
            minimum_exposure=decision.minimum_exposure, starts_at=start.isoformat(),
            review_at=(start + timedelta(days=7)).isoformat(),
            expires_at=(start + timedelta(days=14)).isoformat(),
            created_at=start.isoformat(), updated_at=start.isoformat(),
        )
        stored = self.store.create(experiment)
        self.candidate_store.update(candidate.id, actor="system", reason="selected by portfolio review",
                                    validation_state=ValidationState.VALIDATING,
                                    related_session_id=result.board_session_id,
                                    related_experiment_id=stored.id)
        return stored

    def publish_fake(self, experiment_id: str, artifact: LandingPageArtifact,
                     publisher: LandingPagePublisher) -> ValidationExperiment:
        if publisher.is_external:
            raise ValueError("Slice A only permits a non-external fake publisher")
        experiment = self.store.get(experiment_id)
        if experiment is None:
            raise KeyError(experiment_id)
        if artifact.experiment_id != experiment_id:
            raise ValueError("artifact experiment ID mismatch")
        if experiment.status is ExperimentStatus.DRAFT:
            experiment = self.store.transition(experiment_id, ExperimentStatus.GENERATING,
                                               actor="system", reason="generate fake landing artifact")
        if experiment.status is ExperimentStatus.GENERATING:
            experiment = self.store.transition(experiment_id, ExperimentStatus.READY_TO_PUBLISH,
                                               actor="system", reason="fake artifact ready")
        result = publisher.publish(artifact, idempotency_key=f"landing:{experiment_id}")
        return self.store.transition(experiment_id, ExperimentStatus.PUBLISHED, actor="system",
                                     reason="fake publisher completed", deployment=result.to_dict())
