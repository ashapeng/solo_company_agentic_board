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
