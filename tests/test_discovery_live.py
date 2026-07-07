import pytest

from server.discovery.channels.hackernews import HackerNewsChannel
from server.discovery.channels.reddit import RedditChannel

pytestmark = pytest.mark.live


def test_reddit_live_fetch():
    posts = RedditChannel().fetch(
        {"sub": "knitting", "sort": "top", "window": "week", "label": "knitting"}
    )
    assert len(posts) > 0
    assert all(p.channel == "reddit" for p in posts)


def test_hackernews_live_fetch():
    posts = HackerNewsChannel().fetch({"query": "etsy", "label": "etsy"})
    assert isinstance(posts, list)
