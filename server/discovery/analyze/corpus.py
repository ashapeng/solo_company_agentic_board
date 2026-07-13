from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Any

from server.discovery.channels.base import RawPost


DEFAULT_MAX_POSTS = 80
DEFAULT_BODY_CHARS = 400
DEFAULT_MAX_PAYLOAD_CHARS = 60_000


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def records_digest(records: list[dict[str, Any]]) -> str:
    return hashlib.sha256(canonical_json(records).encode("utf-8")).hexdigest()


def post_engagement(post: RawPost) -> int:
    return max(0, int(post.score or 0)) + max(0, int(post.comments or 0))


def _rank_key(post: RawPost) -> tuple[int, str, str]:
    # Descending engagement and timestamp, then ascending stable key.
    return (-post_engagement(post), _reverse_text(post.created_at or ""), post.key())


def _reverse_text(value: str) -> str:
    """Sortable inverse for ISO timestamps without platform-specific parsing."""
    return "".join(chr(0x10FFFF - ord(ch)) for ch in value)


def normalized_engagement(posts: list[RawPost]) -> dict[str, float]:
    """Compute reproducible within-channel ordinal percentile in [0, 1]."""
    by_channel: dict[str, list[RawPost]] = defaultdict(list)
    for post in posts:
        by_channel[post.channel].append(post)
    result: dict[str, float] = {}
    for channel_posts in by_channel.values():
        ranked = sorted(channel_posts, key=_rank_key)
        denominator = max(1, len(ranked) - 1)
        for index, post in enumerate(ranked):
            result[post.key()] = 1.0 if len(ranked) == 1 else round(1 - index / denominator, 6)
    return result


def _selected_posts(posts: list[RawPost], max_posts: int) -> list[RawPost]:
    if max_posts <= 0:
        return []
    by_channel: dict[str, list[RawPost]] = defaultdict(list)
    for post in posts:
        by_channel[post.channel].append(post)
    for values in by_channel.values():
        values.sort(key=_rank_key)

    channels = sorted(by_channel)
    cap = max_posts if len(channels) <= 1 else max(1, (max_posts + 1) // 2)
    chosen: list[RawPost] = []
    counts: dict[str, int] = defaultdict(int)
    used: set[str] = set()

    # One-record floor when capacity permits. When not, best channels win.
    channel_heads = [values[0] for values in by_channel.values() if values]
    for post in sorted(channel_heads, key=_rank_key)[:max_posts]:
        chosen.append(post)
        used.add(post.key())
        counts[post.channel] += 1

    ranked_all = sorted(posts, key=_rank_key)
    for post in ranked_all:
        if len(chosen) >= max_posts:
            break
        if post.key() in used or counts[post.channel] >= cap:
            continue
        chosen.append(post)
        used.add(post.key())
        counts[post.channel] += 1
    return sorted(chosen, key=_rank_key)


def _truncate(value: str, limit: int) -> str:
    clean = value or ""
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 1)].rstrip() + "…"


def prepare_corpus(
    posts: list[RawPost],
    *,
    max_posts: int = DEFAULT_MAX_POSTS,
    body_chars: int = DEFAULT_BODY_CHARS,
    max_payload_chars: int = DEFAULT_MAX_PAYLOAD_CHARS,
    retrieved_at: str = "",
) -> list[dict[str, Any]]:
    """Select bounded records while preserving active-channel representation."""
    scores = normalized_engagement(posts)
    records: list[dict[str, Any]] = []
    for post in _selected_posts(posts, max_posts):
        record = {
            "post_key": post.key(),
            "channel": post.channel,
            "source": post.source,
            "title": _truncate(post.title, body_chars),
            "body": _truncate(post.body, body_chars),
            "url": post.url,
            "author": post.author,
            "score": max(0, int(post.score or 0)),
            "comments": max(0, int(post.comments or 0)),
            "normalized_engagement": scores[post.key()],
            "created_at": post.created_at,
            "retrieved_at": retrieved_at,
        }
        candidate = [*records, record]
        if len(canonical_json(candidate)) > max_payload_chars:
            break
        records.append(record)
    return records
