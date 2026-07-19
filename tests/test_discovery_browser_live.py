"""Opt-in live browser discovery tests. Requires a logged-in Chrome profile.

Run: uv run pytest -m live tests/test_discovery_browser_live.py
Skipped in the default suite and in cloud VMs without social logins.
"""
from __future__ import annotations

import pytest

from server.discovery.channels.browser import BrowserChannel

pytestmark = pytest.mark.live


def test_browser_health_live():
    h = BrowserChannel().health()
    assert h.status in {"ok", "unconfigured"}
    if h.status == "unconfigured":
        pytest.skip(h.detail)


def test_browser_fetch_public_hackernews_via_generic():
    """Public page smoke — does not need a logged-in social profile."""
    ch = BrowserChannel()
    h = ch.health()
    if h.status != "ok":
        pytest.skip(h.detail)
    posts = ch.fetch(
        {
            "platform": "generic",
            "url": "https://news.ycombinator.com/",
            "label": "hn-live",
            "wait_for": ".athing",
            "max_items": 5,
        }
    )
    # Generic parser may find zero matching articles on HN's markup;
    # the live contract is that fetch completes without raising.
    assert isinstance(posts, list)
