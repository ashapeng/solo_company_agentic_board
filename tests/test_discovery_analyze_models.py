import math

import pytest

from server.discovery.analyze.models import (
    ContractError,
    Evidence,
    Producer,
    Resource,
    Topic,
    TopicReport,
)


def _report():
    return TopicReport(
        schema_version=1,
        week="2026-W28",
        generated_at="2026-07-10T00:00:00+00:00",
        producer=Producer("ide_coding_agent", "codex", "run-1"),
        bundle_digest="a" * 64,
        post_count=2,
        selected_post_count=2,
        topics=[
            Topic(
                id="yarn-inventory",
                title="Yarn inventory",
                summary="Makers lose track of stock.",
                who="Independent makers",
                pain_class="hair_on_fire",
                signal_strength=0.9,
                competition_level="moderate",
                existing_solutions="Some spreadsheet templates and generic inventory apps",
                competition_rationale="Niche maker audience; few specialized launches in-bundle",
                engagement_score=1.5,
                evidence=[
                    Evidence(
                        post_key="fake:fake-1",
                        channel="fake",
                        title="Yarn inventory",
                        url="https://example.com/1",
                        author="",
                        score=42,
                        comments=18,
                        normalized_engagement=1.0,
                        created_at="",
                        retrieved_at="2026-07-10T00:00:00+00:00",
                        quote="Spreadsheets keep breaking",
                    )
                ],
                resources=[Resource("Yarn inventory", "https://example.com/1", "other")],
            )
        ],
    )


def test_topic_report_round_trip_is_strict():
    restored = TopicReport.from_dict(_report().to_dict())
    assert restored == _report()


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda d: d.update(producer={"kind": "model", "name": "x", "run_id": "1"}), "producer.kind"),
        (lambda d: d["topics"][0].update(signal_strength=math.inf), "finite"),
        (lambda d: d["topics"][0].update(pain_class="urgent"), "pain_class"),
        (lambda d: d["topics"][0].update(competition_level="crowded"), "competition_level"),
        (lambda d: d.update(topics={}), "must be a list"),
        (lambda d: d["topics"][0].update(evidence={}), "must be a list"),
    ],
)
def test_topic_report_rejects_bad_contract(mutation, match):
    data = _report().to_dict()
    mutation(data)
    with pytest.raises(ContractError, match=match):
        TopicReport.from_dict(data)


def test_topic_report_rejects_non_object_root():
    with pytest.raises(ContractError, match="must be an object"):
        TopicReport.from_dict([])
