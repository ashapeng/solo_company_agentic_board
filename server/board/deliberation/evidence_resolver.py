"""Evidence resolver for the blinded verifier.

Looks up cited URLs in session.evidence_packets first (the pre-fetched
web_search snippets); falls back to a fresh HTTP GET via the existing
SSRF-guarded helper. See docs/superpowers/specs/2026-05-15-board-hardening-design.md §5.3.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from server.board.tools import _safe_http_get

logger = logging.getLogger(__name__)

_DEFAULT_EVIDENCE_DIR = Path("data/evidence_packets")
_MIN_CACHED_SNIPPET_CHARS = 200


def _load_packet(packet_id: str, evidence_dir: Path) -> dict[str, Any] | None:
    path = evidence_dir / f"{packet_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("could not load evidence packet %s: %s", packet_id, e)
        return None


def _build_cache_from_session(
    session: Any, evidence_dir: Path,
) -> dict[str, str]:
    """Walk session.evidence_packets → {url: longest_snippet_text}."""
    cache: dict[str, str] = {}
    packets = getattr(session, "evidence_packets", None) or {}
    if not isinstance(packets, dict):
        return cache
    for packet_id in packets.values():
        packet = _load_packet(str(packet_id), evidence_dir)
        if not packet:
            continue
        sources = packet.get("sources") or []
        claims = packet.get("claims") or []
        # web_search creates parallel arrays (claims[i] is the snippet for sources[i])
        for i, source in enumerate(sources):
            url = (source.get("url") or "").strip()
            if not url:
                continue
            snippet = claims[i] if i < len(claims) else ""
            existing = cache.get(url, "")
            if len(snippet) > len(existing):
                cache[url] = snippet
    return cache


async def _re_fetch(url: str, *, max_chars: int) -> str:
    try:
        resp = await _safe_http_get(url)
    except Exception as e:
        logger.warning("evidence re-fetch failed for %s: %s", url, e)
        return ""
    body = getattr(resp, "text", "") or ""
    if len(body) > max_chars:
        body = body[:max_chars]
    return body


async def resolve_evidence(
    refs: list[str] | tuple[str, ...],
    session: Any,
    *,
    max_chars: int = 4000,
    evidence_dir: Path = _DEFAULT_EVIDENCE_DIR,
) -> dict[str, str]:
    """Return {url: text} for each non-[UNVERIFIED] ref in `refs`.

    Cache-first using session.evidence_packets; re-fetches misses and any
    cached snippet shorter than `_MIN_CACHED_SNIPPET_CHARS`. Truncates to
    `max_chars`. Failed fetches return an empty string so the caller can
    distinguish "tried but no content" from "never looked up".
    """
    cache = _build_cache_from_session(session, evidence_dir)
    out: dict[str, str] = {}
    for ref in refs:
        ref = (ref or "").strip()
        if not ref or ref == "[UNVERIFIED]":
            continue
        if not ref.startswith(("http://", "https://")):
            # not a URL — pass through as-is, no fetching
            out[ref] = ref
            continue
        cached = cache.get(ref, "")
        if len(cached) >= _MIN_CACHED_SNIPPET_CHARS:
            if len(cached) > max_chars:
                cached = cached[:max_chars]
            out[ref] = cached
            continue
        out[ref] = await _re_fetch(ref, max_chars=max_chars)
    return out
