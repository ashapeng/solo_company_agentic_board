# Plan 2 — Harness Trust (Cluster B)

**Status:** proposed
**Date:** 2026-04-20
**Owner:** TBD
**Related review:** commit 8906ae9 post-review, items P1.1 + P1.2 + P2.5 + P3.6 + P3.7
**Dependencies:** none
**Parallelizable with:** Plans 1, 3, 5
**Estimated scope:** medium (~6 files, ledger schema migration, ~300 LOC)

## Goal

Make the self-evolving harness trustworthy enough to run without a human
rubber-stamp per review. Three problems compound today:

1. Verifier and chairman default to the **same model**
   (`kimi/kimi-k2.5`), so Tuner E's ground-truth signal reinforces a single
   provider's taste.
2. `apply_harness_review` re-runs tuners with `dry_run=False` — it does not
   apply the diff the user approved; ledger drift between approval and apply
   can produce a different config.
3. There is no post-apply regression detector and no rollback path, so a bad
   tuner change stays in production until a human notices in the reliability
   recap.

## Scope

### In scope
- **#3** Enforce verifier ≠ chairman provider; add startup guard.
- **#4** Persist approved diff; `apply_harness_review` applies stored diff;
  shadow watcher auto-reverts on regression.
- **#8** Split `_quality_score` into `(verification, feedback)`; require both
  to be non-negative before promoting a model.
- **#12** Stamp `verifier_model`, `verifier_provider`, `chairman_provider`,
  `applied_review_id`, `applied_at`, `reverted_at` on relevant records;
  per-tuner meta-accuracy = applied-and-not-reverted / applied.

### Out of scope
- Multi-rater feedback (Plan F, deferred).
- Replay tooling (Plan 5).
- Any UI change to the harness review page.
- Any change to classifier or Stage 1/2 pipeline.

## Files touched
- `server/board/config.py` — startup provider guard
- `server/board/deliberation/verification.py` — stamp verifier model/provider into result
- `server/harness/config.py` — add provider helpers
- `server/harness/ledger.py` — new columns; `rolling_stats` helper used by shadow
- `server/harness/reviews.py` — snapshot diff at approval, apply snapshot, `applied_at`/`reverted_at`
- `server/harness/model_assignment.py` — split quality signal
- (new) `server/harness/shadow.py` — post-apply regression watcher + revert
- (new) `server/harness/meta.py` — per-tuner accuracy
- `tests/test_harness_config_contract.py`, `test_tuner_contract.py`, `test_ledger_contract.py` — extend
- (new) `tests/test_harness_shadow_contract.py`

## Phase 0 — Reproduce before code

Each reproduction test is a standalone pytest that must FAIL against current
`main`. Commit them in one repro commit before any implementation.

1. **Verifier/chairman same-provider test:**
   ```python
   def test_default_verifier_not_same_provider_as_chairman():
       from server.board.config import get_chairman_model, get_verification_model
       from server.harness.config_provider import provider_of  # new helper
       assert provider_of(get_chairman_model()) != provider_of(get_verification_model())
   ```
   Fails today: both resolve to `kimi`.

2. **Apply-uses-snapshot test:**
   ```python
   def test_apply_uses_approved_snapshot_not_live_ledger(tmp_db):
       # approve a review with specific model-preference diff
       # mutate the ledger to produce a different diff if tuner re-ran
       # call apply_harness_review; assert applied config matches approved diff
   ```
   Fails today: apply calls `fn(dry_run=False)` which recomputes.

3. **Regression rollback test:**
   ```python
   def test_shadow_reverts_after_regression(tmp_db, fake_sessions):
       # seed pre-apply baseline mean verification = 8
       # apply review that shifts model assignment
       # seed 10 post-apply sessions with mean verification = 4
       # call shadow.watch()
       # assert config reverted + reverted_at stamped + reason recorded
   ```
   Fails today: no shadow module.

4. **Quality-signal split test:**
   ```python
   def test_tuner_e_skips_change_when_feedback_contradicts_verifier():
       # seed outcomes where model X has verifier=9 but feedback=negative
       # assert tuner E does not promote X
   ```
   Fails today: feedback bonus is additive; negative doesn't veto.

## Implementation steps

### Step 1 — provider helper + startup guard (config.py)
- In `server/harness/config_provider.py` (new): `provider_of(model_id) -> str`
  by splitting on `/` or `:`, returning `kimi`, `deepseek`, `qwen`, `glm`,
  `zai`, `openrouter`, or `"unknown"`.
- In `server/board/config.py` at module load: call
  `_assert_verifier_decoupled()` that compares providers; raises unless
  `AGENTIC_BOARD_ALLOW_SAME_VERIFIER=1`. Document env override in CLAUDE.md.
- Update `DEFAULT_VERIFICATION_MODEL = "deepseek/deepseek-chat"` (chairman
  stays on Kimi). Rationale: reviewer is cheaper than chairman, still a
  different provider.

### Step 2 — ledger columns
- Extend `_SCHEMA` and `_ensure_columns` with
  `verifier_model TEXT, verifier_provider TEXT, chairman_provider TEXT, applied_review_id TEXT`.
- `record_session` reads `session.verification.get("verifier_model")`.
- Persist `applied_review_id` only for rows recorded AFTER an apply until the
  next apply/revert; tracked via a new small table `harness_config_activations(id, review_id, activated_at, reverted_at)`.

### Step 3 — verification result carries provider metadata
- `VerificationResult` dataclass gains `verifier_model`, `verifier_provider`.
- `verify_synthesis` populates them.
- `projection.verification_to_dict` includes them.

### Step 4 — snapshot-based apply (reviews.py)
- On approval (`approve_harness_review`), compute canonical diff via
  `tune_*(dry_run=True)` aggregated into `review["snapshot"]`, serialize to JSON.
- `apply_harness_review` applies `snapshot` directly by writing into
  `HarnessConfig` then calling `save_config`. No re-run.
- On apply, insert row into `harness_config_activations`; stamp `applied_at`.

### Step 5 — shadow watcher
- `harness/shadow.py::watch_after_apply(review_id, window=10, regression_threshold=1.0)`.
- Reads the baseline (mean verification score for the 20 sessions preceding
  activation) and the new window (the N sessions after).
- If `baseline - current > threshold` → call `revert_activation(review_id)`:
  restore the previous `HarnessConfig` snapshot, stamp `reverted_at`, append
  reason to review JSON.
- Wire into the HTTP route `POST /harness/review/{id}/apply` asynchronously:
  fire `asyncio.create_task(watch_after_apply(id))`; but make sure test path
  can call synchronously.
- Keep a previous-snapshot column in `harness_config_activations` so revert
  restores the exact prior config.

### Step 6 — quality signal split
- `_quality_score` returns `QualityScore(verification: float | None, feedback: str | None)`.
- `_apply_model_assignment_tuning`:
  - mean of verification values as before, but
  - additionally compute feedback tally per (query_type, member, model);
  - skip promotion if the best candidate has any `negative` feedback and
    runner-up has none.

### Step 7 — per-tuner meta-accuracy
- `harness/meta.py::tuner_accuracy(tuner_name)` → reads
  `harness_config_activations` + tuner diffs from snapshot; returns
  `applied_and_not_reverted / applied` per tuner name.
- Surface in `reviews._reliability_recommendation` as an advisory line.

## Test strategy

- **Unit:** each step has a targeted test. Phase 0 tests flip green as
  corresponding step lands.
- **Contract:** extend `test_tuner_contract.py` with the split-quality case;
  extend `test_ledger_contract.py` for new columns.
- **Integration:** `test_harness_shadow_contract.py` drives a full
  seed-apply-regress-revert loop against a tmp SQLite ledger.
- **Smoke:** `uv run python -m server.cli --list-members` still works (ensures
  startup guard doesn't break normal boot). Remove env override; confirm
  startup raises when verifier provider matches chairman.
- **Edge cases:**
  - Activation table empty (first-ever apply) — meta-accuracy = 1.0 or None.
  - Shadow runs with < window sessions available — no-op, log info.
  - Revert racing with next apply — use row-level locking on
    `harness_config_activations` via a single transaction.

## Cross-cutting execution policy

Same as Plan 1. Key reminders:
1. Phase 0 failing tests committed before any impl commit.
2. Root-cause debugging only; no silent except.
3. 3-attempt cap → `git reset --hard` to last green commit.
4. YAGNI: SQLite + JSON; no MLflow, no feature store, no background scheduler
   library. `asyncio.create_task` fired from the apply handler is enough.
5. Done criteria: all Phase 0 tests green, existing suite green,
   `pytest -W error tests/` clean, manual review-apply-regress-revert loop
   confirmed in a tmp DB.

## Sub-agent assignments

- **Explore** agent first — map all ledger callers and every site that reads
  `HarnessConfig` version, plus every test fixture touching the ledger.
  Thoroughness: `medium`.
- **general-purpose** — primary implementer.
- **superpowers:code-reviewer** — after Step 5, audit shadow rollback math
  (window boundaries, baseline selection, concurrent apply safety).
- **superpowers:code-reviewer** — after Step 6, check that the split quality
  signal cannot regress the existing tuner contract tests.

## Rollback triggers

- **Shadow rollback loop oscillates** (revert → re-apply → revert) → disable
  shadow via env flag `AGENTIC_BOARD_SHADOW_DISABLED=1`, investigate
  baseline selection.
- **Startup guard blocks legitimate dev setups** → bump instructions on
  `AGENTIC_BOARD_ALLOW_SAME_VERIFIER=1` into CLAUDE.md and .env.example; do
  not remove the guard.

## Open questions

- Default regression threshold (1.0 on a 10-point scale) is a first guess;
  validate empirically after first week.
- `harness_config_activations` could grow; add optional `VACUUM` policy if
  row count exceeds 10k (not an initial concern).

## Standalone-context notes

Plan doc self-contained. A fresh Claude Code session can execute this plan
without reading the brainstorming transcript.
