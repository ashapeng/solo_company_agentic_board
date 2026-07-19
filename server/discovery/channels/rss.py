from __future__ import annotations

import feedparser
import httpx

from server.discovery.channels.base import ChannelHealth, RawPost
from server.discovery.http_safety import SafeHttpClient


class RssChannel:
    name = "rss"

    def __init__(
        self,
        parse=None,
        transport: httpx.BaseTransport | None = None,
    ):
        self._parse = parse
        self._client = SafeHttpClient(transport=transport, timeout=30, follow_redirects=True)

    def fetch(self, item: dict) -> list[RawPost]:
        if self._parse is not None:
            feed = self._parse(item["url"])
        else:
            response = self._client.get(item["url"])
            response.raise_for_status()
            feed = feedparser.parse(response.content)
        if feed.get("bozo") and not feed.get("entries"):
            raise ValueError(f"unparseable feed: {item['url']}: {feed.get('bozo_exception')}")
        posts = []
        for entry in feed.entries:
            posts.append(
                RawPost(
                    id=entry.get("id") or entry.get("link", ""),
                    channel=self.name,
                    source=item["label"],
                    title=entry.get("title", ""),
                    body=entry.get("summary", ""),
                    url=entry.get("link", ""),
                    author=entry.get("author", ""),
                    created_at=entry.get("published", ""),
                )
            )
        return posts

    def health(self) -> ChannelHealth:
        return ChannelHealth(self.name, "ok", "feedparser available; feeds probed at fetch time")
