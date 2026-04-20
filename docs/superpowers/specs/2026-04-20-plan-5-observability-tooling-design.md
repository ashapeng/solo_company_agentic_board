# Plan 5 — Observability Tooling (Cluster E)

**Status:** proposed
**Date:** 2026-04-20
**Owner:** TBD
**Related review:** commit 8906ae9 post-review, items P2.4 (drift detection), P2.3 (offline replay)
**Dependencies:** none
**Parallelizable with:** Plans 1, 2, 3
**Estimated scope:** small (~3 files, ~220 LOC)

## Goal

Give the harness two observability primitives the review flagged missing:

1. **Drift detection** — rolling-window aggregates on the ledger so a
   regression in verification score or a classifier-label distribution
   shift is surfaced in `harness review` output, not buried behind a 50-row
   eyeball scan.
2. **Offline replay** — the ability to re-run Stage 3 (and optionally Stage
   4) against saved Stage 1/2 outputs under a **candidate** harness config,
   emitting a projected score delta. Enables testing a config change without
   burning fresh council tokens.

## Scope

### In scope
- **#9** `ledger.rolling_stats(field, recent_n, baseline_n)` helper + a
  `_drift_recommendation` item in the harness review output.
- **#10** `server/cli.py --replay <session_path>` and
  `--candidate-config <path>` flags. Replay module loads stored Stage 1/2
  responses, re-runs Stage 3 synthesis and (optionally) Stage 4 verification
  using either the active or a candidate HarnessConfig, writes a diff
  report to `data/replays/<replay_id>.json`.

### Out of scope
- Full A/B shadow evaluation (owned by Plan 2).
- Dashboards, UI, Grafana.
- New metrics: latency budgets, cost projections (nice-to-have, defer).
- Automated replay-in-CI.

## Files touched
- `server/harness/ledger.py` — add `rolling_stats` and `distribution_shift`
  helpers
- `server/harness/reviews.py` — drift recommendation
- `server/cli.py` — new flags
- (new) `server/harness/replay.py` — loader + re-run + diff
- `tests/test_ledger_contract.py`, `test_harness_integration_contract.py`
  — extend
- (new) `tests/test_replay_contract.py`

## Phase 0 — Reproduce before code

1. **No rolling stats helper:**
   ```python
   def test_rolling_stats_helper_exists():
       from server.harness.ledger import rolling_stats   # ImportError today
       assert callable(rolling_stats)
   ```

2. **Replay CLI flag absent:**
   ```bash
   uv run python -m server.cli --replay data/sessions/board_XXX.json
   # → error: unrecognized arguments: --replay
   ```
   Confirms gap.

3. **Drift signal invisible in review:**
   Seed a fake ledger with a clean pre-window and a regressed
   post-window. Call `run_harness_review(dry_run=True)`. Assert no entry
   with `category == "drift"` in the result. Fails today, will invert after fix.

## Implementation steps

### Step 1 — rolling_stats
- Signature:
  ```python
  def rolling_stats(
      field: str,
      *,
      recent_n: int = 10,
      baseline_n: int = 100,
      query_type: str | None = None,
      db_path: Path | None = None,
  ) -> dict
  ```
- Reads the most recent `recent_n + baseline_n` rows, splits into
  `recent = rows[:recent_n]` and `baseline = rows[recent_n : recent_n + baseline_n]`.
- Computes mean, sample size, and `delta = recent_mean - baseline_mean` for
  the given numeric field.
- Reuses `_NUMERIC_COLUMNS` allowlist.

### Step 2 — distribution_shift (for classifier drift)
- Same input shape, returns per-label count frequency for string fields
  (`query_type`, `complexity`). Reports Jensen–Shannon distance between
  recent and baseline distributions. Keep JS distance computation inline,
  `math.log2`, no SciPy dependency.

### Step 3 — drift recommendation
- `reviews._drift_recommendation()` calls `rolling_stats("verification_score")`
  and `distribution_shift("query_type")`.
- If `recent_mean − baseline_mean < −0.5` (score regression) or JS distance
  > 0.3 (distribution shift), append a `HarnessRecommendation(category="drift", …)`.
- Include numbers, not just flags — humans reviewing the artifact need
  reproducible evidence.

### Step 4 — replay module
- `server/harness/replay.py::replay_session(session_path, candidate_config_path=None, verify=False) -> dict`
- Load saved session JSON from `data/sessions/<id>.json`.
- Reconstruct `MemberResponse` objects for Stage 1 and Stage 2.
- Instantiate a `BoardOrchestrator`; override `HarnessConfig` with candidate
  if supplied via `server.harness.config.load_config(candidate_config_path)`.
- Call `orchestrator.stage3(...)` against stored Stage 1 + Stage 2 inputs.
- If `verify`, run `verify_synthesis(...)`.
- Emit a diff report:
  ```json
  {
    "replay_id": "...",
    "source_session_id": "...",
    "candidate_config_path": "...",
    "baseline": {"verification_score": 8, "synthesis_len": 1820},
    "candidate": {"verification_score": 7, "synthesis_len": 1540},
    "delta": {"verification_score": -1, "synthesis_len": -280}
  }
  ```
  Save to `data/replays/`.

### Step 5 — CLI flags
- Add `--replay SESSION_PATH`, `--candidate-config PATH`, `--replay-verify`.
- When `--replay` present, the CLI short-circuits deliberation and calls
  `replay.replay_session(...)`.
- Print a rich table summary (reuse existing CLI formatter).

### Step 6 — Determinism guard
- Replay forces `temperature=0.0` on Stage 3 and verification model calls
  (pass through `query_llm(..., temperature=0.0)`). Protects the diff from
  being dominated by sampling noise rather than config changes.

## Test strategy

- **Unit:**
  - `test_rolling_stats_basic` with seeded rows.
  - `test_rolling_stats_handles_insufficient_rows` — returns `None` or
    `{"insufficient_samples": true}` when `< recent_n + baseline_n`.
  - `test_distribution_shift_reports_zero_for_identical_distributions`.
- **Contract:**
  - `test_replay_contract.py::test_replay_reproduces_baseline_with_active_config`
    — replay with active config produces same score (within epsilon given
    temperature=0 only on re-run).
  - `test_replay_contract.py::test_replay_candidate_config_changes_score`
    — seeded candidate with different verification threshold produces a
    different `passed` verdict.
- **Integration:**
  - `test_harness_integration_contract.py` extended to assert a drift
    recommendation surfaces when seeded ledger regresses.
- **Smoke (manual):**
  - `uv run python -m server.cli --replay data/sessions/<existing_id>.json --replay-verify`
    prints a replay report; no network calls beyond the verifier model.
- **Edge:**
  - Replay on a session with `stage3 == None` (clarification_required session)
    — exit early with a clear message, not a crash.
  - Replay with a candidate config that removes all active members →
    loader raises, surfaced as a CLI error, not a stack trace.

## Cross-cutting execution policy

Same as Plan 1. Highlights:
1. Phase 0 failing tests committed first.
2. YAGNI: no matplotlib, no pandas. Use stdlib `statistics` and inline math.
3. Determinism: replay sets temperature=0 to isolate the variable.
4. 3-attempt cap applies.

## Sub-agent assignments

- **general-purpose** — implementer.
- **Explore** agent — light pass to confirm the LLM call sites that need
  the `temperature=0.0` override in replay mode; thoroughness: `quick`.

## Rollback triggers

- **Replay output is dominated by provider non-determinism** despite
  temperature=0.0 → stamp and compare only `passed` + structured
  verification fields; de-emphasize numeric score diff.
- **Drift recommendation fires too often and drowns the review** → raise
  threshold or move drift into an advisory `note` rather than a
  `HarnessRecommendation`. Do not remove the signal.

## Open questions

- Should replay also re-run Stage 1/2 against candidate model assignments?
  Decision: **no for V1** — that moves into full shadow evaluation territory
  and overlaps Plan 2. Replay is deliberately Stage 3+ only.

## Standalone-context notes

Plan executable from a fresh Claude Code session using only this document
plus repo state. No dependency on other plans.
