import json

import pytest

from server.discovery.channels import build_channel
from server.discovery.cli import main
from server.discovery.doctor import run_doctor


def test_reddit_and_youtube_are_held_without_health_probe():
    by_name = {item.channel: item for item in run_doctor(["reddit", "youtube"])}
    assert by_name["reddit"].status == "held"
    assert by_name["youtube"].status == "held"
    assert not by_name["reddit"].configured


def test_fetch_records_held_policy_without_network(tmp_path):
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("reddit:\n  - sub: Etsy\n    label: etsy\n", encoding="utf-8")
    data = tmp_path / "data"
    assert main(["fetch", "--watchlist", str(watchlist), "--data-dir", str(data), "--week", "2026-W28"]) == 0
    manifest = json.loads((data / "raw" / "2026-W28" / "manifest.json").read_text(encoding="utf-8"))
    run = manifest["runs"][0]
    assert run["state"] == "held"
    assert run["error"] is None
    assert run["file"] is None


@pytest.mark.parametrize(
    "name,item",
    [
        ("reddit", {"sub": "Etsy"}),
        ("youtube", {"query": "maker pain"}),
    ],
)
def test_default_held_adapter_cannot_be_called_directly(name, item):
    with pytest.raises(RuntimeError, match="held"):
        build_channel(name).fetch(item)
