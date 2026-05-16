"""Runner orchestration tests with deliberate() mocked."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from server.board.deliberation.orchestrator import BoardSession, MemberResponse
from server.board.metrics import SessionMetrics

from evals.corpus import EvalPrompt
from evals.ledger import get_run, get_signals_for_run, init_db
from evals.runner import run_corpus, _tier_to_verify


def _fake_session(session_id: str, verifier_passed: bool) -> BoardSession:
    return BoardSession(
        session_id=session_id, user_query="x",
        stage3_synthesis=MemberResponse(
            member_id="chairperson", stage=3, content="ok",
            model="m", elapsed_seconds=2.0,
        ),
        metrics=SessionMetrics(),
        verification={"score": 9 if verifier_passed else 4,
                      "passed": verifier_passed, "deficiencies": []},
        total_elapsed=2.0,
    )


def test_tier_to_verify():
    assert _tier_to_verify("light") is False
    assert _tier_to_verify("standard") is False
    assert _tier_to_verify("heavy") is True


@pytest.mark.asyncio
async def test_run_corpus_records_per_prompt_signals(tmp_path, monkeypatch):
    db = tmp_path / "eval.db"
    init_db(db)
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()

    prompt1 = EvalPrompt(
        id="hall-001", category="hallucination_planted",
        query="growth rate?", tier="heavy",
        planted={"kind": "numeric", "expected_signal": "x", "ground_truth_note": "z"},
        expected_outcome={"verifier_passed": False, "deficiency_contains": []},
    )
    prompt2 = EvalPrompt(
        id="clean-001", category="clean_baseline",
        query="TLS?", tier="heavy",
        planted={"kind": "n/a", "expected_signal": "no_signal", "ground_truth_note": "ok"},
        expected_outcome={"verifier_passed": True, "contradiction_surfaced": False},
    )

    sess1 = _fake_session("board_eval_001", verifier_passed=True)
    sess2 = _fake_session("board_eval_002", verifier_passed=True)
    mock_deliberate = AsyncMock(side_effect=[sess1, sess2])

    with patch("evals.runner.BoardOrchestrator") as MockOrch:
        MockOrch.return_value.deliberate = mock_deliberate
        run_id = await run_corpus(
            [prompt1, prompt2],
            tier="heavy",
            label="test-run",
            config_version=2,
            db_path=db,
            sessions_dir=sessions_dir,
        )

    assert mock_deliberate.await_count == 2

    run = get_run(run_id, db_path=db)
    assert run["label"] == "test-run"
    assert run["tier"] == "heavy"
    assert run["prompt_count"] == 2
    assert run["completed_at"] is not None
    # Only clean_baseline should pass (sess2 verifier_passed=True matches expectation);
    # hall-001 expects verifier_passed=False but observed True → fail.
    assert run["total_passed"] == 1

    rows = get_signals_for_run(run_id, db_path=db)
    assert len(rows) == 2
    by_prompt = {r["prompt_id"]: r for r in rows}
    assert by_prompt["hall-001"]["passed"] == 0
    assert by_prompt["clean-001"]["passed"] == 1
    assert by_prompt["hall-001"]["raw_session_id"] == "board_eval_001"

    # Session JSON saved
    assert (sessions_dir / "board_eval_001.json").exists()
    saved = json.loads((sessions_dir / "board_eval_001.json").read_text())
    assert saved["session_id"] == "board_eval_001"


@pytest.mark.asyncio
async def test_run_corpus_records_error_when_deliberate_raises(tmp_path):
    from server.board.deliberation.orchestrator import BoardDeliberationError

    db = tmp_path / "eval.db"
    init_db(db)
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()

    prompt = EvalPrompt(
        id="hall-001", category="hallucination_planted",
        query="?", tier="heavy",
        planted={"kind": "x", "expected_signal": "y", "ground_truth_note": "z"},
        expected_outcome={"verifier_passed": False, "deficiency_contains": []},
    )

    mock_deliberate = AsyncMock(side_effect=BoardDeliberationError("provider failed"))

    with patch("evals.runner.BoardOrchestrator") as MockOrch:
        MockOrch.return_value.deliberate = mock_deliberate
        run_id = await run_corpus(
            [prompt], tier="heavy", label="err-run", config_version=2,
            db_path=db, sessions_dir=sessions_dir,
        )

    rows = get_signals_for_run(run_id, db_path=db)
    assert len(rows) == 1
    assert rows[0]["passed"] == 0
    assert "provider failed" in (rows[0]["error"] or "")
    assert rows[0]["raw_session_id"] is None
