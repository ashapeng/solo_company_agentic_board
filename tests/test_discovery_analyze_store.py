import json

import pytest

from server.discovery.channels.base import RawPost
from server.discovery.store import DiscoveryStore


def _post(pid="1"):
    return RawPost(pid, "fake", "unit", "Title", "Body", "https://example.com/1")


def test_read_week_posts_missing_empty_and_legacy(tmp_path):
    store = DiscoveryStore(tmp_path)
    assert store.read_week_posts("2026-W27") == []
    store.write_manifest("2026-W28", {"runs": []})
    assert store.read_week_posts("2026-W28") == []
    path = tmp_path / "raw" / "2026-W28" / "legacy.json"
    path.write_text(json.dumps([{"id": "1", "channel": "fake"}]), encoding="utf-8")
    post = store.read_week_posts("2026-W28")[0]
    assert post.source == "fake"
    assert post.score == 0
    assert store.latest_week_with_posts() == "2026-W28"


def test_read_week_posts_reports_corrupt_path(tmp_path):
    path = tmp_path / "raw" / "2026-W28" / "bad.json"
    path.parent.mkdir(parents=True)
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match=r"bad\.json"):
        DiscoveryStore(tmp_path).read_week_posts("2026-W28")


def test_read_week_posts_rejects_duplicate_keys(tmp_path):
    store = DiscoveryStore(tmp_path)
    store.write_raw("2026-W28", "fake", "one", [_post()])
    store.write_raw("2026-W28", "fake", "two", [_post()])
    with pytest.raises(ValueError, match="duplicate post_key"):
        store.read_week_posts("2026-W28")


def test_atomic_write_replaces_existing_content(tmp_path):
    store = DiscoveryStore(tmp_path)
    first = store.write_raw("2026-W28", "fake", "unit", [_post("1")])
    store.write_raw("2026-W28", "fake", "unit", [_post("2")])
    assert json.loads(first.read_text(encoding="utf-8"))[0]["id"] == "2"
    assert not list(first.parent.glob("*.tmp"))
