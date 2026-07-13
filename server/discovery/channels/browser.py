"""Browser-driven discovery channel — render logged-in search pages via Chrome.

Per-platform parsers are intentionally tiny and disposable: social DOMs change
often. Inject ``fetch_html`` in tests to avoid launching Chrome.
"""
from __future__ import annotations

import os
import re
from typing import Callable
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from server.discovery.browser_session import chrome_channel_resolvable, render_html
from server.discovery.channels.base import ChannelHealth, RawPost

FetchHtml = Callable[[str, str | None], str]

_XHS_BASE = "https://www.xiaohongshu.com"
_TIKTOK_BASE = "https://www.tiktok.com"


def _default_fetch_html(url: str, wait_for: str | None = None) -> str:
    return render_html(url, wait_for)


def _parse_xiaohongshu(html: str, item: dict) -> list[RawPost]:
    soup = BeautifulSoup(html, "html.parser")
    posts: list[RawPost] = []
    for note in soup.select(".note-item[data-note-id], section.note-item[data-note-id]"):
        note_id = (note.get("data-note-id") or "").strip()
        if not note_id:
            continue
        cover = note.select_one("a.cover")
        title_el = cover.select_one("span") if cover else None
        title = (title_el.get_text(strip=True) if title_el else "") or (
            cover.get_text(strip=True) if cover else ""
        )
        href = cover.get("href") if cover else ""
        url = urljoin(_XHS_BASE, href or f"/explore/{note_id}")
        author_el = note.select_one("a.author")
        author = author_el.get_text(strip=True) if author_el else ""
        like_el = note.select_one(".like-count")
        score = 0
        if like_el:
            digits = re.sub(r"[^\d]", "", like_el.get_text())
            score = int(digits) if digits else 0
        posts.append(
            RawPost(
                id=note_id,
                channel="browser",
                source=item.get("label") or item.get("query") or "",
                title=title,
                body=title,
                url=url,
                author=author,
                score=score,
                extra={"platform": "xiaohongshu"},
            )
        )
    return posts


def _parse_tiktok(html: str, item: dict) -> list[RawPost]:
    soup = BeautifulSoup(html, "html.parser")
    posts: list[RawPost] = []
    for card in soup.select('[data-e2e="search-card-item"]'):
        link = card.select_one('a[href*="/video/"]')
        if not link:
            continue
        href = link.get("href") or ""
        match = re.search(r"/video/(\d+)", href)
        if not match:
            continue
        video_id = match.group(1)
        title_el = link.select_one("h3") or link
        title = title_el.get_text(strip=True)
        user_el = card.select_one('[data-e2e="search-card-user-link"]')
        author = ""
        if user_el:
            author = (user_el.get_text(strip=True) or "").lstrip("@")
            if not author:
                author = (user_el.get("href") or "").rstrip("/").split("/")[-1].lstrip("@")
        url = urljoin(_TIKTOK_BASE, href)
        posts.append(
            RawPost(
                id=video_id,
                channel="browser",
                source=item.get("label") or item.get("query") or "",
                title=title,
                body=title,
                url=url,
                author=author,
                extra={"platform": "tiktok"},
            )
        )
    return posts


def _parse_generic(html: str, item: dict) -> list[RawPost]:
    soup = BeautifulSoup(html, "html.parser")
    posts: list[RawPost] = []
    for article in soup.select("article[data-post-id]"):
        post_id = (article.get("data-post-id") or "").strip()
        if not post_id:
            continue
        title_link = article.select_one("h2 a, h3 a, a")
        title = title_link.get_text(strip=True) if title_link else ""
        href = title_link.get("href") if title_link else ""
        url = href or item.get("url", "")
        author_el = article.select_one(".author, [rel='author']")
        author = author_el.get_text(strip=True) if author_el else ""
        body_el = article.select_one(".body") or article.select_one("p:not(.author)")
        body = body_el.get_text(strip=True) if body_el else title
        posts.append(
            RawPost(
                id=post_id,
                channel="browser",
                source=item.get("label") or item.get("query") or "",
                title=title,
                body=body,
                url=url,
                author=author,
                extra={"platform": item.get("platform") or "generic"},
            )
        )
    return posts


# Stubs for platforms without dedicated parsers yet — fall back to generic.
_PARSERS: dict[str, Callable[[str, dict], list[RawPost]]] = {
    "xiaohongshu": _parse_xiaohongshu,
    "xhs": _parse_xiaohongshu,
    "tiktok": _parse_tiktok,
    "instagram": _parse_generic,
    "facebook": _parse_generic,
    "twitter": _parse_generic,
    "reddit": _parse_generic,
    "generic": _parse_generic,
}


class BrowserChannel:
    name = "browser"

    def __init__(self, fetch_html: FetchHtml | None = None):
        self._fetch_html = fetch_html or _default_fetch_html

    def fetch(self, item: dict) -> list[RawPost]:
        platform = (item.get("platform") or "generic").lower()
        parser = _PARSERS.get(platform)
        if parser is None:
            raise ValueError(f"unknown platform: {platform!r}")
        url = item["url"]
        wait_for = item.get("wait_for")
        html = self._fetch_html(url, wait_for)
        posts = parser(html, item)
        max_items = item.get("max_items")
        if max_items is not None:
            posts = posts[: int(max_items)]
        return posts

    def health(
        self,
        *,
        playwright_available: bool | None = None,
        chrome_resolvable: bool | None = None,
    ) -> ChannelHealth:
        mode = (os.getenv("AGENTIC_BOARD_BROWSER") or "chrome").lower()
        if mode == "disabled":
            return ChannelHealth(
                self.name, "unconfigured", "AGENTIC_BOARD_BROWSER=disabled"
            )

        if playwright_available is None:
            try:
                import playwright  # noqa: F401

                playwright_available = True
            except ImportError:
                playwright_available = False

        if not playwright_available:
            return ChannelHealth(
                self.name,
                "unconfigured",
                "playwright not installed (uv add playwright && playwright install chrome)",
            )

        if chrome_resolvable is None:
            chrome_resolvable = chrome_channel_resolvable()
        if not chrome_resolvable:
            return ChannelHealth(
                self.name,
                "unconfigured",
                "Chrome/Chromium binary not found on PATH",
            )
        return ChannelHealth(self.name, "ok", "playwright + chrome available")
