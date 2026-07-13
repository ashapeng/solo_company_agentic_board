import json

from server.discovery.analyze.corpus import normalized_engagement, prepare_corpus
from server.discovery.channels.base import RawPost


def _post(pid, channel, score, created_at=""):
    return RawPost(
        id=pid,
        channel=channel,
        source="unit",
        title=f"title {pid}",
        body="x" * 1000,
        url=f"https://example.com/{pid}",
        score=score,
        comments=0,
        created_at=created_at,
    )


def test_normalizes_engagement_within_channel():
    posts = [_post("a", "reddit", 10), _post("b", "reddit", 1), _post("c", "youtube", 100000)]
    scores = normalized_engagement(posts)
    assert scores["reddit:a"] == 1.0
    assert scores["reddit:b"] == 0.0
    assert scores["youtube:c"] == 1.0


def test_corpus_preserves_channels_truncates_and_budgets():
    posts = [_post(str(i), "reddit", 100 - i) for i in range(10)]
    posts += [_post("video", "youtube", 1)]
    records = prepare_corpus(posts, max_posts=4, body_chars=20, max_payload_chars=4000)
    assert {record["channel"] for record in records} == {"reddit", "youtube"}
    assert all(len(record["body"]) <= 20 for record in records)
    assert len(json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(",", ":"))) <= 4000
    assert sum(record["channel"] == "reddit" for record in records) <= 2


def test_corpus_ties_are_reproducible():
    posts = [_post("b", "fake", 5, "2026-01-01"), _post("a", "fake", 5, "2026-01-02")]
    assert [r["post_key"] for r in prepare_corpus(posts)] == ["fake:a", "fake:b"]
