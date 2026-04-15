# Self-Evolving Harness Phase A — Implementation Plan

**Status: COMPLETED** (2026-04-15)

**Goal:** Instrument the board harness with centralized config, session outcome ledger, and founder feedback — the data foundation for automatic harness evolution.

**Architecture:** Two standalone modules (harness_config, ledger) with full test coverage, wired into the existing orchestrator and API. TDD throughout.

**Tech Stack:** Python 3.12, unittest, sqlite3 (stdlib), FastAPI, React (JSX)

**Test suite:** 102 tests passing (72 original + 30 new, zero regressions)

---

## Commit History

| Commit | Description |
|--------|-------------|
| `ba61637` | Baseline — existing agentic board codebase |
| `c502006` | `harness_config.py` + `.json` — single source of truth |
| `7acfea1` | `ledger.py` — SQLite session outcome tracking |
| `bfae51c` | Wire config into orchestrator + verification |
| `f726cac` | Wire ledger into orchestrator post-deliberation |
| `77f02d1` | Founder feedback API endpoint |
| `f8b6f89` | Feedback UI widget below board decisions |

---

## Completed Files

### New Files

| File | Responsibility | Tests |
|------|---------------|-------|
| `server/board/harness_config.py` | Single source of truth for tunable harness parameters. Load/save/cache from JSON. | 8 tests |
| `server/board/harness_config.json` | Persisted config data (git-committed). Defaults match previous hardcoded values. | — |
| `server/board/ledger.py` | Append-only SQLite ledger recording session outcomes. Record, query, aggregate. | 11 tests |
| `tests/test_harness_config_contract.py` | Contract tests: defaults, load, save, round-trip, versioning, forward/backward compat. | — |
| `tests/test_ledger_contract.py` | Contract tests: insert, duplicate guard, feedback, filters, aggregation, nulls. | — |
| `tests/test_harness_integration_contract.py` | Integration tests: config wiring, ledger wiring, feedback endpoint. | 11 tests |

### Modified Files

| File | Change |
|------|--------|
| `server/board/orchestrator.py` | Deleted `STAGE_MAX_TOKENS`, `MAX_STAGE1_REQUIRED_RESPONSES`, `MAX_STAGE2_REQUIRED_RESPONSES`. Imports `get_config()`. Records to ledger after `session.save()`. |
| `server/board/verification.py` | Deleted hardcoded threshold `7`. Imports `get_config()`. Uses `verification_threshold` from config. |
| `server/api.py` | Added `FeedbackRequest` model, `POST /sessions/{session_id}/feedback` endpoint, `_FEEDBACK_DB_PATH` for testability. |
| `ui/src/main.jsx` | Added `FeedbackWidget` component. Rendered in both structured and unstructured decision paths. |
| `ui/src/styles.css` | Added `.feedback-widget`, `.feedback-btn`, `.feedback-note`, `.feedback-done`, `.feedback-error` styles. |
| `.gitignore` | Added IDE, OS, cache, and local env override patterns. |

---

## Completed Tasks

### Task 1-2: Harness Config (tests + impl) — `c502006`

- [x] Write 8 contract tests (defaults, load, save, round-trip, versioning, forward/backward compat)
- [x] Implement `HarnessConfig` dataclass with all tunable parameters
- [x] Implement `load_config()`, `save_config()`, `get_config()` with LRU cache
- [x] Create `harness_config.json` with canonical defaults
- [x] All 8 tests pass, 80 total (no regressions)

### Task 3-4: Harness Ledger (tests + impl) — `7acfea1`

- [x] Write 11 contract tests (insert, duplicate guard, null classification, feedback, filters, aggregation, verification fields)
- [x] Implement SQLite schema with `session_outcomes` table
- [x] Implement `record_session()` extracting fields from `BoardSession`
- [x] Implement `record_feedback()` with existence check
- [x] Implement `query_outcomes()` with filters (query_type, complexity, since, limit)
- [x] Implement `aggregate()` with column allowlist and group validation
- [x] All 11 tests pass, 91 total (no regressions)

### Task 5-6: Wire Config into Orchestrator + Verification — `bfae51c`

- [x] Write 4 integration tests (constants deleted, config token budget used, config threshold used)
- [x] Delete `STAGE_MAX_TOKENS`, `MAX_STAGE1_REQUIRED_RESPONSES`, `MAX_STAGE2_REQUIRED_RESPONSES` from orchestrator
- [x] Replace with `get_config()` calls throughout orchestrator
- [x] Replace hardcoded `score >= 7` with `get_config().verification_threshold` in verification
- [x] All 95 tests pass (no regressions — defaults match old values)

### Task 7-8: Wire Ledger into Orchestrator — `f726cac`

- [x] Write 2 integration tests (ledger entry created, null query_type when classifier skipped)
- [x] Add `_record_to_ledger()` call after `session.save()` in `deliberate()`
- [x] Wrap in try/except so ledger failures never break deliberation
- [x] Add `_LEDGER_DB_PATH` module constant for testability
- [x] All 97 tests pass

### Task 9-10: Feedback Endpoint (tests + impl) — `77f02d1`

- [x] Write 5 integration tests (valid 200, invalid rating 422, nonexistent 404, long note 422, overwrite)
- [x] Add `FeedbackRequest` Pydantic model to api.py
- [x] Add `POST /sessions/{session_id}/feedback` endpoint
- [x] Validate rating values and note length
- [x] All 102 tests pass

### Task 11: Feedback UI Widget — `f8b6f89`

- [x] Add `FeedbackWidget` React component with thumbs up/down + optional note
- [x] Wire into both structured and unstructured `DecisionRecord` paths
- [x] Add CSS styles for feedback controls
- [x] Submitted state shows confirmation, error state shows message

### Task 12: Final Verification

- [x] 102/102 tests pass
- [x] `harness_config.json` tracked in git
- [x] `data/harness_ledger.db` gitignored (via `data/` rule)
- [x] No sensitive files in tracked history
- [x] Pushed to `origin/main`

---

## What Phase A Delivers

### Data Signals Now Available

Every deliberation session now records to `data/harness_ledger.db`:

| Signal | Source | Future Use |
|--------|--------|-----------|
| Per-stage token counts | `SessionMetrics.by_stage()` | Token budget calibration (Phase B) |
| Per-stage latency | `SessionMetrics.by_stage()` | Performance optimization |
| Query type + complexity | Classifier output | Per-type config tuning |
| Members routed vs responded | Classification + stage1 responses | Routing accuracy scoring (Phase D) |
| Models used per member | Stage 1 response metadata | Model assignment optimization |
| Verification score + pass/fail | Stage 4 output | Threshold adaptation (Phase C) |
| Revision needed | Verification failure detection | Quality trend analysis |
| Total cost USD | Cost estimator | Cost vs quality tradeoffs |
| SOTB update proposed/approved | Memory review output | Memory approval rate tracking |
| Founder feedback (rating + note) | `POST /sessions/{id}/feedback` | Ground truth for all tuners |
| Harness config version | `get_config().version` | Correlate config changes with outcomes |

### Tuner-Ready APIs

```python
# Average stage1 tokens by query type
aggregate("stage1_tokens", group_by="query_type")
# → {"strategic": 1450.0, "product": 980.0}

# All sessions where verification failed
query_outcomes(query_type="strategic", complexity="complex")

# Filter by date range
query_outcomes(since="2026-04-01T00:00:00")
```

---

## Future Phases

### Phase B: Token Budget Tuner

**New file:** `server/board/tuner.py`

**What it does:** Reads ledger data, adjusts config automatically. First algorithm: token budget calibration.

```
For each (query_type, complexity) pair with 3+ sessions:
  actual_usage = median tokens used at each stage
  current_budget = current stage max tokens

  If actual_usage < 0.5 * current_budget:
    new_budget = max(actual_usage * 1.3, floor)    # shrink, save cost
  If actual_usage > 0.9 * current_budget:
    new_budget = min(actual_usage * 1.2, ceiling)  # expand, prevent truncation
```

**Reads:** `ledger.aggregate("stage1_tokens", group_by="query_type")`
**Writes:** `harness_config.save_config(updated)` — populates `per_query_type` dict
**Trigger:** New CLI command (`--tune`) or post-session hook
**Phase A change required:** None — APIs already exist

**Estimated impact:** 20-30% token waste reduction for simple queries.

### Phase C: Verification Threshold Adaptation

**What it does:** Correlates verification scores with founder feedback to adjust the pass threshold per decision type.

```
For sessions where founder_feedback exists:
  If verification_passed=True but feedback_rating="negative":
    threshold += 0.5 for that query_type  (too lenient)
  If verification_passed=False but feedback_rating="positive":
    threshold -= 0.5 for that query_type  (too strict)
```

**Reads:** `ledger.query_outcomes()` correlating `verification_score` with `feedback_rating`
**Writes:** `config.per_query_type[query_type]["verification_threshold"]`
**Requires:** Enough sessions with founder feedback to detect patterns (~20+)
**Phase A change required:** None

### Phase D: Routing Accuracy Scoring + Compaction Tracking

**What it does:** Two capabilities:

1. **Routing accuracy** — Parses Stage 3 synthesis to detect which members' input was actually cited. Members consistently unused for a query type get removed from that decision type's capability mapping.

2. **Compaction effectiveness** — Measures semantic overlap between compacted Stage 1 elements and the final synthesis. Sections that are never used get dropped; critical sections get preserved with more detail.

**Reads:** Ledger `members_routed` + new synthesis citation parser
**Writes:** Roster capability adjustments, compaction strategy config
**Requires:** ~50+ sessions for statistical significance
**Phase A change required:** None

### Phase E: Model Assignment Optimization

**What it does:** Tracks which model produces the best output per member role by correlating model assignments with verification scores and founder feedback. Replaces round-robin assignment with data-driven preferences.

**Reads:** Ledger `models_used` + `verification_score` + `feedback_rating`
**Writes:** `config.per_query_type[type]["model_preferences"]`
**Requires:** Multiple models per role across sessions
**Phase A change required:** None — `per_query_type` dict already supports arbitrary nested keys

---

## Evolution Roadmap

```
Phase A (DONE)     → Instrument: config + ledger + feedback
Phase B (next)     → First auto-tuner: token budgets
Phase C            → Verification threshold adaptation
Phase D            → Routing accuracy + compaction tracking
Phase E            → Model assignment optimization
```

Each phase adds a new file (`tuner.py` grows, or splits into `tuner_tokens.py`, `tuner_verification.py`, etc.) and reads/writes through the Phase A APIs. No Phase A code changes needed for any future phase.
