from __future__ import annotations

import os

import httpx

from server.discovery.channels.base import ChannelHealth, RawPost

API = "https://api.producthunt.com/v2/api/graphql"
QUERY = """
query($topic: String!) {
  posts(first: 20, topic: $topic, order: VOTES) {
    edges { node { id name tagline url votesCount commentsCount createdAt } }
  }
}
"""


class ProductHuntChannel:
    name = "producthunt"

    def __init__(self, transport: httpx.BaseTransport | None = None, token: str | None = None):
        self._token = token or os.environ.get("PRODUCTHUNT_TOKEN")
        self._client = httpx.Client(transport=transport, timeout=30)

    def fetch(self, item: dict) -> list[RawPost]:
        if not self._token:
            raise RuntimeError("PRODUCTHUNT_TOKEN not set")
        resp = self._client.post(
            API,
            json={"query": QUERY, "variables": {"topic": item["topic"]}},
            headers={"Authorization": f"Bearer {self._token}"},
        )
        resp.raise_for_status()
        edges = resp.json()["data"]["posts"]["edges"]
        return [
            RawPost(
                id=str(e["node"]["id"]),
                channel=self.name,
                source=item["topic"],
                title=e["node"].get("name", ""),
                body=e["node"].get("tagline", ""),
                url=e["node"].get("url", ""),
                score=int(e["node"].get("votesCount") or 0),
                comments=int(e["node"].get("commentsCount") or 0),
                created_at=e["node"].get("createdAt", ""),
            )
            for e in edges
        ]

    def health(self) -> ChannelHealth:
        if not self._token:
            return ChannelHealth(self.name, "unconfigured", "PRODUCTHUNT_TOKEN not set")
        return ChannelHealth(self.name, "ok")
