"""Contract tests for the SOTB memory audit/snapshot/consolidate API + CLI.

CRITICAL: every API write in this file targets a NON-default venture id
("apitest") so it lands under the gitignored server/memory/ventures/apitest/
and never touches the tracked default server/memory/sotb.md.
"""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from server.memory.sotb_governance import venture_memory_paths

_TEST_VENTURE = "apitest"
_TEST_TOKEN = "sotb-memory-test-token"


@pytest.fixture
def client(monkeypatch) -> TestClient:
    # TestClient presents a non-local host; authenticate via bearer token.
    monkeypatch.setenv("AGENTIC_BOARD_ALLOW_REMOTE", "1")
    monkeypatch.setenv("AGENTIC_BOARD_REMOTE_TOKEN", _TEST_TOKEN)

    from server.api.app import app
    c = TestClient(app)
    c.headers.update({"Authorization": f"Bearer {_TEST_TOKEN}"})
    yield c

    # Teardown: scrub the non-default venture dir so nothing leaks between runs.
    mp, _ip = venture_memory_paths(_TEST_VENTURE)
    venture_dir = mp.parent
    if venture_dir.exists() and venture_dir.name != "memory":
        shutil.rmtree(venture_dir, ignore_errors=True)


def test_get_sotb_entries_returns_list(client: TestClient) -> None:
    resp = client.get(f"/sotb/entries?venture_id={_TEST_VENTURE}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["venture_id"] == _TEST_VENTURE
    assert isinstance(body["entries"], list)


def test_consolidate_empty_venture_is_noop(client: TestClient) -> None:
    resp = client.post("/sotb/consolidate", json={"venture_id": _TEST_VENTURE})
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, dict)


def test_snapshots_list_and_rollback(client: TestClient) -> None:
    from server.memory.sotb_snapshot import capture_snapshot

    snap = capture_snapshot(venture_id=_TEST_VENTURE, reason="test_fixture")
    snapshot_id = snap.get("snapshot_id")
    assert snapshot_id, f"capture_snapshot failed: {snap}"

    listing = client.get(f"/sotb/snapshots?venture_id={_TEST_VENTURE}")
    assert listing.status_code == 200
    body = listing.json()
    assert body["venture_id"] == _TEST_VENTURE
    ids = {s["snapshot_id"] for s in body["snapshots"]}
    assert snapshot_id in ids

    rollback = client.post(f"/sotb/snapshots/{snapshot_id}/rollback")
    assert rollback.status_code == 200
    assert rollback.json()["restored"] is True


def test_rollback_bogus_snapshot_returns_404(client: TestClient) -> None:
    resp = client.post("/sotb/snapshots/does-not-exist/rollback")
    assert resp.status_code == 404


def test_cli_accepts_consolidate_memory_flag() -> None:
    """The arg parser must accept --consolidate-memory without executing it."""
    import argparse
    from unittest.mock import patch

    captured: dict = {}

    real_parse_args = argparse.ArgumentParser.parse_args

    def fake_parse_args(self, *a, **k):
        ns = real_parse_args(self, ["--consolidate-memory", "--venture", _TEST_VENTURE])
        captured["ns"] = ns
        # Abort before any real consolidation runs.
        raise SystemExit(0)

    from server import cli as cli_module
    with patch.object(argparse.ArgumentParser, "parse_args", fake_parse_args):
        with pytest.raises(SystemExit):
            cli_module.cli()

    ns = captured["ns"]
    assert ns.consolidate_memory is True
    assert ns.venture == _TEST_VENTURE
