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
_HEADLESS_LAUNCH_ARGS = ("--disable-dev-shm-usage", "--no-sandbox")


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


def resolve_launch_user_data_dir(*, headed: bool | None = None) -> str:
    """Profile dir for Playwright launch.

    Explicit ``AGENTIC_BOARD_CHROME_USER_DATA_DIR`` always wins (imported cookies,
    custom profile). Headless/CI without an override uses an isolated cache
    profile so we do not fight the system Chrome SingletonLock.
    Headed local runs use the real OS Chrome profile (logged-in sessions).
    """
    override = os.getenv("AGENTIC_BOARD_CHROME_USER_DATA_DIR")
    if override:
        return override
    if headed is None:
        headed = os.getenv("AGENTIC_BOARD_BROWSER_HEADED", "1") != "0"
    if not headed:
        path = Path(os.path.expanduser("~")) / ".cache" / "agentic-board" / "chrome-profile"
        path.mkdir(parents=True, exist_ok=True)
        return str(path)
    return resolve_chrome_user_data_dir()


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

    headed = os.getenv("AGENTIC_BOARD_BROWSER_HEADED", "1") != "0"
    user_data_dir = resolve_launch_user_data_dir(headed=headed)
    launch_kwargs: dict = {
        "user_data_dir": user_data_dir,
        "channel": "chrome",
        "headless": not headed,
    }
    if not headed:
        launch_kwargs["args"] = list(_HEADLESS_LAUNCH_ARGS)

    with _BROWSER_LOCK:
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(**launch_kwargs)
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
