from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import httpx

from server.discovery.channels.base import ChannelHealth, RawPost

API = "https://api.sam.gov/opportunities/v2/search"


class SamGovChannel:
    name = "sam_gov"

    def __init__(self, transport: httpx.BaseTransport | None = None, api_key: str | None = None):
        self._client = httpx.Client(transport=transport, timeout=30)
        self._api_key = api_key or os.environ.get("SAM_GOV_API_KEY")

    def fetch(self, item: dict) -> list[RawPost]:
        if not self._api_key:
            raise RuntimeError("SAM_GOV_API_KEY not set (free key: https://sam.gov/apis)")
        now = datetime.now(tz=timezone.utc)
        posts: list[RawPost] = []
        for keyword in item["keywords"]:
            resp = self._client.get(
                API,
                params={
                    "api_key": self._api_key,
                    "title": keyword,
                    "postedFrom": (now - timedelta(days=7)).strftime("%m/%d/%Y"),
                    "postedTo": now.strftime("%m/%d/%Y"),
                    "limit": 50,
                },
            )
            resp.raise_for_status()
            for opp in resp.json().get("opportunitiesData", []):
                posts.append(
                    RawPost(
                        id=str(opp.get("noticeId", "")),
                        channel=self.name,
                        source=keyword,
                        title=opp.get("title", ""),
                        body=opp.get("description") or "",
                        url=opp.get("uiLink", ""),
                        created_at=opp.get("postedDate", ""),
                        extra={
                            "deadline": opp.get("responseDeadLine") or "",
                            "agency": opp.get("fullParentPathName") or "",
                            "notice_type": opp.get("type") or "",
                        },
                    )
                )
        return posts

    def health(self) -> ChannelHealth:
        if not self._api_key:
            return ChannelHealth(
                self.name, "unconfigured", "SAM_GOV_API_KEY not set (free key: https://sam.gov/apis)"
            )
        return ChannelHealth(self.name, "ok")
