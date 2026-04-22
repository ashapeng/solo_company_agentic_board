# Focused Boardroom UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flip the Agentic Board UI from obsidian dark to cream editorial, collapse peripheral panels into edge drawers, make the round table the focal zone with stage-gated member arrival, remove duplicate CEO avatar, and capture routing-quality signals in the ledger for future Phase D.

**Architecture:** Two parallel tracks merged by a single final QA. Backend track: one schema column + one API route + one frontend API client function (strict TDD). Frontend track: palette token rewrite in `@theme`, 72px icon-rail shell, Round Table + Composer + Drawers redesign inside `GovernancePage.tsx`, plus retheme sweep across aux pages (implementation + build verification — no unit test framework on frontend).

**Tech Stack:** React 19, TypeScript 5.8, Vite 7, Tailwind 4 (CSS-first `@theme`), Framer Motion 12, lucide-react, recharts, Noto Serif + Manrope. Backend: FastAPI, Pydantic, SQLite (stdlib), pytest.

**Spec reference:** `docs/superpowers/specs/2026-04-21-focused-boardroom-ui-design.md`

---

## File Structure

### New files

| Path | Responsibility |
|------|----------------|
| `tests/test_routing_signal_contract.py` | pytest contract tests for ledger column + `record_routing_signal` + API route |

### Modified files — backend

| Path | Scope |
|------|-------|
| `server/harness/ledger.py` | Add `routing_misses TEXT` to `_SCHEMA` + `_ensure_columns` additions dict; add `record_routing_signal(...)` function |
| `server/api/schemas.py` | Add `RoutingSignalRequest` Pydantic model |
| `server/api/routes/board.py` | Add `POST /sessions/{session_id:path}/routing-signal` route |

### Modified files — frontend

| Path | Scope |
|------|-------|
| `ui/src/index.css` | Rewrite `@theme` palette to cream tokens; retune `.speaking-halo` / `.glass-panel` / `.metallic-gradient` / `.accent-bar-left` for cream |
| `ui/src/shared/api.ts` | Add `recordRoutingSignal(sessionId, memberId, source)` |
| `ui/src/shared/presentation.tsx` | Recalibrate `MEMBER_TONES` for cream bg; retint `taskStatusClass` |
| `ui/src/shared/components.tsx` | No semantic change; token names already abstract — verify dark→cream swap works |
| `ui/src/App.tsx` | Replace 280px side nav with permanent 72px icon rail; remove top bar; preserve tab state |
| `ui/src/domains/board/GovernancePage.tsx` | Remove top CEO avatar; cream round table; done-shrink + failed-burgundy seats; overflow +N seat; holo card state machine; stage pip rail; replace 3-column layout with hero + edge drawers; add `<BriefingDrawer>`, `<OutlookDrawer>`, `<MissingVoiceRow>`, `<OverflowSeat>`; drawer mutual-exclusion + pin + Esc; manual-add "+" popover + signal buffering/flush |
| `ui/src/domains/board/PortfolioPage.tsx` | Retheme only — cream surfaces |
| `ui/src/domains/harness/PerformancePage.tsx` | Recharts palette retheme for cream (axis, tooltip, area/pie/bar colors) |
| `ui/src/domains/execution/AgentExecutionPanel.tsx` | Retheme; renders as an OutlookDrawer accordion section |
| `ui/src/domains/memory/SotbCard.tsx` | Retheme |
| `ui/src/domains/memory/FeedbackWidget.tsx` | Retheme |

### Not changed

- `server/board/deliberation/orchestrator.py`, `classifier.py`, `compaction.py`, `verification.py`, `harness_config.py`
- Any `server/members/*.md`, `server/protocols/*.md`
- `server/cli.py`, `server/board/llm.py`, `server/board/metrics.py`
- `ui/package.json`, `ui/index.html` (fonts already loaded from prior overhaul)

---

## Execution Strategy

Backend track (Tasks 1–4) is independent of frontend and can be done by one sub-agent sequentially. Frontend track (Tasks 5–21) should be sequential because `App.tsx` + `GovernancePage.tsx` edits touch shared state. Final QA (Task 22) runs after both tracks complete.

Recommended split:
- **Sub-agent A**: Tasks 1–4 (backend)
- **Sub-agent B**: Tasks 5–7 (palette + tokens + api client wiring)
- **Sub-agent C**: Tasks 8–10 (shell + icon rail + basic round table retheme)
- **Sub-agent D**: Tasks 11–17 (advanced governance: seats, holo, pips, drawers)
- **Sub-agent E**: Tasks 18–21 (missing-voice, manual-add, aux pages)
- **Sub-agent F**: Task 22 (QA)

Agents B–F depend on A only for Task 7 (frontend api client needs backend route to call). Safe to run A + B in parallel, then C/D/E sequential, then F.

---

## Task 1: Ledger — add `routing_misses` column

**Files:**
- Modify: `server/harness/ledger.py` (schema + `_ensure_columns`)
- Test: `tests/test_routing_signal_contract.py` (new file)

- [ ] **Step 1: Write the failing column-migration test**

Create `tests/test_routing_signal_contract.py`:

```python
"""Contract tests for routing signal capture (Phase A-lite)."""

import json
import sqlite3
from pathlib import Path

import pytest

from server.harness import ledger


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    return tmp_path / "routing_ledger.db"


def test_routing_misses_column_is_created(tmp_db: Path) -> None:
    """init_db must create the routing_misses TEXT column with '[]' default."""
    ledger.init_db(tmp_db)

    conn = sqlite3.connect(str(tmp_db))
    try:
        columns = {row[1]: row for row in conn.execute("PRAGMA table_info(session_outcomes)").fetchall()}
    finally:
        conn.close()

    assert "routing_misses" in columns
    # PRAGMA row: (cid, name, type, notnull, dflt_value, pk)
    assert columns["routing_misses"][2] == "TEXT"


def test_ensure_columns_is_idempotent_for_routing_misses(tmp_db: Path) -> None:
    """Calling init_db twice must not error and must not duplicate the column."""
    ledger.init_db(tmp_db)
    ledger.init_db(tmp_db)  # second call — no error

    conn = sqlite3.connect(str(tmp_db))
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(session_outcomes)").fetchall()]
    finally:
        conn.close()

    assert cols.count("routing_misses") == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/apeng/projects/solo_company_agentic_board && uv run pytest tests/test_routing_signal_contract.py -v`
Expected: FAIL — `assert "routing_misses" in columns` fails.

- [ ] **Step 3: Add the column to `_SCHEMA` and `_ensure_columns`**

Edit `server/harness/ledger.py`. In `_SCHEMA`, append one column before the closing `);`:

```python
_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_outcomes (
    ...existing columns...
    applied_review_id     TEXT,
    routing_misses        TEXT DEFAULT '[]'
);
"""
```

Actually the schema already ends with `harness_config_version INTEGER\n);`. Add `routing_misses TEXT DEFAULT '[]'` as the last column before the closing paren. Also add to `_ensure_columns` `additions` dict:

```python
additions = {
    ...existing entries...,
    "applied_review_id": "TEXT",
    "routing_misses": "TEXT",   # ← add this
}
```

The `_ensure_columns` loop handles idempotent ALTER TABLE ADD COLUMN for existing databases.

Note: SQLite `ALTER TABLE ADD COLUMN` does not apply a DEFAULT backfill to existing rows — they get NULL. Tests in later tasks must handle NULL-vs-`'[]'` gracefully.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/apeng/projects/solo_company_agentic_board && uv run pytest tests/test_routing_signal_contract.py -v`
Expected: PASS — both tests green.

- [ ] **Step 5: Run the existing ledger suite to ensure no regression**

Run: `cd /home/apeng/projects/solo_company_agentic_board && uv run pytest tests/test_harness_integration_contract.py tests/test_growth_extensions_contract.py -v`
Expected: PASS — all existing ledger tests still green.

- [ ] **Step 6: Commit**

```bash
cd /home/apeng/projects/solo_company_agentic_board
git add server/harness/ledger.py tests/test_routing_signal_contract.py
git commit -m "feat(ledger): add routing_misses column (Phase A-lite)"
```

---

## Task 2: Ledger — `record_routing_signal`

**Files:**
- Modify: `server/harness/ledger.py` (add new function + update exports)
- Test: `tests/test_routing_signal_contract.py` (extend)

- [ ] **Step 1: Append failing tests for `record_routing_signal`**

Add to the bottom of `tests/test_routing_signal_contract.py`:

```python
def test_record_routing_signal_appends_entry(tmp_db: Path, monkeypatch) -> None:
    """record_routing_signal appends to routing_misses JSON array."""
    ledger.init_db(tmp_db)

    # Seed a session row so the UPDATE has a target
    conn = sqlite3.connect(str(tmp_db))
    try:
        conn.execute(
            "INSERT INTO session_outcomes (session_id, timestamp) VALUES (?, ?)",
            ("board_1", "2026-04-21T14:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()

    ledger.record_routing_signal(
        "board_1",
        "critic",
        "missing_voice_flag",
        db_path=tmp_db,
    )

    conn = sqlite3.connect(str(tmp_db))
    try:
        row = conn.execute(
            "SELECT routing_misses FROM session_outcomes WHERE session_id = ?",
            ("board_1",),
        ).fetchone()
    finally:
        conn.close()

    parsed = json.loads(row[0])
    assert len(parsed) == 1
    entry = parsed[0]
    assert entry["member_id"] == "critic"
    assert entry["source"] == "missing_voice_flag"
    assert "ts" in entry and entry["ts"].endswith("Z")


def test_record_routing_signal_preserves_existing_entries(tmp_db: Path) -> None:
    """Multiple calls for the same session must append, not overwrite."""
    ledger.init_db(tmp_db)
    conn = sqlite3.connect(str(tmp_db))
    try:
        conn.execute(
            "INSERT INTO session_outcomes (session_id, timestamp, routing_misses) VALUES (?, ?, ?)",
            ("board_2", "2026-04-21T14:00:00Z", "[]"),
        )
        conn.commit()
    finally:
        conn.close()

    ledger.record_routing_signal("board_2", "architect", "manual_add", db_path=tmp_db)
    ledger.record_routing_signal("board_2", "critic", "missing_voice_flag", db_path=tmp_db)

    conn = sqlite3.connect(str(tmp_db))
    try:
        row = conn.execute(
            "SELECT routing_misses FROM session_outcomes WHERE session_id = ?",
            ("board_2",),
        ).fetchone()
    finally:
        conn.close()

    parsed = json.loads(row[0])
    assert len(parsed) == 2
    assert parsed[0]["member_id"] == "architect"
    assert parsed[1]["member_id"] == "critic"


def test_record_routing_signal_raises_on_missing_session(tmp_db: Path) -> None:
    """Unknown session_id must raise LedgerError."""
    ledger.init_db(tmp_db)

    with pytest.raises(ledger.LedgerError):
        ledger.record_routing_signal("board_nope", "critic", "manual_add", db_path=tmp_db)


def test_record_routing_signal_handles_null_column(tmp_db: Path) -> None:
    """Rows created before the column existed have NULL routing_misses; function must treat as empty."""
    ledger.init_db(tmp_db)
    conn = sqlite3.connect(str(tmp_db))
    try:
        # Simulate an existing pre-migration row by explicitly setting NULL
        conn.execute(
            "INSERT INTO session_outcomes (session_id, timestamp, routing_misses) VALUES (?, ?, NULL)",
            ("board_legacy", "2026-04-20T10:00:00Z"),
        )
        conn.commit()
    finally:
        conn.close()

    ledger.record_routing_signal("board_legacy", "critic", "manual_add", db_path=tmp_db)

    conn = sqlite3.connect(str(tmp_db))
    try:
        row = conn.execute(
            "SELECT routing_misses FROM session_outcomes WHERE session_id = ?",
            ("board_legacy",),
        ).fetchone()
    finally:
        conn.close()

    parsed = json.loads(row[0])
    assert len(parsed) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/apeng/projects/solo_company_agentic_board && uv run pytest tests/test_routing_signal_contract.py -v`
Expected: 4 new tests FAIL with `AttributeError: module 'server.harness.ledger' has no attribute 'record_routing_signal'`.

- [ ] **Step 3: Implement `record_routing_signal`**

Append to `server/harness/ledger.py` (near other public functions, e.g., after `record_feedback`):

```python
def record_routing_signal(
    session_id: str,
    member_id: str,
    source: str,
    db_path: Path | None = None,
) -> None:
    """Append a routing-signal entry to the session's routing_misses column.

    source: 'manual_add' or 'missing_voice_flag'.
    Raises LedgerError if session_id not found.
    """
    if source not in ("manual_add", "missing_voice_flag"):
        raise LedgerError(f"invalid source: {source!r}")

    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT routing_misses FROM session_outcomes WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise LedgerError(f"session_id not found: {session_id}")

        current_raw = row["routing_misses"]
        current = json.loads(current_raw) if current_raw else []
        entry = {
            "member_id": member_id,
            "source": source,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        current.append(entry)

        conn.execute(
            "UPDATE session_outcomes SET routing_misses = ? WHERE session_id = ?",
            (json.dumps(current), session_id),
        )
        conn.commit()
    finally:
        conn.close()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/apeng/projects/solo_company_agentic_board && uv run pytest tests/test_routing_signal_contract.py -v`
Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/apeng/projects/solo_company_agentic_board
git add server/harness/ledger.py tests/test_routing_signal_contract.py
git commit -m "feat(ledger): add record_routing_signal for Phase A-lite signal capture"
```

---

## Task 3: API — Pydantic request schema

**Files:**
- Modify: `server/api/schemas.py`

- [ ] **Step 1: Add the schema**

Append to `server/api/schemas.py` (near `FeedbackRequest` at line 52):

```python
class RoutingSignalRequest(BaseModel):
    member_id: str
    source: Literal["manual_add", "missing_voice_flag"]
```

`Literal` is already imported at the top of `schemas.py` (verify with `head -5 server/api/schemas.py` if unsure; if missing, add `from typing import Literal`).

- [ ] **Step 2: Verify module loads cleanly**

Run: `cd /home/apeng/projects/solo_company_agentic_board && uv run python -c "from server.api.schemas import RoutingSignalRequest; print(RoutingSignalRequest.model_fields.keys())"`
Expected output: `dict_keys(['member_id', 'source'])`

- [ ] **Step 3: Commit**

```bash
cd /home/apeng/projects/solo_company_agentic_board
git add server/api/schemas.py
git commit -m "feat(api): add RoutingSignalRequest schema"
```

---

## Task 4: API — `POST /sessions/{session_id}/routing-signal`

**Files:**
- Modify: `server/api/routes/board.py`
- Test: `tests/test_routing_signal_contract.py` (extend)

- [ ] **Step 1: Append failing API route tests**

Add to `tests/test_routing_signal_contract.py`:

```python
from fastapi.testclient import TestClient


@pytest.fixture
def test_client(tmp_path: Path, monkeypatch) -> TestClient:
    """Build a FastAPI test client with ledger state pointed at tmp_path."""
    db = tmp_path / "routing_ledger.db"
    ledger.init_db(db)

    # Seed a known session
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(
            "INSERT INTO session_outcomes (session_id, timestamp, routing_misses) VALUES (?, ?, ?)",
            ("board_10", "2026-04-21T10:00:00Z", "[]"),
        )
        conn.commit()
    finally:
        conn.close()

    from server.api import state as api_state
    monkeypatch.setattr(api_state, "_FEEDBACK_DB_PATH", db)
    # If there's a separate _ROUTING_SIGNAL_DB_PATH attribute, patch it too; otherwise
    # routing-signal route should reuse _FEEDBACK_DB_PATH.

    from server.api import create_app
    app = create_app()
    return TestClient(app)


def test_routing_signal_endpoint_records_success(test_client: TestClient) -> None:
    response = test_client.post(
        "/sessions/board_10/routing-signal",
        json={"member_id": "critic", "source": "missing_voice_flag"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "recorded"
    assert body["session_id"] == "board_10"
    assert body["member_id"] == "critic"


def test_routing_signal_endpoint_rejects_bad_source(test_client: TestClient) -> None:
    response = test_client.post(
        "/sessions/board_10/routing-signal",
        json={"member_id": "critic", "source": "bogus"},
    )
    assert response.status_code == 422


def test_routing_signal_endpoint_rejects_unknown_session(test_client: TestClient) -> None:
    response = test_client.post(
        "/sessions/board_999/routing-signal",
        json={"member_id": "critic", "source": "manual_add"},
    )
    assert response.status_code == 404


def test_routing_signal_endpoint_rejects_invalid_session_id_format(test_client: TestClient) -> None:
    response = test_client.post(
        "/sessions/../etc/passwd/routing-signal",
        json={"member_id": "critic", "source": "manual_add"},
    )
    assert response.status_code in (400, 422)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/apeng/projects/solo_company_agentic_board && uv run pytest tests/test_routing_signal_contract.py -v`
Expected: 4 new tests FAIL with 404 (route not defined).

- [ ] **Step 3: Implement the route**

Edit `server/api/routes/board.py`. Near line 306 (where `/feedback` is defined), add AFTER the `/feedback` handler but BEFORE the greedy `/sessions/{session_id:path}` base route:

```python
@router.post("/sessions/{session_id:path}/routing-signal")
async def routing_signal(
    session_id: str = Path(..., description="Board session id matching ^board_\\d+$"),
    req: RoutingSignalRequest = ...,  # type: ignore[assignment]
):
    _validate_session_id(session_id)

    # Verify member_id is a known roster ID
    if req.member_id not in BOARD_MEMBERS:
        raise HTTPException(422, detail=f"unknown member_id: {req.member_id}")

    try:
        record_routing_signal(
            session_id,
            req.member_id,
            req.source,
            db_path=state._FEEDBACK_DB_PATH,
        )
    except LedgerError as exc:
        msg = str(exc)
        if "not found" in msg:
            raise HTTPException(404, detail="session not found") from exc
        raise HTTPException(422, detail=msg) from exc

    return {
        "status": "recorded",
        "session_id": session_id,
        "member_id": req.member_id,
        "source": req.source,
    }
```

Also update the imports at the top of the file:

```python
from server.harness.ledger import LedgerError, record_feedback, record_routing_signal
```

And extend the schemas import:

```python
from ..schemas import (
    FeedbackRequest,
    MemberInfo,
    QueryRequest,
    RoleGapReviewRequest,
    RoutingSignalRequest,
)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/apeng/projects/solo_company_agentic_board && uv run pytest tests/test_routing_signal_contract.py -v`
Expected: all 10 tests PASS.

- [ ] **Step 5: Regression — full backend suite**

Run: `cd /home/apeng/projects/solo_company_agentic_board && uv run pytest tests/ -x --ignore=tests/__pycache__`
Expected: no regressions. If any existing test fails, investigate (likely an import or state injection issue).

- [ ] **Step 6: Commit**

```bash
cd /home/apeng/projects/solo_company_agentic_board
git add server/api/routes/board.py tests/test_routing_signal_contract.py
git commit -m "feat(api): add POST /sessions/{id}/routing-signal route"
```

---

## Task 5: Frontend — palette swap (`@theme` cream tokens)

**Files:**
- Modify: `ui/src/index.css`

- [ ] **Step 1: Rewrite the `@theme` block**

Edit `ui/src/index.css`. Replace the existing `@theme` block (obsidian palette) with:

```css
@theme {
  /* Surfaces — cream editorial */
  --color-background:                #FAF7F2;
  --color-surface:                   #FAF7F2;
  --color-surface-dim:               #FAF7F2;
  --color-surface-bright:            #FFFFFF;
  --color-surface-container-lowest:  #FFFFFF;
  --color-surface-container-low:     #F4EFE6;
  --color-surface-container:         #EFE8DB;
  --color-surface-container-high:    #E8DFCC;
  --color-surface-container-highest: #DDD2BA;
  --color-surface-variant:           #DDD2BA;

  /* Text */
  --color-on-surface:                #1A1614;
  --color-on-surface-variant:        #5C5348;
  --color-on-background:             #1A1614;

  /* Primary — brass / gold */
  --color-primary:                   #B8860B;
  --color-primary-container:         #8C6608;
  --color-primary-fixed-dim:         #A87C3E;
  --color-primary-fixed:             #C9A04C;
  --color-on-primary:                #FFFFFF;
  --color-on-primary-container:      #FFFFFF;
  --color-on-primary-fixed:          #1A1614;
  --color-on-primary-fixed-variant:  #5E4200;

  /* Secondary — navy (active / interactive) */
  --color-secondary:                 #1E3A5F;
  --color-secondary-container:       #1E3A5F;
  --color-secondary-fixed:           #D8E2FF;
  --color-secondary-fixed-dim:       #4A6B8E;
  --color-on-secondary:              #FFFFFF;
  --color-on-secondary-container:    #FFFFFF;
  --color-on-secondary-fixed:        #001A42;
  --color-on-secondary-fixed-variant:#004395;

  /* Tertiary — neutral accents (rare) */
  --color-tertiary:                  #5C5348;
  --color-tertiary-container:        #C9BFAE;
  --color-tertiary-fixed:            #E2E2EC;
  --color-tertiary-fixed-dim:        #C5C6CF;
  --color-on-tertiary:               #FFFFFF;
  --color-on-tertiary-container:     #1A1614;
  --color-on-tertiary-fixed:         #191B22;
  --color-on-tertiary-fixed-variant: #45464E;

  /* Error — burgundy */
  --color-error:                     #9B2C2C;
  --color-error-container:           #FCE8E6;
  --color-on-error:                  #FFFFFF;
  --color-on-error-container:        #4A1212;

  /* Outline — soft warm */
  --color-outline:                   #9E8F78;
  --color-outline-variant:           #C9BFAE;
  --color-inverse-surface:           #1A1614;
  --color-inverse-on-surface:        #FAF7F2;
  --color-inverse-primary:           #FFDCA1;
  --color-surface-tint:              #B8860B;

  /* Fonts (unchanged from obsidian) */
  --font-headline: 'Noto Serif', serif;
  --font-body:     'Manrope', sans-serif;
  --font-label:    'Manrope', sans-serif;

  /* Radii (unchanged) */
  --radius:      0.125rem;
  --radius-lg:   0.25rem;
  --radius-xl:   0.5rem;
  --radius-full: 0.75rem;
}
```

- [ ] **Step 2: Update global body + headings**

Below the `@theme` block (or in a `@layer base`):

```css
@layer base {
  body {
    background-color: var(--color-background);
    color: var(--color-on-surface);
    font-family: 'Manrope', sans-serif;
  }
  h1, h2, h3, h4, h5, h6, .font-headline {
    font-family: 'Noto Serif', serif;
  }
}
```

If these rules already exist, verify values are present and correct — do not duplicate.

- [ ] **Step 3: Run a type-check + build**

Run: `cd /home/apeng/projects/solo_company_agentic_board/ui && npm run check`
Expected: PASS. CSS tokens are strings and tsc doesn't validate them, so this step is a sanity check that no import broke.

- [ ] **Step 4: Manual smoke**

Run dev server: `cd /home/apeng/projects/solo_company_agentic_board/ui && npm run dev`
Open `http://127.0.0.1:8000` in Chrome (or whichever port Vite reports).
Expected: background is cream `#FAF7F2`, text is dark ink. Will look visually broken in many places (cards, buttons still have dark-tuned opacities) — that's fine, later tasks fix them.

Kill dev server when done.

- [ ] **Step 5: Commit**

```bash
cd /home/apeng/projects/solo_company_agentic_board
git add ui/src/index.css
git commit -m "feat(ui): swap @theme palette to cream editorial"
```

---

## Task 6: Frontend — retune custom utilities for cream

**Files:**
- Modify: `ui/src/index.css`

- [ ] **Step 1: Update `.speaking-halo`**

Replace the existing `.speaking-halo` block (the gold pulsing halo used around speaking members). New CSS:

```css
.speaking-halo {
  position: absolute;
  inset: -14px;
  border-radius: 9999px;
  background: radial-gradient(
    circle,
    rgba(184, 134, 11, 0.28) 0%,
    rgba(184, 134, 11, 0.12) 45%,
    rgba(184, 134, 11, 0) 80%
  );
  animation: speaking-pulse 1.4s ease-in-out infinite;
  pointer-events: none;
  z-index: 0;
}
```

Keep the existing `@keyframes speaking-pulse` rule as-is (only the color stops change). If the keyframes were tuned for dark, tweak scale/opacity values to remain visible on cream:

```css
@keyframes speaking-pulse {
  0%, 100% { transform: scale(0.92); opacity: 0.55; }
  50%      { transform: scale(1.12); opacity: 0.95; }
}
```

- [ ] **Step 2: Update `.glass-panel`**

```css
.glass-panel {
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  box-shadow:
    inset 1px 1px 0 rgba(255, 255, 255, 0.9),
    0 8px 32px rgba(26, 22, 20, 0.08);
}
```

- [ ] **Step 3: Update `.metallic-gradient`**

```css
.metallic-gradient {
  background: linear-gradient(135deg, #B8860B 0%, #8C6608 100%);
  color: #FFFFFF;
}
```

- [ ] **Step 4: Update `.accent-bar-left`**

```css
.accent-bar-left {
  border-left: 2px solid var(--color-secondary-container);
}
```

(Navy for active/selected states on cream.)

- [ ] **Step 5: Update `.prose-lite`**

Find the existing `.prose-lite` block. Replace body, link, and code color rules:

```css
.prose-lite {
  color: var(--color-on-surface);
  font-family: 'Manrope', sans-serif;
  line-height: 1.6;
}
.prose-lite h1, .prose-lite h2, .prose-lite h3 {
  font-family: 'Noto Serif', serif;
  color: var(--color-on-surface);
  font-weight: 700;
}
.prose-lite a {
  color: var(--color-primary);
  text-decoration: underline;
  text-underline-offset: 2px;
}
.prose-lite code {
  background: var(--color-surface-container-low);
  color: var(--color-on-surface);
  padding: 0.1em 0.35em;
  border-radius: 0.25rem;
  font-size: 0.9em;
}
.prose-lite pre {
  background: var(--color-surface-container-low);
  color: var(--color-on-surface);
  padding: 0.75rem 1rem;
  border-radius: 0.5rem;
  overflow-x: auto;
}
.prose-lite blockquote {
  border-left: 2px solid var(--color-secondary-container);
  color: var(--color-on-surface-variant);
  padding-left: 0.75rem;
  margin: 0.5rem 0;
  font-style: italic;
}
```

- [ ] **Step 6: Verify `.board-orbit` geometry untouched**

Grep for `.board-orbit` in `ui/src/index.css`. The rule should define `--orbit-radius` CSS custom property and positioning math only. Do NOT change. If any color was inside it (e.g., background tint), replace with cream-equivalent (`var(--color-surface-container-low)`) but preserve the polar math.

- [ ] **Step 7: Build check**

Run: `cd /home/apeng/projects/solo_company_agentic_board/ui && npm run check`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
cd /home/apeng/projects/solo_company_agentic_board
git add ui/src/index.css
git commit -m "feat(ui): retune utilities (halo, glass, gradient, accent-bar, prose) for cream"
```

---

## Task 7: Frontend — `recordRoutingSignal` API client + buffering helper

**Files:**
- Modify: `ui/src/shared/api.ts`

- [ ] **Step 1: Read current `api.ts` to see base URL convention**

Run: `cd /home/apeng/projects/solo_company_agentic_board && head -30 ui/src/shared/api.ts`
Note the pattern used for `fetch` calls (e.g., relative `/sessions/...` or an API base constant).

- [ ] **Step 2: Append `recordRoutingSignal` and buffering helpers**

Add to the end of `ui/src/shared/api.ts`:

```typescript
// ─── Routing signal (Phase A-lite) ─────────────────────────────────────────

export type RoutingSignalSource = "manual_add" | "missing_voice_flag";

export async function recordRoutingSignal(
  sessionId: string,
  memberId: string,
  source: RoutingSignalSource,
): Promise<void> {
  const res = await fetch(`/sessions/${sessionId}/routing-signal`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ member_id: memberId, source }),
  });
  if (!res.ok) {
    // Best-effort — do not throw; caller continues UI state transitions.
    // eslint-disable-next-line no-console
    console.warn(`routing-signal failed: ${res.status}`);
  }
}

/**
 * Buffer for routing signals that occur before the session is ledger-persisted.
 * Flush via flushRoutingSignalBuffer() when the session reaches T6 completion.
 */
type BufferedSignal = { memberId: string; source: RoutingSignalSource; ts: string };
const routingSignalBuffer: Map<string, BufferedSignal[]> = new Map();

export function bufferRoutingSignal(
  sessionId: string,
  memberId: string,
  source: RoutingSignalSource,
): void {
  const list = routingSignalBuffer.get(sessionId) ?? [];
  list.push({ memberId, source, ts: new Date().toISOString() });
  routingSignalBuffer.set(sessionId, list);
}

export async function flushRoutingSignalBuffer(sessionId: string): Promise<void> {
  const list = routingSignalBuffer.get(sessionId);
  if (!list || list.length === 0) return;
  await Promise.all(
    list.map((sig) => recordRoutingSignal(sessionId, sig.memberId, sig.source)),
  );
  routingSignalBuffer.delete(sessionId);
}

export function dropRoutingSignalBuffer(sessionId: string): void {
  routingSignalBuffer.delete(sessionId);
}
```

- [ ] **Step 3: Build check**

Run: `cd /home/apeng/projects/solo_company_agentic_board/ui && npm run check`
Expected: PASS — no TS errors.

- [ ] **Step 4: Commit**

```bash
cd /home/apeng/projects/solo_company_agentic_board
git add ui/src/shared/api.ts
git commit -m "feat(ui): add recordRoutingSignal + buffering helpers"
```

---

## Task 8: Frontend — MEMBER_TONES recalibration for cream

**Files:**
- Modify: `ui/src/shared/presentation.tsx`

- [ ] **Step 1: Replace the MEMBER_TONES map**

Find `export const MEMBER_TONES` (around line 46 per earlier exploration). Replace the dark-theme hex values with cream-legible jewel tones. Color selection rationale: on cream `#FAF7F2`, these all test ≥ 4.5:1 contrast for icon/ring use and ≥ 3:1 for small decorative chips.

```typescript
export const MEMBER_TONES: Record<string, string> = {
  chairperson:  "#8C6608",  // deep brass
  strategist:   "#1E3A5F",  // navy
  product:      "#6B21A8",  // deep violet
  researcher:   "#047857",  // forest green
  critic:       "#9B2C2C",  // burgundy
  architect:    "#B45309",  // burnt amber
  builder:      "#9D174D",  // deep fuchsia
  // Shelved (not currently loaded but preserve for type-stability):
  guardian:     "#1F2937",  // slate
  operator:     "#78350F",  // dark umber
};
```

- [ ] **Step 2: Retint `taskStatusClass`**

Find `export function taskStatusClass` (around line 293). Replace body:

```typescript
export function taskStatusClass(status: DelegatedTask['status']): string {
  switch (status) {
    case "proposed":
      return "bg-surface-container-high text-on-surface-variant";
    case "approved":
      return "bg-secondary-container/10 text-secondary-container";
    case "running":
      return "bg-primary/15 text-primary-container";
    case "completed":
      return "bg-surface-container-high text-primary-container";
    case "blocked":
      return "bg-error-container text-error";
    case "rejected":
      return "bg-error-container text-error";
    default:
      return "bg-surface-container-high text-on-surface-variant";
  }
}
```

Note: we retain the `rejected` key (per prior implementation) — do not add `failed` to this switch, as it's not in the `DelegatedTask['status']` union.

- [ ] **Step 3: Confirm memberTone() fallback color**

Locate `export function memberTone(id: string)` (around line 289). Verify the fallback returns `#8C6608` (deep brass) or similar cream-compatible color. If it returns a dark-theme default, change:

```typescript
export function memberTone(id: string): string {
  return MEMBER_TONES[id] || "#8C6608";
}
```

- [ ] **Step 4: Build check**

Run: `cd /home/apeng/projects/solo_company_agentic_board/ui && npm run check`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/apeng/projects/solo_company_agentic_board
git add ui/src/shared/presentation.tsx
git commit -m "feat(ui): recalibrate MEMBER_TONES + taskStatusClass for cream"
```

---

## Task 9: Frontend — `App.tsx` icon rail replaces side nav + top bar

**Files:**
- Modify: `ui/src/App.tsx`

- [ ] **Step 1: Read the current App.tsx shell**

Run: `cd /home/apeng/projects/solo_company_agentic_board && cat ui/src/App.tsx | head -80`
Look for the `SideNav` and `TopBar` components (added by prior obsidian overhaul). Identify the tab-state hook (likely `useState<TabId>`).

- [ ] **Step 2: Replace the shell layout**

Inside `App.tsx`, replace the `SideNav` component body with an `IconRail` component. Replace the `TopBar` with nothing (removed). Preserve the tab-state hook.

Representative code for the new `IconRail` (replace the existing nav/topbar JSX blocks with this):

```tsx
import {
  BookOpen,
  Building2,
  Landmark,
  LogIn,
  Settings,
  ShieldCheck,
  Users,
} from "lucide-react";

type TabId = "portfolio" | "governance" | "compliance";

function IconRail({
  active,
  onSelect,
  expanded,
  onToggleExpand,
}: {
  active: TabId;
  onSelect: (tab: TabId) => void;
  expanded: boolean;
  onToggleExpand: () => void;
}) {
  const rows: Array<{ id: TabId; label: string; icon: React.ElementType }> = [
    { id: "portfolio", label: "Portfolio", icon: Users },
    { id: "governance", label: "Governance", icon: Landmark },
    { id: "compliance", label: "Compliance", icon: ShieldCheck },
  ];

  return (
    <nav
      className={`fixed left-0 top-0 h-screen z-40 flex flex-col py-4 transition-[width] duration-200 bg-surface-container-low ${
        expanded ? "w-[240px]" : "w-[72px]"
      }`}
      aria-label="Primary"
    >
      <button
        onClick={onToggleExpand}
        className="flex items-center gap-3 px-4 py-3 hover:bg-surface-container-high transition-colors"
        aria-label="Toggle navigation width"
      >
        <div className="w-10 h-10 flex items-center justify-center font-headline text-lg font-bold text-primary-container italic">
          EA
        </div>
        {expanded && (
          <span className="font-headline italic text-lg text-on-surface">
            The Executive Atelier
          </span>
        )}
      </button>

      <ul className="flex flex-col gap-1 mt-6 px-2">
        {rows.map(({ id, label, icon: Icon }) => {
          const isActive = id === active;
          return (
            <li key={id}>
              <button
                onClick={() => onSelect(id)}
                aria-current={isActive ? "page" : undefined}
                className={`w-full flex items-center gap-3 px-3 py-3 rounded-lg transition-colors ${
                  isActive
                    ? "accent-bar-left bg-surface-container-high text-on-surface"
                    : "text-on-surface-variant/60 hover:bg-surface-container-low hover:text-on-surface"
                }`}
                title={expanded ? undefined : label}
              >
                <Icon className="w-5 h-5 shrink-0" />
                {expanded && <span className="font-body text-sm">{label}</span>}
              </button>
            </li>
          );
        })}
      </ul>

      <div className="mt-auto px-2 pb-2 flex flex-col gap-1">
        <button
          className="w-full flex items-center gap-3 px-3 py-3 rounded-lg text-on-surface-variant/60 hover:bg-surface-container-low hover:text-on-surface"
          title={expanded ? undefined : "Settings"}
        >
          <Settings className="w-5 h-5 shrink-0" />
          {expanded && <span className="font-body text-sm">Settings</span>}
        </button>
        <button
          className="w-full flex items-center gap-3 px-3 py-3 rounded-lg text-on-surface-variant/60 hover:bg-surface-container-low hover:text-on-surface"
          title={expanded ? undefined : "Account"}
        >
          <LogIn className="w-5 h-5 shrink-0" />
          {expanded && <span className="font-body text-sm">Account</span>}
        </button>
      </div>
    </nav>
  );
}
```

Wire the rail width into the main content offset. Replace the main content wrapper to use a dynamic left margin:

```tsx
const [railExpanded, setRailExpanded] = useState(() => {
  try {
    return localStorage.getItem("boardroom.railExpanded") === "1";
  } catch {
    return false;
  }
});

useEffect(() => {
  try {
    localStorage.setItem("boardroom.railExpanded", railExpanded ? "1" : "0");
  } catch { /* ignore quota */ }
}, [railExpanded]);

// Inside the top-level JSX:
<div className="min-h-screen bg-background text-on-surface flex">
  <IconRail
    active={activeTab}
    onSelect={setActiveTab}
    expanded={railExpanded}
    onToggleExpand={() => setRailExpanded(v => !v)}
  />
  <main
    className="flex-1 min-h-screen"
    style={{ marginLeft: railExpanded ? 240 : 72 }}
  >
    {/* ...existing route-switch JSX (PortfolioPage / GovernancePage / PerformancePage)... */}
  </main>
</div>
```

Delete the previous `TopBar` JSX entirely. If a session chip was rendered there, relocate it into the right-hand side of the icon rail (bottom section, above settings) or into the page itself — not into a floating top bar.

- [ ] **Step 3: Verify existing tab state + callbacks still wired**

The existing state hook (`useState<TabId>`) and any toggle callbacks (`toggleManualMember`, etc.) must still be passed into their consumers. Do not delete them. Simply change the shell — page content is unchanged.

- [ ] **Step 4: Build check**

Run: `cd /home/apeng/projects/solo_company_agentic_board/ui && npm run check`
Expected: PASS. If missing lucide icon imports cause errors, add them to the import list.

- [ ] **Step 5: Manual smoke**

Run dev server: `cd /home/apeng/projects/solo_company_agentic_board/ui && npm run dev`
Open in Chrome.
Expected: 72px rail on left, three tab icons, expand toggle works, no top bar. Main content shifts correctly.

- [ ] **Step 6: Commit**

```bash
cd /home/apeng/projects/solo_company_agentic_board
git add ui/src/App.tsx
git commit -m "feat(ui): replace side nav + top bar with 72px icon rail"
```

---

## Task 10: Frontend — `GovernancePage` round table cream restyle + remove top CEO avatar

**Files:**
- Modify: `ui/src/domains/board/GovernancePage.tsx`

- [ ] **Step 1: Locate the `RoundTable` component**

Grep: `Grep "function RoundTable|const RoundTable" ui/src/domains/board/GovernancePage.tsx`
Note the JSX block that renders the orbit, the center holo card, the bottom CEO chair, and the seat list.

- [ ] **Step 2: Restyle the table surface for cream**

Inside the `RoundTable` JSX, find the outer circle div (currently `bg-gradient-to-b from-surface-container-lowest to-surface-container-low`) and replace colors to match cream palette:

```tsx
<div
  className="w-full h-full rounded-[100%] relative overflow-hidden"
  style={{
    background:
      "radial-gradient(ellipse at center, #F4EFE6 0%, #E8DFCC 60%, #DDD2BA 100%)",
    boxShadow: "0 20px 60px -20px rgba(184, 134, 11, 0.25)",
  }}
>
  {/* Texture overlay (reuse existing council-table-texture import) */}
  <div
    aria-hidden
    className="absolute inset-0 opacity-[0.12]"
    style={{
      backgroundImage: `url(${councilTableTexture})`,
      backgroundSize: "cover",
      mixBlendMode: "multiply",
    }}
  />
  {/* Ambient gold glow */}
  <div
    aria-hidden
    className="absolute w-3/4 h-3/4 rounded-full"
    style={{
      background: "rgba(184, 134, 11, 0.05)",
      filter: "blur(100px)",
      top: "12.5%",
      left: "12.5%",
    }}
  />
  {/* ...holo card + seats render absolutely on top... */}
</div>
```

- [ ] **Step 3: Remove the top-of-table CEO avatar**

Inside the `RoundTable` JSX, find the JSX block that renders a seat at the top polar position labelled "CEO" (or a similar placeholder avatar labelled with a CEO tag). It is distinct from the seats derived from `session.relevantMembers` / `stageEvents`. It may be hardcoded at polar angle `-90` or named `CeoTopAvatar` / inline at the top of the orbit.

Delete that entire JSX block. Only the bottom CEO chair icon remains as the user's seat metaphor.

**Safety check:** do NOT delete any dynamic seat rendered from the seats array (loop over members). The deletion target is the hardcoded decorative top placeholder only.

- [ ] **Step 4: Update holo card center tile for cream**

Find the center holo card JSX. Apply `.glass-panel` utility (now cream-tuned) and replace any dark backgrounds:

```tsx
<div className="absolute z-10 w-72 h-36 glass-panel rounded-xl flex flex-col items-center justify-center">
  {/* ...existing state-dependent content (waveform icon, query quote, drafting label, verified check)... */}
</div>
```

- [ ] **Step 5: Build check**

Run: `cd /home/apeng/projects/solo_company_agentic_board/ui && npm run check`
Expected: PASS.

- [ ] **Step 6: Manual smoke**

Dev server + open browser. Navigate to Governance. Expected: cream table, no top CEO avatar, holo card centered with glass effect.

- [ ] **Step 7: Commit**

```bash
cd /home/apeng/projects/solo_company_agentic_board
git add ui/src/domains/board/GovernancePage.tsx
git commit -m "feat(ui): cream round table + remove duplicate top CEO avatar"
```

---

## Task 11: Frontend — idle state (empty table) + roster add button

**Files:**
- Modify: `ui/src/domains/board/GovernancePage.tsx`

- [ ] **Step 1: Gate seat rendering on session-active state**

In `RoundTable` (or wherever seats are mapped), wrap the seat mapping to render zero seats when the session has not yet started:

```tsx
const sessionActive =
  session !== null ||
  stageEvents.length > 0 ||
  Object.values(seatStates).some(s => s.status !== "idle");

const visibleSeats = sessionActive ? seatsForRender : [];
```

Or whatever wiring matches the existing state. Key invariant: at launch before a question is submitted, `visibleSeats` is empty and no avatars render around the orbit.

The bottom CEO chair icon + holo card default state ("Awaiting board question") still render at idle.

- [ ] **Step 2: Replace the old "roster chip strip" with a compact `+ Add members` button**

Locate the horizontal roster chip strip (used in prior iterations to toggle manual members below composer). Replace with a single compact button that expands the strip on click. If the strip already has collapse/expand behavior, verify it starts collapsed at idle.

```tsx
const [rosterOpen, setRosterOpen] = useState(false);

{/* Below composer */}
<div className="flex flex-col items-center gap-3 mt-4">
  {!rosterOpen && (
    <button
      type="button"
      onClick={() => setRosterOpen(true)}
      className="font-body text-sm text-on-surface-variant hover:text-primary-container transition-colors flex items-center gap-1"
    >
      <Plus className="w-4 h-4" />
      Add members
    </button>
  )}
  {rosterOpen && (
    <MemberRosterPicker
      members={allMembers}
      manualMemberIds={manualMemberIds}
      toggleManualMember={toggleManualMember}
      onClose={() => setRosterOpen(false)}
    />
  )}
</div>
```

If `MemberRosterPicker` already exists from the prior iteration, keep using it; just wrap in collapse state.

- [ ] **Step 3: Build check**

Run: `cd /home/apeng/projects/solo_company_agentic_board/ui && npm run check`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/apeng/projects/solo_company_agentic_board
git add ui/src/domains/board/GovernancePage.tsx
git commit -m "feat(ui): empty round table at idle + collapsed roster add button"
```

---

## Task 12: Frontend — stage-gated seat arrival animation

**Files:**
- Modify: `ui/src/domains/board/GovernancePage.tsx`

- [ ] **Step 1: Wrap seat mapping in `AnimatePresence`**

Import from motion (already in package.json):

```tsx
import { AnimatePresence, motion } from "motion/react";
```

(Note: this project uses `motion` package, not `framer-motion`. Import from `motion/react`.)

Replace the seat mapping with a keyed, animated list:

```tsx
<AnimatePresence>
  {visibleSeats.map((seat, idx) => (
    <motion.div
      key={seat.memberId}
      initial={{ opacity: 0, scale: 0.6 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.6 }}
      transition={{ duration: 0.22, delay: idx * 0.12, ease: "easeOut" }}
      className="absolute"
      style={{
        left: `calc(50% + var(--orbit-radius) * cos(${angleForSeat(seat, idx, visibleSeats.length)}))`,
        top:  `calc(50% + var(--orbit-radius) * sin(${angleForSeat(seat, idx, visibleSeats.length)}))`,
        transform: "translate(-50%, -50%)",
      }}
    >
      <BoardAvatar seat={seat} />
    </motion.div>
  ))}
</AnimatePresence>
```

If `.board-orbit` already has the polar math in CSS (not inline), keep that and only wrap with `motion.div` + opacity/scale animation. Do not change the geometry.

- [ ] **Step 2: Build check**

Run: `cd /home/apeng/projects/solo_company_agentic_board/ui && npm run check`
Expected: PASS.

- [ ] **Step 3: Manual smoke**

Dev server, open Governance, submit a question. Expected: routed members fade in at 120ms stagger.

- [ ] **Step 4: Commit**

```bash
cd /home/apeng/projects/solo_company_agentic_board
git add ui/src/domains/board/GovernancePage.tsx
git commit -m "feat(ui): stage-gated seat arrival with motion stagger"
```

---

## Task 13: Frontend — `BoardAvatar` state states (speaking, done-shrink, failed-burgundy, manual-badge)

**Files:**
- Modify: `ui/src/domains/board/GovernancePage.tsx`

- [ ] **Step 1: Rewrite `BoardAvatar` state-driven styling**

Locate `BoardAvatar` (sub-component in `GovernancePage.tsx`). Replace the style logic to drive size/opacity/ring off `seat.status`:

```tsx
function BoardAvatar({ seat, isManualAdd, chairperson }: {
  seat: SeatState;
  isManualAdd?: boolean;
  chairperson?: boolean;
}) {
  const tone = memberTone(seat.memberId);
  const isSpeaking = seat.status === "active";
  const isDone     = seat.status === "done";
  const isFailed   = seat.status === "failed";
  const isIdle     = seat.status === "idle";

  const size = isDone || isFailed ? 48 : 64;
  const opacity = isDone ? 0.7 : isFailed ? 0.55 : 1;

  const ringClass = isSpeaking
    ? "ring-2 ring-primary ring-offset-4 ring-offset-background"
    : isFailed
    ? "ring-2 ring-error"
    : isDone
    ? "ring-2"   // tone applied inline
    : seat.status === "selected"
    ? "ring-2 ring-secondary-container ring-offset-2 ring-offset-background"
    : "";

  return (
    <div className="relative" style={{ width: size, height: size, opacity }}>
      {isSpeaking && <div className="speaking-halo" aria-hidden />}

      <img
        src={MEMBER_IMAGES[seat.memberId]}
        alt={seat.memberId}
        className={`w-full h-full rounded-full object-cover ${ringClass}`}
        style={isDone && !isFailed && !isSpeaking ? { boxShadow: `0 0 0 2px ${tone}` } : undefined}
      />

      {chairperson && isDone && (
        <div className="absolute inset-0 rounded-full ring-1 ring-primary/50 pointer-events-none" />
      )}

      {isSpeaking && (
        <div
          aria-hidden
          className="absolute -bottom-0 -right-0 w-4 h-4 bg-primary rounded-full ring-2 ring-background animate-pulse"
        />
      )}

      {isDone && !isFailed && (
        <div className="absolute -bottom-0 -right-0 w-5 h-5 bg-surface-container-lowest rounded-full ring-2 ring-background flex items-center justify-center">
          <Check className="w-3 h-3 text-primary-container" />
        </div>
      )}

      {isFailed && (
        <div className="absolute -bottom-0 -right-0 w-5 h-5 bg-error-container rounded-full ring-2 ring-background flex items-center justify-center">
          <X className="w-3 h-3 text-error" />
        </div>
      )}

      {isManualAdd && (
        <motion.div
          initial={{ opacity: 1, scale: 1 }}
          animate={{ opacity: 0, scale: 1.3 }}
          transition={{ delay: 1.5, duration: 0.5 }}
          className="absolute -top-1 -right-1 w-5 h-5 bg-secondary-container text-on-secondary rounded-full flex items-center justify-center font-body text-xs"
        >
          +
        </motion.div>
      )}

      <div className="mt-2 text-center text-xs font-body text-on-surface-variant">
        {roleLabelFor(seat.memberId)}
      </div>
    </div>
  );
}
```

Imports needed at top of file: `Check`, `X`, `Plus` from `lucide-react`.

- [ ] **Step 2: Pass `isManualAdd` + `chairperson` props from the orbit mapping**

Track which seats were manually added (local `Set<string>` in `GovernancePage`). Track which seat is `chairperson` (compare `memberId === "chairperson"`). Pass down to `BoardAvatar`.

```tsx
const [manuallyAdded, setManuallyAdded] = useState<Set<string>>(new Set());

// When the manual-add popover selects a member:
const handleManualAdd = (memberId: string) => {
  toggleManualMember(memberId);   // existing wiring
  setManuallyAdded(prev => new Set(prev).add(memberId));
  if (session?.session_id) {
    recordRoutingSignal(session.session_id, memberId, "manual_add");
  } else {
    bufferRoutingSignal(currentSessionTempId, memberId, "manual_add");
  }
};
```

- [ ] **Step 3: Build check**

Run: `cd /home/apeng/projects/solo_company_agentic_board/ui && npm run check`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/apeng/projects/solo_company_agentic_board
git add ui/src/domains/board/GovernancePage.tsx
git commit -m "feat(ui): BoardAvatar state rings (speaking/done/failed/manual)"
```

---

## Task 14: Frontend — Overflow `+N` seat for > 5 routed members

**Files:**
- Modify: `ui/src/domains/board/GovernancePage.tsx`

- [ ] **Step 1: Add a selector that caps visible seats**

Add a helper inside `GovernancePage.tsx`:

```tsx
/**
 * Choose up to `max` visible seats. Chairperson is always included.
 * Remaining slots filled by priority (highest first).
 */
function selectVisibleSeats(
  seats: SeatState[],
  members: BoardMember[],
  max: number = 5,
): { visible: SeatState[]; overflow: SeatState[] } {
  if (seats.length <= max) return { visible: seats, overflow: [] };

  const priorityMap = new Map(members.map(m => [m.id, m.priority ?? 0]));
  const chair = seats.find(s => s.memberId === "chairperson");
  const others = seats
    .filter(s => s.memberId !== "chairperson")
    .sort((a, b) =>
      (priorityMap.get(b.memberId) ?? 0) - (priorityMap.get(a.memberId) ?? 0),
    );

  const visible: SeatState[] = chair ? [chair] : [];
  const overflow: SeatState[] = [];

  for (const seat of others) {
    if (visible.length < max) visible.push(seat);
    else overflow.push(seat);
  }

  return { visible, overflow };
}
```

Wire into the seat mapping:

```tsx
const { visible, overflow } = selectVisibleSeats(allSeats, allMembers, 5);
```

- [ ] **Step 2: Render overflow "+N" pill**

Reserve one polar slot for the overflow pill when `overflow.length > 0`:

```tsx
{overflow.length > 0 && (
  <div
    className="absolute z-10"
    style={{
      left: `calc(50% + var(--orbit-radius) * cos(var(--overflow-angle)))`,
      top:  `calc(50% + var(--orbit-radius) * sin(var(--overflow-angle)))`,
      transform: "translate(-50%, -50%)",
    }}
  >
    <Popover>
      <PopoverTrigger asChild>
        <button
          className="w-12 h-12 rounded-full bg-surface-container-high hover:bg-surface-container-highest flex items-center justify-center font-headline text-sm text-on-surface"
          aria-label={`${overflow.length} more members`}
        >
          +{overflow.length}
        </button>
      </PopoverTrigger>
      <PopoverContent>
        <ul className="flex flex-col gap-1 bg-surface-container-lowest rounded-lg p-2">
          {overflow.map(seat => (
            <li key={seat.memberId}>
              <button
                onClick={() => promoteSeat(seat.memberId)}
                className="w-full flex items-center gap-2 px-2 py-2 rounded hover:bg-surface-container-low"
              >
                <img src={MEMBER_IMAGES[seat.memberId]} className="w-6 h-6 rounded-full" />
                <span className="font-body text-sm">{roleLabelFor(seat.memberId)}</span>
              </button>
            </li>
          ))}
        </ul>
      </PopoverContent>
    </Popover>
  </div>
)}
```

Since this project does not include a `Popover` primitive library, inline a lightweight one using native `<details>` + `<summary>` + absolute positioning, OR use conditional state. Example inline fallback:

```tsx
const [overflowOpen, setOverflowOpen] = useState(false);
// click handler: setOverflowOpen(v => !v); then render a <ul> conditionally with absolute positioning
```

Pick whichever matches existing patterns in `GovernancePage.tsx`.

`promoteSeat(memberId)` swaps the chosen overflow seat with the lowest-priority non-chair visible seat. Implementation:

```tsx
const [promoted, setPromoted] = useState<Set<string>>(new Set());

const promoteSeat = (memberId: string) => {
  setPromoted(prev => new Set(prev).add(memberId));
};

// Inside selectVisibleSeats, bias the ordering: promoted members sort first within their priority bucket.
```

- [ ] **Step 3: Build check**

Run: `cd /home/apeng/projects/solo_company_agentic_board/ui && npm run check`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/apeng/projects/solo_company_agentic_board
git add ui/src/domains/board/GovernancePage.tsx
git commit -m "feat(ui): overflow +N seat with priority-based selection"
```

---

## Task 15: Frontend — holo topic card state machine

**Files:**
- Modify: `ui/src/domains/board/GovernancePage.tsx`

- [ ] **Step 1: Define the holo card state selector**

```tsx
type HoloState =
  | { kind: "idle" }
  | { kind: "active"; query: string; stage: 1 | 2 | 3 | 4 }
  | { kind: "drafting"; charsStreamed: number }
  | { kind: "done"; verified: boolean };

function selectHoloState(
  session: BoardSession | null,
  stageEvents: StageEvent[],
  currentStreamChars: number,
): HoloState {
  if (!session && stageEvents.length === 0) return { kind: "idle" };
  if (session?.decision && session?.verification) {
    return { kind: "done", verified: !!session.verification.passed };
  }
  const lastStage = stageEvents[stageEvents.length - 1];
  if (lastStage?.stage === 3 && lastStage?.active) {
    return { kind: "drafting", charsStreamed: currentStreamChars };
  }
  const query = session?.user_query ?? "";
  const stage = (lastStage?.stage ?? 1) as 1 | 2 | 3 | 4;
  return { kind: "active", query, stage };
}
```

- [ ] **Step 2: Render the holo card per state**

```tsx
function HoloCard({ state }: { state: HoloState }) {
  switch (state.kind) {
    case "idle":
      return (
        <div className="glass-panel rounded-xl w-72 h-36 flex flex-col items-center justify-center gap-3">
          <AudioLines className="w-6 h-6 text-primary-container animate-pulse" />
          <p className="font-headline italic text-lg text-on-surface">
            Awaiting board question
          </p>
        </div>
      );
    case "active": {
      const truncated =
        state.query.length > 120 ? state.query.slice(0, 120) + "…" : state.query;
      return (
        <div className="glass-panel rounded-xl w-72 h-36 flex flex-col justify-between p-4">
          <blockquote className="font-headline italic text-sm text-on-surface line-clamp-2">
            “{truncated}”
          </blockquote>
          <StagePipRow current={state.stage} />
        </div>
      );
    }
    case "drafting":
      return (
        <div className="glass-panel rounded-xl w-72 h-36 flex flex-col items-center justify-center gap-2">
          <FilePen className="w-6 h-6 text-primary-container animate-pulse" />
          <p className="font-headline italic text-base text-on-surface">
            Drafting memo…
          </p>
          <p className="font-body text-xs text-on-surface-variant">
            {state.charsStreamed} characters
          </p>
        </div>
      );
    case "done":
      return (
        <div
          className={`glass-panel rounded-xl w-72 h-36 flex flex-col items-center justify-center gap-2 ${
            state.verified ? "ring-2 ring-primary/40" : "ring-2 ring-error/40"
          }`}
        >
          {state.verified ? (
            <CheckCircle className="w-6 h-6 text-primary-container" />
          ) : (
            <AlertCircle className="w-6 h-6 text-error" />
          )}
          <p className="font-headline italic text-base text-on-surface">
            Decision ready
          </p>
        </div>
      );
  }
}
```

Icons: `AudioLines`, `FilePen`, `CheckCircle`, `AlertCircle` from `lucide-react`.

- [ ] **Step 3: Build check**

Run: `cd /home/apeng/projects/solo_company_agentic_board/ui && npm run check`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/apeng/projects/solo_company_agentic_board
git add ui/src/domains/board/GovernancePage.tsx
git commit -m "feat(ui): holo topic card state machine (idle/active/drafting/done)"
```

---

## Task 16: Frontend — `StagePipRow` component (4-stage rail)

**Files:**
- Modify: `ui/src/domains/board/GovernancePage.tsx`

- [ ] **Step 1: Add StagePipRow component**

```tsx
const STAGE_PIPS = [
  { id: 1 as const, label: "Independent" },
  { id: 2 as const, label: "Peer review" },
  { id: 3 as const, label: "Synthesis"   },
  { id: 4 as const, label: "Verify"      },
];

function StagePipRow({
  current,
  verified,
}: {
  current: 1 | 2 | 3 | 4;
  verified?: boolean;
}) {
  return (
    <div className="flex items-center gap-4">
      {STAGE_PIPS.map(({ id, label }) => {
        const isDone = id < current;
        const isActive = id === current;
        const isVerifyStage = id === 4;
        const dotClass = isActive
          ? "bg-primary animate-pulse"
          : isDone
          ? isVerifyStage && verified !== undefined
            ? verified ? "bg-primary" : "bg-error"
            : "bg-secondary-container"
          : "bg-surface-container-highest";
        return (
          <div key={id} className="flex flex-col items-center gap-1">
            <div className={`w-2.5 h-2.5 rounded-full ${dotClass}`} />
            <span className="font-body text-[10px] text-on-surface-variant/70">
              {label}
            </span>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Render StagePipRow above the composer textarea**

Inside the composer section, above the textarea wrapper:

```tsx
<div className="flex justify-center mb-3">
  <StagePipRow
    current={currentStage}
    verified={session?.verification?.passed}
  />
</div>
```

`currentStage` is derived from `stageEvents` — reuse existing logic (from prior obsidian overhaul's `computeStagePhase`).

- [ ] **Step 3: Build check**

Run: `cd /home/apeng/projects/solo_company_agentic_board/ui && npm run check`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/apeng/projects/solo_company_agentic_board
git add ui/src/domains/board/GovernancePage.tsx
git commit -m "feat(ui): 4-stage pip rail above composer"
```

---

## Task 17: Frontend — `BriefingDrawer` (left edge slide-in)

**Files:**
- Modify: `ui/src/domains/board/GovernancePage.tsx`

- [ ] **Step 1: Build the drawer component**

```tsx
import { AnimatePresence, motion } from "motion/react";
import { Pin, PinOff, X } from "lucide-react";

function BriefingDrawer({
  open,
  pinned,
  onClose,
  onTogglePin,
  children,
}: {
  open: boolean;
  pinned: boolean;
  onClose: () => void;
  onTogglePin: () => void;
  children: React.ReactNode;
}) {
  return (
    <AnimatePresence>
      {open && (
        <motion.aside
          initial={{ x: -320, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: -320, opacity: 0 }}
          transition={{ ease: "easeOut", duration: 0.28 }}
          className="fixed top-0 bottom-0 z-30 w-[320px] bg-surface-container-low shadow-2xl shadow-black/10 overflow-y-auto p-6"
          style={{ left: railLeftOffset /* 72 or 240 */ }}
          aria-label="Briefing Room"
        >
          <header className="flex items-center justify-between mb-4">
            <div>
              <p className="text-[10px] font-body text-primary tracking-wider uppercase">
                Strategic Materials
              </p>
              <h2 className="font-headline text-xl text-on-surface">
                Briefing Room
              </h2>
            </div>
            <div className="flex gap-1">
              <button
                onClick={onTogglePin}
                className="w-8 h-8 rounded-full hover:bg-surface-container-high flex items-center justify-center"
                aria-label={pinned ? "Unpin drawer" : "Pin drawer"}
                title={pinned ? "Unpin" : "Pin open"}
              >
                {pinned ? <PinOff className="w-4 h-4" /> : <Pin className="w-4 h-4" />}
              </button>
              <button
                onClick={onClose}
                className="w-8 h-8 rounded-full hover:bg-surface-container-high flex items-center justify-center"
                aria-label="Close drawer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </header>
          {children}
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
```

Pass `railLeftOffset` from the parent: `railExpanded ? 240 : 72`.

- [ ] **Step 2: Wire drawer open state**

In `GovernancePage`:

```tsx
const [leftOpen, setLeftOpen] = useState(false);
const [leftPinned, setLeftPinned] = useState(() => {
  try { return localStorage.getItem("boardroom.pinLeft") === "1"; } catch { return false; }
});

useEffect(() => {
  try { localStorage.setItem("boardroom.pinLeft", leftPinned ? "1" : "0"); } catch {}
}, [leftPinned]);

// Auto-open when first question submitted:
useEffect(() => {
  if (stageEvents.length > 0 && !leftOpen) setLeftOpen(true);
}, [stageEvents.length, leftOpen]);
```

- [ ] **Step 3: Populate drawer with existing panels**

Inside `<BriefingDrawer>`:

```tsx
<div className="flex flex-col gap-6">
  <StageDigest stageEvents={stageEvents} /* existing component */ />
  <LiveConversation events={liveFeed} cap={5} /* restyle existing to cap 5 + 'View all' link */ />
  <SotbCard sotb={session?.memory} />
</div>
```

Restyle each sub-component in-place to use cream surfaces (`bg-surface-container-lowest`, no border). If the components were restyled in the prior obsidian overhaul, the cream palette swap (Task 5) already propagated — verify visually.

- [ ] **Step 4: Build check**

Run: `cd /home/apeng/projects/solo_company_agentic_board/ui && npm run check`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/apeng/projects/solo_company_agentic_board
git add ui/src/domains/board/GovernancePage.tsx
git commit -m "feat(ui): BriefingDrawer left edge slide-in"
```

---

## Task 18: Frontend — `OutlookDrawer` (right edge slide-in, Stage 3 trigger)

**Files:**
- Modify: `ui/src/domains/board/GovernancePage.tsx`

- [ ] **Step 1: Build the drawer component**

Mirror `BriefingDrawer`, but from the right:

```tsx
function OutlookDrawer({
  open,
  pinned,
  onClose,
  onTogglePin,
  children,
}: {
  open: boolean;
  pinned: boolean;
  onClose: () => void;
  onTogglePin: () => void;
  children: React.ReactNode;
}) {
  return (
    <AnimatePresence>
      {open && (
        <motion.aside
          initial={{ x: 384, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          exit={{ x: 384, opacity: 0 }}
          transition={{ ease: "easeOut", duration: 0.28 }}
          className="fixed top-0 bottom-0 right-0 z-30 w-96 bg-surface-container-low shadow-2xl shadow-black/10 overflow-y-auto p-6"
          aria-label="Strategic Outlook"
        >
          <header className="flex items-center justify-between mb-4">
            <h2 className="font-headline text-xl text-on-surface">
              Strategic Outlook
            </h2>
            <div className="flex gap-1">
              <button
                onClick={onTogglePin}
                className="w-8 h-8 rounded-full hover:bg-surface-container-high flex items-center justify-center"
                aria-label={pinned ? "Unpin drawer" : "Pin drawer"}
              >
                {pinned ? <PinOff className="w-4 h-4" /> : <Pin className="w-4 h-4" />}
              </button>
              <button
                onClick={onClose}
                className="w-8 h-8 rounded-full hover:bg-surface-container-high flex items-center justify-center"
                aria-label="Close drawer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </header>
          {children}
        </motion.aside>
      )}
    </AnimatePresence>
  );
}
```

- [ ] **Step 2: Wire open state to Stage 3 trigger**

```tsx
const [rightOpen, setRightOpen] = useState(false);
const [rightPinned, setRightPinned] = useState(() => {
  try { return localStorage.getItem("boardroom.pinRight") === "1"; } catch { return false; }
});

useEffect(() => {
  try { localStorage.setItem("boardroom.pinRight", rightPinned ? "1" : "0"); } catch {}
}, [rightPinned]);

useEffect(() => {
  const stage3Active = stageEvents.some(s => s.stage === 3 && s.active);
  if (stage3Active && !rightOpen) setRightOpen(true);
}, [stageEvents, rightOpen]);
```

- [ ] **Step 3: Populate with accordion sections**

Inside `<OutlookDrawer>`:

```tsx
<div className="flex flex-col gap-6">
  <AtTheTable seats={allSeats} />
  <section>
    <h3 className="font-headline text-lg text-on-surface mb-2">Latest Decision</h3>
    <DecisionPreview session={session} />
  </section>

  <Accordion title="Execution Roadmap">
    <AgentExecutionPanel
      delegationPlan={delegationPlan}
      executionAgents={executionAgents}
      routingLabel={routingLabel}
      onApproveTask={onApproveTask}
      onPlanTask={onPlanTask}
    />
  </Accordion>

  <Accordion title="Run Settings">
    <RunSettings settings={runSettings} />
  </Accordion>
</div>
```

Quick local `Accordion`:

```tsx
function Accordion({ title, children }: { title: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center justify-between py-2 font-headline text-base text-on-surface"
      >
        {title}
        <ChevronDown className={`w-4 h-4 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && <div className="mt-2">{children}</div>}
    </div>
  );
}
```

- [ ] **Step 4: Build check**

Run: `cd /home/apeng/projects/solo_company_agentic_board/ui && npm run check`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/apeng/projects/solo_company_agentic_board
git add ui/src/domains/board/GovernancePage.tsx
git commit -m "feat(ui): OutlookDrawer right edge slide-in with accordion sections"
```

---

## Task 19: Frontend — drawer mutual exclusion, pin, Esc dismiss, edge tabs

**Files:**
- Modify: `ui/src/domains/board/GovernancePage.tsx`

- [ ] **Step 1: Mutual-exclusion logic**

```tsx
useEffect(() => {
  if (leftOpen && rightOpen) {
    // Rule 1: drawers mutually exclusive unless pinned. The newer opener wins.
    if (!leftPinned && !rightPinned) {
      // If both opened simultaneously, prefer the later event; heuristic:
      // if stage3 just activated, collapse left.
      const stage3Active = stageEvents.some(s => s.stage === 3 && s.active);
      if (stage3Active) setLeftOpen(false);
      else              setRightOpen(false);
    } else if (!leftPinned && rightPinned) {
      setLeftOpen(false);
    } else if (leftPinned && !rightPinned) {
      setRightOpen(false);
    }
    // if both pinned → both stay open
  }
}, [leftOpen, rightOpen, leftPinned, rightPinned, stageEvents]);
```

- [ ] **Step 2: Esc handler**

```tsx
useEffect(() => {
  const onKey = (e: KeyboardEvent) => {
    if (e.key !== "Escape") return;
    if (rightOpen) setRightOpen(false);
    else if (leftOpen) setLeftOpen(false);
  };
  window.addEventListener("keydown", onKey);
  return () => window.removeEventListener("keydown", onKey);
}, [leftOpen, rightOpen]);
```

- [ ] **Step 3: Edge tabs when drawer closed + session active**

Render outside the drawers themselves:

```tsx
{!leftOpen && stageEvents.length > 0 && (
  <button
    onClick={() => setLeftOpen(true)}
    className="fixed top-1/2 -translate-y-1/2 w-10 h-16 bg-surface-container-high hover:bg-surface-container-highest rounded-r-lg flex items-center justify-center z-20"
    style={{ left: railLeftOffset }}
    aria-label="Open Briefing Room"
  >
    <ChevronRight className="w-5 h-5 text-on-surface-variant" />
  </button>
)}

{!rightOpen && stageEvents.some(s => s.stage >= 3) && (
  <button
    onClick={() => setRightOpen(true)}
    className="fixed right-0 top-1/2 -translate-y-1/2 w-10 h-16 bg-surface-container-high hover:bg-surface-container-highest rounded-l-lg flex items-center justify-center z-20"
    aria-label="Open Strategic Outlook"
  >
    <ChevronLeft className="w-5 h-5 text-on-surface-variant" />
  </button>
)}
```

- [ ] **Step 4: Overlay mode when viewport too narrow**

Add a viewport-width check: if `window.innerWidth < railLeftOffset + 320 + 384 + 600`, toggle a CSS class on the drawer container that makes it `position: fixed` + `z-50` + `backdrop-filter: blur(20px)` on a sibling backdrop. This converts push-resize to overlay.

```tsx
const [tightLayout, setTightLayout] = useState(() =>
  typeof window !== "undefined" && window.innerWidth < railLeftOffset + 1304
);

useEffect(() => {
  const onResize = () => setTightLayout(window.innerWidth < railLeftOffset + 1304);
  window.addEventListener("resize", onResize);
  return () => window.removeEventListener("resize", onResize);
}, [railLeftOffset]);
```

Apply `tightLayout` class to drawer wrappers — e.g., raise z-index, add backdrop-blur. If the simpler behavior is acceptable (drawers push content always), skip this step — note this is a nice-to-have from Density Rule 6 that only matters on ~1280px viewports.

- [ ] **Step 5: Build check**

Run: `cd /home/apeng/projects/solo_company_agentic_board/ui && npm run check`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
cd /home/apeng/projects/solo_company_agentic_board
git add ui/src/domains/board/GovernancePage.tsx
git commit -m "feat(ui): drawer mutual-exclusion + pin + Esc + edge tabs"
```

---

## Task 20: Frontend — `MissingVoiceRow` (post-synthesis signal)

**Files:**
- Modify: `ui/src/domains/board/GovernancePage.tsx`

- [ ] **Step 1: Add the component**

```tsx
import { recordRoutingSignal } from "../../shared/api";

function MissingVoiceRow({
  sessionId,
  routedIds,
  allMembers,
}: {
  sessionId: string | null;
  routedIds: Set<string>;
  allMembers: BoardMember[];
}) {
  const [flagged, setFlagged] = useState<Set<string>>(new Set());

  const candidates = allMembers.filter(
    m => m.id !== "chairperson" && !routedIds.has(m.id),
  );

  if (candidates.length === 0) return null;

  const handleFlag = (memberId: string) => {
    if (flagged.has(memberId)) return;
    setFlagged(prev => new Set(prev).add(memberId));
    if (sessionId) {
      recordRoutingSignal(sessionId, memberId, "missing_voice_flag");
    }
  };

  return (
    <section className="mt-6">
      <p className="text-xs italic text-on-surface-variant mb-3">
        Should any voice have been at the table?
      </p>
      <div className="flex flex-wrap gap-2">
        {candidates.map(m => {
          const isFlagged = flagged.has(m.id);
          return (
            <button
              key={m.id}
              type="button"
              disabled={isFlagged}
              onClick={() => handleFlag(m.id)}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-body transition-colors ${
                isFlagged
                  ? "bg-error-container text-error cursor-default"
                  : "bg-surface-container-low text-on-surface-variant hover:bg-surface-container-high"
              }`}
            >
              <img
                src={MEMBER_IMAGES[m.id]}
                alt=""
                className="w-5 h-5 rounded-full"
              />
              {isFlagged ? "Flagged" : m.title}
            </button>
          );
        })}
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Render inside OutlookDrawer after Latest Decision**

Inside the outlook drawer content JSX, below the Latest Decision section and above the Accordions:

```tsx
{session?.decision && (
  <MissingVoiceRow
    sessionId={session.session_id}
    routedIds={new Set(session.classification?.relevant_member_ids ?? [])}
    allMembers={allMembers}
  />
)}
```

- [ ] **Step 3: Build check**

Run: `cd /home/apeng/projects/solo_company_agentic_board/ui && npm run check`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
cd /home/apeng/projects/solo_company_agentic_board
git add ui/src/domains/board/GovernancePage.tsx
git commit -m "feat(ui): MissingVoiceRow post-synthesis routing-signal capture"
```

---

## Task 21: Frontend — manual-add popover + signal buffering/flush

**Files:**
- Modify: `ui/src/domains/board/GovernancePage.tsx`

- [ ] **Step 1: Add `+` affordance near empty seats**

In the seat mapping area, add a conditional `+` button per empty seat slot when hover intent is detected. Simplest: render a single persistent "+ Add member" floating action next to the orbit, and let the popover handle member selection.

```tsx
const [addOpen, setAddOpen] = useState(false);

{sessionActive && (
  <button
    onClick={() => setAddOpen(v => !v)}
    className="absolute bottom-8 right-8 w-12 h-12 rounded-full metallic-gradient text-on-primary flex items-center justify-center shadow-lg z-20"
    aria-label="Add a board member"
  >
    <Plus className="w-5 h-5" />
  </button>
)}

{addOpen && (
  <ManualAddPopover
    seatedIds={new Set(visibleSeats.map(s => s.memberId))}
    allMembers={allMembers}
    onSelect={(memberId) => {
      handleManualAdd(memberId);
      setAddOpen(false);
    }}
    onClose={() => setAddOpen(false)}
  />
)}
```

- [ ] **Step 2: Build the ManualAddPopover**

```tsx
function ManualAddPopover({
  seatedIds,
  allMembers,
  onSelect,
  onClose,
}: {
  seatedIds: Set<string>;
  allMembers: BoardMember[];
  onSelect: (memberId: string) => void;
  onClose: () => void;
}) {
  const available = allMembers.filter(m => !seatedIds.has(m.id));

  return (
    <div
      role="dialog"
      aria-label="Add a board member"
      className="fixed bottom-24 right-8 w-80 bg-surface-container-lowest rounded-xl shadow-2xl z-30 p-4"
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-headline text-base text-on-surface">Add member</h3>
        <button
          onClick={onClose}
          className="w-6 h-6 rounded-full hover:bg-surface-container-high flex items-center justify-center"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
      {available.length === 0 ? (
        <p className="text-sm italic text-on-surface-variant">
          All members seated.
        </p>
      ) : (
        <ul className="flex flex-col gap-1 max-h-80 overflow-y-auto">
          {available.map(m => (
            <li key={m.id}>
              <button
                onClick={() => onSelect(m.id)}
                className="w-full flex items-start gap-3 px-2 py-2 rounded-lg hover:bg-surface-container-low text-left"
              >
                <img
                  src={MEMBER_IMAGES[m.id]}
                  alt=""
                  className="w-8 h-8 rounded-full shrink-0"
                />
                <div>
                  <p className="font-body text-sm text-on-surface">{m.title}</p>
                  <p className="font-body text-xs text-on-surface-variant line-clamp-1">
                    {memberDossier(m.id)?.strength ?? ""}
                  </p>
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Implement `handleManualAdd` + buffer/flush**

Import buffering helpers in `GovernancePage.tsx`:

```tsx
import {
  recordRoutingSignal,
  bufferRoutingSignal,
  flushRoutingSignalBuffer,
  dropRoutingSignalBuffer,
} from "../../shared/api";
```

Implement:

```tsx
const handleManualAdd = (memberId: string) => {
  toggleManualMember(memberId); // existing prop from App.tsx
  setManuallyAdded(prev => new Set(prev).add(memberId));

  if (session?.session_id) {
    recordRoutingSignal(session.session_id, memberId, "manual_add");
  } else {
    // Session not yet saved — buffer. Use a stable temp key per in-flight session.
    bufferRoutingSignal(pendingSessionKey, memberId, "manual_add");
  }
};
```

Where `pendingSessionKey` is a `useRef<string>` seeded at the start of each new question (e.g. `uuid()` or `board_pending_${Date.now()}`). When the real `session_id` lands, remap:

```tsx
useEffect(() => {
  if (session?.session_id && pendingSessionKeyRef.current) {
    // Migrate any buffered signals from the pending key to the real session_id.
    // Simplest: fetch the buffered list, re-buffer under the real id, clear the old key.
    // (See api.ts for exact helper shape; implementation is project-local.)
  }
}, [session?.session_id]);
```

Flush on T6 completion (session.decision finalized):

```tsx
useEffect(() => {
  if (!session?.session_id) return;
  if (!session?.decision) return;
  flushRoutingSignalBuffer(session.session_id).catch(() => {
    /* swallow — best-effort */
  });
}, [session?.session_id, session?.decision]);
```

If a session fails before decision arrives:

```tsx
useEffect(() => {
  return () => {
    if (sessionFailedRef.current && session?.session_id) {
      dropRoutingSignalBuffer(session.session_id);
    }
  };
}, []);
```

If this buffer migration is too intricate for a first pass, a pragmatic alternative: only fire `recordRoutingSignal` when `session.session_id` is already present (and skip silently otherwise). The classifier runs synchronously enough that session_id is typically set by the time the user has any chance to manually add. Document the simplification here and revisit if needed.

- [ ] **Step 4: Build check**

Run: `cd /home/apeng/projects/solo_company_agentic_board/ui && npm run check`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /home/apeng/projects/solo_company_agentic_board
git add ui/src/domains/board/GovernancePage.tsx
git commit -m "feat(ui): manual-add popover + routing-signal buffering/flush"
```

---

## Task 22: Frontend — aux pages retheme sweep

**Files:**
- Modify: `ui/src/domains/board/PortfolioPage.tsx`
- Modify: `ui/src/domains/harness/PerformancePage.tsx`
- Modify: `ui/src/domains/execution/AgentExecutionPanel.tsx`
- Modify: `ui/src/domains/memory/SotbCard.tsx`
- Modify: `ui/src/domains/memory/FeedbackWidget.tsx`

The palette swap in Task 5 and `MEMBER_TONES` swap in Task 8 already shift most styling. This task is a visual audit + retint pass for anything hardcoded.

- [ ] **Step 1: PortfolioPage audit**

Open `ui/src/domains/board/PortfolioPage.tsx`. Grep for any hex codes or obsolete token references:

```bash
grep -n '\[#' ui/src/domains/board/PortfolioPage.tsx || true
grep -n 'bg-black\|text-white' ui/src/domains/board/PortfolioPage.tsx || true
```

Replace any stray hardcoded hex with tokens. Avatar rings already use `memberTone()` (updated in Task 8). Subheadings in `font-headline`; body in Manrope. Card bg: `bg-surface-container-lowest`.

- [ ] **Step 2: PerformancePage Recharts palette**

Edit `ui/src/domains/harness/PerformancePage.tsx`. Update Recharts props:

```tsx
// Area chart gradient
<defs>
  <linearGradient id="stageTokensFill" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%"   stopColor="#B8860B" stopOpacity={0.55} />
    <stop offset="100%" stopColor="#B8860B" stopOpacity={0.05} />
  </linearGradient>
</defs>
<Area dataKey="tokens" stroke="#8C6608" fill="url(#stageTokensFill)" />

// Pie chart palette (jewel tones recalibrated for cream)
const PIE_COLORS = ["#8C6608", "#1E3A5F", "#6B21A8", "#047857", "#9B2C2C", "#B45309", "#9D174D"];

// Bar chart
<Bar dataKey="calls"  fill="#1E3A5F" />
<Bar dataKey="tokens" fill="#A87C3E" />

// Axis
<XAxis stroke="#9E8F78" tick={{ fill: "#5C5348", fontFamily: "Manrope" }} />
<YAxis stroke="#9E8F78" tick={{ fill: "#5C5348", fontFamily: "Manrope" }} />

// Tooltip
<Tooltip
  contentStyle={{
    background: "#FFFFFF",
    border: "none",
    borderRadius: 8,
    boxShadow: "0 8px 24px rgba(26, 22, 20, 0.08)",
  }}
  labelStyle={{ color: "#1A1614", fontFamily: "Manrope", fontWeight: 600 }}
  itemStyle={{  color: "#1A1614", fontFamily: "Manrope" }}
/>
```

- [ ] **Step 3: AgentExecutionPanel audit**

Open `ui/src/domains/execution/AgentExecutionPanel.tsx`. `taskStatusClass` (updated in Task 8) handles most colors. Verify:
- Task card bg: `bg-surface-container-lowest`
- Progress bar: `bg-surface-container-high` with `bg-secondary-container` fill
- Ghost buttons: `text-primary-container` on hover, no background change
- Empty state: `text-on-surface-variant italic`

Fix any stray `text-primary` (dark-palette gold was `#FFDCA1`; now on cream we want `text-primary-container` = deep gold for buttons).

- [ ] **Step 4: SotbCard audit**

Open `ui/src/domains/memory/SotbCard.tsx`. Verify prose container uses `.prose-lite` or equivalent. Gradient fade overlay at clip edge should transition to `var(--color-surface-container-lowest)` (was dark). Meta chips: `bg-surface-container-high text-on-surface-variant`.

- [ ] **Step 5: FeedbackWidget audit**

Open `ui/src/domains/memory/FeedbackWidget.tsx`. Filled textarea: `bg-surface-container-highest text-on-surface`. Focus border `border-b-2 border-b-secondary-container` (the allowed exception). Submit button: `.metallic-gradient text-on-primary`.

- [ ] **Step 6: Build check**

Run: `cd /home/apeng/projects/solo_company_agentic_board/ui && npm run check`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /home/apeng/projects/solo_company_agentic_board
git add ui/src/domains/board/PortfolioPage.tsx ui/src/domains/harness/PerformancePage.tsx ui/src/domains/execution/AgentExecutionPanel.tsx ui/src/domains/memory/SotbCard.tsx ui/src/domains/memory/FeedbackWidget.tsx
git commit -m "feat(ui): retheme aux pages + Recharts palette for cream"
```

---

## Task 23: Final QA — build + dev smoke + static drift sweep

**Files:**
- All files above (read-only audit)

- [ ] **Step 1: Clean build**

Run: `cd /home/apeng/projects/solo_company_agentic_board/ui && npm run check`
Expected: PASS, 0 TS errors.

- [ ] **Step 2: Full backend test suite**

Run: `cd /home/apeng/projects/solo_company_agentic_board && uv run pytest tests/ -q`
Expected: all tests PASS. If any regression, investigate.

- [ ] **Step 3: Static drift sweep — forbidden classes**

Run: `cd /home/apeng/projects/solo_company_agentic_board && grep -rn "border-slate-\|border-gray-\|border-zinc-\|bg-white[^-]\|bg-slate-100\|text-white\|text-black" ui/src --include="*.tsx" --include="*.ts" || echo "clean"`
Expected: `clean` (no matches) or explainable matches only in Recharts string props.

Run: `cd /home/apeng/projects/solo_company_agentic_board && grep -rn "#111318\|#0C0E13\|#1A1B21\|#282A2F\|#FFDCA1\|#FFB800\|#ADC6FF" ui/src --include="*.tsx" --include="*.ts" --include="*.css" || echo "clean"`
Expected: `clean` except for `index.css` `@theme` block references that were intentionally replaced with cream values. Any stray obsidian-era hex in a .tsx file should be removed.

- [ ] **Step 4: Dev server smoke**

Run: `cd /home/apeng/projects/solo_company_agentic_board && ./start.sh` (or `uv run uvicorn server.api:app --reload --port 8000` if `start.sh` isn't ready).

Open Chrome at `http://127.0.0.1:8000`. Manual verification checklist:
- [ ] 72px icon rail on left, three tab icons
- [ ] Rail expands to 240px on wordmark click
- [ ] Cream background, ink text
- [ ] No top bar
- [ ] Governance page: empty round table, only bottom CEO chair, holo card "Awaiting board question"
- [ ] Composer centered below
- [ ] Stage pip row visible above composer (all dots dim at idle)
- [ ] "Add members" button collapses roster

Submit a test question (e.g., "Should we launch a premium tier?"). Verify:
- [ ] Members fade in at orbit positions
- [ ] Left drawer slides in from left
- [ ] Stage pip fills gold as stages advance
- [ ] Speaking member: gold halo
- [ ] Done member: shrinks to 48px at 70% opacity + ✓ badge
- [ ] Right drawer slides in at Stage 3
- [ ] Latest Decision streams
- [ ] After decision: Missing Voice row renders
- [ ] Click a missing-voice chip → turns burgundy (check Network tab: POST /sessions/{id}/routing-signal → 200)

- [ ] **Step 5: Screenshot capture (optional)**

If available: take a screenshot of the idle state + mid-deliberation state. Attach to the commit for posterity.

- [ ] **Step 6: No-op commit to close out**

If Steps 1–4 all passed without needing code changes:

```bash
cd /home/apeng/projects/solo_company_agentic_board
git log --oneline -25   # confirm all 22 task commits are present
```

No commit needed — the work is already on the branch.

---

## Spec Coverage Check

| Spec component | Covered by Task(s) |
|----------------|-------------------|
| 1. Palette & Typography Tokens | 5, 6 |
| 2. Shell — Icon Rail | 9 |
| 3. Hero Canvas — Round Table + Composer | 10, 11, 12, 13, 14, 15, 16 |
| 4. Edge Drawers | 17, 18, 19 |
| 5. Manual Member Add | 21 |
| 6. Ledger Extension | 1, 2 |
| 7. API Route | 3, 4 |
| 8. Frontend API Client | 7 |
| Density Rule 1 (drawer exclusion) | 19 |
| Density Rule 2 (+N overflow) | 14 |
| Density Rule 3 (done-shrink) | 13 |
| Density Rule 4 (feed cap) | 17 |
| Density Rule 5 (lazy accordion) | 18 |
| Density Rule 6 (overlay on tight viewport) | 19 |
| Density Rule 7 (completed quiet state) | 13 |
| MissingVoiceRow (Phase A-lite signal) | 20 |
| taskStatusClass retint | 8 |
| Aux retheme (Portfolio / Performance / Execution / Sotb / Feedback) | 22 |
| Final QA | 23 |
| `MEMBER_TONES` recalibration | 8 |
| Idle state (empty table) | 10, 11 |
| Top CEO avatar removal | 10 |

All 8 spec components + all 7 density rules + the post-synthesis signal row are mapped to tasks. No gaps.

## Notes for the Executor

- The project uses `uv` not `pip` — always use `uv run pytest`, `uv run python`.
- The frontend has no unit test runner; rely on `npm run check` (tsc + vite build) and manual browser verification.
- The `.board-orbit` CSS utility contains the polar-coordinate math; do NOT change it in any task. Only colors inside that rule change.
- Icons: this project uses `lucide-react`. Any icon referenced in this plan must be imported at the top of the relevant file.
- Framer Motion: import as `import { motion, AnimatePresence } from "motion/react"` — this project uses the `motion` package (not `framer-motion`).
- Commit frequently. Each task ends with a commit. Do not squash in-flight.
- The spec allows ONE border exception: `.accent-bar-left` (and filled-input `focus:border-b-2 focus:border-b-secondary-container`). Everywhere else, separate via tonal bg shift.
- When the implementation differs from the spec (e.g., an existing helper works better than the proposed shape), prefer the existing helper and note the divergence in the commit message.
