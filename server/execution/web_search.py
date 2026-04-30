"""Execution-layer web search providers and evidence packet creation.

Providers:
  - brave                : Brave Search API (~1K free requests/mo via $5 credits, needs BRAVE_API_KEY)
  - google_programmable  : Google Programmable Search (Custom Search JSON API, 100/day free)
  - duckduckgo           : DuckDuckGo HTML scraping (free, no key needed)
  - tavily               : Tavily Search API (paid)
  - fake                 : Deterministic test stubs
  - disabled             : No-op placeholder
"""

from __future__ import annotations

import logging
import os
import re
import time
import unicodedata
from collections import deque
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx

from . import evidence
from .search_cache import SearchCache

logger = logging.getLogger(__name__)

_cache = SearchCache(maxsize=128, ttl_seconds=1800)
_SESSION_BUCKETS: dict[str, deque[float]] = {}

# ── Query-type → search-worthiness mapping (Layer 2 auto-trigger) ────────

_SEARCH_WORTHY_TYPES: dict[str, str] = {
    "strategic":   "",       # market sizing, competitive landscape, GTM
    "product":     "",       # MVP definition, feature prioritization, PMF
    "customer":    "",       # customer discovery, personas, pain points
    "technical":   "",       # prototyping, build-vs-buy, tech trends
    "finance":     "",       # pricing, runway analysis, market data
    "legal":       "",       # regulatory landscape, compliance updates
}


def _sweep_empty_session_buckets() -> None:
    """Drop any buckets that emptied between requests."""
    empties = [key for key, bucket in _SESSION_BUCKETS.items() if not bucket]
    for key in empties:
        _SESSION_BUCKETS.pop(key, None)


class WebSearchError(Exception):
    """Raised when a configured web search provider fails."""


def is_query_type_search_worthy(query_type: str | None) -> bool:
    """Return True if this query type should trigger automatic web search."""
    if not query_type:
        return False
    return query_type in _SEARCH_WORTHY_TYPES


def _build_role_specific_query(
    base_query: str,
    member_id: str,
    member_role: str,
) -> str:
    """Augment the base query with member-role context for better results."""
    role_keywords: dict[str, list[str]] = {
        "strategist":  ["market", "competition", "industry trend", "strategy"],
        "product":     ["product", "feature", "user need", "MVP"],
        "researcher":  ["customer", "user research", "persona", "pain point"],
        "critic":      ["risk", "challenge", "failure case", "downside"],
        "architect":   ["technology", "architecture", "stack", "integration"],
        "builder":     ["implementation", "engineering", "tool", "framework"],
        "guardian":    ["security", "privacy", "compliance", "threat"],
        "operator":    ["deployment", "operations", "monitoring", "reliability"],
    }
    keywords = role_keywords.get(member_id, []) or [member_role]
    augments = keywords[:2] if len(keywords) >= 2 else keywords
    return f"{base_query} {' '.join(augments)}"


async def web_search(
    query: str,
    *,
    provider: str | None = None,
    max_results: int = 5,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Search the web from execution workflows and persist an evidence packet."""
    selected = (provider or os.getenv("WEB_SEARCH_PROVIDER") or "tavily").lower()

    if selected in {"", "disabled", "none"}:
        return _disabled_result(query)

    # Cache probe BEFORE rate limit — cache hits cost zero provider calls.
    normalized_query = unicodedata.normalize("NFC", query).strip().lower()
    cache_key = (normalized_query, selected, max_results)
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    # Per-session rate limit.
    bucket_key = session_id or "anon"
    try:
        limit = int(os.getenv("AGENTIC_BOARD_WEB_SEARCH_RATE_LIMIT", "20") or 0)
    except ValueError:
        limit = 20
    try:
        window = int(os.getenv("AGENTIC_BOARD_WEB_SEARCH_RATE_WINDOW_SECONDS", "60") or 0)
    except ValueError:
        window = 60

    if limit > 0 and window > 0:
        _sweep_empty_session_buckets()
        now = time.monotonic()
        bucket = _SESSION_BUCKETS.setdefault(bucket_key, deque())
        while bucket and bucket[0] <= now - window:
            bucket.popleft()
        if len(bucket) >= limit:
            return {
                "query": query,
                "provider": selected,
                "results": [],
                "evidence_packet": None,
                "warnings": [f"session rate limit: {limit}/{window}s"],
            }
        bucket.append(now)

    if selected == "fake":
        results = _fake_results(query)
    elif selected == "tavily":
        results = await _tavily_search(query, max_results=max_results)
    elif selected in {"brave", "brave_search"}:
        results = await _brave_search(query, max_results=max_results)
    elif selected in {"google", "google_programmable", "google_programmable_search"}:
        results = await _google_programmable_search(query, max_results=max_results)
    elif selected in {"duckduckgo", "ddg"}:
        results = await _duckduckgo_search(query, max_results=max_results)
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
    response = {
        "query": query,
        "provider": selected,
        "results": results,
        "evidence_packet": packet,
        "warnings": [],
    }
    _cache.put(cache_key, response)
    return response


def _disabled_result(query: str) -> dict[str, Any]:
    return {
        "query": query,
        "provider": "disabled",
        "results": [],
        "evidence_packet": None,
        "warnings": [
            "Web search unavailable: set WEB_SEARCH_PROVIDER to one of "
            "'brave' (~1K free requests/mo via $5 credits, needs BRAVE_API_KEY), "
            "'google_programmable' (Google Custom Search JSON API, 100/day free, needs GOOGLE_SEARCH_API_KEY + GOOGLE_SEARCH_CX), "
            "'duckduckgo' (free, no key required), "
            "'tavily' (paid, needs TAVILY_API_KEY), "
            "or use provider='fake' in tests.",
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
    """Search via Tavily Search API.

    Required env:
      TAVILY_API_KEY  — your Tavily API key (tvly-...)

    Auth: Bearer token in Authorization header.
    Pricing: 1 credit per request (basic/fast/ultra-fast), 2 credits (advanced).
    Docs: https://docs.tavily.com/documentation/api-reference/endpoint/search
    """
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        logger.warning("Tavily Search requires TAVILY_API_KEY env var.")
        return []

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "query": query,
        "max_results": max(0, min(max_results, 20)),
        "search_depth": "basic",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.tavily.com/search",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("Tavily Search API error %s: %s", exc.response.status_code, exc)
        return []
    except Exception as exc:
        logger.warning("Tavily Search failed: %s", exc)
        return []

    results = []
    for item in data.get("results", []):
        url = item.get("url") or ""
        # Extract domain as publisher from URL
        publisher = ""
        if url:
            try:
                from urllib.parse import urlparse
                publisher = urlparse(url).netloc or ""
            except Exception:
                pass
        results.append({
            "title": item.get("title") or url or "Untitled source",
            "url": url,
            "snippet": (item.get("content") or "")[:500],
            "publisher": publisher,
            "retrieved_at": _utc_now(),
        })
    return results


# ═══════════════════════════════════════════════════════════════════════
# Brave Search
# ═══════════════════════════════════════════════════════════════════════

async def _brave_search(query: str, *, max_results: int) -> list[dict[str, Any]]:
    """Search via Brave Search API.

    Required env:
      BRAVE_API_KEY  — your Brave Search API key

    Free credits: ~1,000 requests/month included ($5 free credits on the $5/1K Search plan).
    Set a spending limit in your Brave dashboard to avoid unexpected charges.
    Capacity: up to 50 req/s on Search plan.
    """
    api_key = os.getenv("BRAVE_API_KEY")
    if not api_key:
        logger.warning(
            "Brave Search requires BRAVE_API_KEY env var. "
            "Get one at https://brave.com/search/api/"
        )
        return []

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "Authorization": f"Bearer {api_key}",
    }
    params = {
        "q": query,
        "count": max(1, min(max_results, 10)),
        "search_type": "news" if any(
            kw in query.lower() for kw in ("news", "today", "latest", "breaking")
        ) else "web",
        "freshness": "pw",  # past week by default for better relevance
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("Brave Search API error %s: %s", exc.response.status_code, exc)
        return []

    results = []
    for item in data.get("web", {}).get("results", []):
        # Clean HTML entities from description/description
        desc = item.get("description") or ""
        desc = re.sub(r"<[^>]+>", "", desc).strip()
        results.append({
            "title": item.get("title") or "Untitled source",
            "url": item.get("url") or "",
            "snippet": desc[:500] if desc else "",
            "publisher": (item.get("meta_url") or {}).get("site_name") or "",
            "retrieved_at": _utc_now(),
        })
    return results


# ═══════════════════════════════════════════════════════════════════════
# Google Programmable Search (Custom Search JSON API)
# ═══════════════════════════════════════════════════════════════════════

async def _google_programmable_search(query: str, *, max_results: int) -> list[dict[str, Any]]:
    """Search via Google Custom Search JSON API (Programmable Search).

    Required env:
      GOOGLE_SEARCH_API_KEY   — your Google Cloud API key
      GOOGLE_SEARCH_CX       — your Programmable Search Engine ID (cx)

    Free tier: 100 queries/day.
    Docs: https://developers.google.com/custom-search/v1/overview
    """
    api_key = os.getenv("GOOGLE_SEARCH_API_KEY")
    cx = os.getenv("GOOGLE_SEARCH_CX")
    if not api_key or not cx:
        logger.warning(
            "Google Programmable Search requires "
            "GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX env vars."
        )
        return []

    params = {
        "key": api_key,
        "cx": cx,
        "q": query,
        "num": max(1, min(max_results, 10)),
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                "https://www.googleapis.com/customsearch/v1",
                params=params,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("Google Search API error %s: %s", exc.response.status_code, exc)
        return []

    results = []
    for item in data.get("items", []):
        snippet = item.get("snippet") or ""
        snippet = re.sub(r"<[^>]+>", "", snippet)
        results.append({
            "title": item.get("title") or "Untitled source",
            "url": item.get("link") or "",
            "snippet": snippet[:500],
            "publisher": item.get("displayLink") or "",
            "retrieved_at": _utc_now(),
        })
    return results


# ═══════════════════════════════════════════════════════════════════════
# DuckDuckGo (free, no key required — best-effort scraper)
# ═══════════════════════════════════════════════════════════════════════

async def _duckduckgo_search(query: str, *, max_results: int) -> list[dict[str, Any]]:
    """Search via DuckDuckGo HTML (free, no API key required).

    This is a lightweight scraper of DuckDuckGo's lite HTML interface.
    It is rate-limited and may break if DuckDuckGo changes their markup.
    For production use, prefer brave or google_programmable.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; AgenticBoard/1.0; "
            "+https://github.com/ashapeng/agentic-board)"
        ),
    }
    params = {"q": query, "kl": "wt-wt", "df": ""}
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.get(
                "https://lite.duckduckgo.com/lite/",
                params=params,
                headers=headers,
            )
            response.raise_for_status()
            html = response.text
    except Exception as exc:
        logger.warning("DuckDuckGo search failed: %s", exc)
        return []

    results = []
    link_pattern = re.compile(
        r'<a[^>]+rel="nofollow"[^>]+href="([^"]+)"[^>]*>([^<]*)</a>',
        re.IGNORECASE,
    )
    snippet_pattern = re.compile(
        r'<td[^>]*class="[^"]*result-snippet[^"]*"[^>]*>(.*?)</td>',
        re.DOTALL | re.IGNORECASE,
    )

    links = link_pattern.findall(html)
    snippets_raw = snippet_pattern.findall(html)

    count = min(len(links), max_results)
    for i in range(count):
        url, title = links[i]
        snippet_html = snippets_raw[i] if i < len(snippets_raw) else ""
        snippet = re.sub(r"<[^>]+>", "", snippet_html).strip()
        if url.startswith("//"):
            url = f"https:{url}"
        results.append({
            "title": title.strip() or "Untitled source",
            "url": url,
            "snippet": snippet[:500] if snippet else "",
            "publisher": "DuckDuckGo",
            "retrieved_at": _utc_now(),
        })

    return results


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
