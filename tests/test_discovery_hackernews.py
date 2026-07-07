import httpx

from server.discovery.channels.hackernews import HackerNewsChannel

HN_FIXTURE = {
    "hits": [
        {
            "objectID": "40001",
            "title": "Show HN: Tool for craft sellers",
            "story_text": "I built this because pricing was painful",
            "url": "https://example.com/tool",
            "author": "maker",
            "points": 120,
            "num_comments": 45,
            "created_at": "2026-07-01T10:00:00Z",
        }
    ]
}


def test_fetch_maps_hits():
    def handler(request):
        assert "hn.algolia.com" in str(request.url)
        assert "query=creator+tools" in str(request.url) or "query=creator%20tools" in str(request.url)
        return httpx.Response(200, json=HN_FIXTURE)

    ch = HackerNewsChannel(transport=httpx.MockTransport(handler))
    posts = ch.fetch({"query": "creator tools", "label": "creator-tools"})
    p = posts[0]
    assert p.id == "40001"
    assert p.channel == "hackernews"
    assert p.score == 120
    assert p.comments == 45
    assert p.url == "https://news.ycombinator.com/item?id=40001"
    assert p.extra["external_url"] == "https://example.com/tool"


def test_health_ok():
    ch = HackerNewsChannel(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"hits": []}))
    )
    assert ch.health().status == "ok"
