"""Integration tests: denying hook surfaces HookDeniedError from web_search."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch):
    from server.harness import ledger as ledger_mod
    db_path = tmp_path / "ledger.db"
    monkeypatch.setattr(ledger_mod, "_DEFAULT_DB_PATH", db_path)
    ledger_mod.init_db(db_path)
    return db_path


@pytest.fixture
def fresh_registry():
    from server.harness.hooks import _snapshot_registry, _restore_registry
    snapshot = _snapshot_registry()
    yield
    _restore_registry(snapshot)


@pytest.mark.asyncio
async def test_denying_hook_blocks_web_search_with_HookDeniedError(tmp_db, fresh_registry):
    from server.harness.hooks import (
        HookContext, HookVerdict, HookDeniedError, register_pre_hook,
    )
    from server.execution.web_search import web_search

    def denying_hook(ctx: HookContext) -> HookVerdict:
        return HookVerdict(action="deny", reason="test denial", metadata={"x": 1})

    register_pre_hook("web_search", denying_hook)

    with pytest.raises(HookDeniedError) as excinfo:
        await web_search("q", provider="fake", session_id="s_t14")
    assert "test denial" in str(excinfo.value)
    assert excinfo.value.reason == "test denial"


@pytest.mark.asyncio
async def test_denying_hook_writes_deny_event_to_ledger(tmp_db, fresh_registry):
    from server.harness.hooks import (
        HookContext, HookVerdict, HookDeniedError, register_pre_hook,
    )
    from server.execution.web_search import web_search

    def denying_hook(ctx: HookContext) -> HookVerdict:
        return HookVerdict(action="deny", reason="cap exceeded", metadata={"cap": 0})

    register_pre_hook("web_search", denying_hook)

    with pytest.raises(HookDeniedError):
        await web_search("q", provider="fake", session_id="s_t14_b")

    conn = sqlite3.connect(str(tmp_db))
    try:
        rows = conn.execute(
            "SELECT action, reason FROM hook_events "
            "WHERE session_id = ? AND tool_name = 'web_search'",
            ("s_t14_b",),
        ).fetchall()
    finally:
        conn.close()
    assert (("deny", "cap exceeded")) in rows


@pytest.mark.asyncio
async def test_allowing_hook_lets_web_search_complete_normally(tmp_db, fresh_registry):
    from server.harness.hooks import (
        HookContext, HookVerdict, register_pre_hook,
    )
    from server.execution.web_search import web_search
    from server.execution import evidence as ev

    def allowing(ctx):
        return HookVerdict("allow", None, {"checked": True})

    register_pre_hook("web_search", allowing)

    with tempfile.TemporaryDirectory() as tmpdir:
        old = ev._EVIDENCE_DIR
        ev._EVIDENCE_DIR = Path(tmpdir)
        try:
            result = await web_search("q", provider="fake", session_id="s_t14_c")
        finally:
            ev._EVIDENCE_DIR = old

    assert result["query"] == "q"
    assert result["results"]
