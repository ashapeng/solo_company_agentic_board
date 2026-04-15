# Self-Evolving Harness — Phase A Design Spec

## Context

The Agentic Board is `Agent = Multiple LLM Models + Harness`. The models are
commodities. The harness — orchestrator, classifier, compaction, protocols,
memory, verification, metrics, roster, schemas — is the product.

Today the harness has no feedback loops. After 100 sessions it behaves
identically to session 1. Tunable parameters (token budgets, verification
thresholds, response minimums) are hardcoded constants scattered across
modules. Session outcomes are saved as JSON but never analyzed.

This spec defines Phase A: the foundation layer that instruments the harness
for self-evolution. Phase A collects data and centralizes configuration.
Phases B-D (auto-tuning) build on top of this foundation without modifying it.

## Scope

**Phase A delivers three components:**

1. **Harness Config** (`server/board/harness_config.py`) — single source of
   truth for all tunable harness parameters, persisted as committed JSON.
2. **Harness Ledger** (`server/board/ledger.py`) — append-only SQLite store
   recording structured session outcomes for analysis.
3. **Founder Feedback** — API endpoint and UI element for binary rating +
   optional note per session.

**Phase A does NOT deliver:**
- Auto-tuning algorithms (Phase B: token budget calibration)
- Verification threshold adaptation (Phase C)
- Routing accuracy scoring (Phase D)
- Compaction effectiveness tracking (Phase D)

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Config structure | Single source of truth | One place to look, one place to change. Modules import from config; old constants deleted. |
| Ledger storage | SQLite (`data/harness_ledger.db`) | Ships with Python stdlib. Tuner needs aggregation queries. No external dependencies. |
| Ledger location | Gitignored | Runtime analytical data, like session JSON. |
| Config location | Git-committed (`server/board/harness_config.json`) | The harness itself, not ephemeral data. Evolution is visible in git history. |
| Feedback granularity | Binary + optional note | Low friction for the founder. Note enables future attribution to harness layers. |
| Implementation approach | Parallel layers then wire | Build config and ledger as standalone tested modules, then integrate. Natural TDD fit. |

---

## Component 1: Harness Config

### File: `server/board/harness_config.py`

### Data Shape

```python
@dataclass
class HarnessConfig:
    # Stage token budgets (from orchestrator.py)
    stage1_max_tokens: int = 1200
    stage2_max_tokens: int = 800
    stage3_max_tokens: int = 4000
    revision_max_tokens: int = 2500

    # Response thresholds (from orchestrator.py)
    min_stage1_responses: int = 3
    min_stage2_responses: int = 2

    # Verification (from verification.py)
    verification_threshold: float = 7.0
    max_revision_attempts: int = 1

    # Complexity multipliers (unused in Phase A, slot for Phase B tuner)
    complexity_multipliers: dict = field(default_factory=lambda: {
        "simple": 0.6,
        "moderate": 1.0,
        "complex": 1.5,
    })

    # Per-query-type overrides (empty in Phase A, populated by tuner in Phase B+)
    per_query_type: dict = field(default_factory=dict)
    # Future shape: {"strategic": {"stage1_max_tokens": 1600, "verification_threshold": 8.0}}

    # Version tracking (for ledger correlation)
    version: int = 1
    last_modified: str = ""
```

### Persistence

- File: `server/board/harness_config.json`
- Committed to git
- Created with defaults if missing on first load

### API

- `load_config(path: Path | None = None) -> HarnessConfig` — reads from JSON,
  returns defaults if file missing
- `save_config(config: HarnessConfig, path: Path | None = None) -> None` —
  writes to JSON, bumps version, sets last_modified, invalidates module cache
- `get_config() -> HarnessConfig` — module-level cached access (load once per
  process; cache is invalidated by `save_config` or explicit
  `get_config.cache_clear()` call)

### Test Contracts

1. Defaults match current hardcoded values exactly (non-breaking migration)
2. Loads from JSON when file exists
3. Falls back to defaults when file is missing
4. Round-trips: save then load produces identical config
5. `version` auto-increments on save
6. Unknown fields in JSON are ignored (forward-compatible)
7. Missing fields in JSON use defaults (backward-compatible)

---

## Component 2: Harness Ledger

### File: `server/board/ledger.py`

### Schema

```sql
CREATE TABLE session_outcomes (
    session_id            TEXT PRIMARY KEY,
    timestamp             TEXT NOT NULL,
    query_type            TEXT,
    complexity            TEXT,
    members_routed        TEXT,       -- JSON array
    members_responded     TEXT,       -- JSON array
    member_failures       TEXT,       -- JSON array of {member_id, error}
    models_used           TEXT,       -- JSON dict {member_id: model}
    stage1_tokens         INTEGER,
    stage2_tokens         INTEGER,
    stage3_tokens         INTEGER,
    stage1_latency        REAL,
    stage2_latency        REAL,
    stage3_latency        REAL,
    verification_score    INTEGER,
    verification_passed   INTEGER,    -- 0/1/NULL
    revision_needed       INTEGER,    -- 0/1
    total_cost_usd        REAL,
    sotb_update_proposed  INTEGER,    -- 0/1
    sotb_update_approved  INTEGER,    -- 0/1/NULL
    feedback_rating       TEXT,       -- positive/negative/NULL
    feedback_note         TEXT,
    harness_config_version INTEGER
);
```

### Location

`data/harness_ledger.db` — gitignored (runtime data).

### API

- `record_session(session: BoardSession, config_version: int) -> None` —
  extract fields from BoardSession, insert row. Raises on duplicate session_id.
- `record_feedback(session_id: str, rating: str, note: str | None = None) -> None` —
  update feedback columns. Raises if session_id not found.
- `query_outcomes(**filters) -> list[dict]` — filtered reads. Supports
  `query_type`, `complexity`, `since` (ISO date), `limit`.
- `aggregate(field: str, group_by: str, **filters) -> dict` — grouped
  aggregation for tuner consumption. Accepts the same filters as
  `query_outcomes` (`query_type`, `complexity`, `since`, `limit`). Example:
  `aggregate("stage1_tokens", group_by="query_type")` returns
  `{"strategic": 1450.0, "product": 980.0}`.

### Design Notes

- Flat table, no normalization. Each row is a self-contained session snapshot.
- JSON arrays/dicts stored as TEXT, parsed on read.
- DB auto-created on first write if missing.
- No ORM — raw `sqlite3` from stdlib.

### Test Contracts

1. `record_session` inserts a complete row from a BoardSession
2. `record_feedback` updates only feedback columns for an existing session
3. `record_feedback` on nonexistent session_id raises
4. `query_outcomes` with no filters returns all rows
5. `query_outcomes` with `query_type="strategic"` filters correctly
6. `aggregate("stage1_tokens", group_by="query_type")` returns correct averages
7. DB is created automatically if missing
8. Duplicate session_id raises (no silent overwrites)
9. Sessions with no classification have NULL query_type/complexity

---

## Component 3: Founder Feedback

### API Endpoint

```
POST /sessions/{session_id}/feedback
Body: {"rating": "positive" | "negative", "note": "optional string"}
Response: {"status": "recorded", "session_id": "..."}
```

### Validation

- `rating` required, must be `"positive"` or `"negative"`
- `note` optional, max 500 characters
- `session_id` must exist in ledger — 404 if not
- Repeated POST overwrites previous feedback (last write wins)

### UI Element

After synthesis renders in `ui/app.js`, show:
- Two buttons: thumbs up / thumbs down
- Optional text input (placeholder: "What could be better?")
- Submit via fetch to the endpoint
- Inline below the board decision, not a modal or form

### File: `server/api.py` (new route added)

### Test Contracts

1. POST with valid rating returns 200 and persists to ledger
2. POST with invalid rating returns 422
3. POST to nonexistent session_id returns 404
4. POST with note exceeding 500 chars returns 422
5. Second POST to same session_id overwrites previous feedback
6. GET `/sessions/{id}` response includes feedback fields when present

---

## Component 4: Wiring

### Config Wiring

| File | Change |
|------|--------|
| `orchestrator.py` | Delete `STAGE_MAX_TOKENS`, `MAX_STAGE1_REQUIRED_RESPONSES`, `MAX_STAGE2_REQUIRED_RESPONSES`. Import from `harness_config.get_config()`. |
| `verification.py` | Delete hardcoded threshold (7) and max revision count (1). Import from `harness_config.get_config()`. |

No other files change for config wiring.

### Ledger Wiring

| File | Change |
|------|--------|
| `orchestrator.py` | After `session.save()`, call `ledger.record_session(session, config_version=get_config().version)`. |

### Feedback Wiring

| File | Change |
|------|--------|
| `api.py` | Add `POST /sessions/{session_id}/feedback` route calling `ledger.record_feedback()`. |

### Files That Do NOT Change

`compaction.py`, `classifier.py`, `memory.py`, `memory_review.py`, `prompts.py`,
`loader.py`, `role_gap.py`, `schemas.py`, `metrics.py`, `config.py`, `llm.py`,
`roster.py`, all member `.md` files, all protocol `.md` files.

### Integration Test Contracts

1. After `deliberate()` completes, a ledger row exists with matching session_id
2. Ledger row's harness_config_version matches the active config version
3. Ledger row has correct query_type and complexity when classifier ran
4. Ledger row has NULL query_type when skip_classify=True
5. Ledger row has correct verification_score when verification ran
6. Ledger row has NULL verification fields when verify=False
7. Orchestrator uses harness_config token budgets (not old hardcoded values)
8. Orchestrator uses harness_config response thresholds
9. Verification uses harness_config threshold and revision count
10. All 72 existing tests still pass unchanged

---

## Forward Compatibility

Phase A's data structures are designed so future phases add new code without
modifying Phase A code.

### Phase B: Token Budget Tuner (`server/board/tuner.py`)

- Reads: `ledger.aggregate("stage1_tokens", group_by="query_type")`
- Writes: `harness_config.save_config(updated)`
- Populates: `config.per_query_type` dict
- Trigger: new CLI command or post-session hook
- Phase A change required: none

### Phase C: Verification Threshold Adaptation

- Reads: `ledger.query_outcomes()` correlating verification_score with
  feedback_rating per query_type
- Writes: `config.per_query_type[query_type]["verification_threshold"]`
- Phase A change required: none

### Phase D: Routing Accuracy Scoring

- Reads: `ledger` members_routed + synthesis citation parsing (new logic)
- Writes: roster capability adjustments
- Phase A change required: none

---

## New Files

| File | Type | Git |
|------|------|-----|
| `server/board/harness_config.py` | Module | Committed |
| `server/board/harness_config.json` | Config data | Committed |
| `tests/test_harness_config_contract.py` | Tests | Committed |
| `server/board/ledger.py` | Module | Committed |
| `tests/test_ledger_contract.py` | Tests | Committed |
| `tests/test_harness_integration_contract.py` | Tests | Committed |
| `data/harness_ledger.db` | Runtime data | Gitignored |

## Modified Files

| File | Scope of Change |
|------|-----------------|
| `server/board/orchestrator.py` | Delete 3 constants, import config, add ledger call |
| `server/board/verification.py` | Delete 2 constants, import config |
| `server/api.py` | Add 1 route |
| `ui/app.js` | Add feedback UI below synthesis |
| `.gitignore` | Add `data/harness_ledger.db` |
