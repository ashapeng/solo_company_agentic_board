from datetime import datetime, timezone

from server.board.portfolio import PortfolioDecision, PortfolioReviewResult
from server.discovery.lifecycle.store import CandidateStore
from server.experiments.landing.models import LandingPageArtifact
from server.experiments.landing.publisher import FakeLandingPagePublisher
from server.experiments.service import ExperimentService
from server.experiments.store import ExperimentStore
from tests.test_discovery_candidate_lifecycle import _report


def decisions(ids, selected=3):
    return PortfolioReviewResult(
        review_id="review_1", board_session_id="board_1",
        decisions=[PortfolioDecision(
            candidate_id=candidate_id, rank=index,
            label="prioritize" if index <= selected else "defer", confidence="medium",
            rationale="Portfolio comparison", strongest_evidence=["quote"],
            weakest_evidence_or_gap=["intent"], critical_assumption="Demand exists",
            cheapest_credible_test="landing page", success_signals=["joins"],
            stop_conditions=["no joins"], minimum_exposure=100,
            selected_for_validation=index <= selected,
        ) for index, candidate_id in enumerate(ids, 1)],
    )


def test_top_three_create_active_initiatives_experiments_idempotently(tmp_path):
    candidate_store = CandidateStore(tmp_path / "discovery")
    ids = []
    for i in range(5):
        report = _report(title=f"Opportunity {i}")
        ids.append(candidate_store.import_report(report)[0].id)
    experiment_store = ExperimentStore(tmp_path / "board.db")
    service = ExperimentService(store=experiment_store, candidate_store=candidate_store)
    result = decisions(ids)
    created = service.create_selected(result, now=datetime(2026, 7, 12, tzinfo=timezone.utc))
    retried = service.create_selected(result, now=datetime(2026, 7, 13, tzinfo=timezone.utc))

    assert len(created) == len(retried) == 3
    assert {item.id for item in created} == {item.id for item in retried}
    assert experiment_store.active_count() == 3
    assert all(item.review_at == "2026-07-19T00:00:00+00:00" for item in created)
    assert all(item.expires_at == "2026-07-26T00:00:00+00:00" for item in created)
    assert all(candidate_store.get(i).validation_state.value == ("validating" if n < 3 else "not_selected")
               for n, i in enumerate(ids))


def test_fake_publisher_is_local_idempotent_and_external_publishers_are_refused(tmp_path):
    candidate_store = CandidateStore(tmp_path / "discovery")
    candidate = candidate_store.import_report(_report())[0]
    store = ExperimentStore(tmp_path / "board.db")
    service = ExperimentService(store=store, candidate_store=candidate_store)
    experiment = service.create_selected(decisions([candidate.id], selected=1))[0]
    artifact = LandingPageArtifact(experiment.id, str(tmp_path / "index.html"), "sha256:x")
    publisher = FakeLandingPagePublisher()
    published = service.publish_fake(experiment.id, artifact, publisher)
    assert published.status.value == "published"
    assert published.landing_page_deployment["external"] is False
    assert publisher.publish(artifact, idempotency_key=f"landing:{experiment.id}").deployment_id == published.landing_page_deployment["deployment_id"]
