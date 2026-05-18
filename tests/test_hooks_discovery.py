"""Tests for hook auto-discovery from _bundled/ and _project/."""
from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path

import pytest


def test_bundled_directory_exists_as_package():
    from server.harness.hooks import _bundled
    pkg_path = Path(_bundled.__file__).parent
    assert pkg_path.is_dir()
    assert (pkg_path / "__init__.py").is_file()


def test_importing_hooks_package_triggers_bundled_discovery(caplog):
    """Discovery is wired to package import; re-importing should not raise."""
    with caplog.at_level(logging.INFO, logger="server.harness.hooks"):
        if "server.harness.hooks" in sys.modules:
            importlib.reload(sys.modules["server.harness.hooks"])
        else:
            importlib.import_module("server.harness.hooks")
    assert any("bundled" in rec.message.lower() for rec in caplog.records), \
        "expected an INFO line listing bundled hooks loaded"


def test_discovery_skips_underscore_modules(tmp_path, monkeypatch):
    """Modules starting with '_' (e.g. __init__, _helpers) are not imported."""
    from server.harness.hooks import _discover_hooks_in
    bundled = tmp_path / "fake_bundled"
    bundled.mkdir()
    (bundled / "__init__.py").write_text("")
    (bundled / "_helpers.py").write_text("raise RuntimeError('should not import')\n")
    (bundled / "real_hook.py").write_text(
        "loaded = True\n"
    )

    monkeypatch.syspath_prepend(str(tmp_path))
    count = _discover_hooks_in("fake_bundled")
    assert count == 1, "only real_hook.py should have imported"


def test_discovery_tolerates_missing_project_dir():
    """_project/ is optional; no error if it doesn't exist."""
    from server.harness.hooks import _discover_hooks_in
    count = _discover_hooks_in("definitely_not_a_package_xyz")
    assert count == 0


def test_discovery_logs_hook_module_crash_without_raising(tmp_path, monkeypatch, caplog):
    """A buggy hook module must not block other hooks from loading."""
    from server.harness.hooks import _discover_hooks_in
    bundled = tmp_path / "fake_bundled2"
    bundled.mkdir()
    (bundled / "__init__.py").write_text("")
    (bundled / "crashy.py").write_text("raise ValueError('module crash')\n")
    (bundled / "good.py").write_text("ok = True\n")

    monkeypatch.syspath_prepend(str(tmp_path))
    with caplog.at_level(logging.ERROR, logger="server.harness.hooks"):
        count = _discover_hooks_in("fake_bundled2")
    assert count == 1, "good.py should still load"
    assert any("crashy" in rec.message for rec in caplog.records), \
        "module import crash should be logged"
