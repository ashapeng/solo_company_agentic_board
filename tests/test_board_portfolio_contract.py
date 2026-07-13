import pytest

from server.board.portfolio import (
    PortfolioContractError, PortfolioReviewInput, PortfolioReviewResult,
    PortfolioCandidateInput, parse_portfolio_result,
)


def request(count=5, capacity=5):
    return PortfolioReviewInput(
        review_id="review_1", week="2026-W29", available_capacity=capacity,
        candidates=[PortfolioCandidateInput(
            candidate_id=f"cand_{i}", title=f"Idea {i}", audience="operators",
            pain_class="important", summary="Pain", signal_strength=.8,
            evidence_summary=["source: exact quote"], report_digest="sha256:x",
        ) for i in range(count)],
    )


def result(req, selected=3):
    return {
        "review_id": req.review_id, "board_session_id": "board_1",
        "decisions": [{
            "candidate_id": item.candidate_id, "rank": index,
            "label": "prioritize" if index <= selected else "defer", "confidence": "medium",
            "rationale": "Compared against the portfolio.", "strongest_evidence": ["quote"],
            "weakest_evidence_or_gap": ["buyer intent"], "critical_assumption": "Demand exists",
            "cheapest_credible_test": "Publish an honest waitlist landing page",
            "success_signals": ["waitlist joins"], "stop_conditions": ["no joins"],
            "minimum_exposure": 100, "selected_for_validation": index <= selected,
        } for index, item in enumerate(req.candidates, 1)],
    }


def test_complete_contiguous_portfolio_parses():
    req = request()
    parsed = parse_portfolio_result(result(req), req)
    assert [d.rank for d in parsed.decisions] == [1, 2, 3, 4, 5]
    assert sum(d.selected_for_validation for d in parsed.decisions) == 3


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "invented", "rank"])
def test_candidate_and_rank_contract_rejects_invalid_result(mutation):
    req = request()
    value = result(req)
    if mutation == "missing": value["decisions"].pop()
    if mutation == "duplicate": value["decisions"][-1]["candidate_id"] = "cand_0"
    if mutation == "invented": value["decisions"][-1]["candidate_id"] = "cand_x"
    if mutation == "rank": value["decisions"][-1]["rank"] = 3
    with pytest.raises(PortfolioContractError):
        parse_portfolio_result(value, req)


def test_selection_never_exceeds_available_capacity():
    req = request(capacity=2)
    with pytest.raises(PortfolioContractError, match="capacity"):
        PortfolioReviewResult.model_validate(result(req, selected=3)).validate_against(req)


def test_default_selection_limit_is_three_even_when_hard_capacity_is_five():
    req = request(capacity=5)
    with pytest.raises(PortfolioContractError, match="capacity"):
        PortfolioReviewResult.model_validate(result(req, selected=4)).validate_against(req)


def test_low_evidence_portfolio_may_select_fewer_than_three():
    req = request()
    assert sum(d.selected_for_validation for d in parse_portfolio_result(result(req, selected=1), req).decisions) == 1
