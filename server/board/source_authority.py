"""Source-authority tier classification for `validate_claim` (spec §7.1).

This module is pure: no LLM calls, no config reads. Overrides are passed in
explicitly. `validate_claim` reads `harness_config.hardening.source_authority_overrides`
at call time and forwards.

Tier rule (spec §7.1.2):
    SUPPORTED requires ≥1 academic OR ≥2 major_news OR ≥3 established_blog.
    Anything weaker → UNVERIFIED.
"""
from __future__ import annotations

import logging
from typing import Literal
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

Tier = Literal["academic", "major_news", "established_blog", "unknown"]

_VALID_TIERS: frozenset[str] = frozenset(("academic", "major_news", "established_blog"))


DOMAIN_TIERS: dict[str, str] = {
    # academic / official
    "*.edu": "academic",
    "*.gov": "academic",
    "arxiv.org": "academic",
    "nature.com": "academic",
    "science.org": "academic",
    "doi.org": "academic",

    # major news / authoritative business press
    "reuters.com": "major_news",
    "ft.com": "major_news",
    "wsj.com": "major_news",
    "bloomberg.com": "major_news",
    "economist.com": "major_news",
    "nytimes.com": "major_news",
    "apnews.com": "major_news",

    # established trade / tech publications
    "techcrunch.com": "established_blog",
    "theverge.com": "established_blog",
    "arstechnica.com": "established_blog",
    "stratechery.com": "established_blog",
    "a16z.com": "established_blog",
}


def _hostname(url: str) -> str:
    """Extract a normalized hostname from a URL. Returns '' for anything
    that doesn't parse to an http(s) URL with a non-empty host."""
    if not isinstance(url, str) or not url:
        return ""
    # Reject non-http(s) schemes and the abstract evidence-ref literals
    # ([UNVERIFIED], [INFERENCE], etc.) before urlparse gets confused.
    if not url.lower().startswith(("http://", "https://")):
        return ""
    try:
        parsed = urlparse(url)
    except Exception:  # noqa: BLE001 — never crash on weird input
        return ""
    host = (parsed.hostname or "").lower().strip()
    if host.startswith("www."):
        host = host[4:]
    return host


def _filter_overrides(overrides: dict[str, str] | None) -> dict[str, str]:
    """Drop override entries whose tier is not in _VALID_TIERS. Logs at
    WARNING for each dropped entry. Returns a new dict (never mutates input)."""
    if not overrides:
        return {}
    cleaned: dict[str, str] = {}
    for host, tier in overrides.items():
        if not isinstance(host, str) or not isinstance(tier, str):
            continue
        if tier not in _VALID_TIERS:
            logger.warning(
                "source_authority: ignoring override %r=%r (invalid tier)",
                host, tier,
            )
            continue
        cleaned[host.lower()] = tier
    return cleaned


def tier_for_url(
    url: str,
    *,
    overrides: dict[str, str] | None = None,
) -> Tier:
    """Return the authority tier for one URL.

    Matching algorithm (spec §7.1.1):
      1. Normalize: lowercase the hostname, strip leading 'www.', strip port,
         path, query, fragment.
      2. Build the lookup map: defaults overlaid with overrides (overrides win).
      3. Exact-host match wins outright.
      4. Otherwise scan wildcard entries (keys starting with '*.'): a wildcard
         '*.SUFFIX' matches when the hostname == SUFFIX OR hostname endswith
         '.SUFFIX'. Among matches, the longest SUFFIX wins.
      5. No match → "unknown".

    The function never raises. Malformed URLs, non-http(s) schemes, the
    `[UNVERIFIED]` literal, and None all return "unknown".
    """
    host = _hostname(url)
    if not host:
        return "unknown"

    merged: dict[str, str] = {**DOMAIN_TIERS, **_filter_overrides(overrides)}

    # 3. exact-host match
    if host in merged:
        tier = merged[host]
        return tier if tier in _VALID_TIERS else "unknown"

    # 4. wildcard scan — longest matching suffix wins
    best_suffix = ""
    best_tier: str = "unknown"
    for pattern, tier in merged.items():
        if not pattern.startswith("*."):
            continue
        suffix = pattern[2:]  # strip "*."
        if not suffix:
            continue
        if host == suffix or host.endswith("." + suffix):
            if len(suffix) > len(best_suffix):
                best_suffix = suffix
                best_tier = tier
    if best_suffix:
        return best_tier if best_tier in _VALID_TIERS else "unknown"

    return "unknown"
