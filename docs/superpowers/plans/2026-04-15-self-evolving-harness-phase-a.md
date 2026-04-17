# Self-Evolving Harness — Implementation Completion Record

**Status: COMPLETED THROUGH PHASE E** (2026-04-15)

**Original goal:** Instrument the board harness with centralized config, a session outcome ledger, and founder feedback so the harness can evolve automatically from real usage data.

**Current result:** The full self-evolving harness loop is implemented through model assignment optimization. The board now records session outcomes, accepts founder feedback, tunes token budgets, adapts verification thresholds, adjusts routing and compaction policy, and selects member models from historical quality signals.

**Tech stack:** Python 3.12, unittest, sqlite3 (stdlib), FastAPI, React (JSX)

**Final verification:** 140 Python tests passing.

```bash
.venv/bin/python -m unittest discover -s tests
# Ran 140 tests in 6.032s - OK
```

Note: the full test run still prints the existing caught duplicate-ledger warning for `board_verify`; the warning is handled by the orchestrator and the suite exits successfully.

---

## Completed Phases

| Phase | Status | Delivered |
|------|--------|-----------|
| Phase A | Done | Config, ledger, founder feedback endpoint, feedback UI |
| Phase B | Done | Token budget tuner |
| Phase C | Done | Verification threshold adaptation |
| Phase D | Done | Routing accuracy scoring and compaction tracking |
| Phase E | Done | Model assignment optimization |

---

## Phase A: Instrumentation Foundation

**Goal:** Add the data foundation for harness evolution.

### New Files

| File | Responsibility |
|------|----------------|
| `server/board/harness_config.py` | Single source of truth for tunable harness parameters, config loading/saving, and runtime resolvers. |
| `server/board/harness_config.json` | Persisted default config, committed to git. |
| `server/board/ledger.py` | SQLite session outcome ledger. |
| `tests/test_harness_config_contract.py` | Config contract and resolver tests. |
| `tests/test_ledger_contract.py` | Ledger contract tests. |
| `tests/test_harness_integration_contract.py` | Cross-module harness integration tests. |

### Runtime Changes

| File | Change |
|------|--------|
| `server/board/orchestrator.py` | Reads config instead of hardcoded stage budgets/thresholds. Records sessions to the ledger after `session.save()`. |
| `server/board/verification.py` | Uses config-driven verification threshold. |
| `server/api.py` | Adds `POST /sessions/{session_id}/feedback`. |
| `ui/src/main.jsx` | Adds decision feedback widget. |
| `ui/src/styles.css` | Adds feedback widget styling. |
| `.gitignore` | Keeps runtime data and local artifacts out of git. |

### Signals Recorded

Every deliberation can now record these signals in `data/harness_ledger.db`:

| Signal | Source | Used By |
|--------|--------|---------|
| Per-stage token counts | `SessionMetrics.by_stage()` | Phase B |
| Per-stage latency | `SessionMetrics.by_stage()` | Future performance tuning |
| Query type and complexity | Classifier output | Phases B-E |
| Members routed/responded | Classification and Stage 1 responses | Phase D |
| Models used per member | Stage 1 response metadata | Phase E |
| Verification score/pass/fail | Stage 4 output | Phases C/E |
| Revision needed | Verification flow | Quality analysis |
| Total cost USD | Cost estimator | Cost/quality tradeoffs |
| SOTB update proposed/approved | Memory review output | Memory tuning |
| Founder feedback | Feedback API/UI | Phases C/E |
| Harness config version | `get_config().version` | Outcome/config correlation |

---

## Phase B: Token Budget Tuner

**Status:** Completed.

**Files:** `server/board/tuner.py`, `tests/test_tuner_contract.py`

**CLI:**

```bash
.venv/bin/python -m server.cli --tune
.venv/bin/python -m server.cli --tune --dry-run --json
```

**Behavior:**

For each `(query_type, complexity)` segment with 3+ sessions:

```text
actual_usage = median tokens used at each stage

if actual_usage < 0.5 * current_budget:
  new_budget = max(actual_usage * 1.3, floor)

if actual_usage > 0.9 * current_budget:
  new_budget = min(actual_usage * 1.2, ceiling)
```

**Writes:**

```python
per_query_type[query_type]["token_budgets"][complexity][stage_field]
```

Example:

```json
{
  "per_query_type": {
    "strategic": {
      "token_budgets": {
        "simple": {
          "stage1_max_tokens": 520,
          "stage3_max_tokens": 4440
        }
      }
    }
  }
}
```

**Runtime wiring:** `server/board/orchestrator.py` resolves stage token budgets through `resolve_stage_max_tokens()`.

---

## Phase C: Verification Threshold Adaptation

**Status:** Completed.

**Files:** `server/board/tuner.py`, `server/board/verification.py`, `tests/test_tuner_contract.py`

**CLI:**

```bash
.venv/bin/python -m server.cli --tune-verification
.venv/bin/python -m server.cli --tune-verification --dry-run --json
.venv/bin/python -m server.cli --tune-verification --min-feedback-sessions 10
```

**Behavior:**

For each `query_type` with enough feedback-bearing sessions:

```text
verification_passed=True  + feedback_rating="negative" -> threshold += 0.5
verification_passed=False + feedback_rating="positive" -> threshold -= 0.5
ties or insufficient evidence -> no change
```

Default minimum feedback sessions: 20.

**Writes:**

```python
per_query_type[query_type]["verification_threshold"]
```

**Runtime wiring:** classified sessions pass `query_type` into verification, and `verify_synthesis()` uses `resolve_verification_threshold()`.

---

## Phase D: Routing Accuracy + Compaction Tracking

**Status:** Completed.

**Files:** `server/board/phase_d.py`, `server/board/compaction.py`, `tests/test_phase_d_contract.py`

**CLI:**

```bash
.venv/bin/python -m server.cli --tune-routing
.venv/bin/python -m server.cli --tune-routing --dry-run --json
.venv/bin/python -m server.cli --tune-routing --min-phase-d-sessions 25
```

**Routing behavior:**

Phase D loads ledger rows plus saved session JSON from `data/sessions`, parses Stage 3 synthesis citations, and compares cited members against routed members.

Members that are consistently routed but not cited for a query type are suppressed through config rather than by mutating `roster.yaml`.

Default minimum sessions per query type: 50.

**Routing writes:**

```python
per_query_type[query_type]["routing"]["suppressed_member_ids"]
```

Example:

```json
{
  "per_query_type": {
    "strategic": {
      "routing": {
        "suppressed_member_ids": ["critic"]
      }
    }
  }
}
```

**Compaction behavior:**

Phase D measures whether Stage 1 compactable sections appear semantically in the final synthesis. Unused sections can be dropped; heavily used risk sections can be preserved with more detail.

**Compaction writes:**

```python
per_query_type[query_type]["compaction"]["stage1_sections"]
per_query_type[query_type]["compaction"]["stage1_detail_sections"]
```

Example:

```json
{
  "per_query_type": {
    "strategic": {
      "compaction": {
        "stage1_sections": ["confidence", "top_risk"],
        "stage1_detail_sections": ["top_risk"]
      }
    }
  }
}
```

**Runtime wiring:**

| File | Behavior |
|------|----------|
| `server/board/orchestrator.py` | Applies routing suppressions after classification while preserving at least one non-chair council member. |
| `server/board/compaction.py` | Uses query-type-specific Stage 1 compaction policy. |
| `server/board/harness_config.py` | Resolves routing and compaction policy from `per_query_type`. |

---

## Phase E: Model Assignment Optimization

**Status:** Completed.

**Files:** `server/board/phase_e.py`, `tests/test_phase_e_contract.py`

**CLI:**

```bash
.venv/bin/python -m server.cli --tune-models
.venv/bin/python -m server.cli --tune-models --dry-run --json
.venv/bin/python -m server.cli --tune-models --min-model-samples 5
```

**Behavior:**

Phase E reads `models_used`, `verification_score`, and `feedback_rating` from the ledger. It scores each `(query_type, member_id, model)` candidate and writes the best model when there is enough evidence.

Default minimum samples per candidate model: 3.

Quality score inputs:

| Signal | Effect |
|--------|--------|
| `verification_score` | Base quality score |
| `feedback_rating="positive"` | Adds positive bonus |
| `feedback_rating="negative"` | Adds negative penalty |

**Writes:**

```python
per_query_type[query_type]["model_preferences"][member_id]
```

Example:

```json
{
  "per_query_type": {
    "strategic": {
      "model_preferences": {
        "strategist": "model-b"
      }
    }
  }
}
```

**Runtime precedence:**

```text
member.model_override > tuned model_preferences > round-robin council model
```

**Runtime wiring:** `server/board/orchestrator.py` passes the classified `query_type` into `_assign_models()`, which resolves preferences through `resolve_model_preferences()`.

---

## Current Config Surface

`HarnessConfig.per_query_type` now supports these nested tuner outputs:

```python
{
    "strategic": {
        "token_budgets": {
            "simple": {
                "stage1_max_tokens": 520,
                "stage3_max_tokens": 4440,
            },
        },
        "verification_threshold": 7.5,
        "routing": {
            "suppressed_member_ids": ["critic"],
        },
        "compaction": {
            "stage1_sections": ["confidence", "top_risk"],
            "stage1_detail_sections": ["top_risk"],
        },
        "model_preferences": {
            "strategist": "model-b",
        },
    },
}
```

All tuners preserve unrelated metadata under the same query type.

---

## CLI Summary

| Command | Phase | Purpose |
|---------|-------|---------|
| `--tune` | B | Tune token budgets by query type/complexity. |
| `--tune-verification` | C | Tune verification thresholds from founder feedback. |
| `--tune-routing` | D | Tune routing suppressions and Stage 1 compaction policy. |
| `--tune-models` | E | Tune per-member model preferences. |

All tuner commands support:

```bash
--dry-run --json
```

Additional sample-size controls:

```bash
--min-feedback-sessions N
--min-phase-d-sessions N
--min-model-samples N
```

---

## Final File Inventory

### New Core Files

| File | Phase | Responsibility |
|------|-------|----------------|
| `server/board/harness_config.py` | A-E | Tunable config, persistence, runtime resolvers. |
| `server/board/harness_config.json` | A | Default committed config. |
| `server/board/ledger.py` | A | SQLite outcome ledger. |
| `server/board/tuner.py` | B-C | Token budget and verification threshold tuners. |
| `server/board/phase_d.py` | D | Routing accuracy and compaction tuner. |
| `server/board/phase_e.py` | E | Model assignment tuner. |

### New Test Files

| File | Coverage |
|------|----------|
| `tests/test_harness_config_contract.py` | Config load/save plus runtime resolvers. |
| `tests/test_ledger_contract.py` | Ledger schema, inserts, queries, feedback, aggregation. |
| `tests/test_harness_integration_contract.py` | Runtime wiring for config, ledger, feedback, token budgets, verification thresholds. |
| `tests/test_tuner_contract.py` | Phase B/C tuner contracts. |
| `tests/test_phase_d_contract.py` | Phase D routing and compaction contracts. |
| `tests/test_phase_e_contract.py` | Phase E model assignment contracts. |

### Modified Runtime Files

| File | Change |
|------|--------|
| `server/board/orchestrator.py` | Uses config-driven token budgets, routing suppressions, compaction policy, verification query type, and model preferences. Records to ledger. |
| `server/board/verification.py` | Uses per-query verification threshold. |
| `server/board/compaction.py` | Supports per-query Stage 1 compaction policy and exposes compaction elements for Phase D. |
| `server/cli.py` | Adds tuner CLI commands for Phases B-E. |
| `server/api.py` | Adds feedback endpoint. |
| `ui/src/main.jsx` | Adds feedback UI. |
| `ui/src/styles.css` | Adds feedback UI styles. |

---

## Verification Commands Run

```bash
.venv/bin/python -m unittest discover -s tests
.venv/bin/python -m server.cli --tune --dry-run --json
.venv/bin/python -m server.cli --tune-verification --dry-run --json
.venv/bin/python -m server.cli --tune-routing --dry-run --json
.venv/bin/python -m server.cli --tune-models --dry-run --json
```

All commands completed successfully in the current workspace. The local ledger currently has no eligible real sessions, so tuner dry-runs return zero changes until enough production sessions accumulate.

---

## Evolution Roadmap Status

```text
Phase A (DONE)  -> Instrument: config + ledger + feedback
Phase B (DONE)  -> Token budget tuner
Phase C (DONE)  -> Verification threshold adaptation
Phase D (DONE)  -> Routing accuracy + compaction tracking
Phase E (DONE)  -> Model assignment optimization
```

The next logical work is operational hardening: schedule tuner runs, add human approval gates before writing config in production, and add dashboard/reporting views over tuner recommendations.
