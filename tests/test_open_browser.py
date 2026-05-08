"""Tests for the open_browser tool."""
from __future__ import annotations

import sys

import pytest

from server.board import tools


def test_chrome_profile_dir_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("AGENTIC_BOARD_CHROME_USER_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    expected = tmp_path / ".config" / "google-chrome"
    assert tools._resolve_chrome_user_data_dir() == str(expected)


def test_chrome_profile_dir_env_override(monkeypatch):
    monkeypatch.setenv("AGENTIC_BOARD_CHROME_USER_DATA_DIR", "/custom/path")
    assert tools._resolve_chrome_user_data_dir() == "/custom/path"


def test_chrome_profile_dir_macos(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("AGENTIC_BOARD_CHROME_USER_DATA_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    expected = tmp_path / "Library" / "Application Support" / "Google" / "Chrome"
    assert tools._resolve_chrome_user_data_dir() == str(expected)


import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


class _FakePage:
    async def goto(self, url, **kw): pass
    async def wait_for_load_state(self, *a, **kw): pass
    async def content(self):
        return "<html><body><h1>Hello</h1><p>Body</p></body></html>"
    async def close(self): pass


class _FakeContext:
    async def new_page(self): return _FakePage()
    async def close(self): pass


class _FakeBrowserType:
    async def launch_persistent_context(self, **kw):
        return _FakeContext()


class _FakePlaywrightCM:
    chromium = _FakeBrowserType()
    async def __aenter__(self): return self
    async def __aexit__(self, *a): pass


async def test_open_browser_returns_markdown(monkeypatch):
    monkeypatch.setenv("AGENTIC_BOARD_BROWSER", "chrome")
    monkeypatch.setenv("AGENTIC_BOARD_CHROME_USER_DATA_DIR", "/tmp/chrome-test")

    fake_async_pw = SimpleNamespace(
        async_playwright=lambda: _FakePlaywrightCM(),
    )
    with patch.dict(
        "sys.modules",
        {"playwright": SimpleNamespace(async_api=fake_async_pw),
         "playwright.async_api": fake_async_pw},
    ):
        result = await tools.execute_tool(
            name="open_browser",
            arguments={"url": "https://example.test"},
            session=None, member_id="strategist",
        )
    assert result.error is None
    assert result.cost_units == 3.0
    assert "Hello" in result.content_for_model


async def test_open_browser_tavily_fallback(monkeypatch):
    monkeypatch.setenv("AGENTIC_BOARD_BROWSER", "tavily")
    fake_results = {"results": [
        {"title": "Hello", "url": "https://example.test",
         "snippet": "Body content", "retrieved_at": "2026-05-07T10:00:00Z"},
    ]}
    fake_search = AsyncMock(return_value=fake_results)
    with patch("server.execution.web_search.web_search", fake_search):
        result = await tools.execute_tool(
            name="open_browser",
            arguments={"url": "https://example.test"},
            session=None, member_id="strategist",
        )
    assert result.error is None
    assert "Hello" in result.content_for_model


async def test_open_browser_disabled_returns_error(monkeypatch):
    monkeypatch.setenv("AGENTIC_BOARD_BROWSER", "disabled")
    result = await tools.execute_tool(
        name="open_browser", arguments={"url": "https://example.test"},
        session=None, member_id="strategist",
    )
    assert result.error is not None
    assert "disabled" in result.error.lower()


async def test_open_browser_fallback_when_playwright_missing(monkeypatch):
    """If playwright import fails, transparently fall back to Tavily."""
    monkeypatch.setenv("AGENTIC_BOARD_BROWSER", "chrome")
    fake_results = {"results": [
        {"title": "T", "url": "https://x.example", "snippet": "snip",
         "retrieved_at": "2026-05-07"},
    ]}
    fake_search = AsyncMock(return_value=fake_results)

    # Make playwright import fail by injecting a sentinel into sys.modules
    # that raises ImportError when attribute access is attempted.
    real_modules = dict(sys.modules)
    # Remove cached playwright modules
    for key in list(sys.modules.keys()):
        if key == "playwright" or key.startswith("playwright."):
            del sys.modules[key]
    # Block re-import by setting to None (Python's standard "module not found" sentinel)
    sys.modules["playwright"] = None
    sys.modules["playwright.async_api"] = None

    try:
        with patch("server.execution.web_search.web_search", fake_search):
            result = await tools.execute_tool(
                name="open_browser", arguments={"url": "https://x.example"},
                session=None, member_id="strategist",
            )
        assert result.error is None
        assert "T" in result.content_for_model
    finally:
        # Restore sys.modules
        sys.modules.clear()
        sys.modules.update(real_modules)
