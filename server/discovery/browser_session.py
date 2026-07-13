"""Shared Chrome profile resolution and sync Playwright rendering for discovery.

Kept outside the board domain so discovery channels never import board tools.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

_BROWSER_LOCK = threading.Lock()
_DEFAULT_TIMEOUT_MS = 30_000


def resolve_chrome_user_data_dir() -> str:
    """Return Chrome's user-data dir for the current OS.

    Override with AGENTIC_BOARD_CHROME_USER_DATA_DIR (same env as board tools).
    """
    override = os.getenv("AGENTIC_BOARD_CHROME_USER_DATA_DIR")
    if override:
        return override
    home = Path(os.path.expanduser("~"))
    if sys.platform.startswith("linux"):
        return str(home / ".config" / "google-chrome")
    if sys.platform == "darwin":
        return str(home / "Library" / "Application Support" / "Google" / "Chrome")
    if sys.platform.startswith("win"):
        local = os.getenv("LOCALAPPDATA") or str(home / "AppData" / "Local")
        return str(Path(local) / "Google" / "Chrome" / "User Data")
    return str(home / ".config" / "google-chrome")


def chrome_channel_resolvable() -> bool:
    """Best-effort check that a Chrome binary is likely available."""
    from shutil import which

    return any(
        which(name)
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
    )


def render_html(url: str, wait_for: str | None = None) -> str:
    """Open *url* in a persistent Chrome context and return rendered HTML.

    Sync Playwright API (discovery Channel.fetch is synchronous). Uses a
    process-wide lock so only one Chrome session runs at a time.
    """
    from playwright.sync_api import sync_playwright

    user_data_dir = resolve_chrome_user_data_dir()
    headed = os.getenv("AGENTIC_BOARD_BROWSER_HEADED", "1") != "0"

    with _BROWSER_LOCK:
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                channel="chrome",
                headless=not headed,
            )
            try:
                page = ctx.new_page()
                page.goto(url, timeout=_DEFAULT_TIMEOUT_MS)
                try:
                    page.wait_for_load_state("networkidle", timeout=20_000)
                except Exception:
                    pass
                if wait_for:
                    try:
                        page.wait_for_selector(wait_for, timeout=15_000)
                    except Exception:
                        pass
                return page.content()
            finally:
                ctx.close()
