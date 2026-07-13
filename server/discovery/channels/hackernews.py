from __future__ import annotations

import time

import httpx

from server.discovery.channels.base import ChannelHealth, RawPost
from server.discovery.http_safety import SafeHttpClient

API = "https://hn.algolia.com/api/v1/search"


class HackerNewsChannel:
    name = "hackernews"

    def __init__(self, transport: httpx.BaseTransport | None = None):
        self._client = SafeHttpClient(transport=transport, timeout=20)

    def fetch(self, item: dict) -> list[RawPost]:
        week_ago = int(time.time()) - 7 * 86400
        resp = self._client.get(
            API,
            params={
                "query": item["query"],
                "tags": "story",
                "hitsPerPage": 50,
                "numericFilters": f"created_at_i>{week_ago}",
            },
        )
        resp.raise_for_status()
        posts = []
        for hit in resp.json().get("hits", []):
            posts.append(
                RawPost(
                    id=str(hit["objectID"]),
                    channel=self.name,
                    source=item["query"],
                    title=hit.get("title", ""),
                    body=hit.get("story_text") or "",
                    url=f"https://news.ycombinator.com/item?id={hit['objectID']}",
                    author=hit.get("author", ""),
                    score=int(hit.get("points") or 0),
                    comments=int(hit.get("num_comments") or 0),
                    created_at=hit.get("created_at", ""),
                    extra={"external_url": hit.get("url") or ""},
                )
            )
        return posts

    def health(self) -> ChannelHealth:
        try:
            resp = self._client.get(API, params={"query": "test", "hitsPerPage": 1})
            resp.raise_for_status()
            return ChannelHealth(self.name, "ok")
        except Exception as exc:
            return ChannelHealth(self.name, "error", str(exc))
