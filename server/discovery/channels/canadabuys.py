from __future__ import annotations

import csv
import io

import httpx

from server.discovery.channels.base import ChannelHealth, RawPost

CSV_URL = (
    "https://canadabuys.canada.ca/opendata/pub/"
    "newTenderNotice-nouvelAvisAppelOffres.csv"
)


def _col(row: dict, *substrings: str) -> str:
    for key, value in row.items():
        lowered = key.lower()
        if all(s in lowered for s in substrings):
            return value or ""
    return ""


class CanadaBuysChannel:
    name = "canadabuys"

    def __init__(self, transport: httpx.BaseTransport | None = None):
        self._client = httpx.Client(transport=transport, timeout=60, follow_redirects=True)

    def fetch(self, item: dict) -> list[RawPost]:
        resp = self._client.get(CSV_URL)
        resp.raise_for_status()
        keywords = [k.lower() for k in item["keywords"]]
        posts = []
        for row in csv.DictReader(io.StringIO(resp.text)):
            title = _col(row, "title", "eng")
            description = _col(row, "description", "eng")
            haystack = f"{title} {description}".lower()
            if not any(k in haystack for k in keywords):
                continue
            posts.append(
                RawPost(
                    id=_col(row, "referencenumber") or title,
                    channel=self.name,
                    source=item["label"],
                    title=title,
                    body=description,
                    url=_col(row, "noticeurl", "eng"),
                    extra={
                        "deadline": _col(row, "closingdate"),
                        "agency": _col(row, "contractingentityname", "eng"),
                        "notice_type": "tender",
                    },
                )
            )
        return posts

    def health(self) -> ChannelHealth:
        try:
            resp = self._client.head(CSV_URL)
            resp.raise_for_status()
            return ChannelHealth(self.name, "ok")
        except Exception as exc:
            return ChannelHealth(self.name, "error", str(exc))
