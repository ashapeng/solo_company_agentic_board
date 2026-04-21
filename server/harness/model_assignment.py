"""Phase E harness evolution: data-driven model assignment."""

from __future__ import annotations

import json
from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from .config import HarnessConfig, load_config, resolve_model_preferences, save_config
from .ledger import query_outcomes


MIN_MODEL_SAMPLES = 3
MIN_MODEL_SCORE_DELTA = 0.5


@dataclass(frozen=True)
class QualityObservation:
    verification: float | None
    feedback: str | None  # "positive" | "negative" | None


def _quality_observation(row: dict) -> QualityObservation | None:
    verification_score = row.get("verification_score")
    feedback_rating = row.get("feedback_rating")
    v: float | None = None
    if verification_score is not None:
        try:
            v = float(verification_score)
        except (TypeError, ValueError):
            v = None
    fb = feedback_rating if feedback_rating in ("positive", "negative") else None
    if v is None and fb is None:
        return None
    return QualityObservation(verification=v, feedback=fb)


def _group_observations_by_assignment(
    outcomes: list[dict],
) -> dict[tuple[str, str], dict[str, list[QualityObservation]]]:
    grouped: dict[tuple[str, str], dict[str, list[QualityObservation]]] = defaultdict(
        lambda: defaultdict(list),
    )
    for row in outcomes:
        query_type = row.get("query_type")
        if not query_type:
            continue
        obs = _quality_observation(row)
        if obs is None:
            continue
        for member_id, model in _models_used(row.get("models_used")).items():
            grouped[(str(query_type), member_id)][model].append(obs)
    return grouped


def _model_score(obs_list: list[QualityObservation]) -> tuple[float, int]:
    """Mean verification score (None-filtered). Returns (mean, sample_count)."""
    values = [o.verification for o in obs_list if o.verification is not None]
    if not values:
        return 0.0, 0
    return mean(values), len(values)


def _has_negative_feedback(obs_list: list[QualityObservation]) -> bool:
    return any(o.feedback == "negative" for o in obs_list)


def _has_positive_feedback(obs_list: list[QualityObservation]) -> bool:
    return any(o.feedback == "positive" for o in obs_list)


@dataclass(frozen=True)
class ModelPreferenceChange:
    query_type: str
    member_id: str
    previous_model: str | None
    new_model: str
    previous_score: float | None
    new_score: float
    sample_count: int
    runner_up_model: str | None
    runner_up_score: float | None


@dataclass(frozen=True)
class ModelAssignmentTuningReport:
    examined_assignments: int
    eligible_assignments: int
    changes: list[ModelPreferenceChange]
    saved: bool
    dry_run: bool
    config_version: int

    def to_dict(self) -> dict:
        return {
            "examined_assignments": self.examined_assignments,
            "eligible_assignments": self.eligible_assignments,
            "changes": [asdict(change) for change in self.changes],
            "saved": self.saved,
            "dry_run": self.dry_run,
            "config_version": self.config_version,
        }


def tune_model_assignments(
    *,
    db_path: Path | None = None,
    config_path: Path | None = None,
    min_samples: int = MIN_MODEL_SAMPLES,
    min_score_delta: float = MIN_MODEL_SCORE_DELTA,
    dry_run: bool = False,
) -> ModelAssignmentTuningReport:
    """Tune per-query/member model preferences from ledger quality signals."""
    config = load_config(config_path)
    working_config = deepcopy(config)
    outcomes = query_outcomes(db_path=db_path)

    changes, examined_assignments, eligible_assignments = _apply_model_assignment_tuning(
        working_config,
        outcomes,
        min_samples=min_samples,
        min_score_delta=min_score_delta,
    )

    saved = False
    if changes and not dry_run:
        save_config(working_config, config_path)
        saved = True

    return ModelAssignmentTuningReport(
        examined_assignments=examined_assignments,
        eligible_assignments=eligible_assignments,
        changes=changes,
        saved=saved,
        dry_run=dry_run,
        config_version=working_config.version,
    )


def _apply_model_assignment_tuning(
    config: HarnessConfig,
    outcomes: list[dict[str, Any]],
    *,
    min_samples: int,
    min_score_delta: float,
) -> tuple[list[ModelPreferenceChange], int, int]:
    grouped = _group_observations_by_assignment(outcomes)
    changes: list[ModelPreferenceChange] = []
    examined_assignments = 0
    eligible_assignments = 0

    for (query_type, member_id), model_obs in sorted(grouped.items()):
        if len(model_obs) < 2:
            continue
        examined_assignments += 1

        candidates = {
            model: obs_list
            for model, obs_list in model_obs.items()
            if sum(1 for o in obs_list if o.verification is not None) >= min_samples
        }
        if len(candidates) < 2:
            continue
        eligible_assignments += 1

        ranked = sorted(
            (
                (model, *_model_score(obs))
                for model, obs in candidates.items()
            ),
            key=lambda item: (item[1], item[2], item[0]),
            reverse=True,
        )
        best_model, best_score, best_count = ranked[0]
        runner_up_model, runner_up_score, _ = ranked[1]

        # Gate 1 — verification-score delta.
        if best_score - runner_up_score < min_score_delta:
            continue

        best_obs = candidates[best_model]
        runner_obs = candidates[runner_up_model]

        # Gate 2 — feedback veto: only-negative signal blocks promotion.
        if _has_negative_feedback(best_obs) and not _has_positive_feedback(best_obs):
            continue
        # Gate 3 — feedback comparison: best cannot have negative feedback
        # when the runner-up has none.
        if _has_negative_feedback(best_obs) and not _has_negative_feedback(runner_obs):
            continue

        preferences = resolve_model_preferences(query_type=query_type, config=config)
        previous_model = preferences.get(member_id)
        if previous_model == best_model:
            continue

        previous_score = None
        if previous_model and previous_model in model_obs:
            previous_verif_values = [
                o.verification
                for o in model_obs[previous_model]
                if o.verification is not None
            ]
            if previous_verif_values:
                previous_score = round(mean(previous_verif_values), 4)

        _set_model_preference(config, query_type, member_id, best_model)
        changes.append(
            ModelPreferenceChange(
                query_type=query_type,
                member_id=member_id,
                previous_model=previous_model,
                new_model=best_model,
                previous_score=previous_score,
                new_score=round(best_score, 4),
                sample_count=best_count,
                runner_up_model=runner_up_model,
                runner_up_score=round(runner_up_score, 4),
            )
        )

    return changes, examined_assignments, eligible_assignments


def _models_used(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        raw = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if not isinstance(parsed, dict):
            return {}
        raw = parsed
    else:
        return {}

    return {
        str(member_id): model
        for member_id, model in raw.items()
        if isinstance(model, str) and model.strip()
    }


def _set_model_preference(
    config: HarnessConfig,
    query_type: str,
    member_id: str,
    model: str,
) -> None:
    query_config = _query_config(config, query_type)
    preferences = query_config.get("model_preferences")
    if not isinstance(preferences, dict):
        preferences = {}
        query_config["model_preferences"] = preferences
    preferences[member_id] = model


def _query_config(config: HarnessConfig, query_type: str) -> dict:
    if not isinstance(config.per_query_type, dict):
        config.per_query_type = {}
    query_config = config.per_query_type.get(query_type)
    if not isinstance(query_config, dict):
        query_config = {}
        config.per_query_type[query_type] = query_config
    return query_config
