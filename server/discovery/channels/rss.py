from __future__ import annotations

import feedparser

from server.discovery.channels.base import ChannelHealth, RawPost


class RssChannel:
    name = "rss"

    def __init__(self, parse=feedparser.parse):
        self._parse = parse

    def fetch(self, item: dict) -> list[RawPost]:
        feed = self._parse(item["url"])
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
