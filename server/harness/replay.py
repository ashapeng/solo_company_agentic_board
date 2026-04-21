# server/harness/replay.py
"""Offline replay of a saved deliberation under a candidate harness config.

Re-runs Stage 3 (synthesis) and optionally Stage 4 (verification) against
stored Stage 1 / Stage 2 responses. Forces temperature=0.0 on the LLM call
path to isolate the effect of config changes from sampling noise.

Public surface:
    replay_session(session_path, candidate_config_path=None, *, verify=False)
        -> ReplayReport
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class ReplayReport:
    replay_id: str
    source_session_id: str
    candidate_config_path: str | None
    baseline: dict[str, Any]
    candidate: dict[str, Any]
    delta: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def replay_session(
    session_path: Path,
    candidate_config_path: Path | None = None,
    *,
    verify: bool = False,
) -> ReplayReport:
    """Re-run Stage 3 (+ optional Stage 4) and return a diff vs the stored baseline."""
    data = json.loads(Path(session_path).read_text())

    stage3 = data.get("stage3") or {}
    if not stage3 or not stage3.get("content"):
        raise ValueError(
            f"Session {data.get('session_id')} has no stage3 content; cannot replay."
        )

    baseline_verification = data.get("verification") or {}
    baseline = {
        "verification_score": baseline_verification.get("score"),
        "verification_passed": baseline_verification.get("passed"),
        "synthesis_len": len(stage3.get("content") or ""),
    }

    candidate = asyncio.run(
        _rerun_stage3_and_verify(data, candidate_config_path, verify=verify)
    )

    delta: dict[str, Any] = {}
    for key in ("verification_score", "synthesis_len"):
        a = baseline.get(key)
        b = candidate.get(key)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            delta[key] = b - a
        else:
            delta[key] = None

    report = ReplayReport(
        replay_id=f"replay_{int(datetime.now(timezone.utc).timestamp())}",
        source_session_id=str(data.get("session_id")),
        candidate_config_path=str(candidate_config_path) if candidate_config_path else None,
        baseline=baseline,
        candidate=candidate,
        delta=delta,
    )
    out_dir = Path("data/replays")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{report.replay_id}.json"
    out_path.write_text(json.dumps(report.to_dict(), indent=2))
    return report


async def _rerun_stage3_and_verify(
    session_data: dict,
    candidate_config_path: Path | None,
    *,
    verify: bool,
) -> dict[str, Any]:
    from server.board.deliberation.orchestrator import (
        BoardOrchestrator,
        MemberResponse,
    )
    from server.memory.sotb import read_sotb
    import server.board.deliberation.orchestrator as orch_module

    if candidate_config_path:
        from server.harness.config import load_config
        load_config(Path(candidate_config_path))  # prime LRU with candidate

    stage1 = [
        MemberResponse(
            member_id=r["member_id"], stage=1, content=r["content"],
            model=r.get("model", ""), elapsed_seconds=r.get("elapsed_seconds", 0.0),
        )
        for r in session_data.get("stage1", [])
    ]
    stage2 = [
        MemberResponse(
            member_id=r["member_id"], stage=2, content=r["content"],
            model=r.get("model", ""), elapsed_seconds=r.get("elapsed_seconds", 0.0),
        )
        for r in session_data.get("stage2", [])
    ]

    orch = BoardOrchestrator()
    query = session_data["user_query"]
    classification = session_data.get("classification") or {}
    query_type = classification.get("query_type")
    complexity = classification.get("complexity")

    original_query_llm = orch_module.query_llm

    async def _deterministic_query_llm(*args, **kwargs):
        kwargs["temperature"] = 0.0
        return await original_query_llm(*args, **kwargs)

    orch_module.query_llm = _deterministic_query_llm
    try:
        stage3_resp = await orch.stage3(
            query, stage1, stage2,
            sotb=read_sotb(),
            query_type=query_type,
            complexity=complexity,
        )
        result: dict[str, Any] = {
            "synthesis_len": len(stage3_resp.content),
        }
        if verify:
            from server.board.deliberation.verification import verify_synthesis
            from server.board.deliberation.compaction import compact_stage2_responses

            compacted = compact_stage2_responses(stage2)
            compacted_text = "\n".join(r.content for r in compacted)
            v = await verify_synthesis(
                synthesis=stage3_resp.content,
                stage2_compacted=compacted_text,
                user_query=query,
                query_type=query_type,
            )
            result["verification_score"] = v.score
            result["verification_passed"] = v.passed
        return result
    finally:
        orch_module.query_llm = original_query_llm
