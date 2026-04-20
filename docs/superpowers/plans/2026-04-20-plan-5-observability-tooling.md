# Plan 5 — Observability Tooling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two observability primitives — rolling-window drift detection in the ledger surfacing into the harness review, and an offline replay CLI that re-runs Stage 3 (+ optional Stage 4) against stored Stage 1/2 outputs under a candidate harness config, emitting a projected score delta.

**Architecture:** `ledger.rolling_stats` and `ledger.distribution_shift` are pure SQL/stdlib helpers. `reviews._drift_recommendation` calls them and appends a `HarnessRecommendation` when thresholds trip. `harness/replay.py` reconstructs `MemberResponse` objects from a saved session JSON, swaps in a candidate `HarnessConfig`, and calls `orchestrator.stage3` + `verify_synthesis` with `temperature=0.0` for determinism.

**Tech Stack:** Python 3.12, SQLite, stdlib `statistics` + `math`, argparse, unittest.

**Spec:** `docs/superpowers/specs/2026-04-20-plan-5-observability-tooling-design.md`

---

## Cross-cutting execution policy

1. Phase 0 before code.
2. Root-cause only.
3. 3-attempt cap → `git reset --hard` to last green.
4. YAGNI. No matplotlib, no pandas. Reuse orchestrator methods for replay.
5. Done criteria: tests green; manual replay of a saved session under current config reproduces its verification pass/fail; drift section appears in `run_harness_review` output when the seeded ledger regresses.

## Sub-agent usage

- **Explore agent** (thoroughness: `quick`) — confirm every `query_llm` call site in Stage 3 + verification path accepts `temperature` (used to pass 0.0 in replay mode).

## File structure map

| File | Action | Responsibility |
|---|---|---|
| `server/harness/ledger.py` | **Modify** | `rolling_stats`, `distribution_shift` |
| `server/harness/reviews.py` | **Modify** | `_drift_recommendation` |
| `server/harness/replay.py` | **Create** | Load session, re-run stage 3 + (optional) verify, emit diff |
| `server/cli.py` | **Modify** | `--replay`, `--candidate-config`, `--replay-verify` flags |
| `tests/test_replay_contract.py` | **Create** | Replay roundtrip + candidate diff |
| `tests/test_ledger_contract.py` | **Modify** | Rolling / distribution helpers |
| `tests/test_harness_integration_contract.py` | **Modify** | Drift surfacing |

---

## Task 1: Phase 0 repro tests

**Files:**
- Create: `tests/test_replay_contract.py` (replay asserts)
- Append cases to `tests/test_ledger_contract.py` (drift helpers)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_replay_contract.py
from __future__ import annotations

import unittest


class ReplayModuleExistsTest(unittest.TestCase):
    def test_replay_module_importable(self):
        from server.harness import replay  # noqa: F401
        self.assertTrue(hasattr(replay, "replay_session"))


class CliFlagExistsTest(unittest.TestCase):
    def test_cli_accepts_replay_flag(self):
        import subprocess
        result = subprocess.run(
            ["uv", "run", "python", "-m", "server.cli", "--help"],
            capture_output=True, text=True,
        )
        self.assertIn("--replay", result.stdout)


if __name__ == "__main__":
    unittest.main()
```

Append to `tests/test_ledger_contract.py`:

```python
class RollingStatsTest(unittest.TestCase):
    def test_rolling_stats_helper_exists(self):
        from server.harness.ledger import rolling_stats
        self.assertTrue(callable(rolling_stats))

    def test_distribution_shift_helper_exists(self):
        from server.harness.ledger import distribution_shift
        self.assertTrue(callable(distribution_shift))
```

- [ ] **Step 2: Run; confirm FAIL**

Run: `uv run python -m unittest tests.test_replay_contract tests.test_ledger_contract.RollingStatsTest -v`

Expected: FAIL on import (`replay`, `rolling_stats`, `distribution_shift` do not exist).

- [ ] **Step 3: Commit**

```bash
git add tests/test_replay_contract.py tests/test_ledger_contract.py
git commit -m "test: phase 0 repro for drift + replay tooling"
```

---

## Task 2: rolling_stats + distribution_shift helpers

**Files:**
- Modify: `server/harness/ledger.py`

- [ ] **Step 1: Implement**

Append:

```python
import math
from collections import Counter


def rolling_stats(
    field: str,
    *,
    recent_n: int = 10,
    baseline_n: int = 100,
    query_type: str | None = None,
    db_path: Path | None = None,
) -> dict:
    if field not in _NUMERIC_COLUMNS:
        raise LedgerError(f"Cannot roll non-numeric field: {field}")
    conn = _connect(db_path)
    try:
        sql = (
            f"SELECT {field} FROM session_outcomes "  # nosec B608
            "WHERE {field} IS NOT NULL".format(field=field)
        )
        params: list = []
        if query_type:
            sql += " AND query_type = ?"
            params.append(query_type)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        params.append(recent_n + baseline_n)
        rows = [r[0] for r in conn.execute(sql, params).fetchall() if r[0] is not None]
    finally:
        conn.close()
    if len(rows) < recent_n + 1:
        return {"insufficient_samples": True, "sample_count": len(rows)}
    recent = rows[:recent_n]
    baseline = rows[recent_n : recent_n + baseline_n]
    if not baseline:
        return {"insufficient_samples": True, "sample_count": len(rows)}
    recent_mean = sum(recent) / len(recent)
    baseline_mean = sum(baseline) / len(baseline)
    return {
        "recent_mean": round(recent_mean, 4),
        "baseline_mean": round(baseline_mean, 4),
        "delta": round(recent_mean - baseline_mean, 4),
        "recent_n": len(recent),
        "baseline_n": len(baseline),
    }


def distribution_shift(
    field: str,
    *,
    recent_n: int = 10,
    baseline_n: int = 100,
    db_path: Path | None = None,
) -> dict:
    if field not in {"query_type", "complexity"}:
        raise LedgerError(f"Cannot report distribution for field: {field}")
    conn = _connect(db_path)
    try:
        rows = [r[0] for r in conn.execute(
            f"SELECT {field} FROM session_outcomes "
            "WHERE {field} IS NOT NULL ORDER BY timestamp DESC LIMIT ?".format(field=field),
            (recent_n + baseline_n,),
        ).fetchall()]
    finally:
        conn.close()
    if len(rows) < recent_n + 1:
        return {"insufficient_samples": True, "sample_count": len(rows)}
    recent = rows[:recent_n]
    baseline = rows[recent_n : recent_n + baseline_n]
    labels = set(recent) | set(baseline)
    if not labels:
        return {"js_distance": 0.0, "recent": {}, "baseline": {}}
    recent_counts = Counter(recent)
    baseline_counts = Counter(baseline)
    recent_dist = {l: recent_counts.get(l, 0) / len(recent) for l in labels}
    baseline_dist = {l: baseline_counts.get(l, 0) / len(baseline) for l in labels}
    m = {l: (recent_dist[l] + baseline_dist[l]) / 2 for l in labels}

    def _kl(p, q):
        total = 0.0
        for l in labels:
            if p[l] > 0 and q[l] > 0:
                total += p[l] * math.log2(p[l] / q[l])
        return total

    js = 0.5 * _kl(recent_dist, m) + 0.5 * _kl(baseline_dist, m)
    return {
        "js_distance": round(math.sqrt(max(0.0, js)), 4),
        "recent": {l: round(v, 3) for l, v in recent_dist.items()},
        "baseline": {l: round(v, 3) for l, v in baseline_dist.items()},
    }
```

- [ ] **Step 2: Run ledger tests**

Run: `uv run python -m unittest tests.test_ledger_contract -v`

Expected: PASS for new helpers.

- [ ] **Step 3: Commit**

```bash
git add server/harness/ledger.py
git commit -m "feat(ledger): rolling_stats and distribution_shift helpers"
```

---

## Task 3: Drift recommendation in reviews

**Files:**
- Modify: `server/harness/reviews.py`

- [ ] **Step 1: Add helper and wire**

```python
def _drift_recommendation() -> HarnessRecommendation | None:
    from .ledger import rolling_stats, distribution_shift
    try:
        verification = rolling_stats("verification_score")
        distribution = distribution_shift("query_type")
    except Exception as exc:
        return HarnessRecommendation(
            category="drift",
            summary="Drift check failed.",
            details={"error": str(exc)},
        )

    notes: list[str] = []
    if verification.get("insufficient_samples"):
        return None
    if verification.get("delta", 0.0) < -0.5:
        notes.append(
            f"verification score regressed: delta={verification['delta']} "
            f"(recent={verification['recent_mean']}, baseline={verification['baseline_mean']})"
        )
    if distribution.get("js_distance", 0.0) > 0.3:
        notes.append(
            f"classifier label distribution shifted: js={distribution['js_distance']}"
        )
    if not notes:
        return None
    return HarnessRecommendation(
        category="drift",
        summary="; ".join(notes),
        details={"verification": verification, "distribution": distribution},
    )
```

In `run_harness_review`, after the reliability block, call:

```python
drift = _drift_recommendation()
if drift:
    recommendations.append(drift)
```

- [ ] **Step 2: Extend harness integration test**

Append to `tests/test_harness_integration_contract.py`:

```python
class DriftRecommendationTest(unittest.TestCase):
    def test_drift_fires_when_recent_sessions_regress(self):
        import tempfile, os
        from pathlib import Path
        from server.harness.ledger import init_db, _connect
        from server.harness.reviews import run_harness_review

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "ledger.db"
            init_db(db_path)
            conn = _connect(db_path)
            try:
                # 100 baseline rows at score 8
                for i in range(100):
                    conn.execute(
                        "INSERT INTO session_outcomes "
                        "(session_id, timestamp, query_type, verification_score, harness_config_version) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (f"board_b{i}", f"2026-04-10T{i%24:02d}:00:00Z", "product", 8, 1),
                    )
                # 10 recent rows at score 3
                for i in range(10):
                    conn.execute(
                        "INSERT INTO session_outcomes "
                        "(session_id, timestamp, query_type, verification_score, harness_config_version) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (f"board_r{i}", f"2026-04-20T{i:02d}:00:00Z", "product", 3, 1),
                    )
                conn.commit()
            finally:
                conn.close()
            import server.harness.reviews as reviews_mod
            import server.harness.ledger as ledger_mod
            os.environ["AGENTIC_BOARD_LEDGER_PATH"] = str(db_path)
            try:
                # NOTE: if reviews module does not honor the env var, patch
                # _DEFAULT_DB_PATH via monkey-patching before the call.
                original = ledger_mod._DEFAULT_DB_PATH
                ledger_mod._DEFAULT_DB_PATH = db_path
                try:
                    review = run_harness_review(dry_run=True)
                finally:
                    ledger_mod._DEFAULT_DB_PATH = original
            finally:
                os.environ.pop("AGENTIC_BOARD_LEDGER_PATH", None)
        categories = {r["category"] for r in review["recommendations"]}
        self.assertIn("drift", categories)
```

- [ ] **Step 3: Run; confirm green**

Run: `uv run python -m unittest tests.test_harness_integration_contract.DriftRecommendationTest -v`

- [ ] **Step 4: Commit**

```bash
git add server/harness/reviews.py tests/test_harness_integration_contract.py
git commit -m "feat(harness): surface ledger drift signal in harness review"
```

---

## Task 4: Replay module

**Files:**
- Create: `server/harness/replay.py`

- [ ] **Step 1: Implement**

```python
# server/harness/replay.py
"""Offline replay of a saved deliberation under a candidate harness config.

Re-runs Stage 3 (synthesis) and optionally Stage 4 (verification) against
stored Stage 1 / Stage 2 responses, using temperature=0.0 for determinism.
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
    data = json.loads(Path(session_path).read_text())

    if not data.get("stage3"):
        raise ValueError(
            f"Session {data.get('session_id')} has no stage3; cannot replay."
        )

    # Baseline = what was persisted last time.
    baseline = {
        "verification_score": (data.get("verification") or {}).get("score"),
        "verification_passed": (data.get("verification") or {}).get("passed"),
        "synthesis_len": len((data.get("stage3") or {}).get("content") or ""),
    }

    candidate = asyncio.run(
        _rerun_stage3_and_verify(data, candidate_config_path, verify=verify)
    )

    delta = {}
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
        BoardOrchestrator, MemberResponse,
    )
    from server.board.llm import query_llm
    from server.board.config import get_chairman_model
    from server.memory.sotb import read_sotb

    stage1 = [
        MemberResponse(
            member_id=r["member_id"], stage=1, content=r["content"],
            model=r.get("model", ""), elapsed_seconds=r.get("elapsed_seconds", 0.0),
        ) for r in session_data.get("stage1", [])
    ]
    stage2 = [
        MemberResponse(
            member_id=r["member_id"], stage=2, content=r["content"],
            model=r.get("model", ""), elapsed_seconds=r.get("elapsed_seconds", 0.0),
        ) for r in session_data.get("stage2", [])
    ]

    if candidate_config_path:
        from server.harness.config import load_config
        load_config(candidate_config_path)  # prime LRU cache w/ candidate

    orch = BoardOrchestrator()
    query = session_data["user_query"]

    # Force determinism in replay.
    from server.board.llm import query_llm as _orig_query_llm
    async def _det_query_llm(*args, **kwargs):
        kwargs["temperature"] = 0.0
        return await _orig_query_llm(*args, **kwargs)

    import server.board.deliberation.orchestrator as orch_module
    original = orch_module.query_llm
    orch_module.query_llm = _det_query_llm
    try:
        stage3_resp = await orch.stage3(
            query, stage1, stage2,
            sotb=read_sotb(),
            query_type=(session_data.get("classification") or {}).get("query_type"),
            complexity=(session_data.get("classification") or {}).get("complexity"),
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
                query_type=(session_data.get("classification") or {}).get("query_type"),
            )
            result["verification_score"] = v.score
            result["verification_passed"] = v.passed
        return result
    finally:
        orch_module.query_llm = original
```

- [ ] **Step 2: Run replay module test (import only — no provider calls yet)**

Run: `uv run python -m unittest tests.test_replay_contract.ReplayModuleExistsTest -v`

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add server/harness/replay.py
git commit -m "feat(harness): offline replay module for stage3 + optional verify"
```

---

## Task 5: CLI flags

**Files:**
- Modify: `server/cli.py`

- [ ] **Step 1: Add argparse flags**

Locate the `argparse.ArgumentParser()` block. Add:

```python
parser.add_argument("--replay", type=str, default=None,
                    help="Path to a saved session JSON to replay")
parser.add_argument("--candidate-config", type=str, default=None,
                    help="Harness config path to use during replay")
parser.add_argument("--replay-verify", action="store_true",
                    help="Also run Stage 4 verification during replay")
```

- [ ] **Step 2: Short-circuit main when `--replay` present**

Immediately after args parsing, before the deliberation code path:

```python
if args.replay:
    from pathlib import Path
    from server.harness.replay import replay_session
    report = replay_session(
        Path(args.replay),
        Path(args.candidate_config) if args.candidate_config else None,
        verify=args.replay_verify,
    )
    import json as _json
    print(_json.dumps(report.to_dict(), indent=2))
    return
```

(Ensure `return` is inside the `main()` function and does not break the
existing CLI flow.)

- [ ] **Step 3: Run CLI flag test**

Run: `uv run python -m unittest tests.test_replay_contract.CliFlagExistsTest -v`

Expected: PASS.

- [ ] **Step 4: Manual smoke**

Find any saved session:

```bash
ls data/sessions/*.json | head -1
uv run python -m server.cli --replay data/sessions/<pick-one>.json
```

Expected: prints a JSON replay report. No crash. `data/replays/replay_*.json`
is written.

Note: this calls the chairman model once. Use a fixture session where the
query is cheap, or set `CHAIRMAN_MODEL` to a local/mock model if provider
credits are constrained.

- [ ] **Step 5: Commit**

```bash
git add server/cli.py
git commit -m "feat(cli): add --replay/--candidate-config/--replay-verify flags"
```

---

## Task 6: Full suite + optional review

- [ ] **Step 1: Run everything**

Run: `uv run python -m unittest discover -s tests -v`

Expected: green.

- [ ] **Step 2: Optional code-reviewer audit**

Dispatch `superpowers:code-reviewer` on the three new modules focusing on:
- JS-distance math correctness (should be ≥ 0; identical dist → 0.0).
- Replay determinism: is `temperature=0.0` honored by every LLM path (classifier / chairman / verifier)?
- Replay failure mode when candidate config removes active members.

- [ ] **Step 3: Address findings**

---

## Definition of done

- All tasks committed.
- `uv run python -m unittest discover -s tests -v` green.
- Drift recommendation fires on seeded regression.
- `--replay` prints a report and writes `data/replays/<id>.json`.
