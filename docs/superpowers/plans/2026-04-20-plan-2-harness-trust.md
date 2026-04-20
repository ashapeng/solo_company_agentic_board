# Plan 2 — Harness Trust Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the self-evolving harness trustworthy by (a) decoupling the verifier model from the chairman, (b) snapshotting approved diffs so apply is deterministic, (c) adding a shadow regression watcher that auto-reverts on post-apply score degradation, (d) splitting verifier and feedback signals so tuner E cannot promote a model one path dislikes, and (e) stamping provider/activation metadata so tuners can be audited.

**Architecture:** Additive modules (`config_provider`, `shadow`, `meta`) plus ledger schema extension via `_ensure_columns`. Reviews change from "re-run tuners at apply" to "persist diff at approval, apply diff at apply." Shadow watcher reads post-apply ledger windows and writes rollbacks when mean verification score regresses.

**Tech Stack:** Python 3.12, SQLite (existing ledger), stdlib `statistics`, FastAPI, unittest.

**Spec:** `docs/superpowers/specs/2026-04-20-plan-2-harness-trust-design.md`

---

## Cross-cutting execution policy (applies to every task)

1. **Phase 0 before code.** Task 1 commits failing repro tests.
2. **Root-cause only.** No silent `except`. Shadow rollback that oscillates → disable via env, diagnose baseline selection.
3. **3-attempt cap → `git reset --hard` to last green.**
4. **YAGNI.** SQLite + JSON snapshots. No MLflow, no feature store, no scheduler library. `asyncio.create_task` is enough for background shadow.
5. **Done criteria.** All new tests green; full `unittest discover` green; manual apply-regress-revert loop confirmed in tmp DB; CLAUDE.md + .env.example note the env override.

## Sub-agent usage

- **Explore agent** (thoroughness: `medium`) before Task 4 — map every call to `query_outcomes`, every reader of `HarnessConfig.version`, every test using a tmp ledger fixture.
- **superpowers:code-reviewer** after Task 7 (shadow watcher math).
- **superpowers:code-reviewer** after Task 8 (split quality signal contract).

## File structure map

| File | Action | Responsibility |
|---|---|---|
| `server/harness/config_provider.py` | **Create** | `provider_of(model_id)` helper |
| `server/board/config.py` | **Modify** | Default verification model change; startup guard |
| `server/board/deliberation/verification.py` | **Modify** | Populate `verifier_model` + `verifier_provider` in result |
| `server/board/projection.py` | **Modify** | Include new fields in `verification_to_dict` |
| `server/harness/ledger.py` | **Modify** | New columns; `harness_config_activations` table; `snapshot_activation`, `revert_activation`, `rolling_mean` helpers |
| `server/harness/reviews.py` | **Modify** | Snapshot at approval; apply from snapshot; stamp `applied_at`/`reverted_at` |
| `server/harness/shadow.py` | **Create** | Post-apply watcher + auto-revert |
| `server/harness/model_assignment.py` | **Modify** | Split quality score; reject promotion on signal disagreement |
| `server/harness/meta.py` | **Create** | Per-tuner accuracy helper |
| `server/api/routes/harness.py` | **Modify** | Trigger shadow watch after apply |
| `tests/test_harness_trust_contract.py` | **Create** | All Phase 0 + cross-step assertions |
| `tests/test_tuner_contract.py` | **Modify** | Add split-quality case |
| `tests/test_ledger_contract.py` | **Modify** | Cover new columns |
| `CLAUDE.md` | **Modify** | Document `AGENTIC_BOARD_ALLOW_SAME_VERIFIER` + `AGENTIC_BOARD_SHADOW_DISABLED` |
| `.env.example` | **Modify** | Same env flags |

---

## Task 1: Phase 0 repro tests

**Files:**
- Create: `tests/test_harness_trust_contract.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_harness_trust_contract.py
"""Phase 0 reproduction tests for the Harness Trust plan.

Every test in this module MUST fail on current main.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path


class VerifierDecouplingTest(unittest.TestCase):
    def test_default_verifier_provider_differs_from_chairman(self):
        os.environ.pop("AGENTIC_BOARD_ALLOW_SAME_VERIFIER", None)
        os.environ.pop("CHAIRMAN_MODEL", None)
        os.environ.pop("VERIFICATION_MODEL", None)
        from server.board.config import get_chairman_model, get_verification_model
        from server.harness.config_provider import provider_of

        self.assertNotEqual(
            provider_of(get_chairman_model()),
            provider_of(get_verification_model()),
            "verifier and chairman must use distinct providers",
        )


class ApplyUsesSnapshotTest(unittest.TestCase):
    def test_apply_uses_snapshot_not_live_ledger(self):
        from server.harness.reviews import (
            run_harness_review,
            approve_harness_review,
            apply_harness_review,
        )
        from server.harness import reviews as reviews_module

        # run + approve captures a snapshot
        review = run_harness_review(dry_run=True)
        approved = approve_harness_review(review["id"], approve=True)
        self.assertIn("snapshot", approved, "approved review must carry a diff snapshot")

        # applying uses snapshot; applied_reports equals snapshot
        applied = apply_harness_review(review["id"])
        self.assertEqual(applied.get("status"), "applied")
        self.assertEqual(
            applied.get("applied_reports"),
            approved["snapshot"],
            "apply must write the approved snapshot, not re-run tuners",
        )
        self.assertIn("applied_at", applied)


class ShadowRollbackTest(unittest.TestCase):
    def test_shadow_reverts_after_regression(self):
        from server.harness.shadow import watch_after_apply
        from server.harness import ledger as ledger_module

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "ledger.db"
            ledger_module.init_db(db_path)

            # seed baseline: 20 sessions, verification_score=8
            self._seed(db_path, scores=[8] * 20)

            # synthetic activation row + post-apply regression: scores=4
            self._activate(db_path, review_id="rev1", snapshot={"token_budgets": {"changes": []}})
            self._seed(db_path, scores=[4] * 10)

            outcome = watch_after_apply(
                review_id="rev1", db_path=db_path, window=10, regression_threshold=1.0,
            )

            self.assertTrue(outcome["reverted"], "must flip reverted=True on regression")
            self.assertIn("reason", outcome)

    def _seed(self, db_path: Path, scores):
        from server.harness.ledger import record_session

        class _Metrics:
            def by_stage(self, _): return []
            def total_cost_estimate(self): return 0.0

        class _Session:
            def __init__(self, sid, score):
                self.session_id = sid
                self.classification = {"query_type": "strategic", "complexity": "moderate",
                                       "relevant_member_ids": []}
                self.verification = {"score": score, "passed": score >= 7}
                self.memory = {}
                self.metrics = _Metrics()
                self.stage1_responses = []
                self.stage2_responses = []
                self.delegation_plan = {}
                self.clarification = {}

        import itertools
        counter = itertools.count(int.from_bytes(os.urandom(2), "big"))
        for score in scores:
            sid = f"board_{next(counter)}"
            try:
                record_session(_Session(sid, score), config_version=1, db_path=db_path)
            except Exception:
                pass

    def _activate(self, db_path: Path, review_id: str, snapshot):
        import json
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS harness_config_activations (
                    review_id TEXT PRIMARY KEY,
                    activated_at TEXT,
                    reverted_at TEXT,
                    snapshot TEXT,
                    previous_snapshot TEXT
                )"""
            )
            conn.execute(
                "INSERT OR REPLACE INTO harness_config_activations "
                "(review_id, activated_at, snapshot, previous_snapshot) VALUES (?, ?, ?, ?)",
                (review_id, "2026-04-20T00:00:00Z", json.dumps(snapshot), json.dumps({})),
            )
            conn.commit()
        finally:
            conn.close()


class SplitQualitySignalTest(unittest.TestCase):
    def test_negative_feedback_blocks_promotion_despite_high_verifier_score(self):
        from server.harness.model_assignment import _apply_model_assignment_tuning
        from server.harness.config import HarnessConfig

        outcomes = [
            {"query_type": "product", "verification_score": 9,
             "feedback_rating": "negative",
             "models_used": '{"researcher": "kimi/kimi-k2.5"}'},
            {"query_type": "product", "verification_score": 9,
             "feedback_rating": "negative",
             "models_used": '{"researcher": "kimi/kimi-k2.5"}'},
            {"query_type": "product", "verification_score": 9,
             "feedback_rating": "negative",
             "models_used": '{"researcher": "kimi/kimi-k2.5"}'},
            {"query_type": "product", "verification_score": 7,
             "feedback_rating": "positive",
             "models_used": '{"researcher": "deepseek/deepseek-chat"}'},
            {"query_type": "product", "verification_score": 7,
             "feedback_rating": "positive",
             "models_used": '{"researcher": "deepseek/deepseek-chat"}'},
            {"query_type": "product", "verification_score": 7,
             "feedback_rating": "positive",
             "models_used": '{"researcher": "deepseek/deepseek-chat"}'},
        ]
        config = HarnessConfig()
        changes, _, _ = _apply_model_assignment_tuning(
            config, outcomes, min_samples=3, min_score_delta=0.0,
        )
        promoted = [c.new_model for c in changes if c.member_id == "researcher"]
        self.assertNotIn(
            "kimi/kimi-k2.5",
            promoted,
            "model with only negative feedback must not be promoted",
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run; confirm all four FAIL**

Run: `uv run python -m unittest tests.test_harness_trust_contract -v`

Expected: four FAIL (ImportErrors for `config_provider`, `shadow`;
`apply_uses_snapshot` fails — `snapshot` key absent;
`negative_feedback` fails — current code promotes on verifier score alone).

- [ ] **Step 3: Commit**

```bash
git add tests/test_harness_trust_contract.py
git commit -m "test: phase 0 repro for harness trust (verifier, snapshot, shadow, split)"
```

---

## Task 2: provider helper + startup guard

**Files:**
- Create: `server/harness/config_provider.py`
- Modify: `server/board/config.py`

- [ ] **Step 1: Create provider helper**

```python
# server/harness/config_provider.py
"""Infer provider tag from a board model_id."""

from __future__ import annotations


def provider_of(model_id: str) -> str:
    """Return the provider prefix for a model_id.

    Examples:
        'kimi/kimi-k2.5'            -> 'kimi'
        'deepseek/deepseek-chat'    -> 'deepseek'
        'glm/glm-4'                 -> 'glm'
        'zai/...'                   -> 'zai'
        'qwen/...'                  -> 'qwen'
        'openrouter:anthropic/claude-3.5-sonnet' -> 'openrouter'
    """
    if not model_id:
        return "unknown"
    if ":" in model_id:
        return model_id.split(":", 1)[0].strip().lower() or "unknown"
    if "/" in model_id:
        return model_id.split("/", 1)[0].strip().lower() or "unknown"
    return model_id.strip().lower() or "unknown"
```

- [ ] **Step 2: Change default verification model**

In `server/board/config.py`:

```python
DEFAULT_VERIFICATION_MODEL = "deepseek/deepseek-chat"
```

(was `"kimi/kimi-k2.5"` — chairman stays on Kimi.)

- [ ] **Step 3: Add startup guard**

Append to the bottom of `server/board/config.py`:

```python
def _assert_verifier_decoupled() -> None:
    """Refuse to boot if verifier and chairman share a provider."""
    import os
    if os.getenv("AGENTIC_BOARD_ALLOW_SAME_VERIFIER") == "1":
        return
    from server.harness.config_provider import provider_of
    chair = provider_of(get_chairman_model())
    verifier = provider_of(get_verification_model())
    if chair == verifier:
        raise RuntimeError(
            f"Chairman and verifier share provider '{chair}'. "
            "Set VERIFICATION_MODEL to a different provider, or export "
            "AGENTIC_BOARD_ALLOW_SAME_VERIFIER=1 to override."
        )


_assert_verifier_decoupled()
```

- [ ] **Step 4: Document env flag**

In `CLAUDE.md`, under the Config section, add:

```markdown
- Verifier must use a different provider than the chairman. To run both on
  the same provider during local experimentation, set
  `AGENTIC_BOARD_ALLOW_SAME_VERIFIER=1`.
```

In `.env.example`, add:

```
# AGENTIC_BOARD_ALLOW_SAME_VERIFIER=1
# AGENTIC_BOARD_SHADOW_DISABLED=1
```

- [ ] **Step 5: Run the verifier test; confirm green**

Run: `uv run python -m unittest tests.test_harness_trust_contract.VerifierDecouplingTest -v`

Expected: PASS.

- [ ] **Step 6: Run full suite**

Run: `uv run python -m unittest discover -s tests -v`

If a test imports `server.board.config` with identical chairman/verifier
env (rare), it will now raise on import. Either unset the env in that test
or use the `AGENTIC_BOARD_ALLOW_SAME_VERIFIER=1` override — root-cause the
test setup, don't weaken the guard.

- [ ] **Step 7: Commit**

```bash
git add server/harness/config_provider.py server/board/config.py CLAUDE.md .env.example
git commit -m "feat(harness): enforce distinct verifier/chairman providers at boot"
```

---

## Task 3: Ledger schema extension

**Files:**
- Modify: `server/harness/ledger.py`
- Modify: `tests/test_ledger_contract.py`

- [ ] **Step 1: Extend schema**

In `server/harness/ledger.py`, update `_ensure_columns`:

```python
def _ensure_columns(conn: sqlite3.Connection) -> None:
    existing = {
        row[1]
        for row in conn.execute("PRAGMA table_info(session_outcomes)").fetchall()
    }
    additions = {
        "parse_warnings": "TEXT",
        "structured_output_failed": "INTEGER",
        "truncation_detected": "INTEGER",
        "blank_member_responses": "TEXT",
        "clarification_questions_count": "INTEGER",
        "clarification_answers_count": "INTEGER",
        "delegation_task_count": "INTEGER",
        "verifier_model": "TEXT",
        "verifier_provider": "TEXT",
        "chairman_provider": "TEXT",
        "applied_review_id": "TEXT",
    }
    for column, column_type in additions.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE session_outcomes ADD COLUMN {column} {column_type}")

    # activation ledger
    conn.execute("""
        CREATE TABLE IF NOT EXISTS harness_config_activations (
            review_id         TEXT PRIMARY KEY,
            activated_at      TEXT NOT NULL,
            reverted_at       TEXT,
            snapshot          TEXT NOT NULL,
            previous_snapshot TEXT,
            reason            TEXT
        )
    """)
```

- [ ] **Step 2: Extend `record_session` to persist new columns**

Find the `INSERT INTO session_outcomes` block. Add three extra columns to
the SQL and three extra values. Replace the INSERT statement with:

```python
    conn.execute(
        """INSERT INTO session_outcomes (
            session_id, timestamp, query_type, complexity,
            members_routed, members_responded, member_failures,
            models_used,
            stage1_tokens, stage2_tokens, stage3_tokens,
            stage1_latency, stage2_latency, stage3_latency,
            verification_score, verification_passed, revision_needed,
            total_cost_usd,
            sotb_update_proposed, sotb_update_approved,
            feedback_rating, feedback_note,
            parse_warnings, structured_output_failed,
            truncation_detected, blank_member_responses,
            clarification_questions_count, clarification_answers_count,
            delegation_task_count,
            harness_config_version,
            verifier_model, verifier_provider, chairman_provider, applied_review_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            session.session_id,
            datetime.now(timezone.utc).isoformat(),
            classification.get("query_type"),
            classification.get("complexity"),
            json.dumps(members_routed),
            json.dumps(members_responded),
            json.dumps([{"member_id": mid} for mid in failures]),
            json.dumps(models_used),
            stage_tokens.get(1, 0),
            stage_tokens.get(2, 0),
            stage_tokens.get(3, 0),
            stage_latency.get(1, 0.0),
            stage_latency.get(2, 0.0),
            stage_latency.get(3, 0.0),
            v_score,
            v_passed,
            revision_needed,
            metrics.total_cost_estimate(),
            sotb_proposed,
            None,
            None,
            None,
            json.dumps(parse_warnings),
            structured_output_failed,
            truncation_detected,
            json.dumps(blank_member_responses),
            len(clarification_questions),
            answers_count,
            len(delegation_tasks) if isinstance(delegation_tasks, list) else 0,
            config_version,
            verification.get("verifier_model"),
            verification.get("verifier_provider"),
            verification.get("chairman_provider"),
            _active_review_id(conn),
        ),
    )
```

Add helper at bottom of file:

```python
def _active_review_id(conn: sqlite3.Connection) -> str | None:
    row = conn.execute(
        "SELECT review_id FROM harness_config_activations "
        "WHERE reverted_at IS NULL ORDER BY activated_at DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None
```

- [ ] **Step 3: Add activation helpers**

Append:

```python
def snapshot_activation(
    review_id: str,
    snapshot: dict,
    previous_snapshot: dict | None,
    db_path: Path | None = None,
) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO harness_config_activations
               (review_id, activated_at, snapshot, previous_snapshot)
               VALUES (?, ?, ?, ?)""",
            (
                review_id,
                datetime.now(timezone.utc).isoformat(),
                json.dumps(snapshot),
                json.dumps(previous_snapshot or {}),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def revert_activation(
    review_id: str, reason: str, db_path: Path | None = None,
) -> dict | None:
    conn = _connect(db_path)
    try:
        row = conn.execute(
            "SELECT previous_snapshot FROM harness_config_activations WHERE review_id = ?",
            (review_id,),
        ).fetchone()
        if not row:
            return None
        previous_snapshot = json.loads(row[0] or "null")
        conn.execute(
            "UPDATE harness_config_activations SET reverted_at = ?, reason = ? WHERE review_id = ?",
            (datetime.now(timezone.utc).isoformat(), reason, review_id),
        )
        conn.commit()
        return previous_snapshot
    finally:
        conn.close()


def rolling_mean(
    field: str, *, limit: int, db_path: Path | None = None,
) -> tuple[float | None, int]:
    if field not in _NUMERIC_COLUMNS:
        raise LedgerError(f"Cannot roll non-numeric field: {field}")
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT {field} FROM session_outcomes "  # nosec B608
            "WHERE {field} IS NOT NULL ORDER BY timestamp DESC LIMIT ?".format(field=field),
            (limit,),
        ).fetchall()
        values = [row[0] for row in rows if row[0] is not None]
        if not values:
            return None, 0
        return sum(values) / len(values), len(values)
    finally:
        conn.close()
```

- [ ] **Step 4: Extend `tests/test_ledger_contract.py`** with column + activation coverage.

Add a new TestCase class:

```python
class LedgerExtensionsTest(unittest.TestCase):
    def test_new_columns_present(self):
        from server.harness.ledger import init_db, _connect
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "l.db"
            init_db(path)
            conn = _connect(path)
            try:
                cols = {r[1] for r in conn.execute("PRAGMA table_info(session_outcomes)").fetchall()}
            finally:
                conn.close()
        for c in ("verifier_model", "verifier_provider", "chairman_provider", "applied_review_id"):
            self.assertIn(c, cols)

    def test_activation_table_exists(self):
        from server.harness.ledger import init_db, _connect
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "l.db"
            init_db(path)
            conn = _connect(path)
            try:
                tables = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()}
            finally:
                conn.close()
        self.assertIn("harness_config_activations", tables)
```

- [ ] **Step 5: Run ledger tests**

Run: `uv run python -m unittest tests.test_ledger_contract -v`

Expected: all green including new cases.

- [ ] **Step 6: Commit**

```bash
git add server/harness/ledger.py tests/test_ledger_contract.py
git commit -m "feat(ledger): add verifier/activation columns and rolling_mean helper"
```

---

## Task 4: Verification result carries provider metadata

**Files:**
- Modify: `server/board/deliberation/verification.py`
- Modify: `server/board/projection.py`

- [ ] **Step 1: Extend `VerificationResult` dataclass**

```python
@dataclass
class VerificationResult:
    score: int
    passed: bool
    deficiencies: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    status: str = "completed"
    verifier_model: str | None = None
    verifier_provider: str | None = None
    chairman_provider: str | None = None
```

- [ ] **Step 2: Populate in `verify_synthesis`**

At the top of the function, capture the models:

```python
from server.board.config import get_verification_model, get_chairman_model
from server.harness.config_provider import provider_of

verifier_model = get_verification_model()
verifier_provider = provider_of(verifier_model)
chairman_provider = provider_of(get_chairman_model())
```

Pass these to both the success `return VerificationResult(...)` and the
exception-path return. Example on the success branch:

```python
return VerificationResult(
    score=score,
    passed=score >= resolve_verification_threshold(query_type=query_type, config=get_config()),
    deficiencies=deficiencies,
    suggestions=suggestions,
    verifier_model=verifier_model,
    verifier_provider=verifier_provider,
    chairman_provider=chairman_provider,
)
```

And on the exception-path return: pass the same three fields.

- [ ] **Step 3: Include fields in projection**

In `server/board/projection.py`, find `verification_to_dict` and ensure the
returned dict includes `verifier_model`, `verifier_provider`, and
`chairman_provider` keys (dataclass `asdict` already includes them — if the
projection uses manual key selection, add them).

- [ ] **Step 4: Run verification contract test**

Run: `uv run python -m unittest tests.test_verification_contract -v`

If a test asserts on the full dict keys, update the assertion to tolerate
the new fields (do not remove the fields).

- [ ] **Step 5: Commit**

```bash
git add server/board/deliberation/verification.py server/board/projection.py tests/
git commit -m "feat(verification): stamp verifier/chairman provider metadata on result"
```

---

## Task 5: Snapshot-based apply in reviews.py

**Files:**
- Modify: `server/harness/reviews.py`

- [ ] **Step 1: Snapshot diff at approval**

In `approve_harness_review`, after the status change, compute a diff
snapshot by calling each tuner in dry-run mode and serializing the report.
Then persist the snapshot on the review object before saving.

Replace `approve_harness_review`:

```python
def approve_harness_review(review_id: str, *, approve: bool = True) -> dict[str, Any]:
    review = _load_review(review_id)
    if review["status"] not in {"proposed", "approved", "rejected"}:
        raise HarnessReviewError(f"Review cannot be changed from status: {review['status']}")
    review["status"] = "approved" if approve else "rejected"
    if approve and "snapshot" not in review:
        review["snapshot"] = {
            "token_budgets": tune_token_budgets(dry_run=True).to_dict(),
            "verification_thresholds": tune_verification_thresholds(dry_run=True).to_dict(),
            "routing_compaction": tune_routing_and_compaction(dry_run=True).to_dict(),
            "model_assignments": tune_model_assignments(dry_run=True).to_dict(),
        }
    _save_review(review)
    return review
```

- [ ] **Step 2: Apply writes the snapshot directly**

Replace `apply_harness_review`:

```python
def apply_harness_review(review_id: str) -> dict[str, Any]:
    review = _load_review(review_id)
    if review["status"] != "approved":
        raise HarnessReviewError("Harness review must be approved before apply.")

    snapshot = review.get("snapshot")
    if not snapshot:
        raise HarnessReviewError("Approved review has no snapshot to apply.")

    from .config import load_config, save_config
    from .ledger import snapshot_activation

    previous = load_config()
    previous_snapshot = _config_to_snapshot(previous)

    # Apply snapshot by writing directly into config (no tuner re-run).
    updated = _apply_snapshot_to_config(previous, snapshot)
    save_config(updated)

    snapshot_activation(
        review_id=review_id,
        snapshot=snapshot,
        previous_snapshot=previous_snapshot,
    )

    review["status"] = "applied"
    review["applied_reports"] = snapshot
    review["applied_at"] = datetime.now(timezone.utc).isoformat()
    _save_review(review)
    return review


def _config_to_snapshot(config) -> dict:
    from dataclasses import asdict
    return asdict(config)


def _apply_snapshot_to_config(config, snapshot):
    """Merge snapshot-reported preferences into the live config."""
    from copy import deepcopy
    updated = deepcopy(config)
    for category_key in ("token_budgets", "verification_thresholds",
                          "routing_compaction", "model_assignments"):
        report = snapshot.get(category_key) or {}
        for change in report.get("changes", []):
            _apply_change(updated, category_key, change)
    return updated


def _apply_change(config, category: str, change: dict) -> None:
    """Translate a tuner change dict into a config mutation.

    Each tuner already knows how to apply its own change via its persistence
    function. We reuse the minimal field mutation here: model assignment
    writes to per_query_type[<qt>]['model_preferences'][<member>].
    """
    import dataclasses
    if category == "model_assignments":
        qt = change.get("query_type")
        member = change.get("member_id")
        model = change.get("new_model")
        if not (qt and member and model):
            return
        per_qt = dict(getattr(config, "per_query_type", {}) or {})
        entry = dict(per_qt.get(qt, {}))
        prefs = dict(entry.get("model_preferences", {}))
        prefs[member] = model
        entry["model_preferences"] = prefs
        per_qt[qt] = entry
        try:
            config.per_query_type = per_qt
        except dataclasses.FrozenInstanceError:
            setattr(config, "per_query_type", per_qt)
```

Note: the original tuners apply richer changes (thresholds, routing). For
V1, model assignment is the pressure-tested path from tuner E. Other
categories' "changes" lists will currently be empty in a fresh snapshot
because the other tuners report `routing_changes`/`compaction_changes`,
handled by their own persistence path. If a non-empty change list appears
for another category, `_apply_change` is a no-op — investigate and extend
this helper deliberately in a follow-up, do not autogenerate mutations.

- [ ] **Step 3: Add top-of-file imports**

```python
from datetime import datetime, timezone
```

(may already be present — do not duplicate).

- [ ] **Step 4: Run snapshot test**

Run: `uv run python -m unittest tests.test_harness_trust_contract.ApplyUsesSnapshotTest -v`

Expected: PASS.

- [ ] **Step 5: Run full harness suite**

Run: `uv run python -m unittest tests.test_harness_config_contract tests.test_phase_d_contract tests.test_phase_e_contract tests.test_tuner_contract -v`

Investigate any regression. Do not skip failing tests — root-cause.

- [ ] **Step 6: Commit**

```bash
git add server/harness/reviews.py
git commit -m "feat(harness): snapshot approved diff and apply snapshot deterministically"
```

---

## Task 6: Shadow watcher

**Files:**
- Create: `server/harness/shadow.py`

- [ ] **Step 1: Implement the watcher**

```python
# server/harness/shadow.py
"""Post-apply regression watcher for harness reviews.

Reads the baseline mean verification score (sessions preceding activation)
and a recent window (sessions after activation). If the delta regresses by
more than a threshold, reverts the activation.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from pathlib import Path
from statistics import mean

logger = logging.getLogger(__name__)


def watch_after_apply(
    review_id: str,
    *,
    window: int = 10,
    baseline: int = 20,
    regression_threshold: float = 1.0,
    db_path: Path | None = None,
) -> dict:
    """Return a dict describing baseline/current/delta and whether reverted."""
    if os.getenv("AGENTIC_BOARD_SHADOW_DISABLED") == "1":
        return {"reverted": False, "reason": "shadow disabled via env"}

    from .ledger import _connect, revert_activation
    from .config import load_config, save_config

    conn = _connect(db_path)
    try:
        act = conn.execute(
            "SELECT activated_at FROM harness_config_activations WHERE review_id = ?",
            (review_id,),
        ).fetchone()
        if not act:
            return {"reverted": False, "reason": "activation not found"}
        activated_at = act[0]

        baseline_rows = conn.execute(
            "SELECT verification_score FROM session_outcomes "
            "WHERE timestamp < ? AND verification_score IS NOT NULL "
            "ORDER BY timestamp DESC LIMIT ?",
            (activated_at, baseline),
        ).fetchall()
        window_rows = conn.execute(
            "SELECT verification_score FROM session_outcomes "
            "WHERE timestamp >= ? AND verification_score IS NOT NULL "
            "ORDER BY timestamp ASC LIMIT ?",
            (activated_at, window),
        ).fetchall()
    finally:
        conn.close()

    if len(baseline_rows) < 3 or len(window_rows) < window:
        return {
            "reverted": False,
            "reason": "insufficient samples",
            "baseline_n": len(baseline_rows),
            "window_n": len(window_rows),
        }

    baseline_mean = mean(r[0] for r in baseline_rows)
    window_mean = mean(r[0] for r in window_rows)
    delta = window_mean - baseline_mean

    if delta >= -regression_threshold:
        return {
            "reverted": False,
            "baseline_mean": baseline_mean,
            "window_mean": window_mean,
            "delta": delta,
        }

    # Regression detected: restore previous config snapshot.
    previous_snapshot = revert_activation(
        review_id, reason=f"regression delta={delta:.2f}", db_path=db_path,
    )
    if previous_snapshot is not None:
        try:
            _restore_from_snapshot(previous_snapshot)
        except Exception:
            logger.exception("Failed to restore previous harness config snapshot")
            return {
                "reverted": False,
                "reason": "restore failed",
                "baseline_mean": baseline_mean,
                "window_mean": window_mean,
                "delta": delta,
            }
    return {
        "reverted": True,
        "reason": f"regression delta={delta:.2f}",
        "baseline_mean": baseline_mean,
        "window_mean": window_mean,
        "delta": delta,
    }


def _restore_from_snapshot(snapshot: dict) -> None:
    """Overwrite live HarnessConfig fields from a snapshot dict."""
    from .config import HarnessConfig, save_config

    restored = HarnessConfig()
    for key, value in (snapshot or {}).items():
        if hasattr(restored, key):
            try:
                setattr(restored, key, value)
            except Exception:  # pragma: no cover - defensive
                logger.warning("Skipped unsettable field during restore: %s", key)
    save_config(restored)
```

- [ ] **Step 2: Wire into the apply route**

Modify `server/api/routes/harness.py`:

```python
import asyncio
from server.harness.shadow import watch_after_apply

@router.post("/harness/review/{review_id}/apply")
async def apply_harness_review_endpoint(review_id: str):
    try:
        result = apply_harness_review(review_id)
    except HarnessReviewError as e:
        raise HTTPException(422, detail=str(e))
    asyncio.create_task(asyncio.to_thread(watch_after_apply, review_id))
    return result
```

- [ ] **Step 3: Run shadow test**

Run: `uv run python -m unittest tests.test_harness_trust_contract.ShadowRollbackTest -v`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add server/harness/shadow.py server/api/routes/harness.py
git commit -m "feat(harness): auto-revert apply on post-window verification regression"
```

---

## Task 7: Split quality signal

**Files:**
- Modify: `server/harness/model_assignment.py`

- [ ] **Step 1: Replace `_quality_score` and block negative-feedback promotions**

Replace the existing `_quality_score` and adjust
`_apply_model_assignment_tuning` grouping logic so that promotion requires
the best candidate to have **no** negative feedback AND at least one
positive feedback (or verification-only positive signal when feedback is
absent everywhere).

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class QualityObservation:
    verification: float | None
    feedback: str | None  # "positive" | "negative" | None


def _quality_observation(row: dict[str, object]) -> QualityObservation | None:
    verification_score = row.get("verification_score")
    feedback_rating = row.get("feedback_rating")
    v = None
    if verification_score is not None:
        try:
            v = float(verification_score)
        except (TypeError, ValueError):
            v = None
    fb = feedback_rating if feedback_rating in ("positive", "negative") else None
    if v is None and fb is None:
        return None
    return QualityObservation(verification=v, feedback=fb)


def _group_observations_by_assignment(
    outcomes: list[dict[str, object]],
) -> dict[tuple[str, str], dict[str, list[QualityObservation]]]:
    from collections import defaultdict
    grouped: dict[tuple[str, str], dict[str, list[QualityObservation]]] = defaultdict(lambda: defaultdict(list))
    for row in outcomes:
        query_type = row.get("query_type")
        if not query_type:
            continue
        obs = _quality_observation(row)
        if obs is None:
            continue
        for member_id, model in _models_used(row.get("models_used")).items():
            grouped[(str(query_type), member_id)][model].append(obs)
    return grouped


def _model_score(obs_list: list[QualityObservation]) -> tuple[float, int]:
    """Verification-mean; returns (mean, count) ignoring rows without verification."""
    values = [o.verification for o in obs_list if o.verification is not None]
    if not values:
        return 0.0, 0
    return mean(values), len(values)


def _has_negative_feedback(obs_list: list[QualityObservation]) -> bool:
    return any(o.feedback == "negative" for o in obs_list)


def _has_positive_feedback(obs_list: list[QualityObservation]) -> bool:
    return any(o.feedback == "positive" for o in obs_list)
```

Then replace `_apply_model_assignment_tuning`:

```python
def _apply_model_assignment_tuning(
    config: HarnessConfig,
    outcomes: list[dict[str, Any]],
    *,
    min_samples: int,
    min_score_delta: float,
) -> tuple[list[ModelPreferenceChange], int, int]:
    grouped = _group_observations_by_assignment(outcomes)
    changes: list[ModelPreferenceChange] = []
    examined_assignments = 0
    eligible_assignments = 0

    for (query_type, member_id), model_obs in sorted(grouped.items()):
        if len(model_obs) < 2:
            continue
        examined_assignments += 1

        candidates = {
            model: obs_list
            for model, obs_list in model_obs.items()
            if sum(1 for o in obs_list if o.verification is not None) >= min_samples
        }
        if len(candidates) < 2:
            continue
        eligible_assignments += 1

        ranked = sorted(
            ((model, *_model_score(obs)) for model, obs in candidates.items()),
            key=lambda item: (item[1], item[2], item[0]),
            reverse=True,
        )
        best_model, best_score, best_count = ranked[0]
        runner_up_model, runner_up_score, _ = ranked[1]

        # Gate 1: verification-score delta.
        if best_score - runner_up_score < min_score_delta:
            continue
        # Gate 2: feedback sanity — best cannot have *only* negative signal.
        best_obs = candidates[best_model]
        if _has_negative_feedback(best_obs) and not _has_positive_feedback(best_obs):
            continue
        # Gate 3: do not promote a model whose feedback is strictly worse than the runner-up's.
        runner_obs = candidates[runner_up_model]
        if _has_negative_feedback(best_obs) and not _has_negative_feedback(runner_obs):
            continue

        preferences = resolve_model_preferences(query_type=query_type, config=config)
        previous_model = preferences.get(member_id)
        if previous_model == best_model:
            continue

        previous_score = None
        if previous_model and previous_model in model_obs:
            previous_verif_values = [o.verification for o in model_obs[previous_model] if o.verification is not None]
            if previous_verif_values:
                previous_score = round(mean(previous_verif_values), 4)

        _set_model_preference(config, query_type, member_id, best_model)
        changes.append(ModelPreferenceChange(
            query_type=query_type,
            member_id=member_id,
            previous_model=previous_model,
            new_model=best_model,
            previous_score=previous_score,
            new_score=round(best_score, 4),
            sample_count=best_count,
            runner_up_model=runner_up_model,
            runner_up_score=round(runner_up_score, 4),
        ))

    return changes, examined_assignments, eligible_assignments
```

Remove the old `_quality_score`, `_group_scores_by_assignment`, and
`FEEDBACK_BONUS` if no longer referenced.

- [ ] **Step 2: Run split-quality test**

Run: `uv run python -m unittest tests.test_harness_trust_contract.SplitQualitySignalTest -v`

Expected: PASS.

- [ ] **Step 3: Run full phase E contract**

Run: `uv run python -m unittest tests.test_phase_e_contract tests.test_tuner_contract -v`

If a test depended on the old `FEEDBACK_BONUS` behavior, the expectation
is now obsolete — update the test to the new semantics. Root-cause the test.

- [ ] **Step 4: Commit**

```bash
git add server/harness/model_assignment.py tests/
git commit -m "feat(harness): require verifier and feedback to agree before promotion"
```

---

## Task 8: Per-tuner meta-accuracy

**Files:**
- Create: `server/harness/meta.py`
- Modify: `server/harness/reviews.py` (surface metric)

- [ ] **Step 1: Implement meta helper**

```python
# server/harness/meta.py
"""Per-tuner accuracy = applied-and-not-reverted / applied."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def tuner_accuracy(db_path: Path | None = None) -> dict[str, dict[str, int | float]]:
    from .ledger import _connect

    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT snapshot, reverted_at FROM harness_config_activations"
        ).fetchall()
    finally:
        conn.close()

    totals: dict[str, dict[str, int]] = {}
    for snapshot_json, reverted_at in rows:
        try:
            snapshot = json.loads(snapshot_json or "{}")
        except json.JSONDecodeError:
            continue
        for tuner_name, report in snapshot.items():
            if not isinstance(report, dict):
                continue
            if not report.get("changes"):
                continue
            stats = totals.setdefault(tuner_name, {"applied": 0, "reverted": 0})
            stats["applied"] += 1
            if reverted_at:
                stats["reverted"] += 1

    return {
        name: {
            "applied": v["applied"],
            "reverted": v["reverted"],
            "accuracy": 0.0 if v["applied"] == 0
            else round(1.0 - (v["reverted"] / v["applied"]), 3),
        }
        for name, v in totals.items()
    }
```

- [ ] **Step 2: Surface in reviews**

In `server/harness/reviews.py`, at the end of `run_harness_review` BEFORE
writing the review, append a meta-accuracy advisory if non-empty:

```python
from .meta import tuner_accuracy

accuracy = tuner_accuracy()
if accuracy:
    recommendations.append(HarnessRecommendation(
        category="meta",
        summary="Historical tuner accuracy",
        details=accuracy,
    ))
```

- [ ] **Step 3: Light contract test**

Add to `tests/test_harness_trust_contract.py`:

```python
class MetaAccuracyTest(unittest.TestCase):
    def test_meta_reports_accuracy_per_tuner(self):
        import tempfile, json
        from server.harness.ledger import init_db, _connect
        from server.harness.meta import tuner_accuracy

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "l.db"
            init_db(path)
            conn = _connect(path)
            try:
                conn.execute(
                    "INSERT INTO harness_config_activations (review_id, activated_at, snapshot) VALUES (?, ?, ?)",
                    ("r1", "2026-04-20T00:00:00Z",
                     json.dumps({"model_assignments": {"changes": [{"member_id": "x"}]}})),
                )
                conn.execute(
                    "INSERT INTO harness_config_activations (review_id, activated_at, snapshot, reverted_at) VALUES (?, ?, ?, ?)",
                    ("r2", "2026-04-21T00:00:00Z",
                     json.dumps({"model_assignments": {"changes": [{"member_id": "y"}]}}),
                     "2026-04-21T01:00:00Z"),
                )
                conn.commit()
            finally:
                conn.close()
            result = tuner_accuracy(db_path=path)
        self.assertEqual(result["model_assignments"]["applied"], 2)
        self.assertEqual(result["model_assignments"]["reverted"], 1)
        self.assertAlmostEqual(result["model_assignments"]["accuracy"], 0.5, places=2)
```

- [ ] **Step 4: Run**

Run: `uv run python -m unittest tests.test_harness_trust_contract.MetaAccuracyTest -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/harness/meta.py server/harness/reviews.py tests/test_harness_trust_contract.py
git commit -m "feat(harness): report per-tuner accuracy from activation ledger"
```

---

## Task 9: Final integration smoke

- [ ] **Step 1: Run full suite**

Run: `uv run python -m unittest discover -s tests -v`

All green. No skips.

- [ ] **Step 2: Manual end-to-end**

```bash
# env guard
unset CHAIRMAN_MODEL VERIFICATION_MODEL AGENTIC_BOARD_ALLOW_SAME_VERIFIER
uv run python -m server.cli --list-members     # should boot without raising

# provoke guard
export VERIFICATION_MODEL=kimi/kimi-k2.5
uv run python -m server.cli --list-members     # must raise same-provider error
unset VERIFICATION_MODEL
```

- [ ] **Step 3: code-reviewer audit**

Dispatch `superpowers:code-reviewer` on commits from Tasks 5, 6, 7 with
focus: "check shadow watcher baseline selection for off-by-one; check
split-quality promotion gates for logical holes; check snapshot/apply
parity with what the user saw at approval time."

- [ ] **Step 4: Address findings**

Root-cause any findings; no mask patches.

---

## Definition of done

- Tasks 1–9 committed.
- `uv run python -m unittest discover -s tests -v` fully green.
- Manual startup guard + non-guard env test confirmed.
- code-reviewer audit clean or findings resolved.
- `CLAUDE.md` and `.env.example` document both env flags.
