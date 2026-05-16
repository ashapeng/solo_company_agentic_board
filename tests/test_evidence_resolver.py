"""Evidence resolver tests."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from server.board.deliberation.evidence_resolver import resolve_evidence


def _make_packet(packet_dir: Path, packet_id: str, sources: list[dict], claims: list[str]) -> None:
    packet_dir.mkdir(parents=True, exist_ok=True)
    (packet_dir / f"{packet_id}.json").write_text(json.dumps({
        "id": packet_id,
        "topic": "test",
        "claims": claims,
        "sources": sources,
        "created_at": "2026-05-16T00:00:00Z",
        "freshness": "current",
        "warnings": [],
    }))


class _FakeSession:
    def __init__(self, evidence_packets: dict[str, str]):
        self.evidence_packets = evidence_packets


@pytest.mark.asyncio
async def test_resolver_returns_empty_for_unverified_refs(tmp_path):
    session = _FakeSession({})
    out = await resolve_evidence(
        ["[UNVERIFIED]"], session,
        evidence_dir=tmp_path,
    )
    assert out == {}


@pytest.mark.asyncio
async def test_resolver_cache_hit_from_evidence_packets(tmp_path):
    url = "https://example.com/report"
    _make_packet(tmp_path, "evidence_abc",
                 sources=[{"title": "Report", "url": url, "retrieved_at": "x", "claim_ids": []}],
                 claims=["The EV battery market grew 30% YoY according to source data" * 5])
    session = _FakeSession({"strategist": "evidence_abc"})

    out = await resolve_evidence([url], session, evidence_dir=tmp_path)
    assert url in out
    assert "EV battery market grew 30% YoY" in out[url]


@pytest.mark.asyncio
async def test_resolver_re_fetches_on_cache_miss(tmp_path):
    url = "https://example.com/page"
    session = _FakeSession({})  # no packets
    mock_resp = AsyncMock()
    mock_resp.text = "Fetched body text " * 50

    with patch(
        "server.board.deliberation.evidence_resolver._safe_http_get",
        new=AsyncMock(return_value=type("R", (), {"text": mock_resp.text})()),
    ):
        out = await resolve_evidence([url], session, evidence_dir=tmp_path)
    assert url in out
    assert "Fetched body text" in out[url]


@pytest.mark.asyncio
async def test_resolver_re_fetches_when_cached_snippet_too_short(tmp_path):
    url = "https://example.com/short"
    _make_packet(tmp_path, "evidence_short",
                 sources=[{"title": "Short", "url": url, "retrieved_at": "x", "claim_ids": []}],
                 claims=["tiny"])  # < 200 chars triggers re-fetch
    session = _FakeSession({"x": "evidence_short"})

    with patch(
        "server.board.deliberation.evidence_resolver._safe_http_get",
        new=AsyncMock(return_value=type("R", (), {"text": "Re-fetched longer body " * 30})()),
    ):
        out = await resolve_evidence([url], session, evidence_dir=tmp_path)
    assert "Re-fetched longer body" in out[url]


@pytest.mark.asyncio
async def test_resolver_truncates_to_max_chars(tmp_path):
    url = "https://example.com/big"
    session = _FakeSession({})
    big_text = "x" * 10_000

    with patch(
        "server.board.deliberation.evidence_resolver._safe_http_get",
        new=AsyncMock(return_value=type("R", (), {"text": big_text})()),
    ):
        out = await resolve_evidence([url], session, evidence_dir=tmp_path, max_chars=4000)
    assert len(out[url]) == 4000


@pytest.mark.asyncio
async def test_resolver_records_empty_string_on_fetch_failure(tmp_path):
    url = "https://example.com/broken"
    session = _FakeSession({})

    with patch(
        "server.board.deliberation.evidence_resolver._safe_http_get",
        new=AsyncMock(side_effect=ValueError("blocked URL")),
    ):
        out = await resolve_evidence([url], session, evidence_dir=tmp_path)
    # URL appears in dict with empty string so caller knows we tried
    assert out[url] == ""
