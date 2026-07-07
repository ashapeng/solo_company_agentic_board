import json

import pytest

from server.discovery.channels.youtube import YouTubeChannel

SEARCH_LINE = json.dumps(
    {
        "id": "vid1",
        "title": "Why my Etsy shop failed",
        "url": "https://www.youtube.com/watch?v=vid1",
        "view_count": 50000,
        "channel": "CraftTalk",
    }
)
VIDEO_JSON = json.dumps(
    {
        "id": "vid1",
        "title": "Why my Etsy shop failed",
        "description": "Story of shipping costs eating margins",
        "comments": [
            {
                "id": "c1",
                "text": "Same! Shipping calculators are all wrong",
                "author": "user9",
                "like_count": 33,
                "timestamp": 1751500000,
            }
        ],
    }
)


def fake_runner(args):
    joined = " ".join(args)
    if "ytsearch" in joined:
        return SEARCH_LINE + "\n"
    if "--version" in joined:
        return "2026.06.01\n"
    return VIDEO_JSON


def test_fetch_returns_videos_and_comments():
    ch = YouTubeChannel(runner=fake_runner)
    posts = ch.fetch(
        {"query": "etsy shop problems", "max_videos": 1, "include_comments": True, "label": "etsy"}
    )
    ids = {p.id for p in posts}
    assert "vid1" in ids
    assert "vid1:c1" in ids
    comment = next(p for p in posts if p.id == "vid1:c1")
    assert comment.extra["video_title"] == "Why my Etsy shop failed"
    assert comment.score == 33


def test_fetch_without_comments_returns_videos_only():
    ch = YouTubeChannel(runner=fake_runner)
    posts = ch.fetch({"query": "q", "max_videos": 1, "include_comments": False, "label": "q"})
    assert [p.id for p in posts] == ["vid1"]


def test_health_unconfigured_when_binary_missing():
    def missing(args):
        raise FileNotFoundError("yt-dlp not found")

    assert YouTubeChannel(runner=missing).health().status == "unconfigured"


def test_fetch_raises_when_binary_missing():
    def missing(args):
        raise FileNotFoundError("yt-dlp not found")

    with pytest.raises(RuntimeError, match="yt-dlp"):
        YouTubeChannel(runner=missing).fetch({"query": "q", "label": "q"})
