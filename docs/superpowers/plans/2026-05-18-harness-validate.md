# Harness Validate (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pure-Python static validator for `HarnessConfig` that catches broken candidates before `apply_harness_review` writes them, with CLI + HTTP + reviews-flow integration.

**Architecture:** New module `server/harness/validate.py` exposes `validate_config(candidate) -> ValidationReport`. `reviews.run_harness_review` attaches a `validation` field; `reviews.apply_harness_review` refuses when `readiness == "blocked"`. New `validation_warnings` column on `session_outcomes` via `_ensure_columns`. New CLI flag and `POST /harness/validate` route.

**Tech Stack:** Python 3.x, dataclasses, sqlite3, FastAPI (existing), argparse (existing), pytest.

---

## Spec source

Authoritative source: `docs/superpowers/specs/2026-05-18-harness-cross-cutting-expansion-design.md` §4 (Phase 1 — `validate.py`). This plan covers all of §4 plus the validate-relevant slices of §7 (ledger integration) and §8 (testing strategy).

## Refinements over the spec defaults

| Topic | Default / naive approach | This plan's choice | Why |
|---|---|---|---|
| Where allowed models come from | Hardcode known model IDs | **Allowed-model set is dynamically computed from `get_chairman_model()`, `get_council_models()`, `get_classifier_model()`, `get_verification_model()` plus the `_PROVIDERS` prefix set from `server/board/llm.py`** | Spec §4.2 demands the live project state, not a frozen list. Pulling from `llm._PROVIDERS` future-proofs against added providers. |
| Validator failure handling | Crash on bad input | **Catch any internal exception inside `reviews.run_harness_review` per spec §4.4; convert to a `HarnessRecommendation` with category `validation`, summary `"validation check failed"`, details `{"error": str(exc)}`.** | Spec §4.4 mandates this. A broken validator must never block the rest of the review pipeline. |
| Member-ID source | Read raw markdown frontmatter | **Use the existing `server/board/loader.load_members(include_shelved_ids=...)` API; shelved-detection runs over file names in `server/members/*.md` (files starting with `_`).** | Reuses the canonical loader. Spec §4.2 explicitly says the loader is the source of truth. |
| Query-type source | Hardcode known types | **Read from `server.board.roster.load_roster()["decision_types"].keys()` (the YAML keys are the canonical enumeration; classifier.py reads from there).** | Avoids drift if a new decision type is added in `roster.yaml`. |
| CLI flag style | Subcommand (`server.cli harness validate ...`) | **Top-level flag `--harness-validate [PATH]` (spec §11 open question: defer to existing CLI shape, which is flag-based: `--tune`, `--tune-verification`, `--tune-routing`, `--tune-models`).** | Matches `server/cli.py` lines 541-550: every existing harness command is a `--<verb>` flag, not a subcommand. |
| `validation_warnings` storage | New table | **New TEXT column on `session_outcomes` via `_ensure_columns`, holding a JSON list. Empty list (`'[]'`) when no warnings.** | Spec §7 prescribes this. Matches the existing `routing_misses TEXT DEFAULT '[]'` column shape (`server/harness/ledger.py:47`). |
| Where the per-review snapshot lives | Standalone field | **Validation snapshot lives inside the review JSON's existing `validation` field (spec §4.3) and also gets re-recorded inside `harness_config_activations.snapshot` JSON blob on apply (no schema change).** | Spec §7 explicitly: "per-review validation snapshot inside `harness_config_activations.snapshot`". Reuse the existing column. |

## File structure

### Created

| File | Purpose |
|---|---|
| `server/harness/validate.py` | Pure-Python `ValidationReport`, `ValidationIssue`, and `validate_config()` |
| `tests/test_harness_validate.py` | Unit tests for the validator's schema/cross-ref/safety checks |
| `tests/test_harness_validate_integration.py` | Integration tests for reviews/CLI/HTTP wiring |

### Modified

| File | Change |
|---|---|
| `server/harness/reviews.py` | (a) `run_harness_review` attaches `validation` field via `validate_config(snapshot)` wrapped in try/except (spec §4.4); (b) `apply_harness_review` calls `validate_config(snapshot)` and raises `HarnessReviewError("validation blocked: <first error code>")` when blocked |
| `server/harness/ledger.py` | Add `validation_warnings TEXT DEFAULT '[]'` to `_ensure_columns` additions dict |
| `server/cli.py` | Add `--harness-validate` flag (top-level, optional argument: path to JSON candidate config) |
| `server/api/routes/harness.py` | Add `POST /harness/validate` route returning the `ValidationReport` as JSON |
| `server/api/schemas.py` | Add `HarnessValidateRequest` pydantic model |

### Untouched (out of scope)

- `server/harness/tuning.py` — only read floor/ceiling constants (`TOKEN_BUDGET_FLOORS`, `TOKEN_BUDGET_CEILINGS`, `VERIFICATION_THRESHOLD_FLOOR`, `VERIFICATION_THRESHOLD_CEILING`)
- `server/harness/config.py` — read-only (validator imports `HarnessConfig`, `_VALID_STAGE1_COMPACTION_SECTIONS`)
- All hooks / skills work — deferred to Phase 2 and Phase 3 plans
- `server/harness/shadow.py`, `server/harness/replay.py`, `server/harness/meta.py` — no changes required
- `server/board/loader.py`, `server/board/llm.py`, `server/board/config.py`, `server/board/roster/*` — read-only

---

## Task 1: Validator skeleton — `ValidationReport`, `ValidationIssue`, empty-config baseline

**Files:**
- Create: `server/harness/validate.py`
- Create: `tests/test_harness_validate.py`

Build the public surface (`validate_config`, `ValidationReport`, `ValidationIssue`) and a first contract test that a default `HarnessConfig()` is `readiness == "ready"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_harness_validate.py`:

```python
"""Unit tests for server.harness.validate."""

from __future__ import annotations

from server.harness.config import HarnessConfig
from server.harness.validate import (
    ValidationIssue,
    ValidationReport,
    validate_config,
)


def test_default_config_is_ready():
    """A freshly constructed HarnessConfig must validate cleanly."""
    report = validate_config(HarnessConfig())
    assert report.ok is True
    assert report.readiness == "ready"
    assert report.errors == []


def test_validation_report_ok_field_mirrors_readiness():
    """ValidationReport.ok must equal (readiness == 'ready')."""
    ready = ValidationReport(ok=True, errors=[], warnings=[], readiness="ready")
    warn = ValidationReport(
        ok=False,
        errors=[],
        warnings=[ValidationIssue(
            code="x", path="y", message="z", severity="warning",
        )],
        readiness="warning",
    )
    blocked = ValidationReport(
        ok=False,
        errors=[ValidationIssue(
            code="x", path="y", message="z", severity="error",
        )],
        warnings=[],
        readiness="blocked",
    )
    assert ready.ok is True
    assert warn.ok is False
    assert blocked.ok is False


def test_validate_config_accepts_dict_input():
    """validate_config must accept a plain-dict input (per spec §4.1 signature)."""
    report = validate_config({})
    # Empty dict → defaults applied → ready
    assert report.readiness in {"ready", "warning"}
```

- [ ] **Step 2: Run the failing test**

```bash
uv run pytest tests/test_harness_validate.py -x 2>&1 | tail -20
```

Expected output (FAIL): `ModuleNotFoundError: No module named 'server.harness.validate'`

- [ ] **Step 3: Write the minimal implementation**

Create `server/harness/validate.py`:

```python
"""Static dry-run validator for HarnessConfig (Phase 1).

Zero LLM calls. Catches typos and structurally broken configs before
`apply_harness_review` writes them. See
`docs/superpowers/specs/2026-05-18-harness-cross-cutting-expansion-design.md`
§4 for the design.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .config import HarnessConfig


Severity = Literal["error", "warning"]
Readiness = Literal["ready", "warning", "blocked"]


@dataclass(frozen=True)
class ValidationIssue:
    """A single check result with a stable code and dotted config path."""
    code: str
    path: str
    message: str
    severity: Severity


@dataclass(frozen=True)
class ValidationReport:
    """The output of validate_config(); see spec §4.1."""
    ok: bool
    errors: list[ValidationIssue]
    warnings: list[ValidationIssue]
    readiness: Readiness

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "readiness": self.readiness,
            "errors": [
                {
                    "code": issue.code,
                    "path": issue.path,
                    "message": issue.message,
                    "severity": issue.severity,
                }
                for issue in self.errors
            ],
            "warnings": [
                {
                    "code": issue.code,
                    "path": issue.path,
                    "message": issue.message,
                    "severity": issue.severity,
                }
                for issue in self.warnings
            ],
        }


def validate_config(candidate: HarnessConfig | dict) -> ValidationReport:
    """Validate a HarnessConfig candidate.

    Per spec §4.1: accepts either a `HarnessConfig` dataclass or a plain dict
    (e.g. parsed straight from JSON). Returns a `ValidationReport` with the
    overall readiness verdict and lists of errors and warnings.
    """
    config = _coerce_to_config(candidate)
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    # Future tasks add: schema, cross-ref, safety checks here.
    readiness = _compute_readiness(errors, warnings)
    return ValidationReport(
        ok=(readiness == "ready"),
        errors=errors,
        warnings=warnings,
        readiness=readiness,
    )


def _coerce_to_config(candidate: HarnessConfig | dict) -> HarnessConfig:
    """Accept either a HarnessConfig or a plain dict; return HarnessConfig."""
    if isinstance(candidate, HarnessConfig):
        return candidate
    if not isinstance(candidate, dict):
        raise TypeError(
            f"validate_config expects HarnessConfig or dict, got {type(candidate).__name__}"
        )
    known_fields = {f.name for f in HarnessConfig.__dataclass_fields__.values()}
    filtered = {k: v for k, v in candidate.items() if k in known_fields}
    return HarnessConfig(**filtered)


def _compute_readiness(
    errors: list[ValidationIssue], warnings: list[ValidationIssue],
) -> Readiness:
    if errors:
        return "blocked"
    if warnings:
        return "warning"
    return "ready"
```

- [ ] **Step 4: Run the test**

```bash
uv run pytest tests/test_harness_validate.py -x 2>&1 | tail -10
```

Expected output (PASS): `3 passed`

- [ ] **Step 5: Commit**

```bash
git add server/harness/validate.py tests/test_harness_validate.py
git commit -m "$(cat <<'EOF'
feat(harness/validate): add ValidationReport/ValidationIssue skeleton

Phase 1 PR1 scaffolding for the static HarnessConfig validator
(spec §4.1). validate_config accepts HarnessConfig or dict; empty
input returns readiness == "ready".

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Schema-check pass (types, ranges, required keys)

**Files:**
- Modify: `server/harness/validate.py`
- Modify: `tests/test_harness_validate.py`

Add schema validation for top-level scalar fields. Most type-checking is already enforced by the `HarnessConfig` dataclass at construction time; the validator's job is to catch *value* problems (negative tokens, out-of-range thresholds) that the dataclass doesn't reject.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_harness_validate.py`:

```python
def test_schema_rejects_negative_stage_tokens():
    """Negative stage budgets are structurally broken."""
    cfg = HarnessConfig(stage1_max_tokens=-100)
    report = validate_config(cfg)
    assert report.readiness == "blocked"
    codes = [issue.code for issue in report.errors]
    assert "schema.stage_tokens_non_positive" in codes


def test_schema_rejects_min_responses_below_one():
    """min_stage1_responses must be >= 1."""
    cfg = HarnessConfig(min_stage1_responses=0)
    report = validate_config(cfg)
    assert report.readiness == "blocked"
    codes = [issue.code for issue in report.errors]
    assert "schema.min_responses_below_one" in codes


def test_schema_rejects_verification_threshold_out_of_range():
    """verification_threshold ranges to floor/ceiling — error if outside."""
    cfg = HarnessConfig(verification_threshold=0.0)
    report = validate_config(cfg)
    codes = [issue.code for issue in report.errors]
    assert "schema.verification_threshold_out_of_range" in codes


def test_schema_complexity_multipliers_required_keys():
    """complexity_multipliers must contain simple/moderate/complex."""
    cfg = HarnessConfig(complexity_multipliers={"simple": 1.0})
    report = validate_config(cfg)
    codes = [issue.code for issue in report.errors]
    assert "schema.complexity_multipliers_missing_keys" in codes
```

- [ ] **Step 2: Run the failing test**

```bash
uv run pytest tests/test_harness_validate.py::test_schema_rejects_negative_stage_tokens -x 2>&1 | tail -10
```

Expected output (FAIL): `AssertionError: assert 'ready' == 'blocked'`

- [ ] **Step 3: Write the minimal implementation**

Replace the `validate_config` body in `server/harness/validate.py` (and add helpers):

```python
def validate_config(candidate: HarnessConfig | dict) -> ValidationReport:
    """Validate a HarnessConfig candidate. See spec §4.1."""
    config = _coerce_to_config(candidate)
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    _check_schema(config, errors)

    readiness = _compute_readiness(errors, warnings)
    return ValidationReport(
        ok=(readiness == "ready"),
        errors=errors,
        warnings=warnings,
        readiness=readiness,
    )


_REQUIRED_COMPLEXITY_KEYS = {"simple", "moderate", "complex"}


def _check_schema(config: HarnessConfig, errors: list[ValidationIssue]) -> None:
    """Schema checks: types/ranges/required keys for top-level fields."""
    from .tuning import (
        VERIFICATION_THRESHOLD_CEILING,
        VERIFICATION_THRESHOLD_FLOOR,
    )

    for stage_field in (
        "stage1_max_tokens",
        "stage2_max_tokens",
        "stage3_max_tokens",
        "stage4_max_tokens",
        "revision_max_tokens",
    ):
        value = getattr(config, stage_field)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            errors.append(ValidationIssue(
                code="schema.stage_tokens_non_positive",
                path=stage_field,
                message=f"{stage_field} must be a positive int, got {value!r}",
                severity="error",
            ))

    for field_name in ("min_stage1_responses", "min_stage2_responses"):
        value = getattr(config, field_name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            errors.append(ValidationIssue(
                code="schema.min_responses_below_one",
                path=field_name,
                message=f"{field_name} must be >= 1, got {value!r}",
                severity="error",
            ))

    if not isinstance(config.max_revision_attempts, int) or config.max_revision_attempts < 0:
        errors.append(ValidationIssue(
            code="schema.max_revision_attempts_negative",
            path="max_revision_attempts",
            message=f"max_revision_attempts must be >= 0, got {config.max_revision_attempts!r}",
            severity="error",
        ))

    threshold = config.verification_threshold
    if (
        not isinstance(threshold, (int, float))
        or isinstance(threshold, bool)
        or threshold < VERIFICATION_THRESHOLD_FLOOR
        or threshold > VERIFICATION_THRESHOLD_CEILING
    ):
        errors.append(ValidationIssue(
            code="schema.verification_threshold_out_of_range",
            path="verification_threshold",
            message=(
                f"verification_threshold must be in "
                f"[{VERIFICATION_THRESHOLD_FLOOR}, {VERIFICATION_THRESHOLD_CEILING}], "
                f"got {threshold!r}"
            ),
            severity="error",
        ))

    multipliers = config.complexity_multipliers
    if not isinstance(multipliers, dict):
        errors.append(ValidationIssue(
            code="schema.complexity_multipliers_not_dict",
            path="complexity_multipliers",
            message=f"complexity_multipliers must be a dict, got {type(multipliers).__name__}",
            severity="error",
        ))
    else:
        missing = sorted(_REQUIRED_COMPLEXITY_KEYS - set(multipliers))
        if missing:
            errors.append(ValidationIssue(
                code="schema.complexity_multipliers_missing_keys",
                path="complexity_multipliers",
                message=f"complexity_multipliers missing required keys: {missing}",
                severity="error",
            ))

    if not isinstance(config.per_query_type, dict):
        errors.append(ValidationIssue(
            code="schema.per_query_type_not_dict",
            path="per_query_type",
            message=f"per_query_type must be a dict, got {type(config.per_query_type).__name__}",
            severity="error",
        ))

    if not isinstance(config.hardening, dict):
        errors.append(ValidationIssue(
            code="schema.hardening_not_dict",
            path="hardening",
            message=f"hardening must be a dict, got {type(config.hardening).__name__}",
            severity="error",
        ))
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_harness_validate.py -x 2>&1 | tail -10
```

Expected output (PASS): `7 passed`

- [ ] **Step 5: Commit**

```bash
git add server/harness/validate.py tests/test_harness_validate.py
git commit -m "$(cat <<'EOF'
feat(harness/validate): schema checks for top-level scalars

Reject non-positive stage tokens, min_responses < 1, out-of-range
verification_threshold, and missing complexity_multipliers keys
(spec §4.2 schema row). Pulls floor/ceiling from tuning.py.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Cross-ref — model existence against the allowed set

**Files:**
- Modify: `server/harness/validate.py`
- Modify: `tests/test_harness_validate.py`

Build the allowed-model set from board accessors + provider prefixes, then validate every model in `per_query_type.*.model_preferences` against it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_harness_validate.py`:

```python
def test_xref_model_pref_matching_known_model_passes():
    """A model preference using a default chairman/council model is allowed."""
    cfg = HarnessConfig()
    cfg.per_query_type = {
        "strategic": {"model_preferences": {"strategist": "deepseek/deepseek-v4-pro"}},
    }
    report = validate_config(cfg)
    codes = [issue.code for issue in report.errors]
    assert "xref.model_unknown" not in codes


def test_xref_model_pref_with_known_prefix_passes():
    """Any model with a known provider prefix is allowed (e.g. qwen/foo)."""
    cfg = HarnessConfig()
    cfg.per_query_type = {
        "strategic": {"model_preferences": {"strategist": "qwen/qwen-mythical"}},
    }
    report = validate_config(cfg)
    codes = [issue.code for issue in report.errors]
    assert "xref.model_unknown" not in codes


def test_xref_model_pref_unknown_prefix_fails():
    """A model with no recognised prefix is rejected."""
    cfg = HarnessConfig()
    cfg.per_query_type = {
        "strategic": {"model_preferences": {"strategist": "fakeprovider/x"}},
    }
    report = validate_config(cfg)
    codes = [issue.code for issue in report.errors]
    assert "xref.model_unknown" in codes


def test_xref_openrouter_colon_prefix_allowed():
    """openrouter:<id> with a colon, not slash, is a valid escape hatch."""
    cfg = HarnessConfig()
    cfg.per_query_type = {
        "strategic": {"model_preferences": {"strategist": "openrouter:anthropic/foo"}},
    }
    report = validate_config(cfg)
    codes = [issue.code for issue in report.errors]
    assert "xref.model_unknown" not in codes
```

- [ ] **Step 2: Run the failing test**

```bash
uv run pytest tests/test_harness_validate.py::test_xref_model_pref_unknown_prefix_fails -x 2>&1 | tail -10
```

Expected output (FAIL): `assert 'xref.model_unknown' in []`

- [ ] **Step 3: Write the minimal implementation**

Add to `server/harness/validate.py`:

```python
def _allowed_models() -> set[str]:
    """Build the set of explicit allowed model IDs from the live project state.

    The check is: a model is allowed if its ID is in this set OR its prefix
    is in the known provider prefix set (see `_known_prefixes()`).
    """
    from server.board.config import (
        get_chairman_model,
        get_classifier_model,
        get_council_models,
        get_verification_model,
    )
    allowed: set[str] = set()
    allowed.add(get_chairman_model())
    allowed.add(get_classifier_model())
    allowed.add(get_verification_model())
    allowed.update(get_council_models())
    return {m for m in allowed if m}


def _known_prefixes() -> set[str]:
    """Set of provider prefixes recognised by the LLM client."""
    from server.board.llm import _PROVIDERS
    return set(_PROVIDERS.keys())


def _model_is_resolvable(model: str) -> bool:
    """A model ID resolves if either listed explicitly or its prefix is known.

    Mirrors `server.board.llm._split_model_id` semantics: `openrouter:<id>`
    has a colon, all others use `<prefix>/<id>`.
    """
    if not isinstance(model, str) or not model.strip():
        return False
    if model in _allowed_models():
        return True
    if model.startswith("openrouter:"):
        return "openrouter" in _known_prefixes()
    if "/" in model:
        prefix = model.split("/", 1)[0]
        return prefix in _known_prefixes()
    return False


def _check_model_preferences(
    config: HarnessConfig, errors: list[ValidationIssue],
) -> None:
    """Cross-ref every per_query_type.*.model_preferences entry."""
    per_qt = config.per_query_type if isinstance(config.per_query_type, dict) else {}
    for query_type, qt_config in per_qt.items():
        if not isinstance(qt_config, dict):
            continue
        prefs = qt_config.get("model_preferences")
        if not isinstance(prefs, dict):
            continue
        for member_id, model in prefs.items():
            if not _model_is_resolvable(model):
                errors.append(ValidationIssue(
                    code="xref.model_unknown",
                    path=f"per_query_type.{query_type}.model_preferences.{member_id}",
                    message=(
                        f"model {model!r} does not resolve: not in the allowed "
                        f"set and prefix not in {sorted(_known_prefixes())}"
                    ),
                    severity="error",
                ))
```

Then wire the call into `validate_config`:

```python
def validate_config(candidate: HarnessConfig | dict) -> ValidationReport:
    """Validate a HarnessConfig candidate. See spec §4.1."""
    config = _coerce_to_config(candidate)
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    _check_schema(config, errors)
    _check_model_preferences(config, errors)

    readiness = _compute_readiness(errors, warnings)
    return ValidationReport(
        ok=(readiness == "ready"),
        errors=errors,
        warnings=warnings,
        readiness=readiness,
    )
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_harness_validate.py -x 2>&1 | tail -10
```

Expected output (PASS): `11 passed`

- [ ] **Step 5: Commit**

```bash
git add server/harness/validate.py tests/test_harness_validate.py
git commit -m "$(cat <<'EOF'
feat(harness/validate): cross-ref model preferences

Build the allowed-model set from board config accessors and the
provider prefix table in server/board/llm.py._PROVIDERS. Reject
unknown prefixes; accept openrouter:<id> + any <prefix>/<id> with
a registered prefix (spec §4.2 model row).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Cross-ref — member ID existence + shelved-member detection

**Files:**
- Modify: `server/harness/validate.py`
- Modify: `tests/test_harness_validate.py`

Suppressed member IDs must exist on disk. Shelved members (file starting with `_`) get a separate `xref.member_shelved` warning rather than an error, because suppressing a shelved member is a benign no-op.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_harness_validate.py`:

```python
def test_xref_suppressed_member_unknown_id_fails():
    """An unknown member ID in routing.suppressed_member_ids is an error."""
    cfg = HarnessConfig()
    cfg.per_query_type = {
        "strategic": {"routing": {"suppressed_member_ids": ["bogus_member"]}},
    }
    report = validate_config(cfg)
    codes = [issue.code for issue in report.errors]
    assert "xref.member_unknown" in codes


def test_xref_suppressed_member_known_id_passes():
    """Real member IDs pass the xref check."""
    cfg = HarnessConfig()
    cfg.per_query_type = {
        "strategic": {"routing": {"suppressed_member_ids": ["builder"]}},
    }
    report = validate_config(cfg)
    codes = [issue.code for issue in report.errors]
    assert "xref.member_unknown" not in codes


def test_xref_suppressed_shelved_member_emits_warning():
    """Suppressing a shelved member (e.g., 'guardian') warns but does not block."""
    cfg = HarnessConfig()
    cfg.per_query_type = {
        "strategic": {"routing": {"suppressed_member_ids": ["guardian"]}},
    }
    report = validate_config(cfg)
    error_codes = [issue.code for issue in report.errors]
    warning_codes = [issue.code for issue in report.warnings]
    assert "xref.member_unknown" not in error_codes
    assert "xref.member_shelved" in warning_codes
```

- [ ] **Step 2: Run the failing test**

```bash
uv run pytest tests/test_harness_validate.py::test_xref_suppressed_member_unknown_id_fails -x 2>&1 | tail -10
```

Expected output (FAIL): `assert 'xref.member_unknown' in []`

- [ ] **Step 3: Write the minimal implementation**

Add to `server/harness/validate.py`:

```python
def _member_universe() -> tuple[set[str], set[str]]:
    """Return (active_ids, shelved_ids) read directly from server/members/*.md.

    Active = filenames without leading underscore. Shelved = filenames with
    leading underscore (and the file stem stripped of that underscore).
    Templates are filtered out via the `_template` shelved-id exclusion.
    """
    from pathlib import Path
    members_dir = Path(__file__).resolve().parent.parent / "members"
    active: set[str] = set()
    shelved: set[str] = set()
    if not members_dir.is_dir():
        return active, shelved
    for filepath in members_dir.glob("*.md"):
        if filepath.name.startswith("_"):
            stem = filepath.stem.lstrip("_")
            if stem and stem != "template":
                shelved.add(stem)
        else:
            active.add(filepath.stem)
    return active, shelved


def _check_suppressed_members(
    config: HarnessConfig,
    errors: list[ValidationIssue],
    warnings: list[ValidationIssue],
) -> None:
    """Cross-ref every per_query_type.*.routing.suppressed_member_ids entry."""
    active, shelved = _member_universe()
    per_qt = config.per_query_type if isinstance(config.per_query_type, dict) else {}
    for query_type, qt_config in per_qt.items():
        if not isinstance(qt_config, dict):
            continue
        routing = qt_config.get("routing")
        if not isinstance(routing, dict):
            continue
        suppressed = routing.get("suppressed_member_ids")
        if not isinstance(suppressed, list):
            continue
        for member_id in suppressed:
            path = f"per_query_type.{query_type}.routing.suppressed_member_ids"
            if not isinstance(member_id, str) or not member_id.strip():
                errors.append(ValidationIssue(
                    code="xref.member_unknown",
                    path=path,
                    message=f"empty or non-string member ID {member_id!r}",
                    severity="error",
                ))
                continue
            if member_id in shelved:
                warnings.append(ValidationIssue(
                    code="xref.member_shelved",
                    path=path,
                    message=(
                        f"member {member_id!r} is shelved (file "
                        f"server/members/_{member_id}.md); suppression is a no-op"
                    ),
                    severity="warning",
                ))
                continue
            if member_id not in active:
                errors.append(ValidationIssue(
                    code="xref.member_unknown",
                    path=path,
                    message=(
                        f"member {member_id!r} not found under server/members/*.md "
                        f"(known active: {sorted(active)})"
                    ),
                    severity="error",
                ))
```

Wire into `validate_config`:

```python
    _check_schema(config, errors)
    _check_model_preferences(config, errors)
    _check_suppressed_members(config, errors, warnings)
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_harness_validate.py -x 2>&1 | tail -10
```

Expected output (PASS): `14 passed`

- [ ] **Step 5: Commit**

```bash
git add server/harness/validate.py tests/test_harness_validate.py
git commit -m "$(cat <<'EOF'
feat(harness/validate): cross-ref suppressed member IDs

Validate routing.suppressed_member_ids against server/members/*.md.
Unknown IDs are errors; shelved IDs ('_'-prefixed files) emit a
warning (suppression is a benign no-op for shelved members).
Spec §4.2 member row.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Cross-ref — query types + stage1_sections + hardening models

**Files:**
- Modify: `server/harness/validate.py`
- Modify: `tests/test_harness_validate.py`

Three small cross-ref checks bundled into one task: (a) `per_query_type` keys against the roster's enumerated decision types; (b) `compaction.stage1_sections` against `_VALID_STAGE1_COMPACTION_SECTIONS`; (c) `hardening.*_model` fields against the allowed model set (None is allowed — falls back to atomizer_model).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_harness_validate.py`:

```python
def test_xref_per_query_type_key_unknown_warns():
    """Unknown query_type keys warn (might be a typo) but don't block."""
    cfg = HarnessConfig()
    cfg.per_query_type = {"non_existent_qt": {}}
    report = validate_config(cfg)
    warning_codes = [issue.code for issue in report.warnings]
    assert "xref.query_type_unknown" in warning_codes


def test_xref_per_query_type_known_key_passes():
    """Real decision types from roster.yaml pass."""
    cfg = HarnessConfig()
    cfg.per_query_type = {"strategic": {}}
    report = validate_config(cfg)
    warning_codes = [issue.code for issue in report.warnings]
    assert "xref.query_type_unknown" not in warning_codes


def test_xref_stage1_sections_unknown_fails():
    """Unknown stage1 compaction section is an error."""
    cfg = HarnessConfig()
    cfg.per_query_type = {
        "strategic": {
            "compaction": {"stage1_sections": ["confidence", "made_up_section"]},
        },
    }
    report = validate_config(cfg)
    codes = [issue.code for issue in report.errors]
    assert "xref.stage1_section_unknown" in codes


def test_xref_stage1_sections_all_known_passes():
    """Valid stage1 sections pass."""
    cfg = HarnessConfig()
    cfg.per_query_type = {
        "strategic": {"compaction": {"stage1_sections": ["confidence", "tldr"]}},
    }
    report = validate_config(cfg)
    codes = [issue.code for issue in report.errors]
    assert "xref.stage1_section_unknown" not in codes


def test_xref_hardening_model_unknown_fails():
    """Unknown hardening.<x>_model rejects."""
    cfg = HarnessConfig()
    cfg.hardening["atomizer_model"] = "fakeprovider/bogus"
    report = validate_config(cfg)
    codes = [issue.code for issue in report.errors]
    assert "xref.hardening_model_unknown" in codes


def test_xref_hardening_model_none_passes():
    """None falls back to atomizer_model — not an error."""
    cfg = HarnessConfig()
    cfg.hardening["contradiction_judge_model"] = None
    cfg.hardening["sotb_judge_model"] = None
    cfg.hardening["auto_promote_summarizer_model"] = None
    report = validate_config(cfg)
    codes = [issue.code for issue in report.errors]
    assert "xref.hardening_model_unknown" not in codes
```

- [ ] **Step 2: Run the failing test**

```bash
uv run pytest tests/test_harness_validate.py::test_xref_stage1_sections_unknown_fails -x 2>&1 | tail -10
```

Expected output (FAIL): `assert 'xref.stage1_section_unknown' in []`

- [ ] **Step 3: Write the minimal implementation**

Add to `server/harness/validate.py`:

```python
_HARDENING_MODEL_FIELDS = (
    "atomizer_model",
    "contradiction_judge_model",
    "sotb_judge_model",
    "auto_promote_summarizer_model",
)


def _known_query_types() -> set[str]:
    """Decision types enumerated in roster.yaml — the classifier output schema."""
    try:
        from server.board.roster import load_roster
        roster = load_roster()
    except Exception:
        return set()
    decision_types = roster.get("decision_types") or {}
    return set(decision_types.keys())


def _check_query_type_keys(
    config: HarnessConfig, warnings: list[ValidationIssue],
) -> None:
    known = _known_query_types()
    if not known:
        return
    per_qt = config.per_query_type if isinstance(config.per_query_type, dict) else {}
    for query_type in per_qt:
        if query_type not in known:
            warnings.append(ValidationIssue(
                code="xref.query_type_unknown",
                path=f"per_query_type.{query_type}",
                message=(
                    f"query_type {query_type!r} is not in roster.yaml "
                    f"decision_types (known: {sorted(known)})"
                ),
                severity="warning",
            ))


def _check_stage1_sections(
    config: HarnessConfig, errors: list[ValidationIssue],
) -> None:
    from .config import _VALID_STAGE1_COMPACTION_SECTIONS
    per_qt = config.per_query_type if isinstance(config.per_query_type, dict) else {}
    for query_type, qt_config in per_qt.items():
        if not isinstance(qt_config, dict):
            continue
        compaction = qt_config.get("compaction")
        if not isinstance(compaction, dict):
            continue
        for sub_key in ("stage1_sections", "stage1_detail_sections"):
            sections = compaction.get(sub_key)
            if not isinstance(sections, list):
                continue
            for section in sections:
                if not isinstance(section, str):
                    errors.append(ValidationIssue(
                        code="xref.stage1_section_unknown",
                        path=f"per_query_type.{query_type}.compaction.{sub_key}",
                        message=f"non-string section entry {section!r}",
                        severity="error",
                    ))
                    continue
                normalized = section.lower()
                if normalized == "tl;dr":
                    normalized = "tldr"
                if normalized not in _VALID_STAGE1_COMPACTION_SECTIONS:
                    errors.append(ValidationIssue(
                        code="xref.stage1_section_unknown",
                        path=f"per_query_type.{query_type}.compaction.{sub_key}",
                        message=(
                            f"section {section!r} is not valid (allowed: "
                            f"{sorted(_VALID_STAGE1_COMPACTION_SECTIONS)})"
                        ),
                        severity="error",
                    ))


def _check_hardening_models(
    config: HarnessConfig, errors: list[ValidationIssue],
) -> None:
    hardening = config.hardening if isinstance(config.hardening, dict) else {}
    for field_name in _HARDENING_MODEL_FIELDS:
        value = hardening.get(field_name)
        if value is None:
            continue  # None falls back to atomizer_model per spec §4.2
        if not _model_is_resolvable(value):
            errors.append(ValidationIssue(
                code="xref.hardening_model_unknown",
                path=f"hardening.{field_name}",
                message=(
                    f"hardening.{field_name} = {value!r} does not resolve: "
                    f"not in allowed set and prefix not in {sorted(_known_prefixes())}"
                ),
                severity="error",
            ))
```

Wire into `validate_config`:

```python
    _check_schema(config, errors)
    _check_model_preferences(config, errors)
    _check_suppressed_members(config, errors, warnings)
    _check_query_type_keys(config, warnings)
    _check_stage1_sections(config, errors)
    _check_hardening_models(config, errors)
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_harness_validate.py -x 2>&1 | tail -10
```

Expected output (PASS): `20 passed`

- [ ] **Step 5: Commit**

```bash
git add server/harness/validate.py tests/test_harness_validate.py
git commit -m "$(cat <<'EOF'
feat(harness/validate): cross-ref query types, stage1 sections, hardening models

Three §4.2 cross-ref rows: (a) per_query_type keys against
roster.yaml decision_types; (b) compaction.stage1_sections against
_VALID_STAGE1_COMPACTION_SECTIONS; (c) hardening.*_model fields
against the allowed-model set (None falls back per spec).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Safety — suppression-empties-routing detection + budget floor/ceiling

**Files:**
- Modify: `server/harness/validate.py`
- Modify: `tests/test_harness_validate.py`

Two higher-level invariants from spec §4.2 safety: (a) reject configs where routing suppression empties the candidate pool for a query type; (b) reject token budgets that fall outside `TOKEN_BUDGET_FLOORS`/`TOKEN_BUDGET_CEILINGS`; (c) reject `disagreement_threshold` outside [1, 10].

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_harness_validate.py`:

```python
def test_safety_suppression_empties_routing_pool_fails():
    """If every active member for a query_type is suppressed, error out."""
    from server.board.roster import load_roster, select_members_for_decision_type

    selection = select_members_for_decision_type("strategic")
    all_routed = list(selection.member_ids)
    assert len(all_routed) >= 1
    cfg = HarnessConfig()
    cfg.per_query_type = {
        "strategic": {"routing": {"suppressed_member_ids": all_routed}},
    }
    report = validate_config(cfg)
    codes = [issue.code for issue in report.errors]
    assert "safety.routing_pool_empty" in codes


def test_safety_routing_partial_suppression_passes():
    """Suppressing only some members leaves a non-empty pool — allowed."""
    cfg = HarnessConfig()
    cfg.per_query_type = {
        "strategic": {"routing": {"suppressed_member_ids": ["builder"]}},
    }
    report = validate_config(cfg)
    codes = [issue.code for issue in report.errors]
    assert "safety.routing_pool_empty" not in codes


def test_safety_stage_budget_below_floor_fails():
    """Stage1 budget below TOKEN_BUDGET_FLOORS rejects."""
    from server.harness.tuning import TOKEN_BUDGET_FLOORS
    cfg = HarnessConfig()
    cfg.per_query_type = {
        "strategic": {
            "token_budgets": {
                "simple": {"stage1_max_tokens": TOKEN_BUDGET_FLOORS["stage1_max_tokens"] - 1},
            },
        },
    }
    report = validate_config(cfg)
    codes = [issue.code for issue in report.errors]
    assert "safety.token_budget_below_floor" in codes


def test_safety_stage_budget_above_ceiling_fails():
    """Stage1 budget above TOKEN_BUDGET_CEILINGS rejects."""
    from server.harness.tuning import TOKEN_BUDGET_CEILINGS
    cfg = HarnessConfig()
    cfg.per_query_type = {
        "strategic": {
            "token_budgets": {
                "simple": {"stage1_max_tokens": TOKEN_BUDGET_CEILINGS["stage1_max_tokens"] + 1},
            },
        },
    }
    report = validate_config(cfg)
    codes = [issue.code for issue in report.errors]
    assert "safety.token_budget_above_ceiling" in codes


def test_safety_disagreement_threshold_out_of_range_fails():
    """hardening.disagreement_threshold must be in [1, 10]."""
    cfg = HarnessConfig()
    cfg.hardening["disagreement_threshold"] = 99
    report = validate_config(cfg)
    codes = [issue.code for issue in report.errors]
    assert "safety.disagreement_threshold_out_of_range" in codes
```

- [ ] **Step 2: Run the failing test**

```bash
uv run pytest tests/test_harness_validate.py::test_safety_stage_budget_below_floor_fails -x 2>&1 | tail -10
```

Expected output (FAIL): `assert 'safety.token_budget_below_floor' in []`

- [ ] **Step 3: Write the minimal implementation**

Add to `server/harness/validate.py`:

```python
def _check_routing_pool_not_empty(
    config: HarnessConfig, errors: list[ValidationIssue],
) -> None:
    """For each per_query_type entry, ensure the routing pool isn't fully suppressed."""
    try:
        from server.board.roster import select_members_for_decision_type
    except Exception:
        return
    known_qts = _known_query_types()
    per_qt = config.per_query_type if isinstance(config.per_query_type, dict) else {}
    for query_type, qt_config in per_qt.items():
        if query_type not in known_qts:
            continue
        if not isinstance(qt_config, dict):
            continue
        routing = qt_config.get("routing")
        if not isinstance(routing, dict):
            continue
        suppressed = routing.get("suppressed_member_ids")
        if not isinstance(suppressed, list):
            continue
        suppressed_set = {s for s in suppressed if isinstance(s, str)}
        if not suppressed_set:
            continue
        try:
            selection = select_members_for_decision_type(query_type)
        except Exception:
            continue
        candidate_pool = set(selection.member_ids)
        remaining = candidate_pool - suppressed_set
        if candidate_pool and not remaining:
            errors.append(ValidationIssue(
                code="safety.routing_pool_empty",
                path=f"per_query_type.{query_type}.routing.suppressed_member_ids",
                message=(
                    f"suppressing {sorted(suppressed_set)} empties the routing "
                    f"pool for query_type {query_type!r} (candidates were "
                    f"{sorted(candidate_pool)})"
                ),
                severity="error",
            ))


def _check_token_budget_bounds(
    config: HarnessConfig, errors: list[ValidationIssue],
) -> None:
    """Per-query token budgets must stay within tuning floors/ceilings."""
    from .tuning import TOKEN_BUDGET_CEILINGS, TOKEN_BUDGET_FLOORS

    per_qt = config.per_query_type if isinstance(config.per_query_type, dict) else {}
    for query_type, qt_config in per_qt.items():
        if not isinstance(qt_config, dict):
            continue
        token_budgets = qt_config.get("token_budgets")
        if not isinstance(token_budgets, dict):
            continue
        for complexity, complexity_config in token_budgets.items():
            if not isinstance(complexity_config, dict):
                continue
            for field_name, value in complexity_config.items():
                if field_name not in TOKEN_BUDGET_FLOORS:
                    continue
                if not isinstance(value, int) or isinstance(value, bool):
                    continue
                path = (
                    f"per_query_type.{query_type}.token_budgets."
                    f"{complexity}.{field_name}"
                )
                floor = TOKEN_BUDGET_FLOORS[field_name]
                ceiling = TOKEN_BUDGET_CEILINGS[field_name]
                if value < floor:
                    errors.append(ValidationIssue(
                        code="safety.token_budget_below_floor",
                        path=path,
                        message=(
                            f"{field_name}={value} is below floor {floor} "
                            f"(see TOKEN_BUDGET_FLOORS in server/harness/tuning.py)"
                        ),
                        severity="error",
                    ))
                elif value > ceiling:
                    errors.append(ValidationIssue(
                        code="safety.token_budget_above_ceiling",
                        path=path,
                        message=(
                            f"{field_name}={value} is above ceiling {ceiling} "
                            f"(see TOKEN_BUDGET_CEILINGS in server/harness/tuning.py)"
                        ),
                        severity="error",
                    ))


def _check_disagreement_threshold(
    config: HarnessConfig, errors: list[ValidationIssue],
) -> None:
    hardening = config.hardening if isinstance(config.hardening, dict) else {}
    threshold = hardening.get("disagreement_threshold")
    if threshold is None:
        return
    if not isinstance(threshold, int) or isinstance(threshold, bool) or threshold < 1 or threshold > 10:
        errors.append(ValidationIssue(
            code="safety.disagreement_threshold_out_of_range",
            path="hardening.disagreement_threshold",
            message=(
                f"hardening.disagreement_threshold must be an int in [1, 10], "
                f"got {threshold!r}"
            ),
            severity="error",
        ))
```

Wire into `validate_config`:

```python
    _check_schema(config, errors)
    _check_model_preferences(config, errors)
    _check_suppressed_members(config, errors, warnings)
    _check_query_type_keys(config, warnings)
    _check_stage1_sections(config, errors)
    _check_hardening_models(config, errors)
    _check_routing_pool_not_empty(config, errors)
    _check_token_budget_bounds(config, errors)
    _check_disagreement_threshold(config, errors)
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_harness_validate.py -x 2>&1 | tail -10
```

Expected output (PASS): `25 passed`

- [ ] **Step 5: Commit**

```bash
git add server/harness/validate.py tests/test_harness_validate.py
git commit -m "$(cat <<'EOF'
feat(harness/validate): safety checks for routing/budget/threshold

Spec §4.2 safety rows: (a) routing.suppressed_member_ids must not
empty the candidate pool; (b) per-segment token budgets stay inside
TOKEN_BUDGET_FLOORS/CEILINGS; (c) hardening.disagreement_threshold
in [1, 10] (auto-promote sanity).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Ledger column add — `validation_warnings`

**Files:**
- Modify: `server/harness/ledger.py`
- Modify: `tests/test_harness_validate.py`

Spec §7 prescribes a new column on `session_outcomes`. Add it via `_ensure_columns` (no migration needed) and verify the additive contract.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_harness_validate.py`:

```python
def test_ledger_has_validation_warnings_column(tmp_path):
    """Spec §7: session_outcomes gains a validation_warnings column."""
    import sqlite3
    from server.harness.ledger import init_db

    db_path = tmp_path / "test_ledger.db"
    init_db(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("PRAGMA table_info(session_outcomes)").fetchall()
        column_names = {row[1] for row in rows}
    finally:
        conn.close()
    assert "validation_warnings" in column_names


def test_ledger_validation_warnings_idempotent_add(tmp_path):
    """_ensure_columns must be idempotent — call init_db twice without error."""
    from server.harness.ledger import init_db

    db_path = tmp_path / "test_ledger.db"
    init_db(db_path)
    init_db(db_path)  # second call must not raise
```

- [ ] **Step 2: Run the failing test**

```bash
uv run pytest tests/test_harness_validate.py::test_ledger_has_validation_warnings_column -x 2>&1 | tail -10
```

Expected output (FAIL): `assert 'validation_warnings' in {...}`

- [ ] **Step 3: Write the minimal implementation**

Edit `server/harness/ledger.py` in the `_ensure_columns` function. Add the new column to the `additions` dict:

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
        "routing_misses": "TEXT",
        "validation_warnings": "TEXT",
    }
    for column, column_type in additions.items():
        if column not in existing:
            conn.execute(
                f"ALTER TABLE session_outcomes ADD COLUMN {column} {column_type}"
            )

    conn.execute(
        """CREATE TABLE IF NOT EXISTS harness_config_activations (
            review_id         TEXT PRIMARY KEY,
            activated_at      TEXT NOT NULL,
            reverted_at       TEXT,
            snapshot          TEXT NOT NULL,
            previous_snapshot TEXT,
            reason            TEXT
        )"""
    )
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_harness_validate.py -x 2>&1 | tail -10
```

Expected output (PASS): `27 passed`

- [ ] **Step 5: Commit**

```bash
git add server/harness/ledger.py tests/test_harness_validate.py
git commit -m "$(cat <<'EOF'
feat(harness/ledger): add validation_warnings column

Spec §7: per-session validation warnings recorded as JSON list on
session_outcomes. Idempotent via _ensure_columns — no migration.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `reviews.run_harness_review` integration — attach `validation` field

**Files:**
- Modify: `server/harness/reviews.py`
- Create: `tests/test_harness_validate_integration.py`

Spec §4.3: every review JSON gets a top-level `validation` field. Per spec §4.4, if the validator crashes, the review surfaces a `validation`-category `HarnessRecommendation` and continues.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_harness_validate_integration.py`:

```python
"""Integration tests: validator wired into reviews, CLI, and HTTP."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from server.harness.config import HarnessConfig
from server.harness.reviews import (
    HarnessReviewError,
    apply_harness_review,
    approve_harness_review,
    run_harness_review,
)


def test_run_harness_review_attaches_validation_field(tmp_path, monkeypatch):
    """run_harness_review must produce a top-level 'validation' field."""
    monkeypatch.chdir(tmp_path)
    review = run_harness_review(dry_run=True)
    assert "validation" in review
    validation = review["validation"]
    assert isinstance(validation, dict)
    assert "readiness" in validation
    assert validation["readiness"] in {"ready", "warning", "blocked"}


def test_run_harness_review_swallows_validator_crash(tmp_path, monkeypatch):
    """Spec §4.4: validator crash must not abort the review."""
    monkeypatch.chdir(tmp_path)

    def boom(_candidate):
        raise RuntimeError("simulated validator crash")

    with patch("server.harness.reviews.validate_config", side_effect=boom):
        review = run_harness_review(dry_run=True)

    categories = [r["category"] for r in review["recommendations"]]
    assert "validation" in categories
    validation_rec = next(r for r in review["recommendations"] if r["category"] == "validation")
    assert "validation check failed" in validation_rec["summary"]
    assert "simulated validator crash" in validation_rec["details"]["error"]
```

- [ ] **Step 2: Run the failing test**

```bash
uv run pytest tests/test_harness_validate_integration.py::test_run_harness_review_attaches_validation_field -x 2>&1 | tail -10
```

Expected output (FAIL): `assert 'validation' in {...}` (the field is not yet present)

- [ ] **Step 3: Write the minimal implementation**

Edit `server/harness/reviews.py` — add an import and wire the validator into `run_harness_review`. At the top:

```python
from .validate import validate_config
```

Then, inside `run_harness_review`, after the meta-accuracy block but before constructing the `HarnessReview`, add:

```python
    # Phase 1 validate.py integration (spec §4.3, §4.4).
    validation_payload: dict
    try:
        candidate_snapshot = HarnessConfig(**{
            k: v
            for k, v in (load_config().__dict__.items())
        })
        validation_report = validate_config(candidate_snapshot)
        validation_payload = validation_report.to_dict()
    except Exception as exc:
        recommendations.append(HarnessRecommendation(
            category="validation",
            summary="validation check failed",
            details={"error": str(exc)},
        ))
        validation_payload = {
            "ok": False,
            "readiness": "blocked",
            "errors": [],
            "warnings": [],
            "error": str(exc),
        }
```

The `from .config import load_config` import must be added at the top of `reviews.py` if not already present (it's currently a local import inside `apply_harness_review`; promote it to a module-level import).

Then update the `HarnessReview` constructor call to include the validation payload in the returned dict. The `HarnessReview.to_dict()` only knows about its current fields; rather than expanding the dataclass, attach the validation payload directly to the returned dict before saving:

```python
    review = HarnessReview(
        id=f"harness_review_{time.time_ns()}",
        created_at=datetime.now(timezone.utc).isoformat(),
        recommendations=recommendations,
        proposed_config_diff=reports,
        status="proposed",
        dry_run=dry_run,
    )
    review_dict = review.to_dict()
    review_dict["validation"] = validation_payload
    _save_review(review_dict)
    return review_dict
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_harness_validate_integration.py -x 2>&1 | tail -10
```

Expected output (PASS): `2 passed`

- [ ] **Step 5: Commit**

```bash
git add server/harness/reviews.py tests/test_harness_validate_integration.py
git commit -m "$(cat <<'EOF'
feat(harness/reviews): attach validation to run_harness_review

Spec §4.3: every review JSON now carries a top-level 'validation'
field. Spec §4.4: validator exceptions become a 'validation'-category
HarnessRecommendation; never aborts the review.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: `reviews.apply_harness_review` refuses when blocked

**Files:**
- Modify: `server/harness/reviews.py`
- Modify: `tests/test_harness_validate_integration.py`

Spec §4.3: `apply_harness_review` calls `validate_config(snapshot)` and raises `HarnessReviewError("validation blocked: <first error code>")` when the result is `blocked`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_harness_validate_integration.py`:

```python
def test_apply_harness_review_refuses_blocked_snapshot(tmp_path, monkeypatch):
    """Spec §4.3: apply must raise HarnessReviewError when blocked."""
    monkeypatch.chdir(tmp_path)

    review = run_harness_review(dry_run=True)
    approved = approve_harness_review(review["id"], approve=True)

    # Inject a snapshot whose model_assignments changes reference a bogus model.
    approved["snapshot"]["model_assignments"] = {
        "changes": [
            {
                "query_type": "strategic",
                "member_id": "strategist",
                "previous_model": "deepseek/deepseek-v4-pro",
                "new_model": "fakeprovider/x",
            }
        ],
    }
    review_path = Path("data/harness_reviews") / f"{approved['id']}.json"
    review_path.write_text(json.dumps(approved, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(HarnessReviewError) as excinfo:
        apply_harness_review(approved["id"])
    assert "validation blocked" in str(excinfo.value)
    assert "xref.model_unknown" in str(excinfo.value)


def test_apply_harness_review_allows_clean_snapshot(tmp_path, monkeypatch):
    """A snapshot that validates as 'ready' or 'warning' must apply."""
    monkeypatch.chdir(tmp_path)

    review = run_harness_review(dry_run=True)
    approved = approve_harness_review(review["id"], approve=True)

    # Default snapshot is clean; apply must succeed.
    result = apply_harness_review(approved["id"])
    assert result["status"] == "applied"
```

- [ ] **Step 2: Run the failing test**

```bash
uv run pytest tests/test_harness_validate_integration.py::test_apply_harness_review_refuses_blocked_snapshot -x 2>&1 | tail -10
```

Expected output (FAIL): `DID NOT RAISE HarnessReviewError` (apply currently doesn't validate)

- [ ] **Step 3: Write the minimal implementation**

Edit `apply_harness_review` in `server/harness/reviews.py`. After the snapshot is loaded and the merged config is computed but BEFORE `save_config(updated)`:

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
    updated = _apply_snapshot_to_config(previous, snapshot)

    # Phase 1: validate the merged candidate before persisting.
    validation_report = validate_config(updated)
    if validation_report.readiness == "blocked":
        first_code = (
            validation_report.errors[0].code
            if validation_report.errors else "unknown"
        )
        raise HarnessReviewError(f"validation blocked: {first_code}")

    save_config(updated)

    snapshot_activation(
        review_id=review_id,
        snapshot=snapshot,
        previous_snapshot=previous_snapshot,
    )

    review["status"] = "applied"
    review["applied_reports"] = snapshot
    review["applied_at"] = datetime.now(timezone.utc).isoformat()
    review["validation"] = validation_report.to_dict()
    _save_review(review)
    return review
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_harness_validate_integration.py -x 2>&1 | tail -10
```

Expected output (PASS): `4 passed`

- [ ] **Step 5: Commit**

```bash
git add server/harness/reviews.py tests/test_harness_validate_integration.py
git commit -m "$(cat <<'EOF'
feat(harness/reviews): block apply on validation failure

Spec §4.3: apply_harness_review now validates the merged candidate
before save_config writes. Raises HarnessReviewError with the first
error code when readiness == "blocked". Clean snapshots proceed
and record the validation payload on the applied review.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: CLI flag `--harness-validate`

**Files:**
- Modify: `server/cli.py`
- Modify: `tests/test_harness_validate_integration.py`

Spec §4.3 + spec §11 deferred to existing CLI shape: top-level flag matching the `--tune-*` pattern. Path argument is optional; without it, validates the active config (`server/harness/harness_config.json`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_harness_validate_integration.py`:

```python
def test_cli_harness_validate_clean_config_exits_zero(tmp_path):
    """uv run python -m server.cli --harness-validate on default config → exit 0."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "server.cli", "--harness-validate"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=30,
    )
    # On a fresh tmpdir (no harness_config.json), defaults apply → ready.
    assert result.returncode == 0
    assert "ready" in result.stdout.lower()


def test_cli_harness_validate_bad_config_exits_nonzero(tmp_path):
    """A blocked config JSON file → exit code non-zero."""
    import subprocess
    import sys

    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps({
        "stage1_max_tokens": -1,
    }))
    result = subprocess.run(
        [sys.executable, "-m", "server.cli", "--harness-validate", str(bad_path)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        timeout=30,
    )
    assert result.returncode != 0
    combined = (result.stdout + result.stderr).lower()
    assert "blocked" in combined
```

- [ ] **Step 2: Run the failing test**

```bash
uv run pytest tests/test_harness_validate_integration.py::test_cli_harness_validate_clean_config_exits_zero -x 2>&1 | tail -10
```

Expected output (FAIL): `unrecognized arguments: --harness-validate`

- [ ] **Step 3: Write the minimal implementation**

Edit `server/cli.py`. Add a helper function near `run_model_tuner`:

```python
def run_harness_validate(*, config_path: str | None = None, json_output: bool = False) -> int:
    """Run the static HarnessConfig validator. Returns shell exit code."""
    import json as _json
    from pathlib import Path as _Path
    from server.harness.config import HarnessConfig, load_config
    from server.harness.validate import validate_config

    if config_path:
        path = _Path(config_path)
        if not path.exists():
            if json_output:
                print(_json.dumps({"error": "not_found", "path": str(path)}))
            else:
                console.print(f"[red]Config file not found: {path}[/red]")
            return 2
        try:
            raw = _json.loads(path.read_text(encoding="utf-8"))
            candidate: HarnessConfig | dict = raw
        except _json.JSONDecodeError as exc:
            if json_output:
                print(_json.dumps({"error": "invalid_json", "detail": str(exc)}))
            else:
                console.print(f"[red]Invalid JSON in {path}: {exc}[/red]")
            return 2
    else:
        candidate = load_config()

    report = validate_config(candidate)

    if json_output:
        print(_json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        console.print()
        console.rule("[bold yellow]Harness Config Validator[/bold yellow]")
        console.print(f"  Readiness: [bold]{report.readiness}[/bold]")
        console.print(f"  Errors: {len(report.errors)}")
        console.print(f"  Warnings: {len(report.warnings)}")
        for issue in report.errors:
            console.print(f"    [red]ERROR[/red] {issue.code} @ {issue.path}: {issue.message}")
        for issue in report.warnings:
            console.print(f"    [yellow]WARN[/yellow] {issue.code} @ {issue.path}: {issue.message}")

    return 0 if report.readiness != "blocked" else 1
```

Add to the argparse block in `cli()` (next to the other `--tune-*` flags):

```python
    parser.add_argument(
        "--harness-validate",
        nargs="?",
        const="",
        default=None,
        metavar="PATH",
        help="Run static HarnessConfig validator (optional PATH to candidate JSON)",
    )
```

Then handle the flag at the top of the `args` dispatch chain (place it before the `--replay` handler so a validate request short-circuits other harness work):

```python
    if args.harness_validate is not None:
        rc = run_harness_validate(
            config_path=args.harness_validate or None,
            json_output=args.json,
        )
        sys.exit(rc)
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_harness_validate_integration.py -x 2>&1 | tail -10
```

Expected output (PASS): `6 passed`

- [ ] **Step 5: Commit**

```bash
git add server/cli.py tests/test_harness_validate_integration.py
git commit -m "$(cat <<'EOF'
feat(cli): add --harness-validate flag

Spec §4.3: top-level CLI flag matching the existing --tune-* shape.
Optional PATH argument; without it, validates the active
harness_config.json. Exits non-zero when readiness == "blocked".

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: HTTP route `POST /harness/validate`

**Files:**
- Modify: `server/api/routes/harness.py`
- Modify: `server/api/schemas.py`
- Modify: `tests/test_harness_validate_integration.py`

Spec §4.3: `POST /harness/validate` with a candidate config body returns the `ValidationReport` as JSON. Body is optional — empty body means "validate the active config".

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_harness_validate_integration.py`:

```python
def test_http_harness_validate_default_returns_report(tmp_path, monkeypatch):
    """POST /harness/validate with empty body returns the active-config report."""
    monkeypatch.chdir(tmp_path)
    from fastapi.testclient import TestClient
    from server.api.app import app

    client = TestClient(app)
    response = client.post("/harness/validate", json={})
    assert response.status_code == 200
    payload = response.json()
    assert "readiness" in payload
    assert payload["readiness"] in {"ready", "warning", "blocked"}


def test_http_harness_validate_bad_candidate_returns_blocked(tmp_path, monkeypatch):
    """POST /harness/validate with a broken candidate body returns blocked."""
    monkeypatch.chdir(tmp_path)
    from fastapi.testclient import TestClient
    from server.api.app import app

    client = TestClient(app)
    response = client.post(
        "/harness/validate",
        json={"candidate": {"stage1_max_tokens": -1}},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["readiness"] == "blocked"
    codes = [issue["code"] for issue in payload["errors"]]
    assert "schema.stage_tokens_non_positive" in codes
```

- [ ] **Step 2: Run the failing test**

```bash
uv run pytest tests/test_harness_validate_integration.py::test_http_harness_validate_default_returns_report -x 2>&1 | tail -10
```

Expected output (FAIL): `assert response.status_code == 200` (will be 404 — route doesn't exist)

- [ ] **Step 3: Write the minimal implementation**

Edit `server/api/schemas.py`. Add (in the existing section near `HarnessReviewRunRequest`):

```python
class HarnessValidateRequest(BaseModel):
    candidate: dict | None = None
```

Edit `server/api/routes/harness.py`. Add the route handler:

```python
"""Harness review routes."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from server.harness.config import load_config
from server.harness.reviews import (
    HarnessReviewError,
    apply_harness_review,
    approve_harness_review,
    latest_harness_review,
    run_harness_review,
)
from server.harness.shadow import watch_after_apply
from server.harness.validate import validate_config

from ..schemas import (
    HarnessReviewApprovalRequest,
    HarnessReviewRunRequest,
    HarnessValidateRequest,
)


router = APIRouter()


@router.post("/harness/review/run")
async def run_harness_review_endpoint(req: HarnessReviewRunRequest):
    return run_harness_review(dry_run=req.dry_run)


@router.get("/harness/review/latest")
async def latest_harness_review_endpoint():
    review = latest_harness_review()
    if not review:
        raise HTTPException(404, detail="No harness review found")
    return review


@router.post("/harness/review/{review_id}/approve")
async def approve_harness_review_endpoint(review_id: str, req: HarnessReviewApprovalRequest):
    try:
        return approve_harness_review(review_id, approve=req.approve)
    except HarnessReviewError as e:
        raise HTTPException(422, detail=str(e))


@router.post("/harness/review/{review_id}/apply")
async def apply_harness_review_endpoint(review_id: str):
    try:
        result = apply_harness_review(review_id)
    except HarnessReviewError as e:
        raise HTTPException(422, detail=str(e))
    try:
        asyncio.create_task(asyncio.to_thread(watch_after_apply, review_id))
    except Exception:
        # Shadow watcher must not surface errors through the apply response.
        pass
    return result


@router.post("/harness/validate")
async def harness_validate_endpoint(req: HarnessValidateRequest):
    """Spec §4.3: run the static HarnessConfig validator and return the report."""
    candidate = req.candidate if req.candidate is not None else load_config()
    report = validate_config(candidate)
    return report.to_dict()
```

- [ ] **Step 4: Run the tests**

```bash
uv run pytest tests/test_harness_validate_integration.py -x 2>&1 | tail -10
```

Expected output (PASS): `8 passed`

- [ ] **Step 5: Commit**

```bash
git add server/api/routes/harness.py server/api/schemas.py tests/test_harness_validate_integration.py
git commit -m "$(cat <<'EOF'
feat(api): add POST /harness/validate route

Spec §4.3: HTTP surface for the static validator. Empty body
validates the active harness config; non-empty body validates the
provided candidate dict. Always returns 200 with a ValidationReport
JSON (readiness tells the caller pass/fail).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Full-suite contract sanity check

**Files:**
- None modified

Final task: re-run the whole validator test suite plus the existing harness tests, to confirm no regressions. No code change.

- [ ] **Step 1: Run the full harness test suite**

```bash
uv run pytest tests/test_harness_validate.py tests/test_harness_validate_integration.py tests/test_harness_config.py tests/test_harness_config_contract.py tests/test_harness_integration_contract.py tests/test_harness_trust_contract.py tests/test_ledger_contract.py -x 2>&1 | tail -20
```

Expected output (PASS): all listed test files pass; the new validate tests show 8 + the schema/xref/safety tests (~27 tests in `test_harness_validate.py` plus 8 integration tests = 35+ new tests).

- [ ] **Step 2: Run the spec-validator coverage check**

Confirm every §4.2 row maps to at least one passing test:

```bash
uv run pytest tests/test_harness_validate.py tests/test_harness_validate_integration.py -v 2>&1 | grep -E "PASSED|FAILED" | tail -40
```

Expected: every line ends in `PASSED`. The test names enumerate spec rows:
- schema: `test_schema_*`
- xref models: `test_xref_model_*`
- xref members: `test_xref_suppressed_*`
- xref query types: `test_xref_per_query_type_*`
- xref stage1 sections: `test_xref_stage1_sections_*`
- xref hardening models: `test_xref_hardening_model_*`
- safety routing: `test_safety_*routing*`
- safety budgets: `test_safety_*budget*`
- safety thresholds: `test_safety_disagreement_*`
- ledger: `test_ledger_*`
- reviews integration: `test_run_harness_review_*`, `test_apply_harness_review_*`
- CLI: `test_cli_harness_validate_*`
- HTTP: `test_http_harness_validate_*`

No commit for this step — verification only.
