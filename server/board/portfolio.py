"""Strict, bounded contracts for comparing discovery candidates as a portfolio."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from server.board.deliberation.structured import _iter_json_blocks


class PortfolioContractError(ValueError):
    pass


class PortfolioCandidateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    candidate_id: str
    title: str
    audience: str
    pain_class: str
    summary: str
    signal_strength: float = Field(ge=0, le=1)
    evidence_summary: list[str] = Field(min_length=1, max_length=12)
    evidence_packet_id: str | None = None
    report_digest: str


class PortfolioReviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    review_id: str
    week: str
    candidates: list[PortfolioCandidateInput] = Field(min_length=1, max_length=10)
    default_select: int = Field(default=3, ge=0, le=5)
    max_select: int = Field(default=5, ge=1, le=5)
    available_capacity: int = Field(default=5, ge=0, le=5)
    config_version: str = "1"

    @field_validator("candidates")
    @classmethod
    def unique_candidates(cls, values: list[PortfolioCandidateInput]) -> list[PortfolioCandidateInput]:
        ids = [item.candidate_id for item in values]
        if len(ids) != len(set(ids)):
            raise ValueError("input candidate IDs must be unique")
        return values


class PortfolioDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    candidate_id: str
    rank: int = Field(ge=1)
    label: Literal["prioritize", "investigate", "defer", "reject"]
    confidence: Literal["low", "medium", "high"]
    rationale: str = Field(min_length=1, max_length=3000)
    strongest_evidence: list[str] = Field(default_factory=list, max_length=12)
    weakest_evidence_or_gap: list[str] = Field(default_factory=list, max_length=12)
    critical_assumption: str = Field(min_length=1, max_length=1000)
    cheapest_credible_test: str = Field(min_length=1, max_length=1000)
    success_signals: list[str] = Field(min_length=1, max_length=12)
    stop_conditions: list[str] = Field(min_length=1, max_length=12)
    minimum_exposure: int = Field(ge=1)
    selected_for_validation: bool


class PortfolioReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    review_id: str
    board_session_id: str
    decisions: list[PortfolioDecision] = Field(min_length=1, max_length=10)

    def validate_against(self, request: PortfolioReviewInput) -> PortfolioReviewResult:
        expected = [item.candidate_id for item in request.candidates]
        actual = [item.candidate_id for item in self.decisions]
        if len(actual) != len(set(actual)):
            raise PortfolioContractError("portfolio result has duplicate candidate IDs")
        if set(actual) != set(expected):
            missing = sorted(set(expected) - set(actual))
            invented = sorted(set(actual) - set(expected))
            raise PortfolioContractError(f"portfolio candidate mismatch; missing={missing}, invented={invented}")
        ranks = sorted(item.rank for item in self.decisions)
        if ranks != list(range(1, len(expected) + 1)):
            raise PortfolioContractError("portfolio ranks must be unique and contiguous")
        selected = [item for item in self.decisions if item.selected_for_validation]
        ceiling = min(request.default_select, request.max_select, request.available_capacity)
        if len(selected) > ceiling:
            raise PortfolioContractError(f"portfolio selected {len(selected)} candidates; capacity is {ceiling}")
        if any(item.selected_for_validation and item.label != "prioritize" for item in self.decisions):
            raise PortfolioContractError("only prioritize decisions may be selected for validation")
        return self


def parse_portfolio_result(content: str | dict[str, Any], request: PortfolioReviewInput) -> PortfolioReviewResult:
    candidates: list[Any]
    if isinstance(content, dict):
        candidates = [content]
    elif isinstance(content, str):
        candidates = [json.loads(block) for block in _iter_json_blocks(content)]
    else:
        raise PortfolioContractError("portfolio result must be an object or JSON text")
    errors: list[str] = []
    for value in candidates:
        try:
            return PortfolioReviewResult.model_validate(value).validate_against(request)
        except (ValidationError, PortfolioContractError) as exc:
            errors.append(str(exc))
    detail = errors[-1] if errors else "no valid JSON object found"
    raise PortfolioContractError(f"invalid portfolio result: {detail}")


def candidate_to_input(candidate: Any) -> PortfolioCandidateInput:
    evidence = []
    for item in candidate.evidence[:12]:
        quote = " ".join(str(item.quote).split())[:500]
        evidence.append(f"{item.channel}: {quote}")
    return PortfolioCandidateInput(
        candidate_id=candidate.id, title=candidate.title[:200], audience=candidate.audience[:500],
        pain_class=candidate.pain_class, summary=" ".join(candidate.summary.split())[:2000],
        signal_strength=candidate.signal_strength, evidence_summary=evidence,
        evidence_packet_id=(candidate.promotion or {}).get("evidence_packet_id"),
        report_digest=candidate.report_digest,
    )


def render_portfolio_prompt(request: PortfolioReviewInput) -> str:
    payload = request.model_dump(mode="json")
    return (
        "Compare the entire opportunity portfolio and return one strict JSON decision for every candidate. "
        "Optimize opportunity cost and validate assumptions before building products. A selected candidate must "
        "use the cheapest credible falsification test, normally a landing page, fake door, interviews, waitlist, "
        "or concierge workflow. Select fewer than the default when evidence is insufficient. Never exceed capacity.\n\n"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    )
