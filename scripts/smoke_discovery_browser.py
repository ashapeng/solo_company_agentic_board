"""Smoke: prove browser discovery channel can render a public page.

Does not require social logins. Uses the generic parser; may return 0 posts
on sites without article[data-post-id] markup — success means fetch completes.

Run: AGENTIC_BOARD_BROWSER_HEADED=0 uv run python scripts/smoke_discovery_browser.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from server.discovery.channels.browser import BrowserChannel


def main() -> int:
    os.environ.setdefault("AGENTIC_BOARD_BROWSER_HEADED", "0")
    # Isolated profile avoids SingletonLock hangs against the system Chrome
    # profile in CI/cloud. For logged-in capture, set
    # AGENTIC_BOARD_CHROME_USER_DATA_DIR to the real profile instead.
    os.environ.setdefault(
        "AGENTIC_BOARD_CHROME_USER_DATA_DIR",
        str(Path.home() / ".cache" / "agentic-board" / "chrome-profile"),
    )
    ch = BrowserChannel()
    health = ch.health()
    print(f"health: {health.status} — {health.detail}")
    if health.status != "ok":
        print("✗ browser channel not ready")
        return 1
    posts = ch.fetch(
        {
            "platform": "generic",
            "url": "https://news.ycombinator.com/",
            "label": "hn-smoke",
            "wait_for": ".athing",
            "max_items": 5,
        }
    )
    print(f"✓ fetch completed ({len(posts)} posts via generic parser)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
