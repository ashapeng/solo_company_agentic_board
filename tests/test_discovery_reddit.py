import json

import httpx

from server.discovery.channels.reddit import RedditChannel

REDDIT_FIXTURE = {
    "data": {
        "children": [
            {
                "data": {
                    "id": "abc123",
                    "title": "Why is pricing handmade items so hard?",
                    "selftext": "I never know what to charge...",
                    "permalink": "/r/Etsy/comments/abc123/why/",
                    "author": "crafty1",
                    "score": 412,
                    "num_comments": 87,
                    "created_utc": 1751500000,
                }
            }
        ]
    }
}


def _transport(payload, status=200):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler), calls


def test_fetch_maps_posts():
    transport, calls = _transport(REDDIT_FIXTURE)
    ch = RedditChannel(transport=transport, sleep=lambda s: None)
    posts = ch.fetch({"sub": "Etsy", "sort": "top", "window": "week", "label": "etsy"})
    assert len(posts) == 1
    p = posts[0]
    assert p.id == "abc123"
    assert p.channel == "reddit"
    assert p.source == "Etsy"
    assert p.url == "https://www.reddit.com/r/Etsy/comments/abc123/why/"
    assert p.score == 412
    assert p.comments == 87
    assert p.created_at.startswith("2025-") or p.created_at.startswith("2026-")
    assert "top.json" in str(calls[0].url)
    assert calls[0].headers["user-agent"].startswith("agentic-board-discovery")


def test_fetch_retries_once_on_429():
    responses = iter([429, 200])

    def handler(request):
        status = next(responses)
        return httpx.Response(status, json=REDDIT_FIXTURE if status == 200 else {})

    sleeps = []
    ch = RedditChannel(transport=httpx.MockTransport(handler), sleep=sleeps.append)
    posts = ch.fetch({"sub": "Etsy", "sort": "top", "window": "week"})
    assert len(posts) == 1
    assert 30 in sleeps


def test_health_error_on_failure():
    def handler(request):
        return httpx.Response(500)

    ch = RedditChannel(transport=httpx.MockTransport(handler), sleep=lambda s: None)
    assert ch.health().status == "error"
