import json
from dataclasses import replace

import pytest

from server.discovery.analyze.models import Evidence, Producer, Resource, Topic, TopicReport
from server.discovery.lifecycle.models import Candidate, CandidateStatus
from server.discovery.lifecycle.store import CandidateStore


def _report(*, title="Maker inventory", generated_at="2026-07-10T00:00:00+00:00"):
    return TopicReport(
        schema_version=1,
        week="2026-W28",
        generated_at=generated_at,
        producer=Producer("ide_coding_agent", "codex", "run-1"),
        bundle_digest="a" * 64,
        post_count=1,
        selected_post_count=1,
        topics=[
            Topic(
                id="producer-topic-1",
                title=title,
                summary="Makers cannot trust their stock records.",
                who="Independent makers",
                pain_class="important",
                signal_strength=0.8,
                competition_level="moderate",
                existing_solutions="Generic spreadsheets and marketplace seller tools",
                competition_rationale="Maker audience; few specialized inventory launches in-bundle",
                engagement_score=0.7,
                evidence=[
                    Evidence(
                        post_key="fake:1",
                        channel="fake",
                        title="Broken stock sheet",
                        url="https://example.com/1",
                        author="maker",
                        score=10,
                        comments=2,
                        normalized_engagement=0.7,
                        created_at="2026-07-09T00:00:00+00:00",
                        retrieved_at="2026-07-10T00:00:00+00:00",
                        quote="My spreadsheet breaks every week.",
                    )
                ],
                resources=[Resource("Broken stock sheet", "https://example.com/1", "other")],
            )
        ],
    )


def test_import_creates_uuid_identity_independent_of_slug_and_valid_file(tmp_path):
    store = CandidateStore(tmp_path)
    result = store.import_report(_report())

    assert result.created == 1
    candidate = result[0]
    assert candidate.id.startswith("cand_")
    assert candidate.id != "cand_maker-inventory"
    assert candidate.title_slug == "maker-inventory"
    assert Candidate.from_dict(
        json.loads((tmp_path / "candidates" / f"{candidate.id}.json").read_text())
    ) == candidate


def test_reimport_is_idempotent_and_preserves_founder_owned_fields(tmp_path):
    store = CandidateStore(tmp_path)
    original = store.import_report(_report())[0]
    decided = replace(
        original,
        status=CandidateStatus.SHORTLISTED,
        founder_decisions=[{"type": "shortlist", "note": "test"}],
        promotion={"id": "promo_1"},
        board_sessions=[{"session_id": "board_1"}],
        updated_at="2026-07-11T00:00:00+00:00",
    )
    store.save(decided)

    # A retry's wall-clock generation timestamp is not substantive report content.
    result = store.import_report(_report(generated_at="2026-07-11T00:00:00+00:00"))

    assert result.created == 0
    assert result.existing == 1
    assert result[0] == decided
    assert len(list((tmp_path / "candidates").glob("cand_*.json"))) == 1


def test_same_title_in_different_report_has_new_identity(tmp_path):
    store = CandidateStore(tmp_path)
    first = store.import_report(_report())[0]
    changed = _report()
    changed = replace(changed, bundle_digest="b" * 64)
    second = store.import_report(changed)[0]
    assert first.title_slug == second.title_slug
    assert first.id != second.id


def test_index_rebuilds_when_missing_or_invalid(tmp_path):
    store = CandidateStore(tmp_path)
    candidate = store.import_report(_report())[0]
    store.index_path.unlink()
    assert store.list()[0].id == candidate.id
    store.index_path.write_text("not json", encoding="utf-8")
    assert store.list()[0].id == candidate.id
    assert json.loads(store.index_path.read_text())["schema_version"] == 1


@pytest.mark.parametrize(
    "current,target,valid",
    [
        ("new", "shortlisted", True),
        ("new", "rejected", True),
        ("new", "promoted", True),
        ("shortlisted", "rejected", True),
        ("shortlisted", "promoted", True),
        ("promoted", "board_started", True),
        ("rejected", "shortlisted", False),
        ("rejected", "promoted", False),
        ("promoted", "rejected", False),
        ("board_started", "promoted", False),
    ],
)
def test_candidate_status_transitions(tmp_path, current, target, valid):
    store = CandidateStore(tmp_path)
    candidate = store.import_report(_report())[0]
    store.save(replace(candidate, status=CandidateStatus(current)))
    if valid:
        assert store.transition(candidate.id, target).status == CandidateStatus(target)
    else:
        with pytest.raises(ValueError, match="invalid candidate transition"):
            store.transition(candidate.id, target)


def test_schema_rejection_is_visible_and_does_not_hide_bad_files(tmp_path):
    store = CandidateStore(tmp_path)
    candidate = store.import_report(_report())[0]
    path = tmp_path / "candidates" / f"{candidate.id}.json"
    data = json.loads(path.read_text())
    data["unexpected"] = True
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="unknown field"):
        store.get(candidate.id)
    store.index_path.unlink()
    with pytest.raises(ValueError, match="unknown field"):
        store.list()
