import json
import re

from server.discovery.channels.base import RawPost
from server.discovery.store import DiscoveryStore, iso_week


def _post(pid: str) -> RawPost:
    return RawPost(id=pid, channel="fake", source="unit", title="t", body="b", url="u")


def test_filter_new_and_mark_seen(tmp_path):
    store = DiscoveryStore(tmp_path)
    posts = [_post("a"), _post("b")]
    assert store.filter_new(posts) == posts
    store.mark_seen(posts)
    assert store.filter_new([_post("a"), _post("c")]) == [_post("c")]


def test_seen_ids_persist_across_instances(tmp_path):
    DiscoveryStore(tmp_path).mark_seen([_post("a")])
    assert DiscoveryStore(tmp_path).filter_new([_post("a")]) == []


def test_write_raw_creates_week_file(tmp_path):
    store = DiscoveryStore(tmp_path)
    path = store.write_raw("2026-W28", "fake", "unit", [_post("a")])
    assert path == tmp_path / "raw" / "2026-W28" / "fake-unit.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data[0]["id"] == "a"


def test_manifest_roundtrip_and_latest(tmp_path):
    store = DiscoveryStore(tmp_path)
    assert store.read_manifest("2026-W28") is None
    assert store.latest_manifest() is None
    store.write_manifest("2026-W27", {"runs": []})
    store.write_manifest("2026-W28", {"runs": [1]})
    assert store.read_manifest("2026-W28") == {"runs": [1]}
    assert store.latest_manifest() == ("2026-W28", {"runs": [1]})


def test_iso_week_format():
    assert re.fullmatch(r"\d{4}-W\d{2}", iso_week())
