# Initiative-Native Solo Company OS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a thin initiative-native vertical slice where founder commands, board sessions, delegated tasks, artifacts, memory context, marketing execution, and closeout belong to durable operating initiatives.

**Architecture:** Add a focused `server/initiatives/` domain backed by the existing local SQLite ledger style, then thread `initiative_id` through board sessions, projection, delegated tasks, and the web UI. Preserve ad hoc sessions for one-off questions while making initiative-owned runs first-class.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, SQLite, pytest, React, TypeScript, Vite.

---

## File Structure

Create:

- `server/initiatives/__init__.py` - public interface for initiative functions and dataclasses.
- `server/initiatives/models.py` - initiative dataclasses, enums, normalization helpers, and JSON conversion.
- `server/initiatives/store.py` - SQLite schema, CRUD, links, closeout, carryover, and session/task lookup.
- `server/api/routes/initiatives.py` - HTTP routes for initiatives.
- `tests/test_initiatives_contract.py` - backend initiative domain/API contract tests.
- `ui/src/domains/initiatives/index.ts` - frontend initiative types and API calls.
- `ui/src/domains/initiatives/InitiativeCockpit.tsx` - compact cockpit panel for active initiative and closeout.

Modify:

- `server/api/app.py` - include initiative routes.
- `server/api/schemas.py` - add initiative request models and board initiative fields.
- `server/board/deliberation/orchestrator.py` - add `initiative_id` to `BoardSession`, board request flow, delegation plan recording, and saved JSON.
- `server/board/deliberation/live.py` - preserve compatibility by carrying optional `initiative_id` in live sessions.
- `server/board/projection.py` - expose `initiative_id` in adapter output.
- `server/execution/tasks.py` - persist `initiative_id`, external-action metadata, and initiative task filtering.
- `server/execution/agents.py` - add marketing lead execution agent accountable to strategy.
- `server/execution/units.py` - no direct edit expected; units derive from `EXECUTION_AGENTS`, so adding `marketing_lead` creates the marketing unit.
- `server/execution/__init__.py` - export initiative-aware helpers.
- `server/api/routes/board.py` - pass `initiative_id` and `initiative_mode` into board runs and stream completions.
- `server/api/routes/execution.py` - expose external action approval and maintain existing task routes.
- `ui/src/shared/types.ts` - add initiative fields to `BoardSession`, `DelegatedTask`, tab union, and initiative types if shared.
- `ui/src/shared/api.ts` - pass initiative routing fields to `/deliberate/stream`; initiative CRUD calls live in `ui/src/domains/initiatives/index.ts`.
- `ui/src/App.tsx` - add cockpit state, initiative loading, route suggestion controls, and closeout action.
- `tests/test_api_cli_contract.py` - extend board/task API contract tests.
- `tests/test_board_session_shape.py` - assert session JSON includes initiative fields.
- `tests/test_execution_contract.py` - assert initiative task fields and marketing agent behavior.
- `tests/conftest.py`, `server/board/llm.py`, `server/harness/replay.py`, and `tests/test_sotb_governance.py` - stabilize current failing test baseline before initiative work.

---

## Task 0: Stabilize Current Test Baseline

**Files:**
- Modify: `server/board/llm.py`
- Modify: `tests/conftest.py`
- Modify: `server/execution/tasks.py`
- Modify: `tests/test_sotb_governance.py`
- Test: existing failing tests from the previous baseline run

- [ ] **Step 1: Run focused failing tests to confirm the current baseline**

Run:

```bash
uv run pytest \
  tests/test_api_cli_contract.py::ApiExecutionContractTest \
  tests/test_llm_kimi.py::test_kimi_default_base_url_is_dot_ai \
  tests/test_replay_contract.py::ReplayPatchesVerifierTest::test_replay_patches_verifier_query_llm \
  tests/test_sotb_governance.py::DetectQueryConflictsTest \
  tests/test_sotb_governance.py::ReadSotbGovernedTest \
  tests/test_sotb_governance.py::ApplySotbUpdateGovernedTest \
  -q
```

Expected: fails reproduce the known baseline clusters: delegated task hook rate limit, Kimi default URL, replay verifier patching, and SOTB event-loop errors.

- [ ] **Step 2: Fix Kimi default base URL**

In `server/board/llm.py`, replace both default Moonshot URLs:

```python
base_url = os.getenv("MOONSHOT_BASE_URL", "https://api.moonshot.ai/v1")
```

Run:

```bash
uv run pytest tests/test_llm_kimi.py::test_kimi_default_base_url_is_dot_ai -q
```

Expected: PASS.

- [ ] **Step 3: Isolate delegated-task hook rate limit in tests**

In `tests/conftest.py`, add an autouse fixture that raises the delegated-task test limit while preserving production defaults:

```python
import pytest


@pytest.fixture(autouse=True)
def _unit_test_hook_rate_limits(monkeypatch):
    monkeypatch.setenv("AGENTIC_BOARD_DELEGATED_TASK_RATE_LIMIT", "1000")
    monkeypatch.setenv("AGENTIC_BOARD_DELEGATED_TASK_RATE_WINDOW_SECONDS", "1")
```

Run:

```bash
uv run pytest tests/test_api_cli_contract.py::ApiExecutionContractTest -q
```

Expected: the delegated task route tests no longer fail with `HookDeniedError: delegated_task rate limit`.

- [ ] **Step 4: Preserve explicit hook rate-limit tests**

Keep the existing per-test overrides in:

```text
tests/test_hooks_bundled.py
tests/test_tasks_hook_integration.py::test_bundled_rate_limit_denies_after_limit
```

Those tests already set `AGENTIC_BOARD_DELEGATED_TASK_RATE_LIMIT` locally, which overrides the autouse fixture from Step 3.

Run:

```bash
uv run pytest tests/test_hooks_bundled.py tests/test_tasks_hook_integration.py -q
```

Expected: PASS.

- [ ] **Step 5: Fix SOTB event-loop test helper**

In `tests/test_sotb_governance.py`, replace each helper shaped like this:

```python
def _run(self, coro):
    return asyncio.get_event_loop().run_until_complete(coro)
```

with:

```python
def _run(self, coro):
    return asyncio.run(coro)
```

Run:

```bash
uv run pytest \
  tests/test_sotb_governance.py::DetectQueryConflictsTest \
  tests/test_sotb_governance.py::ReadSotbGovernedTest \
  tests/test_sotb_governance.py::ApplySotbUpdateGovernedTest \
  -q
```

Expected: no `RuntimeError: There is no current event loop in thread 'MainThread'`.

- [ ] **Step 6: Fix replay verifier patching**

Run the focused replay test:

```bash
uv run pytest tests/test_replay_contract.py::ReplayPatchesVerifierTest::test_replay_patches_verifier_query_llm -q
```

If it fails because `server.board.deliberation.verification.query_llm` is not rebound during replay, modify `server/harness/replay.py` so `_rerun_stage3_and_verify` patches both orchestrator and verification modules in the same context:

```python
import server.board.deliberation.orchestrator as orch_module
import server.board.deliberation.verification as verif_module

original_orch_query_llm = orch_module.query_llm
original_verif_query_llm = verif_module.query_llm
try:
    orch_module.query_llm = candidate_query_llm
    verif_module.query_llm = candidate_query_llm
    # existing stage3 and verification rerun code stays here
finally:
    orch_module.query_llm = original_orch_query_llm
    verif_module.query_llm = original_verif_query_llm
```

Use the actual candidate query function already used in `_rerun_stage3_and_verify`; do not introduce a second mock path.

Run:

```bash
uv run pytest tests/test_replay_contract.py::ReplayPatchesVerifierTest::test_replay_patches_verifier_query_llm -q
```

Expected: PASS.

- [ ] **Step 7: Run the full non-live suite**

Run:

```bash
uv run pytest -q
```

Expected: all non-live tests pass, with live tests deselected by pytest config.

- [ ] **Step 8: Commit baseline repair**

Run:

```bash
git add server/board/llm.py server/harness/replay.py tests/conftest.py tests/test_sotb_governance.py
git commit -m "test: stabilize current baseline"
```

Expected: commit includes only baseline stabilization files.

---

## Task 1: Add Initiative Domain Model And SQLite Store

**Files:**
- Create: `server/initiatives/models.py`
- Create: `server/initiatives/store.py`
- Create: `server/initiatives/__init__.py`
- Test: `tests/test_initiatives_contract.py`

- [ ] **Step 1: Write failing model/store tests**

Create `tests/test_initiatives_contract.py` with:

```python
from pathlib import Path

import pytest

from server.initiatives import (
    InitiativeError,
    activate_initiative,
    close_initiative,
    create_initiative,
    create_link,
    get_initiative,
    list_initiatives,
)


def test_create_get_list_activate_initiative(tmp_path: Path):
    db_path = tmp_path / "ledger.db"

    created = create_initiative(
        title="Validate founder command loop",
        objective="Run one initiative-native board workflow.",
        success_criteria=["Board session linked", "Tasks linked"],
        departments=["strategy", "product", "engineering"],
        created_from="manual",
        db_path=db_path,
    )

    assert created["id"].startswith("init_")
    assert created["status"] == "draft"
    assert created["approval_state"] == "draft"
    assert created["timebox_start"]
    assert created["timebox_end"]

    fetched = get_initiative(created["id"], db_path=db_path)
    assert fetched["title"] == "Validate founder command loop"

    active = activate_initiative(created["id"], db_path=db_path)
    assert active["status"] == "active"
    assert active["approval_state"] == "approved"

    all_rows = list_initiatives(db_path=db_path)
    assert [row["id"] for row in all_rows] == [created["id"]]


def test_initiative_links_and_closeout(tmp_path: Path):
    db_path = tmp_path / "ledger.db"
    initiative = create_initiative(
        title="Ship cockpit slice",
        objective="Create UI and API for initiatives.",
        success_criteria=["Founder can close initiative"],
        departments=["product", "engineering"],
        created_from="founder_command",
        db_path=db_path,
    )

    link = create_link(
        initiative["id"],
        target_type="board_session",
        target_id="board_1700000001",
        relationship="output",
        db_path=db_path,
    )

    assert link["initiative_id"] == initiative["id"]
    assert link["target_type"] == "board_session"

    closed = close_initiative(
        initiative["id"],
        founder_outcome="mixed",
        founder_notes="Useful but engineering task carried over.",
        retrospective_session_id="board_1700000002",
        memory_proposals=["sotb:proposal:1"],
        carryover_decisions=[
            {
                "task_id": "board_1700000001_task_1",
                "decision": "carry_over",
                "target_initiative_id": "init_next",
            }
        ],
        db_path=db_path,
    )

    assert closed["status"] == "closed"
    assert closed["closeout"]["founder_outcome"] == "mixed"
    assert closed["closeout"]["carryover_decisions"][0]["decision"] == "carry_over"


def test_invalid_status_transition_rejected(tmp_path: Path):
    db_path = tmp_path / "ledger.db"
    initiative = create_initiative(
        title="Closed cannot reactivate",
        objective="Verify lifecycle guard.",
        success_criteria=["Closed state enforced"],
        departments=["strategy"],
        created_from="manual",
        db_path=db_path,
    )
    close_initiative(
        initiative["id"],
        founder_outcome="success",
        founder_notes="Done.",
        retrospective_session_id=None,
        memory_proposals=[],
        carryover_decisions=[],
        db_path=db_path,
    )

    with pytest.raises(InitiativeError):
        activate_initiative(initiative["id"], db_path=db_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
uv run pytest tests/test_initiatives_contract.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'server.initiatives'`.

- [ ] **Step 3: Implement initiative models**

Create `server/initiatives/models.py`:

```python
"""Initiative domain models."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal


InitiativeStatus = Literal["draft", "active", "closed"]
ApprovalState = Literal["draft", "approved"]
CreatedFrom = Literal["manual", "founder_command", "board_suggestion"]
FounderOutcome = Literal["success", "failure", "mixed"]
LinkTargetType = Literal["sotb_entry", "initiative", "board_session", "delegated_task", "artifact"]
LinkRelationship = Literal["context", "output", "carryover", "evidence", "artifact"]
CarryoverDecisionValue = Literal["carry_over", "abandon", "backlog"]


class InitiativeError(Exception):
    """Raised when initiative state or input is invalid."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_timebox() -> tuple[str, str]:
    start = datetime.now(timezone.utc)
    end = start + timedelta(days=7)
    return start.isoformat(), end.isoformat()


def json_list(value: list[Any] | None) -> str:
    return json.dumps(value or [], ensure_ascii=False)


def parse_json_list(raw: str | None) -> list[Any]:
    if not raw:
        return []
    value = json.loads(raw)
    return value if isinstance(value, list) else []


@dataclass
class Initiative:
    id: str
    title: str
    objective: str
    status: InitiativeStatus
    timebox_start: str
    timebox_end: str
    success_criteria: list[str] = field(default_factory=list)
    departments: list[str] = field(default_factory=list)
    approval_state: ApprovalState = "draft"
    created_from: CreatedFrom = "manual"
    source_session_id: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InitiativeLink:
    id: str
    initiative_id: str
    target_type: LinkTargetType
    target_id: str
    relationship: LinkRelationship
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InitiativeCloseout:
    initiative_id: str
    founder_outcome: FounderOutcome
    founder_notes: str
    retrospective_session_id: str | None
    memory_proposals: list[str] = field(default_factory=list)
    carryover_decisions: list[dict[str, Any]] = field(default_factory=list)
    closed_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
```

- [ ] **Step 4: Implement SQLite store**

Create `server/initiatives/store.py` with:

```python
"""SQLite persistence for initiatives."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .models import (
    Initiative,
    InitiativeCloseout,
    InitiativeError,
    InitiativeLink,
    default_timebox,
    json_list,
    parse_json_list,
    utc_now,
)


DEFAULT_DB_PATH = Path("data/harness_ledger.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS initiatives (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    objective TEXT NOT NULL,
    status TEXT NOT NULL,
    timebox_start TEXT NOT NULL,
    timebox_end TEXT NOT NULL,
    success_criteria TEXT NOT NULL,
    departments TEXT NOT NULL,
    approval_state TEXT NOT NULL,
    created_from TEXT NOT NULL,
    source_session_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_initiatives_status_updated
ON initiatives(status, updated_at);

CREATE TABLE IF NOT EXISTS initiative_links (
    id TEXT PRIMARY KEY,
    initiative_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    relationship TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_initiative_links_initiative
ON initiative_links(initiative_id);

CREATE TABLE IF NOT EXISTS initiative_closeouts (
    initiative_id TEXT PRIMARY KEY,
    founder_outcome TEXT NOT NULL,
    founder_notes TEXT NOT NULL,
    retrospective_session_id TEXT,
    memory_proposals TEXT NOT NULL,
    carryover_decisions TEXT NOT NULL,
    closed_at TEXT NOT NULL
);
"""

VALID_STATUSES = {"draft", "active", "closed"}
VALID_APPROVALS = {"draft", "approved"}
VALID_CREATED_FROM = {"manual", "founder_command", "board_suggestion"}
VALID_OUTCOMES = {"success", "failure", "mixed"}
VALID_TARGET_TYPES = {"sotb_entry", "initiative", "board_session", "delegated_task", "artifact"}
VALID_RELATIONSHIPS = {"context", "output", "carryover", "evidence", "artifact"}
VALID_CARRYOVER = {"carry_over", "abandon", "backlog"}


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DEFAULT_DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def _new_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}"


def _row_to_initiative(row: sqlite3.Row, *, db_path: Path | None = None) -> dict[str, Any]:
    item = Initiative(
        id=row["id"],
        title=row["title"],
        objective=row["objective"],
        status=row["status"],
        timebox_start=row["timebox_start"],
        timebox_end=row["timebox_end"],
        success_criteria=[str(x) for x in parse_json_list(row["success_criteria"])],
        departments=[str(x) for x in parse_json_list(row["departments"])],
        approval_state=row["approval_state"],
        created_from=row["created_from"],
        source_session_id=row["source_session_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    ).to_dict()
    closeout = get_closeout(item["id"], db_path=db_path)
    if closeout:
        item["closeout"] = closeout
    return item


def create_initiative(
    *,
    title: str,
    objective: str,
    success_criteria: list[str] | None = None,
    departments: list[str] | None = None,
    created_from: str = "manual",
    source_session_id: str | None = None,
    timebox_start: str | None = None,
    timebox_end: str | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    clean_title = title.strip()
    clean_objective = objective.strip()
    if not clean_title:
        raise InitiativeError("Initiative title is required.")
    if not clean_objective:
        raise InitiativeError("Initiative objective is required.")
    if created_from not in VALID_CREATED_FROM:
        raise InitiativeError(f"Invalid created_from: {created_from}")
    if not timebox_start or not timebox_end:
        timebox_start, timebox_end = default_timebox()

    now = utc_now()
    initiative = Initiative(
        id=_new_id("init"),
        title=clean_title,
        objective=clean_objective,
        status="draft",
        timebox_start=timebox_start,
        timebox_end=timebox_end,
        success_criteria=[str(x).strip() for x in (success_criteria or []) if str(x).strip()],
        departments=[str(x).strip() for x in (departments or []) if str(x).strip()],
        approval_state="draft",
        created_from=created_from,
        source_session_id=source_session_id,
        created_at=now,
        updated_at=now,
    )

    conn = _connect(db_path)
    try:
        conn.execute(
            """INSERT INTO initiatives (
                id, title, objective, status, timebox_start, timebox_end,
                success_criteria, departments, approval_state, created_from,
                source_session_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                initiative.id, initiative.title, initiative.objective,
                initiative.status, initiative.timebox_start, initiative.timebox_end,
                json_list(initiative.success_criteria), json_list(initiative.departments),
                initiative.approval_state, initiative.created_from,
                initiative.source_session_id, initiative.created_at, initiative.updated_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_initiative(initiative.id, db_path=db_path)
```

Continue the same file with `get_initiative`, `list_initiatives`, `update_initiative`, `activate_initiative`, `create_link`, `delete_link`, `list_links`, `get_closeout`, and `close_initiative`:

```python
def get_initiative(initiative_id: str, *, db_path: Path | None = None) -> dict[str, Any] | None:
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM initiatives WHERE id = ?", (initiative_id,)).fetchone()
    finally:
        conn.close()
    return _row_to_initiative(row, db_path=db_path) if row else None


def list_initiatives(*, status: str | None = None, db_path: Path | None = None) -> list[dict[str, Any]]:
    conn = _connect(db_path)
    try:
        if status:
            rows = conn.execute(
                "SELECT * FROM initiatives WHERE status = ? ORDER BY updated_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM initiatives ORDER BY updated_at DESC").fetchall()
    finally:
        conn.close()
    return [_row_to_initiative(row, db_path=db_path) for row in rows]


def update_initiative(
    initiative_id: str,
    *,
    title: str | None = None,
    objective: str | None = None,
    success_criteria: list[str] | None = None,
    departments: list[str] | None = None,
    timebox_start: str | None = None,
    timebox_end: str | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    current = get_initiative(initiative_id, db_path=db_path)
    if not current:
        raise InitiativeError(f"Initiative not found: {initiative_id}")
    if current["status"] == "closed":
        raise InitiativeError("Closed initiatives cannot be edited.")

    next_title = (title if title is not None else current["title"]).strip()
    next_objective = (objective if objective is not None else current["objective"]).strip()
    if not next_title:
        raise InitiativeError("Initiative title is required.")
    if not next_objective:
        raise InitiativeError("Initiative objective is required.")

    conn = _connect(db_path)
    try:
        conn.execute(
            """UPDATE initiatives SET
                title = ?, objective = ?, success_criteria = ?, departments = ?,
                timebox_start = ?, timebox_end = ?, updated_at = ?
               WHERE id = ?""",
            (
                next_title,
                next_objective,
                json_list(success_criteria if success_criteria is not None else current["success_criteria"]),
                json_list(departments if departments is not None else current["departments"]),
                timebox_start or current["timebox_start"],
                timebox_end or current["timebox_end"],
                utc_now(),
                initiative_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_initiative(initiative_id, db_path=db_path)


def activate_initiative(initiative_id: str, *, db_path: Path | None = None) -> dict[str, Any]:
    initiative = get_initiative(initiative_id, db_path=db_path)
    if not initiative:
        raise InitiativeError(f"Initiative not found: {initiative_id}")
    if initiative["status"] == "closed":
        raise InitiativeError("Closed initiatives cannot be activated.")
    now = utc_now()
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE initiatives SET status = ?, approval_state = ?, updated_at = ? WHERE id = ?",
            ("active", "approved", now, initiative_id),
        )
        conn.commit()
    finally:
        conn.close()
    return get_initiative(initiative_id, db_path=db_path)


def create_link(
    initiative_id: str,
    *,
    target_type: str,
    target_id: str,
    relationship: str,
    db_path: Path | None = None,
) -> dict[str, Any]:
    if not get_initiative(initiative_id, db_path=db_path):
        raise InitiativeError(f"Initiative not found: {initiative_id}")
    if target_type not in VALID_TARGET_TYPES:
        raise InitiativeError(f"Invalid link target_type: {target_type}")
    if relationship not in VALID_RELATIONSHIPS:
        raise InitiativeError(f"Invalid link relationship: {relationship}")
    link = InitiativeLink(
        id=_new_id("link"),
        initiative_id=initiative_id,
        target_type=target_type,
        target_id=target_id.strip(),
        relationship=relationship,
    )
    if not link.target_id:
        raise InitiativeError("Link target_id is required.")
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO initiative_links (id, initiative_id, target_type, target_id, relationship, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (link.id, link.initiative_id, link.target_type, link.target_id, link.relationship, link.created_at),
        )
        conn.commit()
    finally:
        conn.close()
    return link.to_dict()


def list_links(initiative_id: str, *, db_path: Path | None = None) -> list[dict[str, Any]]:
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM initiative_links WHERE initiative_id = ? ORDER BY created_at",
            (initiative_id,),
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def delete_link(initiative_id: str, link_id: str, *, db_path: Path | None = None) -> None:
    conn = _connect(db_path)
    try:
        cursor = conn.execute(
            "DELETE FROM initiative_links WHERE initiative_id = ? AND id = ?",
            (initiative_id, link_id),
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise InitiativeError(f"Initiative link not found: {link_id}")
    finally:
        conn.close()


def get_closeout(initiative_id: str, *, db_path: Path | None = None) -> dict[str, Any] | None:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM initiative_closeouts WHERE initiative_id = ?",
            (initiative_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return InitiativeCloseout(
        initiative_id=row["initiative_id"],
        founder_outcome=row["founder_outcome"],
        founder_notes=row["founder_notes"],
        retrospective_session_id=row["retrospective_session_id"],
        memory_proposals=[str(x) for x in parse_json_list(row["memory_proposals"])],
        carryover_decisions=[dict(x) for x in parse_json_list(row["carryover_decisions"])],
        closed_at=row["closed_at"],
    ).to_dict()


def close_initiative(
    initiative_id: str,
    *,
    founder_outcome: str,
    founder_notes: str,
    retrospective_session_id: str | None,
    memory_proposals: list[str],
    carryover_decisions: list[dict[str, Any]],
    db_path: Path | None = None,
) -> dict[str, Any]:
    if founder_outcome not in VALID_OUTCOMES:
        raise InitiativeError(f"Invalid founder_outcome: {founder_outcome}")
    if not get_initiative(initiative_id, db_path=db_path):
        raise InitiativeError(f"Initiative not found: {initiative_id}")
    for decision in carryover_decisions:
        if decision.get("decision") not in VALID_CARRYOVER:
            raise InitiativeError(f"Invalid carryover decision: {decision.get('decision')}")
        if not str(decision.get("task_id") or "").strip():
            raise InitiativeError("Carryover decision task_id is required.")

    closeout = InitiativeCloseout(
        initiative_id=initiative_id,
        founder_outcome=founder_outcome,
        founder_notes=founder_notes.strip(),
        retrospective_session_id=retrospective_session_id,
        memory_proposals=[str(x) for x in memory_proposals],
        carryover_decisions=carryover_decisions,
    )
    now = utc_now()
    conn = _connect(db_path)
    try:
        conn.execute(
            "UPDATE initiatives SET status = ?, updated_at = ? WHERE id = ?",
            ("closed", now, initiative_id),
        )
        conn.execute(
            """INSERT OR REPLACE INTO initiative_closeouts (
                initiative_id, founder_outcome, founder_notes, retrospective_session_id,
                memory_proposals, carryover_decisions, closed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                closeout.initiative_id, closeout.founder_outcome, closeout.founder_notes,
                closeout.retrospective_session_id, json.dumps(closeout.memory_proposals),
                json.dumps(closeout.carryover_decisions), closeout.closed_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return get_initiative(initiative_id, db_path=db_path)
```

- [ ] **Step 5: Export public initiative interface**

Create `server/initiatives/__init__.py`:

```python
"""Initiative domain public interface."""

from pathlib import Path

from .models import Initiative, InitiativeCloseout, InitiativeError, InitiativeLink
from . import store as _store


_DEFAULT_DB_PATH: Path | None = _store.DEFAULT_DB_PATH


def create_initiative(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _store.create_initiative(*args, **kwargs)


def get_initiative(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _store.get_initiative(*args, **kwargs)


def list_initiatives(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _store.list_initiatives(*args, **kwargs)


def update_initiative(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _store.update_initiative(*args, **kwargs)


def activate_initiative(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _store.activate_initiative(*args, **kwargs)


def create_link(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _store.create_link(*args, **kwargs)


def list_links(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _store.list_links(*args, **kwargs)


def delete_link(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _store.delete_link(*args, **kwargs)


def close_initiative(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _store.close_initiative(*args, **kwargs)


__all__ = [
    "Initiative",
    "InitiativeCloseout",
    "InitiativeError",
    "InitiativeLink",
    "activate_initiative",
    "close_initiative",
    "create_initiative",
    "create_link",
    "delete_link",
    "get_initiative",
    "list_initiatives",
    "list_links",
    "update_initiative",
]
```

- [ ] **Step 6: Run initiative contract tests**

Run:

```bash
uv run pytest tests/test_initiatives_contract.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit initiative store**

Run:

```bash
git add server/initiatives tests/test_initiatives_contract.py
git commit -m "feat: add initiative persistence"
```

Expected: commit contains initiative domain and tests.

---

## Task 2: Add Initiative API Routes

**Files:**
- Create: `server/api/routes/initiatives.py`
- Modify: `server/api/app.py`
- Modify: `server/api/schemas.py`
- Test: `tests/test_initiatives_contract.py`

- [ ] **Step 1: Add failing API route tests**

Append to `tests/test_initiatives_contract.py`:

```python
import tempfile
import unittest

from fastapi import HTTPException

from server.api.routes import initiatives as initiative_routes
from server.api.schemas import (
    InitiativeActivateRequest,
    InitiativeCloseoutRequest,
    InitiativeCreateRequest,
    InitiativeLinkRequest,
)


class InitiativeApiContractTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "ledger.db"
        import server.initiatives as initiatives

        self._old_db_path = initiatives._DEFAULT_DB_PATH
        initiatives._DEFAULT_DB_PATH = self.db_path

    def tearDown(self):
        import server.initiatives as initiatives

        initiatives._DEFAULT_DB_PATH = self._old_db_path
        self.tmpdir.cleanup()

    async def test_create_activate_link_closeout_routes(self):
        created = await initiative_routes.create_initiative_route(
            InitiativeCreateRequest(
                title="Run launch cycle",
                objective="Coordinate strategy and engineering.",
                success_criteria=["Launch checklist exists"],
                departments=["strategy", "engineering"],
                created_from="manual",
            )
        )
        self.assertEqual("draft", created["status"])

        active = await initiative_routes.activate_initiative_route(
            created["id"], InitiativeActivateRequest()
        )
        self.assertEqual("active", active["status"])

        link = await initiative_routes.create_initiative_link_route(
            created["id"],
            InitiativeLinkRequest(
                target_type="board_session",
                target_id="board_1700000001",
                relationship="output",
            ),
        )
        self.assertEqual("board_session", link["target_type"])

        closed = await initiative_routes.closeout_initiative_route(
            created["id"],
            InitiativeCloseoutRequest(
                founder_outcome="success",
                founder_notes="Closed from API.",
                retrospective_session_id="board_1700000002",
                memory_proposals=["proposal:1"],
                carryover_decisions=[],
            ),
        )
        self.assertEqual("closed", closed["status"])
        self.assertEqual("success", closed["closeout"]["founder_outcome"])

    async def test_missing_initiative_returns_404(self):
        with self.assertRaises(HTTPException) as ctx:
            await initiative_routes.get_initiative_route("init_missing")
        self.assertEqual(404, ctx.exception.status_code)
```

- [ ] **Step 2: Run tests to verify route module is missing**

Run:

```bash
uv run pytest tests/test_initiatives_contract.py::InitiativeApiContractTest -q
```

Expected: FAIL because `server.api.routes.initiatives` or request schemas do not exist.

- [ ] **Step 3: Add Pydantic request schemas**

In `server/api/schemas.py`, add:

```python
class InitiativeCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    objective: str = Field(min_length=1, max_length=2000)
    success_criteria: list[str] = Field(default_factory=list)
    departments: list[str] = Field(default_factory=list)
    created_from: Literal["manual", "founder_command", "board_suggestion"] = "manual"
    source_session_id: str | None = None
    timebox_start: str | None = None
    timebox_end: str | None = None


class InitiativeUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    objective: str | None = Field(default=None, min_length=1, max_length=2000)
    success_criteria: list[str] | None = None
    departments: list[str] | None = None
    timebox_start: str | None = None
    timebox_end: str | None = None


class InitiativeActivateRequest(BaseModel):
    approve: bool = True


class InitiativeLinkRequest(BaseModel):
    target_type: Literal["sotb_entry", "initiative", "board_session", "delegated_task", "artifact"]
    target_id: str = Field(min_length=1, max_length=300)
    relationship: Literal["context", "output", "carryover", "evidence", "artifact"]


class InitiativeCloseoutRequest(BaseModel):
    founder_outcome: Literal["success", "failure", "mixed"]
    founder_notes: str = ""
    retrospective_session_id: str | None = None
    memory_proposals: list[str] = Field(default_factory=list)
    carryover_decisions: list[dict] = Field(default_factory=list)
```

- [ ] **Step 4: Add initiative API routes**

Create `server/api/routes/initiatives.py`:

```python
"""Initiative routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from server.initiatives import (
    InitiativeError,
    activate_initiative,
    close_initiative,
    create_initiative,
    create_link,
    get_initiative,
    list_initiatives,
    list_links,
    update_initiative,
    delete_link,
)

from ..schemas import (
    InitiativeActivateRequest,
    InitiativeCloseoutRequest,
    InitiativeCreateRequest,
    InitiativeLinkRequest,
    InitiativeUpdateRequest,
)


router = APIRouter()


@router.get("/initiatives")
async def list_initiatives_route(status: str | None = None):
    return list_initiatives(status=status)


@router.post("/initiatives")
async def create_initiative_route(req: InitiativeCreateRequest):
    try:
        return create_initiative(
            title=req.title,
            objective=req.objective,
            success_criteria=req.success_criteria,
            departments=req.departments,
            created_from=req.created_from,
            source_session_id=req.source_session_id,
            timebox_start=req.timebox_start,
            timebox_end=req.timebox_end,
        )
    except InitiativeError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@router.get("/initiatives/{initiative_id}")
async def get_initiative_route(initiative_id: str):
    initiative = get_initiative(initiative_id)
    if not initiative:
        raise HTTPException(404, detail=f"Initiative not found: {initiative_id}")
    initiative["links"] = list_links(initiative_id)
    return initiative


@router.patch("/initiatives/{initiative_id}")
async def update_initiative_route(initiative_id: str, req: InitiativeUpdateRequest):
    try:
        return update_initiative(
            initiative_id,
            title=req.title,
            objective=req.objective,
            success_criteria=req.success_criteria,
            departments=req.departments,
            timebox_start=req.timebox_start,
            timebox_end=req.timebox_end,
        )
    except InitiativeError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@router.post("/initiatives/{initiative_id}/activate")
async def activate_initiative_route(initiative_id: str, req: InitiativeActivateRequest):
    if not req.approve:
        raise HTTPException(422, detail="activate requires approve=true")
    try:
        return activate_initiative(initiative_id)
    except InitiativeError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@router.post("/initiatives/{initiative_id}/links")
async def create_initiative_link_route(initiative_id: str, req: InitiativeLinkRequest):
    try:
        return create_link(
            initiative_id,
            target_type=req.target_type,
            target_id=req.target_id,
            relationship=req.relationship,
        )
    except InitiativeError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


@router.get("/initiatives/{initiative_id}/links")
async def list_initiative_links_route(initiative_id: str):
    if not get_initiative(initiative_id):
        raise HTTPException(404, detail=f"Initiative not found: {initiative_id}")
    return list_links(initiative_id)


@router.delete("/initiatives/{initiative_id}/links/{link_id}")
async def delete_initiative_link_route(initiative_id: str, link_id: str):
    try:
        delete_link(initiative_id, link_id)
    except InitiativeError as exc:
        raise HTTPException(404, detail=str(exc)) from exc
    return {"status": "deleted", "initiative_id": initiative_id, "link_id": link_id}


@router.post("/initiatives/{initiative_id}/closeout")
async def closeout_initiative_route(initiative_id: str, req: InitiativeCloseoutRequest):
    try:
        return close_initiative(
            initiative_id,
            founder_outcome=req.founder_outcome,
            founder_notes=req.founder_notes,
            retrospective_session_id=req.retrospective_session_id,
            memory_proposals=req.memory_proposals,
            carryover_decisions=req.carryover_decisions,
        )
    except InitiativeError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
```

- [ ] **Step 5: Register route module**

In `server/api/app.py`, change imports:

```python
from .routes import board, execution, harness, initiatives, memory, system
```

Add router registration before board routes:

```python
app.include_router(system.router)
app.include_router(initiatives.router)
app.include_router(board.router)
```

- [ ] **Step 6: Run initiative API tests**

Run:

```bash
uv run pytest tests/test_initiatives_contract.py::InitiativeApiContractTest -q
```

Expected: PASS.

- [ ] **Step 7: Commit API routes**

Run:

```bash
git add server/api/app.py server/api/schemas.py server/api/routes/initiatives.py tests/test_initiatives_contract.py
git commit -m "feat: expose initiative API"
```

Expected: commit contains API schemas, route registration, route handlers, and tests.

---

## Task 3: Thread Initiatives Through Board Sessions And Projection

**Files:**
- Modify: `server/api/schemas.py`
- Modify: `server/api/routes/board.py`
- Modify: `server/board/deliberation/orchestrator.py`
- Modify: `server/board/deliberation/live.py`
- Modify: `server/board/projection.py`
- Test: `tests/test_board_session_shape.py`
- Test: `tests/test_api_cli_contract.py`

- [ ] **Step 1: Add failing board initiative tests**

In `tests/test_board_session_shape.py`, add:

```python
def test_board_session_serializes_initiative_id():
    from server.board.deliberation.orchestrator import BoardSession

    session = BoardSession(
        session_id="board_1700000001",
        user_query="Run this initiative.",
        initiative_id="init_1700000000000",
        initiative_mode="attach",
    )
    payload = session.to_dict()

    assert payload["initiative_id"] == "init_1700000000000"
    assert payload["initiative_mode"] == "attach"
```

In `tests/test_api_cli_contract.py`, add:

```python
def test_query_request_accepts_initiative_fields():
    req = QueryRequest(
        query="Launch the cockpit slice",
        initiative_id="init_1700000000000",
        initiative_mode="attach",
    )

    assert req.initiative_id == "init_1700000000000"
    assert req.initiative_mode == "attach"
```

In a projection test file, or `tests/test_board_session_shape.py`, add:

```python
def test_session_adapter_exposes_initiative_id():
    from server.board.projection import adapt_session_record

    adapted = adapt_session_record({
        "session_id": "board_1700000001",
        "user_query": "q",
        "initiative_id": "init_1700000000000",
        "initiative_mode": "attach",
        "stage3": {"content": "### Executive Summary\nok"},
    })

    assert adapted["initiative_id"] == "init_1700000000000"
    assert adapted["initiative_mode"] == "attach"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
uv run pytest \
  tests/test_board_session_shape.py::test_board_session_serializes_initiative_id \
  tests/test_board_session_shape.py::test_session_adapter_exposes_initiative_id \
  tests/test_api_cli_contract.py::test_query_request_accepts_initiative_fields \
  -q
```

Expected: FAIL because initiative fields are missing.

- [ ] **Step 3: Add board request fields**

In `server/api/schemas.py`, update `QueryRequest`:

```python
class QueryRequest(BaseModel):
    query: str
    session_id: str | None = None
    member_ids: list[str] | None = None
    full_board: bool = False
    verify: bool = False
    clarification_answers: dict | None = None
    discussion_mode: Literal["staged", "live"] = "staged"
    initiative_id: str | None = None
    initiative_mode: Literal["ad_hoc", "attach", "create_draft"] = "ad_hoc"
```

- [ ] **Step 4: Add fields to BoardSession**

In `server/board/deliberation/orchestrator.py`, add fields to `BoardSession`:

```python
initiative_id: str | None = None
initiative_mode: str = "ad_hoc"
```

Add them to `to_dict()`:

```python
"initiative_id": self.initiative_id,
"initiative_mode": self.initiative_mode,
```

- [ ] **Step 5: Pass initiative fields into staged board runs**

In `BoardOrchestrator.deliberate`, add parameters:

```python
initiative_id: str | None = None,
initiative_mode: str = "ad_hoc",
```

When constructing `BoardSession`, include:

```python
session = BoardSession(
    session_id=session_id,
    user_query=user_query,
    initiative_id=initiative_id,
    initiative_mode=initiative_mode,
)
```

When calling `record_delegation_plan`, pass initiative ID:

```python
if session.delegation_plan and session.initiative_id:
    session.delegation_plan["initiative_id"] = session.initiative_id
```

- [ ] **Step 6: Pass initiative fields from API routes**

In `server/api/routes/board.py`, update staged and streaming calls:

```python
session = await orchestrator.deliberate(
    req.query,
    member_ids=req.member_ids,
    skip_classify=req.full_board,
    verify=req.verify,
    session_id=req.session_id,
    clarification_answers=req.clarification_answers,
    initiative_id=req.initiative_id,
    initiative_mode=req.initiative_mode,
)
```

Apply the same arguments in the streaming staged branch.

- [ ] **Step 7: Preserve live mode compatibility**

In `server/board/deliberation/live.py`, add optional fields to the live session construction or after `BoardSession` creation:

```python
session.initiative_id = initiative_id
session.initiative_mode = initiative_mode
```

Add matching parameters to `LiveBoardConversation.discuss`:

```python
initiative_id: str | None = None,
initiative_mode: str = "ad_hoc",
```

Pass the values from `server/api/routes/board.py` live calls.

- [ ] **Step 8: Expose initiative fields in adapter**

In `server/board/projection.py`, add to `adapt_session_record` return dict:

```python
"initiative_id": record.get("initiative_id"),
"initiative_mode": record.get("initiative_mode", "ad_hoc"),
```

- [ ] **Step 9: Run focused board tests**

Run:

```bash
uv run pytest \
  tests/test_board_session_shape.py \
  tests/test_api_cli_contract.py::test_query_request_accepts_initiative_fields \
  -q
```

Expected: PASS.

- [ ] **Step 10: Commit board initiative threading**

Run:

```bash
git add server/api/schemas.py server/api/routes/board.py server/board/deliberation/orchestrator.py server/board/deliberation/live.py server/board/projection.py tests/test_board_session_shape.py tests/test_api_cli_contract.py
git commit -m "feat: thread initiatives through board sessions"
```

Expected: commit contains board request/session/projection initiative fields.

---

## Task 4: Link Delegated Tasks To Initiatives And External Action Gates

**Files:**
- Modify: `server/execution/tasks.py`
- Modify: `server/execution/__init__.py`
- Modify: `server/api/routes/execution.py`
- Modify: `server/api/schemas.py`
- Test: `tests/test_execution_contract.py`
- Test: `tests/test_api_cli_contract.py`

- [ ] **Step 1: Add failing delegated task tests**

In `tests/test_execution_contract.py`, add:

```python
def test_delegation_plan_carries_initiative_and_external_action_fields(tmp_path):
    from server.execution import get_delegation_plan, parse_delegation_plan, record_delegation_plan

    plan = parse_delegation_plan(
        """### Delegation Plan
```json
{
  "tasks": [{
    "title": "Draft launch outreach",
    "objective": "Prepare outreach copy for founder approval.",
    "execution_unit_id": "marketing",
    "manager_agent_id": "marketing_lead",
    "priority": "p1",
    "external_action_required": true,
    "external_action_type": "outreach",
    "acceptance_criteria": ["Draft copy exists"]
  }]
}
```""",
        session_id="board_1700000001",
        initiative_id="init_1700000000000",
    )
    task = plan["tasks"][0]

    assert task["initiative_id"] == "init_1700000000000"
    assert task["external_action_required"] is True
    assert task["external_action_type"] == "outreach"

    record_delegation_plan(plan, db_path=tmp_path / "ledger.db")
    persisted = get_delegation_plan("board_1700000001", db_path=tmp_path / "ledger.db")
    assert persisted["tasks"][0]["initiative_id"] == "init_1700000000000"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run pytest tests/test_execution_contract.py::test_delegation_plan_carries_initiative_and_external_action_fields -q
```

Expected: FAIL because `parse_delegation_plan` does not accept `initiative_id`.

- [ ] **Step 3: Extend DelegatedTask dataclass**

In `server/execution/tasks.py`, add fields:

```python
    initiative_id: str | None = None
    external_action_required: bool = False
    external_action_type: str = "none"
    external_action_approved: bool = False
```

Add constants:

```python
EXTERNAL_ACTION_TYPES = {"outreach", "publish", "deploy", "spend", "none"}
```

- [ ] **Step 4: Extend parse_delegation_plan signature**

Change:

```python
def parse_delegation_plan(
    synthesis_content: str | None,
    *,
    session_id: str,
    initiative_id: str | None = None,
) -> dict[str, Any]:
```

When normalizing tasks:

```python
task = _normalize_delegated_task(
    raw_task,
    session_id=session_id,
    initiative_id=initiative_id,
    index=index,
)
```

Set top-level plan field:

```python
return DelegationPlan(session_id=session_id, tasks=tasks, warnings=warnings).to_dict() | {"initiative_id": initiative_id}
```

If the project avoids `|` for dicts, use:

```python
plan = DelegationPlan(session_id=session_id, tasks=tasks, warnings=warnings).to_dict()
plan["initiative_id"] = initiative_id
return plan
```

- [ ] **Step 5: Normalize initiative and external action fields**

Change `_normalize_delegated_task` signature:

```python
def _normalize_delegated_task(
    raw: dict[str, Any],
    *,
    session_id: str,
    initiative_id: str | None,
    index: int,
) -> DelegatedTask | None:
```

Add:

```python
external_type = str(raw.get("external_action_type") or "none").strip().lower()
if external_type not in EXTERNAL_ACTION_TYPES:
    external_type = "none"
external_required = bool(raw.get("external_action_required", external_type != "none"))
external_approved = bool(raw.get("external_action_approved", False))
```

Pass into `DelegatedTask`:

```python
initiative_id=initiative_id or raw.get("initiative_id"),
external_action_required=external_required,
external_action_type=external_type,
external_action_approved=external_approved,
```

- [ ] **Step 6: Add initiative task listing helper**

In `server/execution/tasks.py`, add:

```python
def get_delegated_tasks_for_initiative(
    initiative_id: str,
    *,
    db_path: Path | None = None,
) -> list[dict[str, Any]]:
    conn = _connect_tasks(db_path)
    try:
        rows = conn.execute(
            "SELECT payload FROM delegated_tasks ORDER BY created_at, task_id",
        ).fetchall()
    finally:
        conn.close()
    tasks = [json.loads(row["payload"]) for row in rows]
    return [task for task in tasks if task.get("initiative_id") == initiative_id]
```

Export it from `server/execution/__init__.py`:

```python
def get_delegated_tasks_for_initiative(*args, **kwargs):
    kwargs.setdefault("db_path", _DEFAULT_DB_PATH)
    return _tasks.get_delegated_tasks_for_initiative(*args, **kwargs)
```

Add to `__all__`.

- [ ] **Step 7: Add external action approval helper**

In `server/execution/tasks.py`, add:

```python
def approve_external_action(
    task_id: str,
    *,
    approve: bool = True,
    db_path: Path | None = None,
) -> dict[str, Any]:
    task = _load_required_task(task_id, db_path=db_path)
    if not task.get("external_action_required"):
        raise ExecutionError("Task does not require external action approval.")
    task["external_action_approved"] = bool(approve)
    return save_delegated_task(task, db_path=db_path)
```

Export it from `server/execution/__init__.py`.

- [ ] **Step 8: Add API schema and route**

In `server/api/schemas.py`, add:

```python
class ExternalActionApprovalRequest(BaseModel):
    approve: bool = True
```

In `server/api/routes/execution.py`, import and add:

```python
from server.execution import approve_external_action
from ..schemas import ExternalActionApprovalRequest


@router.post("/delegated-tasks/{task_id}/approve-external-action")
async def approve_task_external_action(task_id: str, req: ExternalActionApprovalRequest):
    try:
        return approve_external_action(task_id, approve=req.approve)
    except ExecutionError as e:
        raise HTTPException(422, detail=str(e))
```

- [ ] **Step 9: Pass initiative ID from board delegation build**

In `server/board/deliberation/orchestrator.py`, pass `initiative_id=session.initiative_id` into `build_delegation_plan` and `parse_delegation_plan`.

Update `build_delegation_plan` signature:

```python
async def build_delegation_plan(
    self,
    *,
    user_query: str,
    synthesis_content: str,
    session_id: str,
    query_type: str,
    complexity: str,
    initiative_id: str | None = None,
) -> dict[str, Any]:
```

Inside it:

```python
plan = parse_delegation_plan(
    first.content,
    session_id=session_id,
    initiative_id=initiative_id,
)
```

- [ ] **Step 10: Run execution tests**

Run:

```bash
uv run pytest \
  tests/test_execution_contract.py::test_delegation_plan_carries_initiative_and_external_action_fields \
  tests/test_api_cli_contract.py::ApiExecutionContractTest \
  -q
```

Expected: PASS.

- [ ] **Step 11: Commit execution linkage**

Run:

```bash
git add server/execution/tasks.py server/execution/__init__.py server/api/routes/execution.py server/api/schemas.py server/board/deliberation/orchestrator.py tests/test_execution_contract.py tests/test_api_cli_contract.py
git commit -m "feat: link delegated tasks to initiatives"
```

Expected: commit contains initiative-aware tasks and external action approval.

---

## Task 5: Add Initiative Session/Task API Helpers

**Files:**
- Modify: `server/initiatives/store.py`
- Modify: `server/api/routes/initiatives.py`
- Test: `tests/test_initiatives_contract.py`

- [ ] **Step 1: Add failing route tests for initiative sessions/tasks**

Append:

```python
async def test_initiative_sessions_and_tasks_routes(self):
    created = await initiative_routes.create_initiative_route(
        InitiativeCreateRequest(
            title="Linked work",
            objective="Verify session and task routes.",
            success_criteria=["Links visible"],
            departments=["engineering"],
        )
    )
    await initiative_routes.create_initiative_link_route(
        created["id"],
        InitiativeLinkRequest(
            target_type="board_session",
            target_id="board_1700000001",
            relationship="output",
        ),
    )

    sessions = await initiative_routes.list_initiative_sessions_route(created["id"])
    assert sessions["session_ids"] == ["board_1700000001"]

    tasks = await initiative_routes.list_initiative_tasks_route(created["id"])
    assert tasks["initiative_id"] == created["id"]
    assert tasks["tasks"] == []
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run pytest tests/test_initiatives_contract.py::InitiativeApiContractTest::test_initiative_sessions_and_tasks_routes -q
```

Expected: FAIL because routes are missing.

- [ ] **Step 3: Add store helper for linked session IDs**

In `server/initiatives/store.py`, add:

```python
def list_linked_session_ids(initiative_id: str, *, db_path: Path | None = None) -> list[str]:
    links = list_links(initiative_id, db_path=db_path)
    return [
        str(link["target_id"])
        for link in links
        if link.get("target_type") == "board_session"
    ]
```

Export it from `server/initiatives/__init__.py`.

- [ ] **Step 4: Add routes**

In `server/api/routes/initiatives.py`, import:

```python
from server.execution import get_delegated_tasks_for_initiative
from server.initiatives import list_linked_session_ids
```

Add:

```python
@router.get("/initiatives/{initiative_id}/sessions")
async def list_initiative_sessions_route(initiative_id: str):
    if not get_initiative(initiative_id):
        raise HTTPException(404, detail=f"Initiative not found: {initiative_id}")
    return {
        "initiative_id": initiative_id,
        "session_ids": list_linked_session_ids(initiative_id),
    }


@router.get("/initiatives/{initiative_id}/tasks")
async def list_initiative_tasks_route(initiative_id: str):
    if not get_initiative(initiative_id):
        raise HTTPException(404, detail=f"Initiative not found: {initiative_id}")
    return {
        "initiative_id": initiative_id,
        "tasks": get_delegated_tasks_for_initiative(initiative_id),
    }
```

- [ ] **Step 5: Run route tests**

Run:

```bash
uv run pytest tests/test_initiatives_contract.py::InitiativeApiContractTest::test_initiative_sessions_and_tasks_routes -q
```

Expected: PASS.

- [ ] **Step 6: Commit initiative route helpers**

Run:

```bash
git add server/initiatives server/api/routes/initiatives.py tests/test_initiatives_contract.py
git commit -m "feat: expose initiative sessions and tasks"
```

Expected: commit contains session/task helper routes.

---

## Task 6: Add Marketing Execution Unit And Agent

**Files:**
- Modify: `server/execution/agents.py`
- Modify: `server/execution/units.py`
- Test: `tests/test_execution_contract.py`

- [ ] **Step 1: Add failing marketing tests**

In `tests/test_execution_contract.py`, add:

```python
def test_marketing_execution_agent_is_active_and_strategy_accountable():
    from server.execution import list_execution_agents, list_execution_units
    from server.execution.tasks import parse_delegation_plan

    agents = {agent["id"]: agent for agent in list_execution_agents()}
    assert "marketing_lead" in agents
    assert agents["marketing_lead"]["execution_unit_id"] == "marketing"
    assert "campaign_planning" in agents["marketing_lead"]["capabilities"]

    units = {unit["id"]: unit for unit in list_execution_units()}
    assert "marketing" in units

    plan = parse_delegation_plan(
        """### Delegation Plan
```json
{"tasks": [{"title": "Draft campaign", "objective": "Prepare launch campaign.", "execution_unit_id": "marketing"}]}
```""",
        session_id="board_1700000001",
        initiative_id="init_1700000000000",
    )
    task = plan["tasks"][0]
    assert task["execution_unit_id"] == "marketing"
    assert task["manager_agent_id"] == "marketing_lead"
    assert task["accountable_board_member_id"] == "strategist"
```

- [ ] **Step 2: Run test to verify failure**

Run:

```bash
uv run pytest tests/test_execution_contract.py::test_marketing_execution_agent_is_active_and_strategy_accountable -q
```

Expected: FAIL because marketing unit and agent are missing.

- [ ] **Step 3: Add marketing execution agent**

In `server/execution/agents.py`, add before finance:

```python
ExecutionAgent(
    id="marketing_lead",
    title="Marketing Lead Agent",
    execution_unit_id="marketing",
    role="Owns campaign planning, outreach drafts, distribution experiments, and result analysis.",
    capabilities=["campaign_planning", "outreach_drafts", "content_planning", "distribution_experiments", "marketing_analytics"],
    system_prompt="You convert strategy decisions into approval-gated marketing execution work.",
    allowed_tools=["files", "web_search"],
    default_approval_required=True,
    max_parallel_subagents=2,
    subagent_templates=_templates(
        ("campaign_planner", "Campaign Planner Agent", "Plan campaign steps and assets.", ["files"], "Campaign plan with channels, assets, and approval gates."),
        ("distribution_analyst", "Distribution Analyst Agent", "Analyze channels and experiment results.", ["web_search", "files"], "Distribution analysis with next experiment recommendation."),
    ),
    benchmark_queries=["What is the smallest marketing experiment that can produce signal?"],
),
```

- [ ] **Step 4: Verify marketing unit registry derives from agents**

`server/execution/units.py` already derives `EXECUTION_UNITS` from `EXECUTION_AGENTS`:

```python
EXECUTION_UNITS = [
    ExecutionUnit(
        id=agent.execution_unit_id,
        title=agent.title.replace(" Agent", " Unit"),
        description=agent.role,
        capabilities=agent.capabilities,
        manager_agent_id=agent.id,
        active=agent.active,
    )
    for agent in EXECUTION_AGENTS
]
```

Do not add a separate manual marketing unit list. The `marketing_lead` agent from Step 3 creates the marketing unit.

- [ ] **Step 5: Map marketing unit to strategist**

In `server/execution/tasks.py`, update `BOARD_MEMBER_BY_UNIT`:

```python
"marketing": "strategist",
```

Update `_infer_execution_unit` keyword map:

```python
("marketing", ["marketing", "campaign", "outreach", "content", "distribution", "launch"]),
```

Place marketing before strategy so campaign/outreach tasks do not fall into general strategy.

- [ ] **Step 6: Run marketing tests**

Run:

```bash
uv run pytest tests/test_execution_contract.py::test_marketing_execution_agent_is_active_and_strategy_accountable -q
```

Expected: PASS.

- [ ] **Step 7: Commit marketing execution unit**

Run:

```bash
git add server/execution/agents.py server/execution/units.py server/execution/tasks.py tests/test_execution_contract.py
git commit -m "feat: add marketing execution unit"
```

Expected: commit contains marketing agent/unit and inference mapping.

---

## Task 7: Add Frontend Initiative Types And API Client

**Files:**
- Create: `ui/src/domains/initiatives/index.ts`
- Modify: `ui/src/shared/types.ts`
- Modify: `ui/src/shared/api.ts`
- Test: `ui` typecheck/build command

- [ ] **Step 1: Add initiative frontend types**

Create `ui/src/domains/initiatives/index.ts`:

```typescript
import { API } from '../../shared/api';

export type InitiativeStatus = 'draft' | 'active' | 'closed';
export type FounderOutcome = 'success' | 'failure' | 'mixed';

export type InitiativeLink = {
  id: string;
  initiative_id: string;
  target_type: 'sotb_entry' | 'initiative' | 'board_session' | 'delegated_task' | 'artifact';
  target_id: string;
  relationship: 'context' | 'output' | 'carryover' | 'evidence' | 'artifact';
  created_at: string;
};

export type CarryoverDecision = {
  task_id: string;
  decision: 'carry_over' | 'abandon' | 'backlog';
  target_initiative_id?: string | null;
};

export type InitiativeCloseout = {
  initiative_id: string;
  founder_outcome: FounderOutcome;
  founder_notes: string;
  retrospective_session_id?: string | null;
  memory_proposals: string[];
  carryover_decisions: CarryoverDecision[];
  closed_at: string;
};

export type Initiative = {
  id: string;
  title: string;
  objective: string;
  status: InitiativeStatus;
  timebox_start: string;
  timebox_end: string;
  success_criteria: string[];
  departments: string[];
  approval_state: 'draft' | 'approved';
  created_from: 'manual' | 'founder_command' | 'board_suggestion';
  source_session_id?: string | null;
  created_at: string;
  updated_at: string;
  links?: InitiativeLink[];
  closeout?: InitiativeCloseout;
};

export async function loadInitiatives(): Promise<Initiative[]> {
  const response = await fetch(`${API}/initiatives`);
  if (!response.ok) throw new Error('Failed to load initiatives.');
  return response.json();
}

export async function createInitiative(payload: {
  title: string;
  objective: string;
  success_criteria?: string[];
  departments?: string[];
  created_from?: 'manual' | 'founder_command' | 'board_suggestion';
}): Promise<Initiative> {
  const response = await fetch(`${API}/initiatives`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error('Failed to create initiative.');
  return response.json();
}

export async function activateInitiative(initiativeId: string): Promise<Initiative> {
  const response = await fetch(`${API}/initiatives/${encodeURIComponent(initiativeId)}/activate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ approve: true }),
  });
  if (!response.ok) throw new Error('Failed to activate initiative.');
  return response.json();
}

export async function closeInitiative(
  initiativeId: string,
  payload: {
    founder_outcome: FounderOutcome;
    founder_notes: string;
    retrospective_session_id?: string | null;
    memory_proposals?: string[];
    carryover_decisions?: CarryoverDecision[];
  },
): Promise<Initiative> {
  const response = await fetch(`${API}/initiatives/${encodeURIComponent(initiativeId)}/closeout`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok) throw new Error('Failed to close initiative.');
  return response.json();
}
```

- [ ] **Step 2: Extend shared types**

In `ui/src/shared/types.ts`, update:

```typescript
export type Tab = 'governance' | 'portfolio' | 'performance' | 'initiatives';
```

Add fields to `DelegatedTask`:

```typescript
  initiative_id?: string | null;
  external_action_required?: boolean;
  external_action_type?: 'outreach' | 'publish' | 'deploy' | 'spend' | 'none';
  external_action_approved?: boolean;
```

Add fields to `BoardSession`:

```typescript
  initiative_id?: string | null;
  initiative_mode?: 'ad_hoc' | 'attach' | 'create_draft';
```

- [ ] **Step 3: Extend streamDeliberation params**

In `ui/src/shared/api.ts`, update `streamDeliberation` params:

```typescript
    initiative_id?: string | null;
    initiative_mode?: 'ad_hoc' | 'attach' | 'create_draft';
```

- [ ] **Step 4: Run frontend typecheck/build**

Run:

```bash
npm --prefix ui run check
```

Expected: TypeScript check and Vite build succeed.

- [ ] **Step 5: Commit frontend API types**

Run:

```bash
git add ui/src/domains/initiatives/index.ts ui/src/shared/types.ts ui/src/shared/api.ts
git commit -m "feat: add initiative frontend API types"
```

Expected: commit contains frontend types and API client.

---

## Task 8: Add Minimal Initiative Cockpit UI

**Files:**
- Create: `ui/src/domains/initiatives/InitiativeCockpit.tsx`
- Modify: `ui/src/App.tsx`
- Modify: `ui/src/shared/types.ts`
- Test: frontend build

- [ ] **Step 1: Create cockpit component**

Create `ui/src/domains/initiatives/InitiativeCockpit.tsx`:

```tsx
import { CheckCircle2, CircleDot, Plus, XCircle } from 'lucide-react';
import type { Initiative } from './index';

type Props = {
  initiatives: Initiative[];
  activeInitiativeId: string | null;
  onSelect: (id: string | null) => void;
  onCreateDraft: () => void;
  onActivate: (id: string) => void;
  onClose: (id: string, outcome: 'success' | 'failure' | 'mixed') => void;
};

export function InitiativeCockpit({
  initiatives,
  activeInitiativeId,
  onSelect,
  onCreateDraft,
  onActivate,
  onClose,
}: Props) {
  const active = initiatives.find((item) => item.id === activeInitiativeId) ?? null;

  return (
    <section className="initiative-cockpit" aria-label="Initiative cockpit">
      <div className="initiative-cockpit__header">
        <div>
          <p className="eyebrow">Initiative</p>
          <h2>{active ? active.title : 'Ad hoc board session'}</h2>
        </div>
        <button type="button" className="icon-button" onClick={onCreateDraft} title="Create draft initiative">
          <Plus size={16} />
        </button>
      </div>

      <div className="initiative-cockpit__selector">
        <button
          type="button"
          className={!activeInitiativeId ? 'selected' : ''}
          onClick={() => onSelect(null)}
        >
          Ad hoc
        </button>
        {initiatives.map((initiative) => (
          <button
            key={initiative.id}
            type="button"
            className={initiative.id === activeInitiativeId ? 'selected' : ''}
            onClick={() => onSelect(initiative.id)}
          >
            {initiative.title}
          </button>
        ))}
      </div>

      {active ? (
        <div className="initiative-cockpit__body">
          <div className="initiative-cockpit__status">
            <CircleDot size={16} />
            <span>{active.status}</span>
            <span>{active.approval_state}</span>
          </div>
          <p>{active.objective}</p>
          <ul>
            {active.success_criteria.map((criterion) => (
              <li key={criterion}>{criterion}</li>
            ))}
          </ul>
          <div className="initiative-cockpit__actions">
            {active.status === 'draft' && (
              <button type="button" onClick={() => onActivate(active.id)}>
                <CheckCircle2 size={16} />
                Activate
              </button>
            )}
            {active.status !== 'closed' && (
              <>
                <button type="button" onClick={() => onClose(active.id, 'success')}>
                  <CheckCircle2 size={16} />
                  Close success
                </button>
                <button type="button" onClick={() => onClose(active.id, 'mixed')}>
                  <CircleDot size={16} />
                  Close mixed
                </button>
                <button type="button" onClick={() => onClose(active.id, 'failure')}>
                  <XCircle size={16} />
                  Close failure
                </button>
              </>
            )}
          </div>
        </div>
      ) : (
        <p className="initiative-cockpit__empty">This command will run without initiative memory or carryover tracking.</p>
      )}
    </section>
  );
}
```

- [ ] **Step 2: Wire cockpit state into App**

In `ui/src/App.tsx`, import:

```tsx
import {
  InitiativeCockpit,
  activateInitiative,
  closeInitiative,
  createInitiative,
  loadInitiatives,
  type Initiative,
} from './domains/initiatives';
```

Add state:

```tsx
const [initiatives, setInitiatives] = useState<Initiative[]>([]);
const [activeInitiativeId, setActiveInitiativeId] = useState<string | null>(null);
```

In the existing startup `useEffect`, add:

```tsx
loadInitiatives()
  .then((items) => {
    setInitiatives(items);
    const active = items.find((item) => item.status === 'active') ?? items[0] ?? null;
    setActiveInitiativeId(active?.id ?? null);
  })
  .catch(() => setInitiatives([]));
```

- [ ] **Step 3: Add cockpit handlers**

In `App`, add:

```tsx
async function createDraftInitiative() {
  const cleanQuery = query.trim();
  const created = await createInitiative({
    title: cleanQuery ? cleanQuery.slice(0, 80) : 'New initiative',
    objective: cleanQuery || 'Founder-created operating cycle.',
    success_criteria: [],
    departments: ['strategy', 'product', 'engineering'],
    created_from: cleanQuery ? 'founder_command' : 'manual',
  });
  setInitiatives((current) => [created, ...current]);
  setActiveInitiativeId(created.id);
}

async function activateSelectedInitiative(id: string) {
  const updated = await activateInitiative(id);
  setInitiatives((current) => current.map((item) => (item.id === id ? updated : item)));
}

async function closeSelectedInitiative(id: string, founder_outcome: 'success' | 'failure' | 'mixed') {
  const updated = await closeInitiative(id, {
    founder_outcome,
    founder_notes: `Closed from cockpit with outcome: ${founder_outcome}`,
    retrospective_session_id: session?.session_id ?? null,
    memory_proposals: session?.memory?.proposed_sotb_update ? [session.memory.proposed_sotb_update] : [],
    carryover_decisions: [],
  });
  setInitiatives((current) => current.map((item) => (item.id === id ? updated : item)));
}
```

- [ ] **Step 4: Pass initiative fields into board stream**

In `submitQuery`, when calling `streamDeliberation`, include:

```tsx
initiative_id: activeInitiativeId,
initiative_mode: activeInitiativeId ? 'attach' : 'ad_hoc',
```

- [ ] **Step 5: Render cockpit**

Place the cockpit near the command box or current governance page composition:

```tsx
<InitiativeCockpit
  initiatives={initiatives}
  activeInitiativeId={activeInitiativeId}
  onSelect={setActiveInitiativeId}
  onCreateDraft={createDraftInitiative}
  onActivate={activateSelectedInitiative}
  onClose={closeSelectedInitiative}
/>
```

- [ ] **Step 6: Add minimal CSS**

In `ui/src/index.css`, add:

```css
.initiative-cockpit {
  display: grid;
  gap: 12px;
  padding: 16px;
  border: 1px solid var(--border, #d8dee8);
  border-radius: 8px;
  background: var(--surface, #ffffff);
}

.initiative-cockpit__header,
.initiative-cockpit__actions,
.initiative-cockpit__status {
  display: flex;
  align-items: center;
  gap: 8px;
}

.initiative-cockpit__header {
  justify-content: space-between;
}

.initiative-cockpit__selector {
  display: flex;
  gap: 8px;
  overflow-x: auto;
}

.initiative-cockpit__selector button.selected {
  border-color: #111827;
  background: #111827;
  color: white;
}

.initiative-cockpit__body {
  display: grid;
  gap: 10px;
}

.initiative-cockpit__empty {
  color: #667085;
  margin: 0;
}
```

- [ ] **Step 7: Run frontend build**

Run:

```bash
npm --prefix ui run check
```

Expected: TypeScript check and Vite build succeed.

- [ ] **Step 8: Commit cockpit UI**

Run:

```bash
git add ui/src/domains/initiatives/InitiativeCockpit.tsx ui/src/App.tsx ui/src/index.css
git commit -m "feat: add initiative cockpit"
```

Expected: commit contains cockpit component and App wiring.

---

## Task 9: Add End-To-End API Smoke Coverage

**Files:**
- Modify: `tests/test_api_cli_contract.py`
- Modify: `scripts/smoke_browser.py` or create no browser code if Playwright smoke is out of scope

- [ ] **Step 1: Add API vertical-slice test**

In `tests/test_api_cli_contract.py`, add:

```python
class InitiativeVerticalSliceContractTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "ledger.db"
        import server.initiatives as initiatives
        import server.execution as execution

        self._old_init_db = initiatives._DEFAULT_DB_PATH
        self._old_exec_db = execution._DEFAULT_DB_PATH
        initiatives._DEFAULT_DB_PATH = self.db_path
        execution._DEFAULT_DB_PATH = self.db_path

    def tearDown(self):
        import server.initiatives as initiatives
        import server.execution as execution

        initiatives._DEFAULT_DB_PATH = self._old_init_db
        execution._DEFAULT_DB_PATH = self._old_exec_db
        self.tmpdir.cleanup()

    async def test_initiative_api_vertical_slice(self):
        from server.api.routes.initiatives import (
            activate_initiative_route,
            closeout_initiative_route,
            create_initiative_route,
            list_initiative_tasks_route,
        )
        from server.api.schemas import (
            InitiativeActivateRequest,
            InitiativeCloseoutRequest,
            InitiativeCreateRequest,
        )

        created = await create_initiative_route(InitiativeCreateRequest(
            title="Founder command loop",
            objective="Run initiative-native task tracking.",
            success_criteria=["Task visible"],
            departments=["strategy", "engineering", "marketing"],
        ))
        active = await activate_initiative_route(created["id"], InitiativeActivateRequest())
        self.assertEqual("active", active["status"])

        from server.execution import parse_delegation_plan, record_delegation_plan
        plan = parse_delegation_plan(
            """### Delegation Plan
```json
{"tasks": [{"title": "Draft outreach", "objective": "Prepare message.", "execution_unit_id": "marketing", "external_action_type": "outreach"}]}
```""",
            session_id="board_1700000001",
            initiative_id=created["id"],
        )
        record_delegation_plan(plan)

        tasks = await list_initiative_tasks_route(created["id"])
        self.assertEqual(created["id"], tasks["tasks"][0]["initiative_id"])
        self.assertEqual("outreach", tasks["tasks"][0]["external_action_type"])

        closed = await closeout_initiative_route(created["id"], InitiativeCloseoutRequest(
            founder_outcome="mixed",
            founder_notes="Task needs carryover.",
            retrospective_session_id="board_1700000002",
            memory_proposals=[],
            carryover_decisions=[{
                "task_id": tasks["tasks"][0]["id"],
                "decision": "backlog",
            }],
        ))
        self.assertEqual("closed", closed["status"])
        self.assertEqual("backlog", closed["closeout"]["carryover_decisions"][0]["decision"])
```

- [ ] **Step 2: Run vertical slice test**

Run:

```bash
uv run pytest tests/test_api_cli_contract.py::InitiativeVerticalSliceContractTest -q
```

Expected: PASS.

- [ ] **Step 3: Run backend initiative-related suite**

Run:

```bash
uv run pytest \
  tests/test_initiatives_contract.py \
  tests/test_execution_contract.py \
  tests/test_board_session_shape.py \
  tests/test_api_cli_contract.py \
  -q
```

Expected: PASS.

- [ ] **Step 4: Commit vertical slice smoke tests**

Run:

```bash
git add tests/test_api_cli_contract.py
git commit -m "test: cover initiative vertical slice"
```

Expected: commit contains initiative API vertical-slice test.

---

## Task 10: Final Verification And Documentation Update

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture/runtime-flow.md`
- Modify: `docs/architecture/README.md`

- [ ] **Step 1: Update runtime documentation**

In `docs/architecture/runtime-flow.md`, add this initiative section before deliberation:

````markdown
## Initiative-Native Founder Command Loop

```text
founder command
  -> initiative route suggestion
  -> founder override/approval
  -> board deliberation with initiative_id or ad hoc mode
  -> linked session JSON
  -> linked delegation tasks
  -> external action approvals
  -> closeout with founder outcome and carryover decisions
  -> board retrospective memory proposals
```
````

- [ ] **Step 2: Update architecture overview**

In `docs/architecture/README.md`, add a backend domain row:

```markdown
| Initiatives | `server/initiatives/` | Time-boxed operating cycles, links, closeouts, carryovers |
```

Add a frontend domain row:

```markdown
| Initiatives UI | `ui/src/domains/initiatives/` | Initiative cockpit, initiative API types, closeout controls |
```

- [ ] **Step 3: Update README**

In `README.md`, add a short "Initiatives" section:

```markdown
## Initiatives

Initiatives are the durable operating cycle for the solo-company OS. A board
session can run ad hoc, attach to an existing initiative, or create a draft
initiative. Initiative-owned sessions can produce delegated tasks, artifacts,
memory proposals, and closeout carryovers.
```

- [ ] **Step 4: Run final backend tests**

Run:

```bash
uv run pytest -q
```

Expected: all non-live tests pass.

- [ ] **Step 5: Run frontend build/typecheck**

Run:

```bash
npm --prefix ui run check
```

Expected: TypeScript check and Vite build succeed.

- [ ] **Step 6: Commit docs and final verification**

Run:

```bash
git add README.md docs/architecture/runtime-flow.md docs/architecture/README.md
git commit -m "docs: describe initiative-native workflow"
```

Expected: commit contains documentation only.

---

## Self-Review Notes

Spec coverage:

- Initiative-native runtime object: Tasks 1, 2, 3, 5.
- Manual and auto-drafted initiatives: Tasks 1, 2, 8.
- Ad hoc sessions preserved: Tasks 3 and 8.
- `initiative_id` through sessions/tasks/projection: Tasks 3 and 4.
- Marketing execution unit accountable to strategist: Task 6.
- Web-first cockpit: Tasks 7 and 8.
- Closeout with founder outcome, notes, memory proposals, and carryover: Tasks 1, 2, 5, 8, 9.
- External-action approval gates: Task 4.
- Baseline reliability risk: Task 0.

Plan constraints:

- Each task has a focused file set.
- Each feature task starts with failing tests.
- Each task ends with focused verification and a commit.
- The plan preserves ad hoc board behavior while adding initiative-native paths.
