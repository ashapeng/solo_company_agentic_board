from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from server.board.deliberation.orchestrator import BoardSession
from server.discovery.board_start import BoardStartError, build_board_question, start_board
from server.discovery.promotion import PromotionError, promote_candidate
from server.harness.ledger import init_db, record_session


def candidate(status="shortlisted"):
    return {
        "id": "cand_1", "title": "Pain", "summary": "A" * 2000,
        "audience": "makers", "pain_class": "important", "status": status,
        "report_digest": "sha256:report", "board_sessions": [],
        "evidence": [{"source_key": "reddit:1", "quote": "exact words", "url": "https://x/1",
                      "retrieved_at": "2026-07-01", "title": "Source"}],
    }


def test_promotion_is_explicit_idempotent_and_preserves_evidence(tmp_path):
    item = candidate()
    saved = []
    venture = lambda venture_id, **_: {"id": venture_id, "status": "active"}
    first = promote_candidate(item, save_candidate=lambda c: saved.append(dict(c)), venture_id="v1",
                              get_venture_fn=venture, evidence_dir=tmp_path)
    second = promote_candidate(item, save_candidate=lambda c: None, venture_id="v1",
                               get_venture_fn=venture, evidence_dir=tmp_path)
    assert second == first
    assert item["status"] == "promoted" and len(saved) == 1
    packet = json.loads((tmp_path / f'{first["evidence_packet_id"]}.json').read_text())
    assert packet["canonical_quotes"][0] == {
        "source_key": "reddit:1", "quote": "exact words", "url": "https://x/1",
        "retrieved_at": "2026-07-01", "title": "Source",
    }
    assert packet["report_digest"] == "sha256:report"
    assert packet["discovery_candidate_id"] == "cand_1"
    assert packet["source_keys"] == ["reddit:1"]


def test_promotion_rejects_implicit_venture_and_rejected_candidate():
    with pytest.raises(PromotionError, match="exactly one"):
        promote_candidate(candidate(), save_candidate=lambda _: None)
    with pytest.raises(PromotionError, match="rejected"):
        promote_candidate(candidate("rejected"), save_candidate=lambda _: None, venture_id="v1")


class FakeMetrics:
    def by_stage(self, stage): return []
    def total_cost_estimate(self): return 0.0
    def summary(self): return {}


class FakeOrchestrator:
    def __init__(self, fail=False): self.calls = []; self.fail = fail
    async def deliberate(self, question, **kwargs):
        self.calls.append((question, kwargs))
        if self.fail: raise RuntimeError("boom")
        session = BoardSession(session_id=kwargs["session_id"], user_query=question,
                               venture_id=kwargs["venture_id"])
        session.metrics = FakeMetrics()
        session.save = lambda: Path("ignored")
        return session


@pytest.mark.asyncio
async def test_start_board_sets_provenance_and_prevents_duplicate(tmp_path):
    item = candidate("promoted")
    item["promotion"] = {"id": "promo_1", "venture_id": "v1", "evidence_packet_id": "ev_1",
                         "board_session_id": None}
    orchestrator = FakeOrchestrator()
    saved = []
    session = await start_board(item, orchestrator=orchestrator,
                                save_candidate=lambda c: saved.append(c["status"]))
    assert session.discovery_candidate_id == "cand_1"
    assert session.discovery_promotion_id == "promo_1"
    assert session.evidence_packet_id == "ev_1"
    assert orchestrator.calls[0][1]["venture_id"] == "v1"
    existing = await start_board(item, orchestrator=orchestrator, save_candidate=lambda _: None)
    assert existing["session_id"] == session.session_id
    assert len(orchestrator.calls) == 1
    assert len(build_board_question(item, item["promotion"])) < 2500


@pytest.mark.asyncio
async def test_failed_board_attempt_is_retryable():
    item = candidate("promoted")
    item["promotion"] = {"id": "p", "venture_id": "v", "evidence_packet_id": "e"}
    with pytest.raises(RuntimeError):
        await start_board(item, orchestrator=FakeOrchestrator(True), save_candidate=lambda _: None)
    assert item["board_sessions"][-1]["status"] == "failed"
    await start_board(item, orchestrator=FakeOrchestrator(), save_candidate=lambda _: None)
    assert item["status"] == "board_started"


def test_session_discovery_fields_round_trip_to_ledger(tmp_path):
    session = BoardSession("s1", "q", discovery_candidate_id="c", discovery_promotion_id="p",
                           evidence_packet_id="e")
    session.metrics = FakeMetrics()
    assert session.to_dict()["discovery_candidate_id"] == "c"
    db = tmp_path / "ledger.db"
    init_db(db)
    record_session(session, 1, db)
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT discovery_candidate_id, discovery_promotion_id, evidence_packet_id "
                       "FROM session_outcomes").fetchone()
    assert row == ("c", "p", "e")
