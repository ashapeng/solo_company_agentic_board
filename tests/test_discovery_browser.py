"""Offline unit tests for the browser discovery channel and Layer B import."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.discovery.channels.base import RawPost
from server.discovery.store import DiscoveryStore, iso_week

# ---------------------------------------------------------------------------
# Fixtures — minimal HTML matching the disposable per-platform parsers
# ---------------------------------------------------------------------------

XHS_HTML = """
<html><body>
<section class="note-item" data-note-id="note123">
  <a class="cover" href="/explore/note123"><span>手作卖不出去怎么办</span></a>
  <a class="author" href="/user/u1">匠人小美</a>
  <span class="like-count">42</span>
</section>
<section class="note-item" data-note-id="note456">
  <a class="cover" href="/explore/note456"><span>库存积压崩溃日记</span></a>
  <a class="author" href="/user/u2">工作室主阿强</a>
</section>
</body></html>
"""

TIKTOK_HTML = """
<html><body>
<div data-e2e="search-card-item">
  <a href="/@seller/video/777001"><h3>Etsy shop struggles with shipping</h3></a>
  <a data-e2e="search-card-user-link" href="/@seller">craftseller</a>
</div>
<div data-e2e="search-card-item">
  <a href="/@maker/video/777002"><h3>Why my craft business failed</h3></a>
  <a data-e2e="search-card-user-link" href="/@maker">makerjane</a>
</div>
</body></html>
"""

GENERIC_HTML = """
<html><body>
<article data-post-id="g1">
  <h2><a href="https://example.com/p/g1">Generic pain point</a></h2>
  <p class="author">alice</p>
  <p class="body">Customers hate waiting for inventory sync.</p>
</article>
</body></html>
"""


def test_xiaohongshu_parser_maps_notes():
    from server.discovery.channels.browser import BrowserChannel

    ch = BrowserChannel(fetch_html=lambda url, wait_for: XHS_HTML)
    posts = ch.fetch(
        {
            "platform": "xiaohongshu",
            "url": "https://www.xiaohongshu.com/search_result?keyword=test",
            "query": "手作 卖不出去",
            "label": "shouzuo",
            "max_items": 20,
        }
    )
    assert len(posts) == 2
    assert posts[0].id == "note123"
    assert posts[0].channel == "browser"
    assert posts[0].source == "shouzuo"
    assert "手作" in posts[0].title
    assert posts[0].author == "匠人小美"
    assert posts[0].score == 42
    assert "note123" in posts[0].url
    assert posts[0].extra.get("platform") == "xiaohongshu"


def test_tiktok_parser_maps_cards():
    from server.discovery.channels.browser import BrowserChannel

    ch = BrowserChannel(fetch_html=lambda url, wait_for: TIKTOK_HTML)
    posts = ch.fetch(
        {
            "platform": "tiktok",
            "url": "https://www.tiktok.com/search?q=etsy",
            "query": "etsy shop struggles",
            "label": "etsy-shop-struggles",
        }
    )
    assert len(posts) == 2
    assert posts[0].id == "777001"
    assert posts[0].title.startswith("Etsy shop")
    assert posts[0].author == "craftseller"
    assert "777001" in posts[0].url
    assert posts[0].extra.get("platform") == "tiktok"


def test_generic_parser_maps_articles():
    from server.discovery.channels.browser import BrowserChannel

    ch = BrowserChannel(fetch_html=lambda url, wait_for: GENERIC_HTML)
    posts = ch.fetch(
        {
            "platform": "generic",
            "url": "https://example.com/search",
            "query": "inventory",
            "label": "generic-search",
        }
    )
    assert len(posts) == 1
    assert posts[0].id == "g1"
    assert posts[0].title == "Generic pain point"
    assert posts[0].author == "alice"
    assert "inventory" in posts[0].body


def test_unknown_platform_raises():
    from server.discovery.channels.browser import BrowserChannel

    ch = BrowserChannel(fetch_html=lambda url, wait_for: "<html></html>")
    with pytest.raises(ValueError, match="unknown platform"):
        ch.fetch({"platform": "myspace", "url": "https://x", "label": "x"})


def test_max_items_caps_results():
    from server.discovery.channels.browser import BrowserChannel

    ch = BrowserChannel(fetch_html=lambda url, wait_for: XHS_HTML)
    posts = ch.fetch(
        {
            "platform": "xiaohongshu",
            "url": "https://www.xiaohongshu.com/search_result",
            "label": "cap",
            "max_items": 1,
        }
    )
    assert len(posts) == 1


def test_health_ok_when_playwright_importable():
    from server.discovery.channels.browser import BrowserChannel

    ch = BrowserChannel(fetch_html=lambda url, wait_for: "")
    # If playwright is installed in the env, health should be ok (or unconfigured
    # only when explicitly disabled). Inject a health probe for determinism.
    status = ch.health(playwright_available=True, chrome_resolvable=True).status
    assert status == "ok"


def test_health_unconfigured_without_playwright():
    from server.discovery.channels.browser import BrowserChannel

    ch = BrowserChannel(fetch_html=lambda url, wait_for: "")
    h = ch.health(playwright_available=False, chrome_resolvable=True)
    assert h.status == "unconfigured"
    assert "playwright" in h.detail.lower()


def test_health_unconfigured_when_browser_disabled(monkeypatch):
    from server.discovery.channels.browser import BrowserChannel

    monkeypatch.setenv("AGENTIC_BOARD_BROWSER", "disabled")
    ch = BrowserChannel(fetch_html=lambda url, wait_for: "")
    h = ch.health(playwright_available=True, chrome_resolvable=True)
    assert h.status == "unconfigured"


def test_fetch_html_receives_url_and_wait_for():
    from server.discovery.channels.browser import BrowserChannel

    seen: dict = {}

    def fake(url, wait_for):
        seen["url"] = url
        seen["wait_for"] = wait_for
        return GENERIC_HTML

    ch = BrowserChannel(fetch_html=fake)
    ch.fetch(
        {
            "platform": "generic",
            "url": "https://example.com/s",
            "wait_for": ".note-item",
            "label": "w",
        }
    )
    assert seen["url"] == "https://example.com/s"
    assert seen["wait_for"] == ".note-item"


# ---------------------------------------------------------------------------
# Layer B — drop-folder / import round-trip
# ---------------------------------------------------------------------------


def _browser_post(pid: str, platform: str = "xiaohongshu") -> RawPost:
    return RawPost(
        id=pid,
        channel="browser",
        source=f"browser-{platform}",
        title=f"title-{pid}",
        body=f"body-{pid}",
        url=f"https://example.com/{pid}",
        author="capturer",
        extra={"platform": platform},
    )


def test_layer_b_store_roundtrip_and_dedup(tmp_path):
    store = DiscoveryStore(tmp_path)
    week = "2026-W28"
    posts = [_browser_post("note123"), _browser_post("note456")]
    new = store.filter_new(posts)
    path = store.write_raw(week, "browser", "xiaohongshu", new)
    store.mark_seen(new)

    assert path == tmp_path / "raw" / week / "browser-xiaohongshu.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert {p["id"] for p in data} == {"note123", "note456"}
    assert all(p["channel"] == "browser" for p in data)

    # Re-import same ids → nothing new
    again = store.filter_new([_browser_post("note123"), _browser_post("note789")])
    assert [p.id for p in again] == ["note789"]


def test_import_browser_capture_script(tmp_path, monkeypatch):
    """scripts/import_browser_capture.py reads agent JSON and writes via store."""
    from scripts import import_browser_capture as mod

    capture = tmp_path / "capture.json"
    capture.write_text(
        json.dumps(
            [
                {
                    "id": "note999",
                    "channel": "browser",
                    "source": "browser-xiaohongshu",
                    "title": "手工滞销",
                    "body": "仓库爆满",
                    "url": "https://www.xiaohongshu.com/explore/note999",
                    "author": "小美",
                    "score": 10,
                    "comments": 2,
                    "created_at": "2026-07-13T00:00:00Z",
                    "extra": {"platform": "xiaohongshu"},
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store_root = tmp_path / "discovery"
    monkeypatch.setattr(mod, "DEFAULT_STORE_ROOT", store_root)

    result = mod.import_capture(
        capture_path=capture,
        platform="xiaohongshu",
        week="2026-W28",
    )
    assert result["imported"] == 1
    assert result["skipped"] == 0
    out = store_root / "raw" / "2026-W28" / "browser-xiaohongshu.json"
    assert out.exists()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data[0]["id"] == "note999"

    # Second import of the same file should skip
    result2 = mod.import_capture(
        capture_path=capture,
        platform="xiaohongshu",
        week="2026-W28",
    )
    assert result2["imported"] == 0
    assert result2["skipped"] == 1


def test_iso_week_helper_available():
    assert iso_week()  # smoke — format covered in store tests
