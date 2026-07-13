from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

from server.discovery.channels.base import ChannelHealth, RawPost

USER_AGENT = "agentic-board-discovery/0.1 (weekly market research; contact via repo)"


class RedditChannel:
    name = "reddit"

    def __init__(self, transport: httpx.BaseTransport | None = None, sleep=time.sleep):
        self._fixture_mode = transport is not None
        self._client = httpx.Client(
            transport=transport,
            headers={"User-Agent": USER_AGENT},
            timeout=20,
            follow_redirects=True,
        )
        self._sleep = sleep

    def fetch(self, item: dict) -> list[RawPost]:
        if not self._fixture_mode:
            raise RuntimeError(
                "reddit adapter is held: approved OAuth/Data API replacement required"
            )
        sub = item["sub"]
        url = f"https://www.reddit.com/r/{sub}/{item.get('sort', 'top')}.json"
        params = {"t": item.get("window", "week"), "limit": 50}
        resp = self._client.get(url, params=params)
        if resp.status_code == 429:
            self._sleep(30)
            resp = self._client.get(url, params=params)
        resp.raise_for_status()
        posts = []
        for child in resp.json().get("data", {}).get("children", []):
            d = child.get("data", {})
            created = d.get("created_utc")
            posts.append(
                RawPost(
                    id=str(d.get("id", "")),
                    channel=self.name,
                    source=sub,
                    title=d.get("title", ""),
                    body=d.get("selftext", ""),
                    url=f"https://www.reddit.com{d.get('permalink', '')}",
                    author=d.get("author", ""),
                    score=int(d.get("score") or 0),
                    comments=int(d.get("num_comments") or 0),
                    created_at=(
                        datetime.fromtimestamp(created, tz=timezone.utc).isoformat()
                        if created
                        else ""
                    ),
                )
            )
        self._sleep(2)
        return posts

    def health(self) -> ChannelHealth:
        if not self._fixture_mode:
            return ChannelHealth(
                self.name,
                "held",
                "approved OAuth/Data API replacement required",
                posture="held",
            )
        try:
            resp = self._client.get(
                "https://www.reddit.com/r/all/top.json", params={"limit": 1}
            )
            resp.raise_for_status()
            return ChannelHealth(self.name, "ok")
        except Exception as exc:
            return ChannelHealth(self.name, "error", str(exc))
