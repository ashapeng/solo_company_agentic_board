from __future__ import annotations

import httpx

from server.discovery.channels.base import ChannelHealth, RawPost

API = "https://api.grants.gov/v1/api/search2"


class GrantsGovChannel:
    name = "grants_gov"

    def __init__(self, transport: httpx.BaseTransport | None = None):
        self._client = httpx.Client(transport=transport, timeout=30)

    def fetch(self, item: dict) -> list[RawPost]:
        posts: list[RawPost] = []
        for keyword in item["keywords"]:
            resp = self._client.post(API, json={"keyword": keyword, "rows": 50})
            resp.raise_for_status()
            for hit in (resp.json().get("data") or {}).get("oppHits", []):
                opp_id = str(hit.get("id", ""))
                posts.append(
                    RawPost(
                        id=opp_id,
                        channel=self.name,
                        source=keyword,
                        title=hit.get("title", ""),
                        body=f"Opportunity number: {hit.get('number', '')}",
                        url=f"https://www.grants.gov/search-results-detail/{opp_id}",
                        created_at=hit.get("openDate") or "",
                        extra={
                            "deadline": hit.get("closeDate") or "",
                            "agency": hit.get("agencyName") or "",
                            "notice_type": "grant",
                        },
                    )
                )
        return posts

    def health(self) -> ChannelHealth:
        try:
            resp = self._client.post(API, json={"keyword": "test", "rows": 1})
            resp.raise_for_status()
            return ChannelHealth(self.name, "ok")
        except Exception as exc:
            return ChannelHealth(self.name, "error", str(exc))
