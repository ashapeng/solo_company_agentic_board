from pathlib import Path

import pytest

from server.discovery.watchlist import WatchlistError, load_watchlist


def _write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "watchlist.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_load_normalizes_reddit_defaults(tmp_path):
    p = _write(tmp_path, "reddit:\n  - sub: knitting\n")
    wl = load_watchlist(p)
    item = wl["reddit"][0]
    assert item == {"sub": "knitting", "sort": "top", "window": "week", "label": "knitting"}


def test_gov_section_flattens_to_channels(tmp_path):
    p = _write(
        tmp_path,
        "gov:\n  sam_gov:\n    - keywords: [\"design services\"]\n"
        "  grants_gov:\n    - keywords: [\"arts\"]\n",
    )
    wl = load_watchlist(p)
    assert wl["sam_gov"][0]["keywords"] == ["design services"]
    assert wl["grants_gov"][0]["label"] == "arts"


def test_unknown_channel_rejected(tmp_path):
    p = _write(tmp_path, "myspace:\n  - sub: x\n")
    with pytest.raises(WatchlistError, match="myspace"):
        load_watchlist(p)


def test_missing_required_field_rejected(tmp_path):
    p = _write(tmp_path, "reddit:\n  - sort: top\n")
    with pytest.raises(WatchlistError, match="sub"):
        load_watchlist(p)


def test_default_seed_file_loads():
    wl = load_watchlist()
    assert len(wl["reddit"]) >= 6
    assert "sam_gov" in wl
