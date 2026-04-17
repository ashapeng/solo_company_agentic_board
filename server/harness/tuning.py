"""Automatic harness tuning from the session outcome ledger."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict, dataclass
from math import ceil
from pathlib import Path
from statistics import median
from typing import Any

from .config import (
    HarnessConfig,
    load_config,
    resolve_stage_max_tokens,
    resolve_verification_threshold,
    save_config,
)
from .ledger import query_outcomes


MIN_SESSIONS_PER_SEGMENT = 3
SHRINK_THRESHOLD = 0.5
SHRINK_HEADROOM = 1.3
EXPAND_THRESHOLD = 0.9
EXPAND_HEADROOM = 1.2
MIN_FEEDBACK_SESSIONS_PER_QUERY_TYPE = 20
VERIFICATION_THRESHOLD_STEP = 0.5
VERIFICATION_THRESHOLD_FLOOR = 1.0
VERIFICATION_THRESHOLD_CEILING = 10.0

TOKEN_BUDGET_FIELDS = {
    1: ("stage1_tokens", "stage1_max_tokens"),
    2: ("stage2_tokens", "stage2_max_tokens"),
    3: ("stage3_tokens", "stage3_max_tokens"),
}

TOKEN_BUDGET_FLOORS = {
    "stage1_max_tokens": 400,
    "stage2_max_tokens": 250,
    "stage3_max_tokens": 1000,
}

TOKEN_BUDGET_CEILINGS = {
    "stage1_max_tokens": 4000,
    "stage2_max_tokens": 2500,
    "stage3_max_tokens": 10000,
}


@dataclass(frozen=True)
class TokenBudgetChange:
    query_type: str
    complexity: str
    stage: int
    field: str
    previous_budget: int
    new_budget: int
    median_usage: float
    session_count: int
    direction: str


@dataclass(frozen=True)
class TokenBudgetTuningReport:
    examined_segments: int
    eligible_segments: int
    changes: list[TokenBudgetChange]
    saved: bool
    dry_run: bool
    config_version: int

    def to_dict(self) -> dict:
        return {
            "examined_segments": self.examined_segments,
            "eligible_segments": self.eligible_segments,
            "changes": [asdict(change) for change in self.changes],
            "saved": self.saved,
            "dry_run": self.dry_run,
            "config_version": self.config_version,
        }


@dataclass(frozen=True)
class VerificationThresholdChange:
    query_type: str
    previous_threshold: float
    new_threshold: float
    feedback_count: int
    false_passes: int
    false_fails: int
    direction: str


@dataclass(frozen=True)
class VerificationThresholdTuningReport:
    examined_query_types: int
    eligible_query_types: int
    changes: list[VerificationThresholdChange]
    saved: bool
    dry_run: bool
    config_version: int

    def to_dict(self) -> dict:
        return {
            "examined_query_types": self.examined_query_types,
            "eligible_query_types": self.eligible_query_types,
            "changes": [asdict(change) for change in self.changes],
            "saved": self.saved,
            "dry_run": self.dry_run,
            "config_version": self.config_version,
        }


def tune_token_budgets(
    *,
    db_path: Path | None = None,
    config_path: Path | None = None,
    min_sessions: int = MIN_SESSIONS_PER_SEGMENT,
    dry_run: bool = False,
) -> TokenBudgetTuningReport:
    """Tune per-query/complexity stage token budgets from ledger medians."""
    config = load_config(config_path)
    working_config = deepcopy(config)
    outcomes = query_outcomes(db_path=db_path)

    changes, examined_segments, eligible_segments = _apply_token_budget_tuning(
        working_config,
        outcomes,
        min_sessions=min_sessions,
    )

    saved = False
    if changes and not dry_run:
        save_config(working_config, config_path)
        saved = True

    return TokenBudgetTuningReport(
        examined_segments=examined_segments,
        eligible_segments=eligible_segments,
        changes=changes,
        saved=saved,
        dry_run=dry_run,
        config_version=working_config.version,
    )


def tune_verification_thresholds(
    *,
    db_path: Path | None = None,
    config_path: Path | None = None,
    min_feedback_sessions: int = MIN_FEEDBACK_SESSIONS_PER_QUERY_TYPE,
    dry_run: bool = False,
) -> VerificationThresholdTuningReport:
    """Tune per-query verification thresholds from founder feedback."""
    config = load_config(config_path)
    working_config = deepcopy(config)
    outcomes = query_outcomes(db_path=db_path)

    changes, examined_query_types, eligible_query_types = _apply_verification_threshold_tuning(
        working_config,
        outcomes,
        min_feedback_sessions=min_feedback_sessions,
    )

    saved = False
    if changes and not dry_run:
        save_config(working_config, config_path)
        saved = True

    return VerificationThresholdTuningReport(
        examined_query_types=examined_query_types,
        eligible_query_types=eligible_query_types,
        changes=changes,
        saved=saved,
        dry_run=dry_run,
        config_version=working_config.version,
    )


def _apply_token_budget_tuning(
    config: HarnessConfig,
    outcomes: list[dict[str, Any]],
    *,
    min_sessions: int,
) -> tuple[list[TokenBudgetChange], int, int]:
    segments = _group_by_segment(outcomes)
    changes: list[TokenBudgetChange] = []
    eligible_segments = 0

    for (query_type, complexity), rows in sorted(segments.items()):
        if len(rows) < min_sessions:
            continue
        eligible_segments += 1

        for stage, (ledger_field, config_field) in TOKEN_BUDGET_FIELDS.items():
            samples = _positive_token_samples(rows, ledger_field)
            if len(samples) < min_sessions:
                continue

            actual_usage = median(samples)
            current_budget = resolve_stage_max_tokens(
                stage,
                query_type=query_type,
                complexity=complexity,
                config=config,
            )
            new_budget, direction = _calibrated_budget(
                actual_usage,
                current_budget,
                floor=TOKEN_BUDGET_FLOORS[config_field],
                ceiling=TOKEN_BUDGET_CEILINGS[config_field],
            )
            if direction is None or new_budget == current_budget:
                continue

            _set_token_budget(config, query_type, complexity, config_field, new_budget)
            changes.append(TokenBudgetChange(
                query_type=query_type,
                complexity=complexity,
                stage=stage,
                field=config_field,
                previous_budget=current_budget,
                new_budget=new_budget,
                median_usage=float(actual_usage),
                session_count=len(samples),
                direction=direction,
            ))

    return changes, len(segments), eligible_segments


def _apply_verification_threshold_tuning(
    config: HarnessConfig,
    outcomes: list[dict[str, Any]],
    *,
    min_feedback_sessions: int,
) -> tuple[list[VerificationThresholdChange], int, int]:
    segments = _group_feedback_by_query_type(outcomes)
    changes: list[VerificationThresholdChange] = []
    eligible_query_types = 0

    for query_type, rows in sorted(segments.items()):
        if len(rows) < min_feedback_sessions:
            continue
        eligible_query_types += 1

        false_passes = sum(
            1
            for row in rows
            if _verification_passed(row.get("verification_passed"))
            and row.get("feedback_rating") == "negative"
        )
        false_fails = sum(
            1
            for row in rows
            if _verification_failed(row.get("verification_passed"))
            and row.get("feedback_rating") == "positive"
        )
        if false_passes == false_fails:
            continue

        previous_threshold = _resolve_threshold(config, query_type)
        if false_passes > false_fails:
            new_threshold = min(
                previous_threshold + VERIFICATION_THRESHOLD_STEP,
                VERIFICATION_THRESHOLD_CEILING,
            )
            direction = "increase"
        else:
            new_threshold = max(
                previous_threshold - VERIFICATION_THRESHOLD_STEP,
                VERIFICATION_THRESHOLD_FLOOR,
            )
            direction = "decrease"

        new_threshold = round(new_threshold, 2)
        if new_threshold == previous_threshold:
            continue

        _set_verification_threshold(config, query_type, new_threshold)
        changes.append(VerificationThresholdChange(
            query_type=query_type,
            previous_threshold=previous_threshold,
            new_threshold=new_threshold,
            feedback_count=len(rows),
            false_passes=false_passes,
            false_fails=false_fails,
            direction=direction,
        ))

    return changes, len(segments), eligible_query_types


def _group_by_segment(outcomes: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    segments: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in outcomes:
        query_type = row.get("query_type")
        complexity = row.get("complexity")
        if not query_type or not complexity:
            continue
        segments[(str(query_type), str(complexity))].append(row)
    return segments


def _group_feedback_by_query_type(outcomes: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    segments: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in outcomes:
        query_type = row.get("query_type")
        feedback_rating = row.get("feedback_rating")
        verification_passed = row.get("verification_passed")
        if not query_type or feedback_rating not in {"positive", "negative"}:
            continue
        if not _is_verification_passed_value(verification_passed):
            continue
        segments[str(query_type)].append(row)
    return segments


def _positive_token_samples(rows: list[dict[str, Any]], field: str) -> list[int]:
    samples: list[int] = []
    for row in rows:
        value = row.get(field)
        if isinstance(value, bool) or value is None:
            continue
        try:
            token_count = int(value)
        except (TypeError, ValueError):
            continue
        if token_count > 0:
            samples.append(token_count)
    return samples


def _is_verification_passed_value(value: Any) -> bool:
    return value in {0, 1, True, False, "0", "1", "true", "false", "True", "False"}


def _verification_passed(value: Any) -> bool:
    return value in {1, True, "1", "true", "True"}


def _verification_failed(value: Any) -> bool:
    return value in {0, False, "0", "false", "False"}


def _resolve_threshold(config: HarnessConfig, query_type: str) -> float:
    return resolve_verification_threshold(query_type=query_type, config=config)


def _calibrated_budget(
    actual_usage: float,
    current_budget: int,
    *,
    floor: int,
    ceiling: int,
) -> tuple[int, str | None]:
    if actual_usage < SHRINK_THRESHOLD * current_budget:
        return max(ceil(actual_usage * SHRINK_HEADROOM), floor), "shrink"
    if actual_usage > EXPAND_THRESHOLD * current_budget:
        return min(ceil(actual_usage * EXPAND_HEADROOM), ceiling), "expand"
    return current_budget, None


def _set_token_budget(
    config: HarnessConfig,
    query_type: str,
    complexity: str,
    field: str,
    value: int,
) -> None:
    if not isinstance(config.per_query_type, dict):
        config.per_query_type = {}

    query_config = config.per_query_type.get(query_type)
    if not isinstance(query_config, dict):
        query_config = {}
        config.per_query_type[query_type] = query_config

    token_budgets = query_config.get("token_budgets")
    if not isinstance(token_budgets, dict):
        token_budgets = {}
        query_config["token_budgets"] = token_budgets

    complexity_config = token_budgets.get(complexity)
    if not isinstance(complexity_config, dict):
        complexity_config = {}
        token_budgets[complexity] = complexity_config

    complexity_config[field] = value


def _set_verification_threshold(
    config: HarnessConfig,
    query_type: str,
    threshold: float,
) -> None:
    if not isinstance(config.per_query_type, dict):
        config.per_query_type = {}

    query_config = config.per_query_type.get(query_type)
    if not isinstance(query_config, dict):
        query_config = {}
        config.per_query_type[query_type] = query_config

    query_config["verification_threshold"] = threshold
