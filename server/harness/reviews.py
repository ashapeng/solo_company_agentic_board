"""Approval-gated harness review artifacts.

This wraps the existing tuner phases in a review object. Running a review is
dry-run by default; applying a review reruns the tuners with writes enabled.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_config
from .model_assignment import tune_model_assignments
from .routing_compaction import tune_routing_and_compaction
from .tuning import tune_token_budgets, tune_verification_thresholds
from .ledger import query_outcomes
from .validate import validate_config


_REVIEWS_DIR = Path("data/harness_reviews")
_VALID_STATUSES = {"proposed", "approved", "rejected", "applied"}


class HarnessReviewError(Exception):
    """Raised when a harness review cannot be changed."""


@dataclass
class HarnessRecommendation:
    category: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HarnessReview:
    id: str
    created_at: str
    recommendations: list[HarnessRecommendation]
    proposed_config_diff: dict[str, Any] | None = None
    proposed_agent_changes: list[dict[str, Any]] = field(default_factory=list)
    status: str = "proposed"
    dry_run: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "recommendations": [item.to_dict() for item in self.recommendations],
            "proposed_config_diff": self.proposed_config_diff,
            "proposed_agent_changes": self.proposed_agent_changes,
            "status": self.status,
            "dry_run": self.dry_run,
        }


def run_harness_review(*, dry_run: bool = True) -> dict[str, Any]:
    """Run all available harness tuners and persist a review artifact."""
    recommendations: list[HarnessRecommendation] = []
    reports: dict[str, Any] = {}

    for name, fn in (
        ("token_budgets", lambda: tune_token_budgets(dry_run=True)),
        ("verification_thresholds", lambda: tune_verification_thresholds(dry_run=True)),
        ("routing_compaction", lambda: tune_routing_and_compaction(dry_run=True)),
        ("model_assignments", lambda: tune_model_assignments(dry_run=True)),
    ):
        try:
            report = fn().to_dict()
            reports[name] = report
            change_count = _change_count(report)
            if change_count:
                recommendations.append(HarnessRecommendation(
                    category=name,
                    summary=f"{change_count} harness change(s) proposed.",
                    details=report,
                ))
        except Exception as exc:
            recommendations.append(HarnessRecommendation(
                category=name,
                summary=f"{name} review failed.",
                details={"error": str(exc)},
            ))

    reliability = _reliability_recommendation()
    if reliability:
        recommendations.append(reliability)

    drift = _drift_recommendation()
    if drift:
        recommendations.append(drift)

    try:
        from .meta import tuner_accuracy
        accuracy = tuner_accuracy()
        if accuracy:
            recommendations.append(
                HarnessRecommendation(
                    category="meta",
                    summary="Historical tuner accuracy",
                    details=accuracy,
                )
            )
    except Exception as exc:  # defensive: never break a review because of meta
        recommendations.append(
            HarnessRecommendation(
                category="meta",
                summary="Tuner accuracy check failed.",
                details={"error": str(exc)},
            )
        )

    # Phase 1 validate.py integration (spec §4.3, §4.4).
    validation_payload: dict
    try:
        candidate_snapshot = load_config()
        validation_report = validate_config(candidate_snapshot)
        validation_payload = validation_report.to_dict()
    except Exception as exc:
        recommendations.append(HarnessRecommendation(
            category="validation",
            summary="validation check failed",
            details={"error": str(exc)},
        ))
        validation_payload = {
            "ok": False,
            "readiness": "blocked",
            "errors": [],
            "warnings": [],
            "error": str(exc),
        }

    review = HarnessReview(
        id=f"harness_review_{time.time_ns()}",
        created_at=datetime.now(timezone.utc).isoformat(),
        recommendations=recommendations,
        proposed_config_diff=reports,
        status="proposed",
        dry_run=dry_run,
    )
    review_dict = review.to_dict()
    review_dict["validation"] = validation_payload
    _save_review(review_dict)
    return review_dict


def latest_harness_review() -> dict[str, Any] | None:
    if not _REVIEWS_DIR.exists():
        return None
    files = sorted(_REVIEWS_DIR.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        return None
    return json.loads(files[0].read_text(encoding="utf-8"))


def approve_harness_review(review_id: str, *, approve: bool = True) -> dict[str, Any]:
    review = _load_review(review_id)
    if review["status"] not in {"proposed", "approved", "rejected"}:
        raise HarnessReviewError(f"Review cannot be changed from status: {review['status']}")
    review["status"] = "approved" if approve else "rejected"
    if approve and "snapshot" not in review:
        review["snapshot"] = {
            "token_budgets": tune_token_budgets(dry_run=True).to_dict(),
            "verification_thresholds": tune_verification_thresholds(dry_run=True).to_dict(),
            "routing_compaction": tune_routing_and_compaction(dry_run=True).to_dict(),
            "model_assignments": tune_model_assignments(dry_run=True).to_dict(),
        }
    _save_review(review)
    return review


def apply_harness_review(review_id: str) -> dict[str, Any]:
    review = _load_review(review_id)
    if review["status"] != "approved":
        raise HarnessReviewError("Harness review must be approved before apply.")

    snapshot = review.get("snapshot")
    if not snapshot:
        raise HarnessReviewError("Approved review has no snapshot to apply.")

    from .config import save_config
    from .ledger import snapshot_activation

    previous = load_config()
    previous_snapshot = _config_to_snapshot(previous)
    updated = _apply_snapshot_to_config(previous, snapshot)
    save_config(updated)

    snapshot_activation(
        review_id=review_id,
        snapshot=snapshot,
        previous_snapshot=previous_snapshot,
    )

    review["status"] = "applied"
    review["applied_reports"] = snapshot
    review["applied_at"] = datetime.now(timezone.utc).isoformat()
    _save_review(review)
    return review


def _load_review(review_id: str) -> dict[str, Any]:
    path = _REVIEWS_DIR / f"{review_id}.json"
    if not path.exists():
        raise HarnessReviewError(f"Harness review not found: {review_id}")
    review = json.loads(path.read_text(encoding="utf-8"))
    if review.get("status") not in _VALID_STATUSES:
        raise HarnessReviewError("Harness review has invalid status.")
    return review


def _save_review(review: dict[str, Any]) -> None:
    _REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    path = _REVIEWS_DIR / f"{review['id']}.json"
    path.write_text(json.dumps(review, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _change_count(report: dict[str, Any]) -> int:
    return sum(
        len(report.get(key) or [])
        for key in ("changes", "routing_changes", "compaction_changes")
    )


def _config_to_snapshot(config) -> dict:
    """Serialize a HarnessConfig to a plain dict for activation auditing."""
    from dataclasses import asdict
    try:
        return asdict(config)
    except TypeError:
        # Fallback if HarnessConfig is not a plain dataclass.
        return {
            k: getattr(config, k)
            for k in dir(config)
            if not k.startswith("_") and not callable(getattr(config, k))
        }


def _apply_snapshot_to_config(config, snapshot):
    """Merge snapshot-reported preferences into the live config.

    V1 only implements model_assignments; the other tuner categories report
    empty `changes` lists from their dry-run invocations, so the per-change
    loop is a no-op for them. Follow-up tasks should extend _apply_change
    for those categories.
    """
    from copy import deepcopy
    updated = deepcopy(config)
    for category_key in (
        "token_budgets",
        "verification_thresholds",
        "routing_compaction",
        "model_assignments",
    ):
        report = snapshot.get(category_key) or {}
        for change in report.get("changes", []):
            _apply_change(updated, category_key, change)
    return updated


def _apply_change(config, category: str, change: dict) -> None:
    """Translate a tuner change dict into a config mutation (V1: model_assignments only)."""
    import dataclasses

    if category == "model_assignments":
        qt = change.get("query_type")
        member = change.get("member_id")
        model = change.get("new_model")
        if not (qt and member and model):
            return
        per_qt = dict(getattr(config, "per_query_type", {}) or {})
        entry = dict(per_qt.get(qt, {}))
        prefs = dict(entry.get("model_preferences", {}))
        prefs[member] = model
        entry["model_preferences"] = prefs
        per_qt[qt] = entry
        try:
            config.per_query_type = per_qt
        except dataclasses.FrozenInstanceError:
            setattr(config, "per_query_type", per_qt)


def _drift_recommendation() -> HarnessRecommendation | None:
    from .ledger import rolling_stats, distribution_shift

    try:
        verification = rolling_stats("verification_score")
        distribution = distribution_shift("query_type")
    except Exception as exc:
        return HarnessRecommendation(
            category="drift",
            summary="Drift check failed.",
            details={"error": str(exc)},
        )

    if verification.get("insufficient_samples"):
        return None

    import os

    try:
        score_threshold = float(
            os.getenv("AGENTIC_BOARD_DRIFT_SCORE_DELTA", "-0.5")
        )
    except ValueError:
        score_threshold = -0.5
    try:
        js_threshold = float(
            os.getenv("AGENTIC_BOARD_DRIFT_JS", "0.3")
        )
    except ValueError:
        js_threshold = 0.3

    notes: list[str] = []
    delta = verification.get("delta", 0.0)
    if isinstance(delta, (int, float)) and delta < score_threshold:
        notes.append(
            f"verification score regressed: delta={delta} "
            f"(recent={verification.get('recent_mean')}, "
            f"baseline={verification.get('baseline_mean')})"
        )
    js = distribution.get("js_distance", 0.0)
    if isinstance(js, (int, float)) and js > js_threshold:
        notes.append(
            f"classifier label distribution shifted: js={js}"
        )
    if not notes:
        return None
    return HarnessRecommendation(
        category="drift",
        summary="; ".join(notes),
        details={"verification": verification, "distribution": distribution},
    )


def _reliability_recommendation() -> HarnessRecommendation | None:
    try:
        rows = query_outcomes(limit=50)
    except Exception as exc:
        return HarnessRecommendation(
            category="reliability",
            summary="Reliability review failed.",
            details={"error": str(exc)},
        )
    if not rows:
        return None

    parse_failures = sum(1 for row in rows if row.get("structured_output_failed"))
    truncations = sum(1 for row in rows if row.get("truncation_detected"))
    blank_responses = sum(1 for row in rows if row.get("blank_member_responses") not in {None, "", "[]"})
    negative_feedback = sum(1 for row in rows if row.get("feedback_rating") == "negative")
    if not any((parse_failures, truncations, blank_responses, negative_feedback)):
        return None

    recommendations = []
    if truncations:
        recommendations.append("Review Stage 3/delegation token budgets for recurrent truncation.")
    if parse_failures:
        recommendations.append("Keep structured delegation generation on JSON-only retry path.")
    if blank_responses:
        recommendations.append("Review model assignments for members returning blank responses.")
    if negative_feedback:
        recommendations.append("Inspect negative feedback before applying tuner changes.")

    return HarnessRecommendation(
        category="reliability",
        summary=f"{len(recommendations)} reliability signal(s) need review.",
        details={
            "recent_sessions": len(rows),
            "parse_failures": parse_failures,
            "truncations": truncations,
            "blank_response_sessions": blank_responses,
            "negative_feedback_sessions": negative_feedback,
            "recommendations": recommendations,
        },
    )
