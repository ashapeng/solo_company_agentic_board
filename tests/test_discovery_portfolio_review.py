import pytest

from server.discovery.lifecycle.store import CandidateStore
from server.discovery.portfolio_review import PortfolioReviewService
from server.experiments.store import ExperimentStore
from tests.test_discovery_candidate_lifecycle import _report


class FakeBoard:
    def __init__(self, malformed=False):
        self.calls = 0
        self.malformed = malformed

    def review_portfolio(self, request, **_):
        self.calls += 1
        decisions = []
        for rank, item in enumerate(request.candidates, 1):
            decisions.append({
                "candidate_id": item.candidate_id, "rank": rank,
                "label": "prioritize" if rank <= 3 else "defer", "confidence": "medium",
                "rationale": "Compared opportunity cost", "strongest_evidence": ["quote"],
                "weakest_evidence_or_gap": ["intent"], "critical_assumption": "Demand exists",
                "cheapest_credible_test": "honest landing page", "success_signals": ["joins"],
                "stop_conditions": ["no joins"], "minimum_exposure": 100,
                "selected_for_validation": rank <= 3,
            })
        if self.malformed:
            decisions.pop()
        return {"review_id": request.review_id, "board_session_id": "board_1", "decisions": decisions}


def candidates(tmp_path):
    store = CandidateStore(tmp_path / "discovery")
    values = [store.import_report(_report(title=f"Opportunity {i}"))[0] for i in range(5)]
    return store, values


@pytest.mark.asyncio
async def test_review_applies_every_decision_only_after_full_validation(tmp_path):
    store, values = candidates(tmp_path)
    board = FakeBoard()
    service = PortfolioReviewService(candidate_store=store,
                                     experiment_store=ExperimentStore(tmp_path / "board.db"),
                                     orchestrator=board)
    result = await service.review(week="2026-W28")
    assert len(result.decisions) == 5 and board.calls == 1
    ranked = sorted((store.get(item.id) for item in values), key=lambda item: item.board_rank)
    assert [item.board_rank for item in ranked] == [1, 2, 3, 4, 5]
    assert [item.validation_state.value for item in ranked[:3]] == ["queued"] * 3
    assert await service.review(week="2026-W28") == result
    assert board.calls == 1


@pytest.mark.asyncio
async def test_malformed_result_repairs_once_and_leaves_candidates_unchanged(tmp_path):
    store, values = candidates(tmp_path)
    board = FakeBoard(malformed=True)
    service = PortfolioReviewService(candidate_store=store,
                                     experiment_store=ExperimentStore(tmp_path / "board.db"),
                                     orchestrator=board)
    with pytest.raises(ValueError):
        await service.review(week="2026-W28")
    assert board.calls == 2
    assert all(store.get(item.id).discovery_status.value == "ready_for_board" for item in values)
    assert all(store.get(item.id).board_label is None for item in values)
