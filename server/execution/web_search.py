"""Execution-layer web search providers and evidence packet creation."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx

from . import evidence


class WebSearchError(Exception):
    """Raised when a configured web search provider fails."""


async def web_search(
    query: str,
    *,
    provider: str | None = None,
    max_results: int = 5,
) -> dict[str, Any]:
    """Search the web from execution workflows and persist an evidence packet."""
    selected = (provider or os.getenv("WEB_SEARCH_PROVIDER") or "disabled").lower()
    if selected in {"", "disabled", "none"}:
        return _disabled_result(query)
    if selected == "fake":
        results = _fake_results(query)
    elif selected == "tavily":
        results = await _tavily_search(query, max_results=max_results)
    else:
        return {
            "query": query,
            "provider": selected,
            "results": [],
            "evidence_packet": None,
            "warnings": [f"Web search provider '{selected}' is unavailable."],
        }

    packet = evidence.create_evidence_packet(
        topic=f"Web search: {query}",
        claims=[item["snippet"] for item in results if item.get("snippet")],
        sources=[
            {
                "title": item.get("title") or item.get("url") or "Untitled source",
                "url": item.get("url") or "",
                "publisher": item.get("publisher"),
                "retrieved_at": item.get("retrieved_at") or _utc_now(),
                "claim_ids": [f"claim-{index + 1}"],
            }
            for index, item in enumerate(results)
        ],
        freshness="current",
        warnings=[],
    )
    return {
        "query": query,
        "provider": selected,
        "results": results,
        "evidence_packet": packet,
        "warnings": [],
    }


def _disabled_result(query: str) -> dict[str, Any]:
    return {
        "query": query,
        "provider": "disabled",
        "results": [],
        "evidence_packet": None,
        "warnings": [
            "Web search unavailable: set WEB_SEARCH_PROVIDER=tavily and TAVILY_API_KEY, or use provider='fake' in tests."
        ],
    }


def _fake_results(query: str) -> list[dict[str, Any]]:
    return [
        {
            "title": f"Fake result for {query}",
            "url": f"https://example.com/search?q={quote_plus(query)}",
            "snippet": f"Test evidence claim for {query}.",
            "publisher": "Example",
            "retrieved_at": _utc_now(),
        }
    ]


async def _tavily_search(query: str, *, max_results: int) -> list[dict[str, Any]]:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return []
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": max(1, min(max_results, 10)),
        "search_depth": "basic",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post("https://api.tavily.com/search", json=payload)
        response.raise_for_status()
        data = response.json()
    results = []
    for item in data.get("results", []):
        results.append({
            "title": item.get("title") or item.get("url") or "Untitled source",
            "url": item.get("url") or "",
            "snippet": item.get("content") or "",
            "publisher": item.get("source"),
            "retrieved_at": _utc_now(),
        })
    return results


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
