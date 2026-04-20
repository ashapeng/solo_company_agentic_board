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

from .model_assignment import tune_model_assignments
from .routing_compaction import tune_routing_and_compaction
from .tuning import tune_token_budgets, tune_verification_thresholds
from .ledger import query_outcomes


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

    review = HarnessReview(
        id=f"harness_review_{time.time_ns()}",
        created_at=datetime.now(timezone.utc).isoformat(),
        recommendations=recommendations,
        proposed_config_diff=reports,
        status="proposed",
        dry_run=dry_run,
    )
    _save_review(review.to_dict())
    return review.to_dict()


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
    _save_review(review)
    return review


def apply_harness_review(review_id: str) -> dict[str, Any]:
    review = _load_review(review_id)
    if review["status"] != "approved":
        raise HarnessReviewError("Harness review must be approved before apply.")

    applied: dict[str, Any] = {}
    for name, fn in (
        ("token_budgets", tune_token_budgets),
        ("verification_thresholds", tune_verification_thresholds),
        ("routing_compaction", tune_routing_and_compaction),
        ("model_assignments", tune_model_assignments),
    ):
        try:
            applied[name] = fn(dry_run=False).to_dict()
        except Exception as exc:
            applied[name] = {"error": str(exc)}

    review["status"] = "applied"
    review["applied_reports"] = applied
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
