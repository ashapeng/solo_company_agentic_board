"""Import agent-captured browser posts into the discovery store (Layer B).

Usage:
  uv run python scripts/import_browser_capture.py capture.json --platform xiaohongshu
  uv run python scripts/import_browser_capture.py capture.json --platform tiktok --week 2026-W28

Input JSON: array of RawPost dicts (see server/discovery/channels/base.py).
Output: data/discovery/raw/<week>/browser-<platform>.json via DiscoveryStore
(filter_new → write_raw → mark_seen).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import fields
from pathlib import Path

from server.discovery.channels.base import RawPost
from server.discovery.store import DiscoveryStore, iso_week

DEFAULT_STORE_ROOT = Path("data/discovery")

_RAW_POST_KEYS = {f.name for f in fields(RawPost)}


def _to_raw_post(raw: dict, *, platform: str) -> RawPost:
    data = {k: v for k, v in raw.items() if k in _RAW_POST_KEYS}
    data.setdefault("channel", "browser")
    data.setdefault("source", f"browser-{platform}")
    data.setdefault("title", "")
    data.setdefault("body", "")
    data.setdefault("url", "")
    data.setdefault("author", "")
    data.setdefault("score", 0)
    data.setdefault("comments", 0)
    data.setdefault("created_at", "")
    extra = dict(data.get("extra") or {})
    extra.setdefault("platform", platform)
    data["extra"] = extra
    if not data.get("id"):
        raise ValueError("each post requires a stable platform-unique id")
    return RawPost(**data)


def import_capture(
    *,
    capture_path: Path,
    platform: str,
    week: str | None = None,
    store_root: Path | None = None,
) -> dict:
    """Load agent JSON, dedup via store, write browser-<platform>.json."""
    payload = json.loads(capture_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("capture file must be a JSON array of RawPost objects")

    posts = [_to_raw_post(item, platform=platform) for item in payload]
    root = store_root or DEFAULT_STORE_ROOT
    store = DiscoveryStore(root)
    week_key = week or iso_week()
    new_posts = store.filter_new(posts)
    skipped = len(posts) - len(new_posts)
    path = None
    if new_posts:
        label = platform
        path = store.write_raw(week_key, "browser", label, new_posts)
        store.mark_seen(new_posts)
    return {
        "week": week_key,
        "platform": platform,
        "imported": len(new_posts),
        "skipped": skipped,
        "path": str(path) if path else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path, help="JSON array of RawPost dicts")
    parser.add_argument(
        "--platform",
        required=True,
        help="Platform label used in browser-<platform>.json (e.g. xiaohongshu)",
    )
    parser.add_argument("--week", default=None, help="ISO week override (default: current)")
    parser.add_argument(
        "--store-root",
        type=Path,
        default=None,
        help="Discovery store root (default: data/discovery)",
    )
    args = parser.parse_args(argv)
    root = args.store_root if args.store_root is not None else DEFAULT_STORE_ROOT
    result = import_capture(
        capture_path=args.capture,
        platform=args.platform,
        week=args.week,
        store_root=root,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
