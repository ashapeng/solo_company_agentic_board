"""Harness review routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from server.harness.reviews import (
    HarnessReviewError,
    apply_harness_review,
    approve_harness_review,
    latest_harness_review,
    run_harness_review,
)

from ..schemas import HarnessReviewApprovalRequest, HarnessReviewRunRequest


router = APIRouter()


@router.post("/harness/review/run")
async def run_harness_review_endpoint(req: HarnessReviewRunRequest):
    return run_harness_review(dry_run=req.dry_run)


@router.get("/harness/review/latest")
async def latest_harness_review_endpoint():
    review = latest_harness_review()
    if not review:
        raise HTTPException(404, detail="No harness review found")
    return review


@router.post("/harness/review/{review_id}/approve")
async def approve_harness_review_endpoint(review_id: str, req: HarnessReviewApprovalRequest):
    try:
        return approve_harness_review(review_id, approve=req.approve)
    except HarnessReviewError as e:
        raise HTTPException(422, detail=str(e))


@router.post("/harness/review/{review_id}/apply")
async def apply_harness_review_endpoint(review_id: str):
    try:
        return apply_harness_review(review_id)
    except HarnessReviewError as e:
        raise HTTPException(422, detail=str(e))
