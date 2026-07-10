import httpx
import pytest

from server.discovery.channels import CHANNELS, build_channel
from server.discovery.channels.fake import FakeChannel
from server.discovery.channels.producthunt import ProductHuntChannel

EXPECTED = {
    "reddit",
    "hackernews",
    "youtube",
    "github",
    "rss",
    "producthunt",
    "sam_gov",
    "grants_gov",
    "canadabuys",
    "fake",
    "agent_reach",
}

PH_FIXTURE = {
    "data": {
        "posts": {
            "edges": [
                {
                    "node": {
                        "id": "ph1",
                        "name": "YarnStock",
                        "tagline": "Inventory for fiber artists",
                        "url": "https://producthunt.com/posts/yarnstock",
                        "votesCount": 210,
                        "commentsCount": 34,
                        "createdAt": "2026-07-01T10:00:00Z",
                    }
                }
            ]
        }
    }
}


def test_registry_contains_all_channels():
    assert set(CHANNELS) == EXPECTED


def test_build_channel_instantiates():
    assert build_channel("fake").name == "fake"


def test_build_channel_unknown_raises():
    with pytest.raises(KeyError):
        build_channel("myspace")


def test_fake_channel_deterministic():
    posts = FakeChannel().fetch({"label": "unit"})
    assert len(posts) == 2
    assert posts[0].channel == "fake"


def test_producthunt_maps_posts():
    def handler(request):
        assert request.headers["authorization"] == "Bearer tok"
        return httpx.Response(200, json=PH_FIXTURE)

    ch = ProductHuntChannel(transport=httpx.MockTransport(handler), token="tok")
    posts = ch.fetch({"topic": "creator-economy", "label": "creator"})
    assert posts[0].id == "ph1"
    assert posts[0].score == 210


def test_producthunt_unconfigured_without_token(monkeypatch):
    monkeypatch.delenv("PRODUCTHUNT_TOKEN", raising=False)
    assert ProductHuntChannel().health().status == "unconfigured"


def test_agent_reach_is_stub():
    ch = build_channel("agent_reach")
    assert ch.health().status == "unconfigured"
    with pytest.raises(RuntimeError):
        ch.fetch({"channel": "twitter", "label": "x"})
