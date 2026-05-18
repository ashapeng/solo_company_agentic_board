# Harness Skills (Phase 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add member-declared skills: YAML frontmatter `skills: [...]` in each member file; the harness loads `SKILL.md` bodies from `server/harness/skills/_library/<name>/` and appends them to the member's system prompt at Stage 1 and Stage 2.

**Architecture:** New subpackage `server/harness/skills/` exposes `load_skills(names) -> list[Skill]` and `list_skills()`. Skill files live at `server/harness/skills/_library/<skill-name>/SKILL.md` with YAML frontmatter (`name`, `description`) plus a markdown body. The board's member parser (`server/board/loader.py`) gains a `skills: list[str]` field on `BoardMember`. Prompt assembly in `server/board/deliberation/prompts.py` appends skill bodies after the member's own system prompt, separated by `\n\n---\n\n`, at both Stage 1 and Stage 2. Missing skills warn via `logging.warning` and are recorded in the session JSON; the ledger column `skills_used` only carries successfully-loaded skills. Body size cap (`MAX_SKILL_BODY_CHARS = 8000`) prevents a runaway skill from blowing the prompt budget — overflow is truncated with a `[…truncated…]` marker.

**Tech Stack:** Python 3.11, dataclasses, PyYAML (already used in `server/board/loader.py`), sqlite3, pytest, `caplog` for logger assertions, `tempfile.TemporaryDirectory` + monkeypatch for filesystem isolation. No live LLM calls — every test uses mocked `query_llm` or pure-Python loaders.

---

## Refinements over the spec defaults

The spec (`docs/superpowers/specs/2026-05-18-harness-cross-cutting-expansion-design.md` §6) leaves the prompt-assembly injection point under-specified — §6.4 says "located during implementation". This plan locks the injection point to the single seam `_query_member` in `server/board/deliberation/orchestrator.py` (lines 1074–1084) which Stage 1 and Stage 2 both funnel through. Rationale: both stages already share this exactly-one site where `system_prompt` is computed for `query_llm`, so injecting once via a helper applied here is strictly cleaner than dual call-site edits in `format_stage1` / `format_stage2`. The helper itself lives in `server/board/deliberation/prompts.py` as `compose_system_prompt(base_prompt, skill_bodies)` so it stays testable in isolation and `prompts.py` remains the home for all stage-prompt assembly.

| Topic | Default / naive approach | This plan's choice | Why |
|---|---|---|---|
| Where the skill helper lives | A new module like `server/board/deliberation/skill_inject.py`. | A function `compose_system_prompt(base_prompt: str, skill_bodies: list[str]) -> str` in `server/board/deliberation/prompts.py`. | `prompts.py` is the single home for prompt assembly today. Adding a new module fragments that. |
| Where the injection runs | Inside `format_stage1` and `format_stage2` (two call sites). | Inside `_query_member` in `orchestrator.py` (one call site that both stages funnel through). | Per inspection (see §"Spec coverage" below): the system prompt is sent via the `system=` kwarg of `query_llm` and is computed only at `_query_member`. `format_stage1`/`format_stage2` replace `{{system_prompt}}` with empty string. The right seam is therefore `_query_member`. |
| When skills are loaded | Inside `_query_member` (lazy, every call). | Once during orchestrator initialization (`__init__`), cached per member id. | The orchestrator already caches per-member state; reloading skill files on every Stage 1/2 fan-out call multiplies disk reads by `len(council)`. |
| Verdict on missing-skill recording | A separate `data/sessions/<id>.json` write hook. | Append to a new session field `skills: {"missing": {member_id: [names]}, "used": {member_id: [names]}}`. `BoardSession.to_dict()` already round-trips dict fields. | Mirrors the existing pattern for `contradictions`, `tool_call_results` (plain dict/list session attrs round-tripped via `to_dict`). |
| Skill cache scope | Module-level global. | Per-orchestrator-instance dict `self._skill_cache: dict[str, list[Skill]]`. | Safer across test isolation; matches how `_evidence_addenda` is stored on `self`. |
| Body truncation marker | The literal ASCII `[...truncated...]`. | The literal Unicode `[…truncated…]` (with U+2026 HORIZONTAL ELLIPSIS) per spec §6.6. | Spec uses the Unicode ellipsis explicitly; tests assert exact match. |
| Stage-2 behaviour append order | Skill bodies BEFORE the `stage2_behavior` string already injected into the user prompt. | Skill bodies are appended to the **system** prompt (not the user prompt) regardless of stage — `stage2_behavior` continues to live in the user prompt via `format_stage2`. | The spec §6.4 says "appended after the member's own system prompt" — `stage2_behavior` is not part of the system prompt today, so the two don't interact. |
| Ledger column type | A JSON column on `session_outcomes`. | `skills_used TEXT` (JSON-encoded `{member_id: [skill_names]}`) added via `_ensure_columns` — same pattern as `parse_warnings`. | Matches every other JSON-shaped column in the ledger; tuner queries already JSON-decode these on read. |
| Empty-skills behaviour | Always append the divider, body list may be empty. | If `skill_bodies == []`, `compose_system_prompt` returns `base_prompt` unchanged (no divider, no marker). | Spec §6.4: "Empty `skills` (absent or `[]`) means the member behaves exactly as today — no extra divider, no marker." |
| Description injection | Inject both description and body. | Inject body only; descriptions exist only for `list_skills()` and operator readability. | Spec §6.4. |

## Spec ↔ Plan crosswalk

| Spec section | Requirement | Plan task |
|---|---|---|
| §6.1 | Skill file shape: `_library/<name>/SKILL.md` with `name` / `description` frontmatter + markdown body | T1, T7, T8 |
| §6.2 | Member frontmatter `skills: [...]`, default `[]`, no behaviour change when absent | T9, T10, T11, T12 |
| §6.3 | `Skill` dataclass with `name`, `description`, `body`, `path` | T1 |
| §6.3 | `load_skills(names) -> list[Skill]`, ordered by request; unknown names skipped + warned + persisted | T2, T5, T18 |
| §6.3 | `list_skills() -> list[Skill]` enumerates library | T6 |
| §6.3 | `skills_used` ledger column carries only successfully-loaded skills | T17 |
| §6.4 | Append skill bodies after member's system prompt with `\n\n---\n\n` divider at Stage 1 entry | T13, T14 |
| §6.4 | Same injection at Stage 2 entry | T15, T16 |
| §6.4 | Descriptions NOT injected — only bodies | T13 |
| §6.5 | Two example skills ship: `pricing_research`, `jtbd_interview` | T7, T8 |
| §6.5 | `pricing_research` wired to `strategist`; `jtbd_interview` wired to `researcher` | T11 (and `product.md` may be wired as future work, out of scope here per "two example skills" minimum) |
| §6.6 | Missing skill → warn + skip + persist | T2, T18 |
| §6.6 | Malformed frontmatter → warn + skip | T3 |
| §6.6 | Body over `MAX_SKILL_BODY_CHARS` (8000) → truncate with `[…truncated…]` marker + warn | T4 |
| §7 | `skills_used` JSON column on `session_outcomes` via `_ensure_columns`; per-member list also in session JSON | T17 |
| §8 | Loader unit tests: well-formed, malformed, missing | T1, T2, T3, T4, T5, T6 |
| §8 | Integration test: mocked orchestrator + assembled prompt contains skill body at Stage 1 and Stage 2 | T14, T16 |
| §8 | No live LLM tests | All test tasks (verified via mocked `query_llm`) |

## File structure

### Created

| File | Purpose |
|---|---|
| `server/harness/skills/__init__.py` | Re-exports `Skill`, `load_skills`, `list_skills`, `MAX_SKILL_BODY_CHARS` |
| `server/harness/skills/loader.py` | `Skill` dataclass + loader functions + cap constant |
| `server/harness/skills/_library/pricing_research/SKILL.md` | Example skill bundle (strategist) |
| `server/harness/skills/_library/jtbd_interview/SKILL.md` | Example skill bundle (researcher) |
| `tests/test_harness_skills.py` | Loader unit tests (Tasks T1–T6) |
| `tests/test_member_skills_frontmatter.py` | `BoardMember.skills` parsing tests (Task T12) |
| `tests/test_board_skills_injection.py` | Orchestrator integration tests for Stage 1 / Stage 2 injection (Tasks T14, T16, T18) |
| `tests/test_ledger_skills_used.py` | Ledger `skills_used` column tests (Task T17) |

### Modified

| File | Change |
|---|---|
| `server/board/config.py` | Add `skills: list[str] = field(default_factory=list)` to `BoardMember` dataclass. |
| `server/board/loader.py` | Parse `skills:` from frontmatter; default `[]` if absent or null; coerce list-of-str. |
| `server/board/deliberation/prompts.py` | Add `compose_system_prompt(base_prompt: str, skill_bodies: list[str]) -> str` helper. |
| `server/board/deliberation/orchestrator.py` | Add `self._skill_cache` init; on `__init__`, eagerly load each member's skills and cache. In `_query_member`, replace `system_prompt = member.system_prompt` with a call to `compose_system_prompt` using cached bodies. Add `BoardSession.skills` field (`dict` with `used: {mid: [names]}`, `missing: {mid: [names]}`) and round-trip via `to_dict()`. Record missing skills onto the session at orchestrator init. |
| `server/harness/ledger.py` | Add `skills_used` to `_ensure_columns` additions table; thread `session.skills["used"]` (JSON-encoded) into `record_session` insert. |
| `server/members/strategist.md` | Add `skills: [pricing_research]` to frontmatter. |
| `server/members/researcher.md` | Add `skills: [jtbd_interview]` to frontmatter. |

### Untouched (out of scope)

- All other `server/members/*.md` files — they keep no `skills:` key and continue to behave exactly as today.
- `server/protocols/*.md` — stage protocol templates are unchanged; the `{{system_prompt}}` placeholder remains empty and the injection happens at `_query_member`.
- `server/board/deliberation/live.py` — out of scope; spec §6.4 names Stage 1 and Stage 2 only.
- Other harness subsystems (`validate.py`, `hooks/`) — covered by separate plans (Phase 1 and Phase 2 of the spec).

---

## PR4 — Skills infra and library

This PR ships the loader, two example skills, and the `BoardMember.skills` field. It does NOT touch the Board's prompt assembly — that's PR5. PR4 is reversible on its own: removing the new subpackage and the loader hook restores the prior behavior.

### Task T1: Create `server/harness/skills/` package + `Skill` dataclass + well-formed loader test

**Files**
- Create: `server/harness/skills/__init__.py`
- Create: `server/harness/skills/loader.py`
- Create: `server/harness/skills/_library/.gitkeep`
- Create: `tests/test_harness_skills.py`

**Steps**

- [ ] Step 1: Create the failing test.

Write `tests/test_harness_skills.py`:

```python
"""Tests for `server.harness.skills` — loader + dataclass + library."""

from __future__ import annotations

import logging
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


def _make_skill(library_dir: Path, name: str, description: str, body: str) -> Path:
    skill_dir = library_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        textwrap.dedent(f"""\
            ---
            name: {name}
            description: |
              {description}
            ---
            {body}
        """),
        encoding="utf-8",
    )
    return skill_path


class SkillLoaderWellFormedTest(unittest.TestCase):
    def test_parse_well_formed_skill_file(self):
        from server.harness.skills.loader import Skill, load_skills

        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "_library"
            path = _make_skill(
                library,
                "pricing_research",
                "Methods for SaaS pricing research.",
                "When asked about pricing, prefer van Westendorp.",
            )

            skills = load_skills(["pricing_research"], library_dir=library)

            self.assertEqual(len(skills), 1)
            skill = skills[0]
            self.assertIsInstance(skill, Skill)
            self.assertEqual(skill.name, "pricing_research")
            self.assertIn("Methods for SaaS pricing research.", skill.description)
            self.assertIn("van Westendorp", skill.body)
            self.assertEqual(skill.path, path)


if __name__ == "__main__":
    unittest.main()
```

- [ ] Step 2: Run the failing test; expect a `ModuleNotFoundError`.

```bash
uv run pytest tests/test_harness_skills.py::SkillLoaderWellFormedTest::test_parse_well_formed_skill_file -x
```

Expected output (last line): `ModuleNotFoundError: No module named 'server.harness.skills'`.

- [ ] Step 3: Create `server/harness/skills/__init__.py`:

```python
"""Member-declared skill bundles loaded into the Stage 1/2 system prompt."""

from .loader import (
    MAX_SKILL_BODY_CHARS,
    Skill,
    list_skills,
    load_skills,
)

__all__ = ["MAX_SKILL_BODY_CHARS", "Skill", "list_skills", "load_skills"]
```

- [ ] Step 4: Create `server/harness/skills/loader.py`:

```python
"""Loader for member-declared skill bundles.

Each skill lives at ``server/harness/skills/_library/<name>/SKILL.md``
with YAML frontmatter (``name``, ``description``) plus a markdown body.

Public API:

- :func:`load_skills` — load a list of skills by name, in request order.
- :func:`list_skills` — enumerate every skill in the library.
- :data:`MAX_SKILL_BODY_CHARS` — body-length cap; overflow is truncated
  with the ``[…truncated…]`` marker.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

MAX_SKILL_BODY_CHARS: int = 8000
TRUNCATION_MARKER: str = "[…truncated…]"

_DEFAULT_LIBRARY_DIR = Path(__file__).resolve().parent / "_library"


@dataclass(frozen=True)
class Skill:
    """A single member-declared skill bundle."""

    name: str
    description: str
    body: str
    path: Path


def _parse_skill_file(path: Path) -> Skill | None:
    """Parse one SKILL.md file. Returns None on any failure (warn + skip)."""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        logger.warning("Skill file unreadable at %s: %s", path, exc)
        return None

    if not text.startswith("---"):
        logger.warning("Skill file %s missing YAML frontmatter; skipping", path)
        return None

    parts = text.split("---", 2)
    if len(parts) < 3:
        logger.warning("Skill file %s missing closing ---; skipping", path)
        return None

    try:
        frontmatter = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        logger.warning("Skill file %s has malformed YAML: %s; skipping", path, exc)
        return None

    if not isinstance(frontmatter, dict):
        logger.warning("Skill file %s frontmatter is not a mapping; skipping", path)
        return None

    name = frontmatter.get("name")
    description = frontmatter.get("description")
    if not isinstance(name, str) or not name.strip():
        logger.warning("Skill file %s missing 'name'; skipping", path)
        return None
    if description is None:
        description = ""
    description = str(description).strip()

    body = parts[2].strip()
    if len(body) > MAX_SKILL_BODY_CHARS:
        logger.warning(
            "Skill %s body length %d exceeds MAX_SKILL_BODY_CHARS=%d; truncating",
            name,
            len(body),
            MAX_SKILL_BODY_CHARS,
        )
        body = body[:MAX_SKILL_BODY_CHARS] + TRUNCATION_MARKER

    return Skill(name=name.strip(), description=description, body=body, path=path)


def load_skills(
    names: list[str],
    *,
    library_dir: Path | None = None,
) -> list[Skill]:
    """Load skills by name in request order.

    Unknown names emit a ``logging.warning`` and are dropped from the
    returned list. Callers may also inspect the warning records via
    ``caplog`` or compute the diff between ``names`` and
    ``[s.name for s in returned]`` to detect misses.
    """
    base = library_dir if library_dir is not None else _DEFAULT_LIBRARY_DIR
    loaded: list[Skill] = []
    for name in names:
        skill_path = base / name / "SKILL.md"
        if not skill_path.is_file():
            logger.warning("Skill %r not found at %s; skipping", name, skill_path)
            continue
        parsed = _parse_skill_file(skill_path)
        if parsed is None:
            continue
        loaded.append(parsed)
    return loaded


def list_skills(*, library_dir: Path | None = None) -> list[Skill]:
    """Enumerate every well-formed SKILL.md in the library, alphabetically."""
    base = library_dir if library_dir is not None else _DEFAULT_LIBRARY_DIR
    if not base.is_dir():
        return []
    out: list[Skill] = []
    for skill_dir in sorted(base.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_path = skill_dir / "SKILL.md"
        if not skill_path.is_file():
            continue
        parsed = _parse_skill_file(skill_path)
        if parsed is not None:
            out.append(parsed)
    return out
```

- [ ] Step 5: Create `server/harness/skills/_library/.gitkeep` (empty file) so the directory is tracked:

```bash
mkdir -p server/harness/skills/_library
touch server/harness/skills/_library/.gitkeep
```

- [ ] Step 6: Run the test again; expect PASS.

```bash
uv run pytest tests/test_harness_skills.py::SkillLoaderWellFormedTest::test_parse_well_formed_skill_file -x
```

Expected last line: `1 passed in <time>s`.

- [ ] Step 7: Commit.

```bash
git add server/harness/skills/__init__.py server/harness/skills/loader.py server/harness/skills/_library/.gitkeep tests/test_harness_skills.py
git commit -m "$(cat <<'EOF'
feat(skills): add Skill dataclass + load_skills/list_skills loader

Creates server/harness/skills/ subpackage per design spec §6. Skill
files live at _library/<name>/SKILL.md with name/description frontmatter
plus markdown body. Loader warns + skips on malformed/missing files
rather than raising, and truncates bodies over MAX_SKILL_BODY_CHARS
(8000) with the spec's […truncated…] marker.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task T2: Loader — missing skill file warns and is skipped

**Files**
- Modify: `tests/test_harness_skills.py`

**Steps**

- [ ] Step 1: Append the failing test.

Append to `tests/test_harness_skills.py`:

```python
class SkillLoaderMissingTest(unittest.TestCase):
    def test_missing_skill_warns_and_is_skipped(self):
        from server.harness.skills.loader import load_skills

        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "_library"
            library.mkdir(parents=True, exist_ok=True)
            # Note: no skill files created.

            with self.assertLogs("server.harness.skills.loader", level="WARNING") as cm:
                skills = load_skills(["does_not_exist"], library_dir=library)

            self.assertEqual(skills, [])
            joined = " ".join(cm.output)
            self.assertIn("does_not_exist", joined)
            self.assertIn("not found", joined.lower())

    def test_partial_load_keeps_known_skips_unknown(self):
        from server.harness.skills.loader import load_skills

        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "_library"
            _make_skill(library, "alpha", "alpha desc", "alpha body")

            with self.assertLogs("server.harness.skills.loader", level="WARNING"):
                skills = load_skills(["alpha", "ghost"], library_dir=library)

            self.assertEqual([s.name for s in skills], ["alpha"])
```

- [ ] Step 2: Run; expect PASS already (logic is in T1).

```bash
uv run pytest tests/test_harness_skills.py::SkillLoaderMissingTest -x
```

Expected last line: `2 passed in <time>s`.

If FAIL: T1's loader had a bug — fix `load_skills` so missing files trigger `logger.warning("Skill %r not found at %s; skipping", ...)` and skip.

- [ ] Step 3: Commit.

```bash
git add tests/test_harness_skills.py
git commit -m "$(cat <<'EOF'
test(skills): missing skill file warns + is skipped

Locks the contract that load_skills() never raises on missing files —
it emits a logging.warning naming the missing skill and continues with
the remaining requested skills.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task T3: Loader — malformed frontmatter warns and is skipped

**Files**
- Modify: `tests/test_harness_skills.py`

**Steps**

- [ ] Step 1: Append the failing test.

Append to `tests/test_harness_skills.py`:

```python
class SkillLoaderMalformedTest(unittest.TestCase):
    def test_missing_frontmatter_delim_warns_and_skips(self):
        from server.harness.skills.loader import load_skills

        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "_library"
            skill_dir = library / "broken"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                "no frontmatter here, just body text",
                encoding="utf-8",
            )

            with self.assertLogs("server.harness.skills.loader", level="WARNING") as cm:
                skills = load_skills(["broken"], library_dir=library)

            self.assertEqual(skills, [])
            self.assertTrue(any("frontmatter" in line.lower() for line in cm.output))

    def test_malformed_yaml_warns_and_skips(self):
        from server.harness.skills.loader import load_skills

        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "_library"
            skill_dir = library / "bad_yaml"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: bad_yaml\ndescription: : :\n---\nbody\n",
                encoding="utf-8",
            )

            with self.assertLogs("server.harness.skills.loader", level="WARNING") as cm:
                skills = load_skills(["bad_yaml"], library_dir=library)

            self.assertEqual(skills, [])
            self.assertTrue(any("malformed" in line.lower() or "yaml" in line.lower() for line in cm.output))

    def test_missing_name_field_warns_and_skips(self):
        from server.harness.skills.loader import load_skills

        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "_library"
            skill_dir = library / "noname"
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(
                "---\ndescription: no name field\n---\nbody\n",
                encoding="utf-8",
            )

            with self.assertLogs("server.harness.skills.loader", level="WARNING") as cm:
                skills = load_skills(["noname"], library_dir=library)

            self.assertEqual(skills, [])
            self.assertTrue(any("name" in line.lower() for line in cm.output))
```

- [ ] Step 2: Run; expect PASS (logic is in T1's `_parse_skill_file`).

```bash
uv run pytest tests/test_harness_skills.py::SkillLoaderMalformedTest -x
```

Expected last line: `3 passed in <time>s`.

If FAIL: revisit `_parse_skill_file` to ensure each branch logs the relevant keyword (`frontmatter`, `malformed`/`yaml`, `name`).

- [ ] Step 3: Commit.

```bash
git add tests/test_harness_skills.py
git commit -m "$(cat <<'EOF'
test(skills): malformed frontmatter warns + skips

Covers three malformations: missing --- delimiters, broken YAML, and
missing 'name' field. Each emits a logger.warning naming the issue and
returns an empty load result rather than raising.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task T4: Loader — body length cap with truncation marker

**Files**
- Modify: `tests/test_harness_skills.py`

**Steps**

- [ ] Step 1: Append the failing test.

Append to `tests/test_harness_skills.py`:

```python
class SkillBodyCapTest(unittest.TestCase):
    def test_body_within_cap_is_unchanged(self):
        from server.harness.skills.loader import MAX_SKILL_BODY_CHARS, load_skills

        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "_library"
            short_body = "a" * (MAX_SKILL_BODY_CHARS - 10)
            _make_skill(library, "small", "small skill", short_body)

            skills = load_skills(["small"], library_dir=library)

            self.assertEqual(len(skills), 1)
            self.assertEqual(skills[0].body, short_body)
            self.assertNotIn("truncated", skills[0].body.lower())

    def test_body_over_cap_is_truncated_with_marker(self):
        from server.harness.skills.loader import (
            MAX_SKILL_BODY_CHARS,
            TRUNCATION_MARKER,
            load_skills,
        )

        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "_library"
            oversize_body = "b" * (MAX_SKILL_BODY_CHARS + 500)
            _make_skill(library, "big", "big skill", oversize_body)

            with self.assertLogs("server.harness.skills.loader", level="WARNING") as cm:
                skills = load_skills(["big"], library_dir=library)

            self.assertEqual(len(skills), 1)
            body = skills[0].body
            self.assertTrue(body.endswith(TRUNCATION_MARKER))
            self.assertEqual(len(body), MAX_SKILL_BODY_CHARS + len(TRUNCATION_MARKER))
            self.assertTrue(any("truncating" in line.lower() for line in cm.output))

    def test_truncation_marker_uses_unicode_ellipsis(self):
        from server.harness.skills.loader import TRUNCATION_MARKER

        self.assertEqual(TRUNCATION_MARKER, "[…truncated…]")
```

- [ ] Step 2: Run; expect PASS (truncation logic is in T1).

```bash
uv run pytest tests/test_harness_skills.py::SkillBodyCapTest -x
```

Expected last line: `3 passed in <time>s`.

- [ ] Step 3: Commit.

```bash
git add tests/test_harness_skills.py
git commit -m "$(cat <<'EOF'
test(skills): enforce MAX_SKILL_BODY_CHARS truncation

Body within cap is unchanged; body over cap is sliced to exactly
MAX_SKILL_BODY_CHARS chars and appended with the Unicode-ellipsis
[…truncated…] marker. A logging.warning fires on truncation.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task T5: `load_skills` preserves request order; unknown names interleaved correctly

**Files**
- Modify: `tests/test_harness_skills.py`

**Steps**

- [ ] Step 1: Append the failing test.

Append to `tests/test_harness_skills.py`:

```python
class SkillLoaderOrderTest(unittest.TestCase):
    def test_load_skills_returns_request_order(self):
        from server.harness.skills.loader import load_skills

        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "_library"
            _make_skill(library, "first", "1st", "first body")
            _make_skill(library, "second", "2nd", "second body")
            _make_skill(library, "third", "3rd", "third body")

            skills = load_skills(
                ["third", "first", "second"],
                library_dir=library,
            )

            self.assertEqual([s.name for s in skills], ["third", "first", "second"])

    def test_unknown_interleaved_skips_only_unknown(self):
        from server.harness.skills.loader import load_skills

        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "_library"
            _make_skill(library, "alpha", "a", "abody")
            _make_skill(library, "gamma", "g", "gbody")

            with self.assertLogs("server.harness.skills.loader", level="WARNING"):
                skills = load_skills(
                    ["alpha", "beta", "gamma", "delta"],
                    library_dir=library,
                )

            self.assertEqual([s.name for s in skills], ["alpha", "gamma"])

    def test_empty_names_returns_empty_list_no_warnings(self):
        from server.harness.skills.loader import load_skills

        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "_library"
            library.mkdir(parents=True, exist_ok=True)

            skills = load_skills([], library_dir=library)

            self.assertEqual(skills, [])
```

- [ ] Step 2: Run; expect PASS (T1's loop is order-preserving).

```bash
uv run pytest tests/test_harness_skills.py::SkillLoaderOrderTest -x
```

Expected last line: `3 passed in <time>s`.

- [ ] Step 3: Commit.

```bash
git add tests/test_harness_skills.py
git commit -m "$(cat <<'EOF'
test(skills): load_skills preserves request order, skips unknown

Locks two contracts: (1) returned list order matches the input names
list, and (2) unknown names interleaved with known ones are skipped
without disturbing the remaining order.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task T6: `list_skills` enumerates the library

**Files**
- Modify: `tests/test_harness_skills.py`

**Steps**

- [ ] Step 1: Append the failing test.

Append to `tests/test_harness_skills.py`:

```python
class SkillListTest(unittest.TestCase):
    def test_list_skills_returns_sorted_well_formed_only(self):
        from server.harness.skills.loader import list_skills

        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "_library"
            _make_skill(library, "zebra", "z", "zbody")
            _make_skill(library, "apple", "a", "abody")
            broken_dir = library / "broken"
            broken_dir.mkdir(parents=True, exist_ok=True)
            (broken_dir / "SKILL.md").write_text("no frontmatter", encoding="utf-8")

            with self.assertLogs("server.harness.skills.loader", level="WARNING"):
                listed = list_skills(library_dir=library)

            names = [s.name for s in listed]
            self.assertEqual(names, ["apple", "zebra"])

    def test_list_skills_empty_library_returns_empty(self):
        from server.harness.skills.loader import list_skills

        with TemporaryDirectory() as tmp:
            library = Path(tmp) / "_library"
            library.mkdir(parents=True, exist_ok=True)

            self.assertEqual(list_skills(library_dir=library), [])

    def test_list_skills_missing_library_returns_empty(self):
        from server.harness.skills.loader import list_skills

        with TemporaryDirectory() as tmp:
            missing = Path(tmp) / "no_such_dir"

            self.assertEqual(list_skills(library_dir=missing), [])
```

- [ ] Step 2: Run; expect PASS.

```bash
uv run pytest tests/test_harness_skills.py::SkillListTest -x
```

Expected last line: `3 passed in <time>s`.

- [ ] Step 3: Commit.

```bash
git add tests/test_harness_skills.py
git commit -m "$(cat <<'EOF'
test(skills): list_skills enumerates library alphabetically

Returns only well-formed skills, sorted by directory name. Handles
empty and missing library directories without raising.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task T7: Example skill — `pricing_research`

**Files**
- Create: `server/harness/skills/_library/pricing_research/SKILL.md`
- Modify: `tests/test_harness_skills.py`

**Steps**

- [ ] Step 1: Append the failing test.

Append to `tests/test_harness_skills.py`:

```python
class BundledSkillsTest(unittest.TestCase):
    def test_pricing_research_skill_loads(self):
        from server.harness.skills.loader import load_skills

        skills = load_skills(["pricing_research"])  # uses real _library

        self.assertEqual(len(skills), 1, "pricing_research skill must ship in the library")
        skill = skills[0]
        self.assertEqual(skill.name, "pricing_research")
        self.assertTrue(skill.description)
        self.assertTrue(skill.body)
        self.assertIn("van Westendorp", skill.body, "must reference the canonical method")
```

- [ ] Step 2: Run; expect FAIL with `pricing_research skill must ship in the library`.

```bash
uv run pytest tests/test_harness_skills.py::BundledSkillsTest::test_pricing_research_skill_loads -x
```

Expected last line: `AssertionError: 0 != 1 : pricing_research skill must ship in the library`.

- [ ] Step 3: Create `server/harness/skills/_library/pricing_research/SKILL.md`:

```markdown
---
name: pricing_research
description: |
  Methods for early-stage SaaS pricing research: van Westendorp,
  Gabor-Granger, willingness-to-pay interviews. Apply when a question
  centers on price discovery, packaging, or willingness-to-pay.
---

## Pricing Research Toolkit

When a question asks about price, packaging, or willingness-to-pay, work
through these methods in order. Pick the first that matches the available
evidence; do not skip ahead.

### 1. Van Westendorp Price Sensitivity Meter
Ask four questions of 30–100 target users:

- At what price would this be SO EXPENSIVE you wouldn't consider it?
- At what price would this start to feel EXPENSIVE but you would still consider it?
- At what price would this be a BARGAIN — great value for the money?
- At what price would this be SO CHEAP you would question the quality?

Plot the four cumulative distributions. The intersection of "too expensive"
and "too cheap" is the optimal price point; the intersection of "expensive"
and "bargain" is the indifference price point. Use both to size a range.

### 2. Gabor-Granger Direct Test
Present a single price; ask "would you buy at $X?". Repeat across a price
ladder. Fit a demand curve. Use when you already have a working concept
and need a revenue-maximizing point estimate.

### 3. Willingness-to-Pay Interview
Open-ended: "What would you expect to pay for a tool that does X?" then
"What would you pay if it also did Y?". Use early, before any pricing
concept exists. Capture the reasoning, not just the number — the reasoning
generalizes; the number rarely does.

### Decision Heuristics
- Fewer than 30 interviews → WTP interviews only; both quantitative methods
  need sample sizes that small studies cannot deliver reliably.
- B2B → anchor on the buyer's existing line-item spend (current vendor,
  internal labor cost). Numbers without an anchor are noise.
- Freemium → run Van Westendorp on the PAID tier only; the free tier price
  is always zero and the question is conversion price, not list price.

### Evidence Hierarchy
Direct paid conversions > Van Westendorp with N≥30 > Gabor-Granger with
N≥30 > WTP interviews with N≥10 > Pricing-page benchmarks > Analyst
reports > Gut feel. Tag every pricing claim with its tier.
```

- [ ] Step 4: Run; expect PASS.

```bash
uv run pytest tests/test_harness_skills.py::BundledSkillsTest::test_pricing_research_skill_loads -x
```

Expected last line: `1 passed in <time>s`.

- [ ] Step 5: Commit.

```bash
git add server/harness/skills/_library/pricing_research/SKILL.md tests/test_harness_skills.py
git commit -m "$(cat <<'EOF'
feat(skills): ship pricing_research example skill

First proof-of-concept skill. Captures the van Westendorp / Gabor-Granger /
WTP-interview ladder so members declaring this skill (PR5 wires it to
strategist) get pricing-research methods injected into their system
prompt at Stage 1 and Stage 2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task T8: Example skill — `jtbd_interview`

**Files**
- Create: `server/harness/skills/_library/jtbd_interview/SKILL.md`
- Modify: `tests/test_harness_skills.py`

**Steps**

- [ ] Step 1: Append the failing test.

Append to `tests/test_harness_skills.py` (inside `BundledSkillsTest`):

```python
    def test_jtbd_interview_skill_loads(self):
        from server.harness.skills.loader import load_skills

        skills = load_skills(["jtbd_interview"])  # uses real _library

        self.assertEqual(len(skills), 1, "jtbd_interview skill must ship in the library")
        skill = skills[0]
        self.assertEqual(skill.name, "jtbd_interview")
        self.assertTrue(skill.description)
        self.assertTrue(skill.body)
        self.assertIn("Jobs to be Done", skill.body)
```

- [ ] Step 2: Run; expect FAIL with `jtbd_interview skill must ship in the library`.

```bash
uv run pytest tests/test_harness_skills.py::BundledSkillsTest::test_jtbd_interview_skill_loads -x
```

Expected last line: `AssertionError: 0 != 1 : jtbd_interview skill must ship in the library`.

- [ ] Step 3: Create `server/harness/skills/_library/jtbd_interview/SKILL.md`:

```markdown
---
name: jtbd_interview
description: |
  Jobs to be Done customer-interview protocol for surfacing the
  underlying job a customer hires a product to do. Apply when designing
  customer discovery questions or synthesising interview transcripts.
---

## Jobs to be Done Interview Protocol

When designing customer interviews or interpreting transcripts, use this
structure to surface the JOB the customer is hiring the product to do —
not the product features they describe.

### 1. Anchor on a Recent Switch
Open every interview with: "Tell me about the last time you switched
from [old solution] to [new solution]." Do not ask "why do you use X?".
The switch is where the job becomes observable; steady-state use rarely
exposes it.

### 2. The Forces Timeline
Walk the customer through four moments, in order:

- **First Thought** — when did they first think a change might be needed?
- **Passive Looking** — when did they start noticing alternatives?
- **Active Looking** — when did they evaluate options seriously?
- **Decision Moment** — what tipped them into buying?

Each moment has two forces: the **push** of the old situation and the
**pull** of the new one. Note both. The combination defines the job.

### 3. The Five "Whys" — Used Sparingly
For the single most surprising answer, ask "why" up to five times. Stop
at the moment the customer cannot answer — that's the boundary of their
articulated job. Anything beyond is your inference.

### 4. Synthesis: The JTBD Statement
Translate each transcript into one canonical sentence:

> "When [situation], I want to [motivation], so I can [expected outcome]."

Cluster identical statements across interviews. A pattern that holds in
≥4 of 8 interviews is a candidate JOB. Below that, it is signal only.

### Anti-Patterns
- Do NOT ask hypotheticals ("would you pay $50 for...?"). Past behavior
  predicts; stated future behavior does not.
- Do NOT lead with feature questions ("would you like a dark mode?").
  Features are solutions; the job is the problem.
- Do NOT confuse demographics with jobs. "Marketing managers want X" is
  almost never true; "people preparing for a quarterly review want X"
  almost always is.

### Output Shape
For each interview, produce:
1. JTBD statement (one sentence, the structure above)
2. Push forces (1–3 bullets, observed in transcript)
3. Pull forces (1–3 bullets, observed in transcript)
4. Anxieties and inertias (forces against the switch)
5. Confidence: Low / Medium / High based on number of corroborating quotes
```

- [ ] Step 4: Run; expect PASS.

```bash
uv run pytest tests/test_harness_skills.py::BundledSkillsTest::test_jtbd_interview_skill_loads -x
```

Expected last line: `1 passed in <time>s`.

- [ ] Step 5: Commit.

```bash
git add server/harness/skills/_library/jtbd_interview/SKILL.md tests/test_harness_skills.py
git commit -m "$(cat <<'EOF'
feat(skills): ship jtbd_interview example skill

Second proof-of-concept skill: Jobs to be Done interview protocol.
Wired to researcher in PR5. Together with pricing_research, this covers
two distinct shapes (analytical method vs interview protocol) so the
loader gets exercised across realistic skill bodies.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task T9: Extend `BoardMember` dataclass with `skills` field

**Files**
- Modify: `server/board/config.py`
- Create: `tests/test_member_skills_frontmatter.py`

**Steps**

- [ ] Step 1: Create the failing test.

Write `tests/test_member_skills_frontmatter.py`:

```python
"""Tests for `BoardMember.skills` and frontmatter parsing."""

from __future__ import annotations

import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class BoardMemberSkillsDataclassTest(unittest.TestCase):
    def test_board_member_has_skills_field_default_empty(self):
        from server.board.config import BoardMember

        member = BoardMember(
            id="m1",
            title="Member 1",
            role="Role 1",
            expertise=[],
            system_prompt="hello",
        )
        self.assertEqual(member.skills, [])

    def test_board_member_accepts_skills_list(self):
        from server.board.config import BoardMember

        member = BoardMember(
            id="m1",
            title="Member 1",
            role="Role 1",
            expertise=[],
            system_prompt="hello",
            skills=["alpha", "beta"],
        )
        self.assertEqual(member.skills, ["alpha", "beta"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] Step 2: Run; expect FAIL with `TypeError: __init__() got an unexpected keyword argument 'skills'`.

```bash
uv run pytest tests/test_member_skills_frontmatter.py::BoardMemberSkillsDataclassTest -x
```

Expected last line: `TypeError: BoardMember.__init__() got an unexpected keyword argument 'skills'`.

- [ ] Step 3: Add the field to `BoardMember` in `server/board/config.py`. Insert the new line immediately after `evidence_required: bool = False` (currently the last field):

Find this block:

```python
@dataclass
class BoardMember:
    """A single board member with a defined role and expertise."""
    id: str
    title: str
    role: str
    expertise: list[str]
    system_prompt: str
    stage2_behavior: str = ""         # peer review behavior instructions
    stage2_addendum: str = ""          # deprecated alias for stage2_behavior
    model_override: str | None = None  # use specific model for this member
    priority: int = 0                  # higher = speaks earlier in synthesis
    tags: list[str] = field(default_factory=list)
    intake: MemberIntake | None = None  # optional structured feedback intake
    evidence_required: bool = False    # whether member requires evidence inputs
```

Append one line so it ends:

```python
    intake: MemberIntake | None = None  # optional structured feedback intake
    evidence_required: bool = False    # whether member requires evidence inputs
    skills: list[str] = field(default_factory=list)  # declared harness skill names (spec §6.2)
```

- [ ] Step 4: Run; expect PASS.

```bash
uv run pytest tests/test_member_skills_frontmatter.py::BoardMemberSkillsDataclassTest -x
```

Expected last line: `2 passed in <time>s`.

- [ ] Step 5: Commit.

```bash
git add server/board/config.py tests/test_member_skills_frontmatter.py
git commit -m "$(cat <<'EOF'
feat(skills): add BoardMember.skills field (default empty list)

Per design spec §6.2, members may declare named skills in YAML
frontmatter; the loader (next task) populates this field. Default of
an empty list keeps every existing member's behaviour identical to
today.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task T10: Extend `load_members` to parse `skills:` frontmatter

**Files**
- Modify: `server/board/loader.py`
- Modify: `tests/test_member_skills_frontmatter.py`

**Steps**

- [ ] Step 1: Append the failing test.

Append to `tests/test_member_skills_frontmatter.py`:

```python
def _write_member(path: Path, frontmatter_extra: str = "") -> None:
    body = textwrap.dedent(f"""\
        ---
        id: test_member
        title: Test Member
        role: Test Role
        expertise: [testing]
        priority: 10
        tags: [test]
        model_override: null
        intake:
          clarifying_question: "q?"
          immediate_concern: "c"
          proposed_path: "p"
          required_execution_unit: "strategy"
        {frontmatter_extra}
        ---

        ## Identity
        Test.

        ## Stage 2 Behavior
        Review peers.
    """)
    path.write_text(body, encoding="utf-8")


class LoaderSkillsParsingTest(unittest.TestCase):
    def test_member_with_skills_list_parses(self):
        from server.board.loader import load_members

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_member(
                tmp_path / "test_member.md",
                frontmatter_extra="skills: [pricing_research, jtbd_interview]",
            )

            members = load_members(directory=tmp_path)

            self.assertEqual(len(members), 1)
            self.assertEqual(
                members[0].skills,
                ["pricing_research", "jtbd_interview"],
            )

    def test_member_without_skills_defaults_empty(self):
        from server.board.loader import load_members

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_member(tmp_path / "test_member.md")

            members = load_members(directory=tmp_path)

            self.assertEqual(len(members), 1)
            self.assertEqual(members[0].skills, [])

    def test_member_with_empty_skills_list_defaults_empty(self):
        from server.board.loader import load_members

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_member(
                tmp_path / "test_member.md",
                frontmatter_extra="skills: []",
            )

            members = load_members(directory=tmp_path)

            self.assertEqual(len(members), 1)
            self.assertEqual(members[0].skills, [])

    def test_member_with_null_skills_defaults_empty(self):
        from server.board.loader import load_members

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_member(
                tmp_path / "test_member.md",
                frontmatter_extra="skills: null",
            )

            members = load_members(directory=tmp_path)

            self.assertEqual(len(members), 1)
            self.assertEqual(members[0].skills, [])

    def test_skills_string_is_coerced_to_single_element_list(self):
        from server.board.loader import load_members

        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_member(
                tmp_path / "test_member.md",
                frontmatter_extra='skills: "pricing_research"',
            )

            members = load_members(directory=tmp_path)

            self.assertEqual(len(members), 1)
            self.assertEqual(members[0].skills, ["pricing_research"])
```

- [ ] Step 2: Run; expect FAIL on all five tests (loader still defaults `skills` to `[]` because it never reads it; `test_member_with_skills_list_parses` and `test_skills_string_is_coerced_to_single_element_list` fail with `AssertionError: [] != ['pricing_research', 'jtbd_interview']` and similar).

```bash
uv run pytest tests/test_member_skills_frontmatter.py::LoaderSkillsParsingTest -x
```

Expected last line: `AssertionError: [] != ['pricing_research', 'jtbd_interview']` (first failure).

- [ ] Step 3: Modify `server/board/loader.py`. Find this block (after the `tags_raw` parsing):

```python
        # Build tags list
        tags_raw = frontmatter.get("tags", [])
        if isinstance(tags_raw, str):
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        elif isinstance(tags_raw, list):
            tags = [str(t) for t in tags_raw]
        else:
            tags = []

        # Handle model_override (YAML null -> None)
```

Insert a new block immediately after the tags block and before the model_override block:

```python
        # Build skills list (spec §6.2). Accept list, single string, null, or absent.
        skills_raw = frontmatter.get("skills", [])
        if skills_raw is None:
            skills = []
        elif isinstance(skills_raw, str):
            skills = [skills_raw.strip()] if skills_raw.strip() else []
        elif isinstance(skills_raw, list):
            skills = [str(s).strip() for s in skills_raw if str(s).strip()]
        else:
            skills = []
```

Then locate the `BoardMember(...)` constructor call further down:

```python
        member = BoardMember(
            id=frontmatter["id"],
            title=frontmatter["title"],
            role=frontmatter["role"],
            expertise=expertise,
            system_prompt=body,
            stage2_behavior=stage2_behavior,
            model_override=model_override,
            priority=int(frontmatter.get("priority", 0)),
            tags=tags,
            intake=_parse_member_intake(frontmatter.get("intake")),
            evidence_required=bool(frontmatter.get("evidence_required", False)),
        )
```

Insert `skills=skills,` immediately after the `evidence_required=...` line:

```python
        member = BoardMember(
            id=frontmatter["id"],
            title=frontmatter["title"],
            role=frontmatter["role"],
            expertise=expertise,
            system_prompt=body,
            stage2_behavior=stage2_behavior,
            model_override=model_override,
            priority=int(frontmatter.get("priority", 0)),
            tags=tags,
            intake=_parse_member_intake(frontmatter.get("intake")),
            evidence_required=bool(frontmatter.get("evidence_required", False)),
            skills=skills,
        )
```

- [ ] Step 4: Run; expect PASS.

```bash
uv run pytest tests/test_member_skills_frontmatter.py::LoaderSkillsParsingTest -x
```

Expected last line: `5 passed in <time>s`.

- [ ] Step 5: Commit.

```bash
git add server/board/loader.py tests/test_member_skills_frontmatter.py
git commit -m "$(cat <<'EOF'
feat(skills): parse 'skills:' frontmatter on member files

Loader accepts list, single-string, null, or absent forms. Strings are
stripped + coerced to a single-element list. Empty / null / absent all
yield []. Members keep behaving identically when no skills field is
present.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task T11: Wire `skills:` into example member files (`strategist`, `researcher`)

**Files**
- Modify: `server/members/strategist.md`
- Modify: `server/members/researcher.md`
- Modify: `tests/test_member_skills_frontmatter.py`

**Steps**

- [ ] Step 1: Append the failing test.

Append to `tests/test_member_skills_frontmatter.py`:

```python
class LoadedMembersDeclareSkillsTest(unittest.TestCase):
    def test_strategist_declares_pricing_research(self):
        from server.board.config import get_members_by_id

        members = get_members_by_id()
        strategist = members.get("strategist")
        self.assertIsNotNone(strategist, "strategist member must exist")
        self.assertIn("pricing_research", strategist.skills)

    def test_researcher_declares_jtbd_interview(self):
        from server.board.config import get_members_by_id

        members = get_members_by_id()
        researcher = members.get("researcher")
        self.assertIsNotNone(researcher, "researcher member must exist")
        self.assertIn("jtbd_interview", researcher.skills)

    def test_other_members_have_no_skills_declared(self):
        from server.board.config import get_board_members

        excluded = {"strategist", "researcher"}
        for member in get_board_members():
            if member.id in excluded:
                continue
            self.assertEqual(
                member.skills,
                [],
                f"member {member.id!r} has unexpected skills: {member.skills}",
            )
```

- [ ] Step 2: Run; expect FAIL with `AssertionError: 'pricing_research' not found in []`.

```bash
uv run pytest tests/test_member_skills_frontmatter.py::LoadedMembersDeclareSkillsTest -x
```

Expected last line: `AssertionError: 'pricing_research' not found in []`.

Note: `get_board_members()` may be cached from earlier tests. The cache is per-process and the test runs in a fresh process, so this is not a concern at TDD time. If you hit a stale-cache surprise in development, run `pytest --forked` or restart the test process.

- [ ] Step 3: Edit `server/members/strategist.md`. Find this frontmatter:

```yaml
---
id: strategist
title: Chief Strategist
role: CSO / Market Strategy & Evidence
expertise: [market analysis, competitive intelligence, market sizing, go-to-market strategy, evidence assessment, customer segmentation]
priority: 90
tags: [strategy, market, evidence, competition, gtm]
model_override: null
evidence_required: true
intake:
  clarifying_question: "Which seller segment and market wedge should this target first?"
  immediate_concern: "Market and competitive assumptions are not yet grounded."
  proposed_path: "Define the wedge and evidence threshold before spend."
  required_execution_unit: "strategy"
---
```

Insert one line immediately after `evidence_required: true`:

```yaml
---
id: strategist
title: Chief Strategist
role: CSO / Market Strategy & Evidence
expertise: [market analysis, competitive intelligence, market sizing, go-to-market strategy, evidence assessment, customer segmentation]
priority: 90
tags: [strategy, market, evidence, competition, gtm]
model_override: null
evidence_required: true
skills: [pricing_research]
intake:
  clarifying_question: "Which seller segment and market wedge should this target first?"
  immediate_concern: "Market and competitive assumptions are not yet grounded."
  proposed_path: "Define the wedge and evidence threshold before spend."
  required_execution_unit: "strategy"
---
```

- [ ] Step 4: Edit `server/members/researcher.md`. Find this frontmatter:

```yaml
---
id: researcher
title: Customer Researcher
role: Voice of Customer / User Research Lead
expertise: [customer discovery, user interviews, persona development, jobs-to-be-done, qualitative research, behavioral analysis]
priority: 80
tags: [customer, research, interviews, personas, jtbd]
model_override: null
evidence_required: true
intake:
  clarifying_question: "Which customers have already shown this pain through behavior or spend?"
  immediate_concern: "No customer evidence has been supplied."
  proposed_path: "Collect customer discovery evidence before the final decision."
  required_execution_unit: "research"
---
```

Insert one line immediately after `evidence_required: true`:

```yaml
---
id: researcher
title: Customer Researcher
role: Voice of Customer / User Research Lead
expertise: [customer discovery, user interviews, persona development, jobs-to-be-done, qualitative research, behavioral analysis]
priority: 80
tags: [customer, research, interviews, personas, jtbd]
model_override: null
evidence_required: true
skills: [jtbd_interview]
intake:
  clarifying_question: "Which customers have already shown this pain through behavior or spend?"
  immediate_concern: "No customer evidence has been supplied."
  proposed_path: "Collect customer discovery evidence before the final decision."
  required_execution_unit: "research"
---
```

- [ ] Step 5: Run; expect PASS.

```bash
uv run pytest tests/test_member_skills_frontmatter.py::LoadedMembersDeclareSkillsTest -x
```

Expected last line: `3 passed in <time>s`.

- [ ] Step 6: Run the full skills test file to confirm no regression.

```bash
uv run pytest tests/test_harness_skills.py tests/test_member_skills_frontmatter.py -x
```

Expected last line: `<N> passed in <time>s` where N matches the total tests across both files (T1–T11 added tests).

- [ ] Step 7: Commit.

```bash
git add server/members/strategist.md server/members/researcher.md tests/test_member_skills_frontmatter.py
git commit -m "$(cat <<'EOF'
feat(skills): declare pricing_research + jtbd_interview on members

Wires the two bundled example skills to their intended members per
spec §6.5. Other members keep no skills declared so we can verify the
no-injection no-op path in PR5 against them.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task T12: PR4 surface sweep — `__init__.py` re-exports + import smoke

**Files**
- Modify: `tests/test_harness_skills.py`

**Steps**

- [ ] Step 1: Append the failing test.

Append to `tests/test_harness_skills.py`:

```python
class PackageSurfaceTest(unittest.TestCase):
    def test_package_reexports_public_api(self):
        import server.harness.skills as pkg

        self.assertTrue(hasattr(pkg, "Skill"))
        self.assertTrue(hasattr(pkg, "load_skills"))
        self.assertTrue(hasattr(pkg, "list_skills"))
        self.assertTrue(hasattr(pkg, "MAX_SKILL_BODY_CHARS"))
        self.assertEqual(pkg.MAX_SKILL_BODY_CHARS, 8000)

    def test_skill_is_frozen_dataclass(self):
        from dataclasses import FrozenInstanceError

        from server.harness.skills import Skill

        s = Skill(name="x", description="d", body="b", path=Path("/tmp/x"))
        with self.assertRaises(FrozenInstanceError):
            s.name = "y"  # type: ignore[misc]
```

- [ ] Step 2: Run; expect PASS (T1 already wired everything).

```bash
uv run pytest tests/test_harness_skills.py::PackageSurfaceTest -x
```

Expected last line: `2 passed in <time>s`.

- [ ] Step 3: Run the whole PR4 test surface.

```bash
uv run pytest tests/test_harness_skills.py tests/test_member_skills_frontmatter.py -v
```

Expected: all tests pass; no warnings about skipped tests.

- [ ] Step 4: Commit.

```bash
git add tests/test_harness_skills.py
git commit -m "$(cat <<'EOF'
test(skills): lock PR4 public surface — re-exports + frozen dataclass

Confirms server.harness.skills exposes Skill, load_skills, list_skills,
and MAX_SKILL_BODY_CHARS; and that Skill is a frozen dataclass so the
loaded cache cannot be mutated downstream by accident.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

**PR4 done.** Push the branch and open the PR. PR5 (next section) is independently mergeable and adds the Board-side injection.

---

## PR5 — Board prompt injection

This PR wires the loaded skills into the Stage 1 / Stage 2 system prompt at orchestrator-level, adds the `skills` session field, persists it in session JSON, and adds the `skills_used` ledger column.

### Task T13: `compose_system_prompt` helper in `prompts.py`

**Files**
- Modify: `server/board/deliberation/prompts.py`
- Create: `tests/test_board_skills_injection.py`

**Steps**

- [ ] Step 1: Create the failing test.

Write `tests/test_board_skills_injection.py`:

```python
"""Stage 1 / Stage 2 skill injection — orchestrator + helper tests."""

from __future__ import annotations

import unittest


class ComposeSystemPromptHelperTest(unittest.TestCase):
    def test_empty_skill_bodies_returns_base_unchanged(self):
        from server.board.deliberation.prompts import compose_system_prompt

        out = compose_system_prompt("BASE", [])

        self.assertEqual(out, "BASE")

    def test_single_skill_appended_with_divider(self):
        from server.board.deliberation.prompts import compose_system_prompt

        out = compose_system_prompt("BASE", ["SKILL_BODY"])

        self.assertEqual(out, "BASE\n\n---\n\nSKILL_BODY")

    def test_multiple_skills_appended_with_divider_between(self):
        from server.board.deliberation.prompts import compose_system_prompt

        out = compose_system_prompt("BASE", ["A", "B", "C"])

        self.assertEqual(out, "BASE\n\n---\n\nA\n\n---\n\nB\n\n---\n\nC")

    def test_divider_is_exactly_two_newlines_dashes_two_newlines(self):
        from server.board.deliberation.prompts import compose_system_prompt

        out = compose_system_prompt("X", ["Y"])

        self.assertIn("\n\n---\n\n", out)
        # No double-divider, no extra blank lines:
        self.assertNotIn("\n\n\n---", out)
        self.assertNotIn("---\n\n\n", out)

    def test_empty_base_with_skill_yields_divider_then_skill(self):
        from server.board.deliberation.prompts import compose_system_prompt

        out = compose_system_prompt("", ["BODY"])

        # Edge case: empty base prompt is unusual but mustn't crash.
        # The helper appends with the standard divider; downstream consumers
        # never pass empty base in practice (every member has a system_prompt).
        self.assertEqual(out, "\n\n---\n\nBODY")


if __name__ == "__main__":
    unittest.main()
```

- [ ] Step 2: Run; expect FAIL with `ImportError: cannot import name 'compose_system_prompt'`.

```bash
uv run pytest tests/test_board_skills_injection.py::ComposeSystemPromptHelperTest -x
```

Expected last line: `ImportError: cannot import name 'compose_system_prompt' from 'server.board.deliberation.prompts'`.

- [ ] Step 3: Add the helper. Open `server/board/deliberation/prompts.py` and append immediately above the line that starts `# Stage 1 — Independent Analysis` (currently around line 97):

Locate this anchor:

```python
# ---------------------------------------------------------------------------
# Stage 1 — Independent Analysis
# ---------------------------------------------------------------------------
```

Insert ABOVE it:

```python
# ---------------------------------------------------------------------------
# Skill injection helper (spec §6.4)
# ---------------------------------------------------------------------------

_SKILL_DIVIDER = "\n\n---\n\n"


def compose_system_prompt(base_prompt: str, skill_bodies: list[str]) -> str:
    """Append member-declared skill bodies to a base system prompt.

    Spec §6.4: skill bodies are appended after the member's own system
    prompt, separated by ``\\n\\n---\\n\\n``, in the order declared in
    member frontmatter. Skill descriptions are NOT injected — only bodies.
    An empty ``skill_bodies`` list returns ``base_prompt`` unchanged (no
    divider, no marker).
    """
    if not skill_bodies:
        return base_prompt
    return _SKILL_DIVIDER.join([base_prompt, *skill_bodies])


```

- [ ] Step 4: Run; expect PASS.

```bash
uv run pytest tests/test_board_skills_injection.py::ComposeSystemPromptHelperTest -x
```

Expected last line: `5 passed in <time>s`.

- [ ] Step 5: Commit.

```bash
git add server/board/deliberation/prompts.py tests/test_board_skills_injection.py
git commit -m "$(cat <<'EOF'
feat(skills): compose_system_prompt helper for skill injection

Appends skill bodies to a base system prompt with the spec's
'\\n\\n---\\n\\n' divider. Empty skills list returns the base unchanged
(no extra divider). Descriptions are NOT injected — only bodies. This
helper is called from the orchestrator's _query_member next.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task T14: Stage 1 injection — orchestrator loads skills + calls helper

**Files**
- Modify: `server/board/deliberation/orchestrator.py`
- Modify: `tests/test_board_skills_injection.py`

**Steps**

- [ ] Step 1: Append the failing test.

Append to `tests/test_board_skills_injection.py`:

```python
class Stage1SkillInjectionTest(unittest.TestCase):
    def test_query_member_appends_skill_body_to_system_prompt_at_stage_1(self):
        import asyncio
        from unittest.mock import AsyncMock, patch

        from server.board.config import BoardMember
        from server.board.deliberation.orchestrator import BoardDeliberation

        member = BoardMember(
            id="strategist",
            title="Strategist",
            role="CSO",
            expertise=[],
            system_prompt="STRATEGIST BASE PROMPT",
            skills=["pricing_research"],
        )

        with patch(
            "server.board.deliberation.orchestrator.query_llm",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = type(
                "Resp",
                (),
                {
                    "content": "ok",
                    "model": "test/model",
                    "latency_seconds": 0.01,
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cost_estimate": 0.0,
                },
            )()

            board = BoardDeliberation(
                council=[member],
                chairman=member,
                model_assignments={member.id: "test/model"},
            )
            asyncio.run(board._query_member(member, prompt="PROMPT", stage=1))

            self.assertTrue(mock_llm.called)
            kwargs = mock_llm.call_args.kwargs
            system_prompt = kwargs["system"]
            self.assertIn("STRATEGIST BASE PROMPT", system_prompt)
            self.assertIn("\n\n---\n\n", system_prompt)
            self.assertIn("van Westendorp", system_prompt,
                          "pricing_research body must be appended at Stage 1")

    def test_member_without_skills_sends_base_prompt_unchanged_at_stage_1(self):
        import asyncio
        from unittest.mock import AsyncMock, patch

        from server.board.config import BoardMember
        from server.board.deliberation.orchestrator import BoardDeliberation

        member = BoardMember(
            id="critic",
            title="Critic",
            role="Red Team",
            expertise=[],
            system_prompt="CRITIC BASE PROMPT",
            skills=[],
        )

        with patch(
            "server.board.deliberation.orchestrator.query_llm",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = type(
                "Resp",
                (),
                {
                    "content": "ok",
                    "model": "test/model",
                    "latency_seconds": 0.01,
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cost_estimate": 0.0,
                },
            )()

            board = BoardDeliberation(
                council=[member],
                chairman=member,
                model_assignments={member.id: "test/model"},
            )
            asyncio.run(board._query_member(member, prompt="PROMPT", stage=1))

            kwargs = mock_llm.call_args.kwargs
            system_prompt = kwargs["system"]
            self.assertEqual(system_prompt, "CRITIC BASE PROMPT")
            self.assertNotIn("---", system_prompt)
```

- [ ] Step 2: Run; expect FAIL — orchestrator does not yet call `compose_system_prompt`, so the system prompt sent equals `"STRATEGIST BASE PROMPT"` exactly, not the skill-appended form.

```bash
uv run pytest tests/test_board_skills_injection.py::Stage1SkillInjectionTest -x
```

Expected first failure line: `AssertionError: '\n\n---\n\n' not found in 'STRATEGIST BASE PROMPT'`.

- [ ] Step 3: Modify `server/board/deliberation/orchestrator.py`.

First, extend the import at the top (the existing `from .prompts import` line). Find line 46:

```python
from .prompts import format_stage1, format_stage2, format_stage3, format_stage4, format_standalone_secretary_brief
```

Replace with:

```python
from .prompts import (
    compose_system_prompt,
    format_stage1,
    format_stage2,
    format_stage3,
    format_stage4,
    format_standalone_secretary_brief,
)
```

Add a new import for the loader. Locate the existing block of imports from `server.harness`. If none exists in this file yet, add this new line near the other `from server.` imports at the top:

```python
from server.harness.skills import load_skills as _load_skills_for_member
```

If unsure where it goes: append it to the import block right after `from .prompts import (...)`.

Next, locate `_query_member` around lines 1060–1098. Find this block:

```python
        system_prompt = member.system_prompt
        addendum = getattr(self, "_evidence_addenda", {}).get(member.id)
        if stage == 1 and addendum:
            system_prompt = f"{member.system_prompt}\n\n{addendum}"
```

Replace with:

```python
        base_prompt = member.system_prompt
        addendum = getattr(self, "_evidence_addenda", {}).get(member.id)
        if stage == 1 and addendum:
            base_prompt = f"{member.system_prompt}\n\n{addendum}"

        # Spec §6.4: append member-declared skill bodies at Stage 1 and Stage 2.
        skill_bodies: list[str] = []
        if stage in (1, 2) and getattr(member, "skills", []):
            skill_cache = getattr(self, "_skill_cache", None)
            if skill_cache is None:
                skill_cache = {}
                self._skill_cache = skill_cache  # type: ignore[attr-defined]
            cached = skill_cache.get(member.id)
            if cached is None:
                cached = _load_skills_for_member(list(member.skills))
                skill_cache[member.id] = cached
            skill_bodies = [s.body for s in cached]

        system_prompt = compose_system_prompt(base_prompt, skill_bodies)
```

- [ ] Step 4: Run; expect PASS.

```bash
uv run pytest tests/test_board_skills_injection.py::Stage1SkillInjectionTest -x
```

Expected last line: `2 passed in <time>s`.

- [ ] Step 5: Run the existing orchestrator contract tests to confirm no regression.

```bash
uv run pytest tests/test_board_core_contracts.py tests/test_board_contract.py -x
```

Expected: all pass.

- [ ] Step 6: Commit.

```bash
git add server/board/deliberation/orchestrator.py tests/test_board_skills_injection.py
git commit -m "$(cat <<'EOF'
feat(skills): inject skill bodies into Stage 1 system prompt

Wires compose_system_prompt() into _query_member at the single seam
that both Stage 1 and Stage 2 funnel through. Loads each member's
declared skills via server.harness.skills.load_skills(), caches the
result per orchestrator instance, and appends the bodies with the
spec's '\\n\\n---\\n\\n' divider. Members with no declared skills get
their base prompt verbatim — no divider, no marker.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task T15: Stage 2 injection — same code path verifies via stage=2

**Files**
- Modify: `tests/test_board_skills_injection.py`

**Steps**

- [ ] Step 1: Append the failing test.

Append to `tests/test_board_skills_injection.py`:

```python
class Stage2SkillInjectionTest(unittest.TestCase):
    def test_query_member_appends_skill_body_to_system_prompt_at_stage_2(self):
        import asyncio
        from unittest.mock import AsyncMock, patch

        from server.board.config import BoardMember
        from server.board.deliberation.orchestrator import BoardDeliberation

        member = BoardMember(
            id="researcher",
            title="Researcher",
            role="Voice of Customer",
            expertise=[],
            system_prompt="RESEARCHER BASE",
            skills=["jtbd_interview"],
        )

        with patch(
            "server.board.deliberation.orchestrator.query_llm",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = type(
                "Resp",
                (),
                {
                    "content": "ok",
                    "model": "test/model",
                    "latency_seconds": 0.01,
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cost_estimate": 0.0,
                },
            )()

            board = BoardDeliberation(
                council=[member],
                chairman=member,
                model_assignments={member.id: "test/model"},
            )
            asyncio.run(board._query_member(member, prompt="PROMPT", stage=2))

            kwargs = mock_llm.call_args.kwargs
            system_prompt = kwargs["system"]
            self.assertIn("RESEARCHER BASE", system_prompt)
            self.assertIn("Jobs to be Done", system_prompt,
                          "jtbd_interview body must be appended at Stage 2")

    def test_stage_3_and_4_do_not_inject_skills(self):
        import asyncio
        from unittest.mock import AsyncMock, patch

        from server.board.config import BoardMember
        from server.board.deliberation.orchestrator import BoardDeliberation

        member = BoardMember(
            id="strategist",
            title="Strategist",
            role="CSO",
            expertise=[],
            system_prompt="STRATEGIST BASE",
            skills=["pricing_research"],
        )

        with patch(
            "server.board.deliberation.orchestrator.query_llm",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = type(
                "Resp",
                (),
                {
                    "content": "ok",
                    "model": "test/model",
                    "latency_seconds": 0.01,
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cost_estimate": 0.0,
                },
            )()

            board = BoardDeliberation(
                council=[member],
                chairman=member,
                model_assignments={member.id: "test/model"},
            )
            # Stage 3 / 4 prompts are sent via different methods, but the helper
            # _query_member is the gate that controls injection. We pass stage=3
            # directly to verify the conditional excludes non-1/2 stages.
            asyncio.run(board._query_member(member, prompt="PROMPT", stage=3))

            kwargs = mock_llm.call_args.kwargs
            self.assertEqual(kwargs["system"], "STRATEGIST BASE")
            self.assertNotIn("---", kwargs["system"])
```

- [ ] Step 2: Run; expect PASS (T14's logic already covers stage 2 via the `stage in (1, 2)` guard).

```bash
uv run pytest tests/test_board_skills_injection.py::Stage2SkillInjectionTest -x
```

Expected last line: `2 passed in <time>s`.

If FAIL on `test_stage_3_and_4_do_not_inject_skills`: revisit the T14 guard — it must be `if stage in (1, 2)`, not `if stage >= 1`.

- [ ] Step 3: Commit.

```bash
git add tests/test_board_skills_injection.py
git commit -m "$(cat <<'EOF'
test(skills): lock Stage 2 injection + Stage 3/4 no-injection

Stage 2 must inject skills via the same _query_member seam as Stage 1.
Stage 3 (chairman synthesis) and Stage 4 (secretary brief) MUST NOT
inject member skills — those stages use different system prompts and
the spec only covers Stages 1 and 2.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task T16: Skill cache is per-orchestrator and reloaded between instances

**Files**
- Modify: `tests/test_board_skills_injection.py`

**Steps**

- [ ] Step 1: Append the failing test.

Append to `tests/test_board_skills_injection.py`:

```python
class SkillCacheScopeTest(unittest.TestCase):
    def test_skill_cache_is_per_orchestrator_instance(self):
        import asyncio
        from unittest.mock import AsyncMock, patch

        from server.board.config import BoardMember
        from server.board.deliberation.orchestrator import BoardDeliberation

        member = BoardMember(
            id="strategist",
            title="Strategist",
            role="CSO",
            expertise=[],
            system_prompt="BASE",
            skills=["pricing_research"],
        )

        with patch(
            "server.board.deliberation.orchestrator.query_llm",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = type(
                "Resp",
                (),
                {
                    "content": "ok",
                    "model": "test/model",
                    "latency_seconds": 0.01,
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cost_estimate": 0.0,
                },
            )()

            board_a = BoardDeliberation(
                council=[member],
                chairman=member,
                model_assignments={member.id: "test/model"},
            )
            board_b = BoardDeliberation(
                council=[member],
                chairman=member,
                model_assignments={member.id: "test/model"},
            )
            asyncio.run(board_a._query_member(member, prompt="P", stage=1))
            asyncio.run(board_b._query_member(member, prompt="P", stage=1))

            self.assertIsNotNone(getattr(board_a, "_skill_cache", None))
            self.assertIsNotNone(getattr(board_b, "_skill_cache", None))
            self.assertIsNot(board_a._skill_cache, board_b._skill_cache)

    def test_skill_cache_repeat_call_does_not_reload(self):
        import asyncio
        from unittest.mock import AsyncMock, patch

        from server.board.config import BoardMember
        from server.board.deliberation.orchestrator import BoardDeliberation

        member = BoardMember(
            id="strategist",
            title="Strategist",
            role="CSO",
            expertise=[],
            system_prompt="BASE",
            skills=["pricing_research"],
        )

        with patch(
            "server.board.deliberation.orchestrator.query_llm",
            new_callable=AsyncMock,
        ) as mock_llm, patch(
            "server.board.deliberation.orchestrator._load_skills_for_member"
        ) as mock_load:
            mock_llm.return_value = type(
                "Resp",
                (),
                {
                    "content": "ok",
                    "model": "test/model",
                    "latency_seconds": 0.01,
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cost_estimate": 0.0,
                },
            )()
            # Build a real Skill object so the cache stores a usable entry.
            from server.harness.skills import Skill
            from pathlib import Path
            mock_load.return_value = [
                Skill(name="pricing_research", description="d",
                      body="van Westendorp body", path=Path("/tmp/p")),
            ]

            board = BoardDeliberation(
                council=[member],
                chairman=member,
                model_assignments={member.id: "test/model"},
            )
            asyncio.run(board._query_member(member, prompt="P", stage=1))
            asyncio.run(board._query_member(member, prompt="P", stage=2))
            asyncio.run(board._query_member(member, prompt="P", stage=1))

            self.assertEqual(mock_load.call_count, 1,
                             "skills must be loaded once per orchestrator per member")
```

- [ ] Step 2: Run; expect PASS.

```bash
uv run pytest tests/test_board_skills_injection.py::SkillCacheScopeTest -x
```

Expected last line: `2 passed in <time>s`.

If FAIL on `test_skill_cache_repeat_call_does_not_reload`: the cache check in `_query_member` is broken — the `cached is None` branch must be the only path that calls `_load_skills_for_member`.

- [ ] Step 3: Commit.

```bash
git add tests/test_board_skills_injection.py
git commit -m "$(cat <<'EOF'
test(skills): skill cache is per-instance and reload-once

Two orchestrator instances must own independent skill caches (no
cross-test bleed). Repeat _query_member calls for the same member
must hit the cache, not the loader.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task T17: `skills_used` ledger column

**Files**
- Modify: `server/harness/ledger.py`
- Modify: `server/board/deliberation/orchestrator.py`
- Create: `tests/test_ledger_skills_used.py`

**Steps**

- [ ] Step 1: Create the failing test.

Write `tests/test_ledger_skills_used.py`:

```python
"""Tests for the `skills_used` column on `session_outcomes`."""

from __future__ import annotations

import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace


def _make_session_stub(session_id: str, skills_used: dict[str, list[str]]):
    """Build the minimum-shape session that `record_session` reads."""
    from server.board.metrics import SessionMetrics

    metrics = SessionMetrics()

    session = SimpleNamespace(
        session_id=session_id,
        classification={"query_type": "strategy", "complexity": "standard"},
        verification={},
        memory={},
        metrics=metrics,
        stage1_responses=[],
        stage2_responses=[],
        delegation_plan={},
        clarification={},
        skills={"used": skills_used, "missing": {}},
    )
    return session


class LedgerSkillsUsedColumnTest(unittest.TestCase):
    def test_ensure_columns_adds_skills_used(self):
        from server.harness.ledger import init_db

        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "ledger.db"
            init_db(db)
            conn = sqlite3.connect(str(db))
            try:
                cols = {row[1] for row in conn.execute("PRAGMA table_info(session_outcomes)")}
            finally:
                conn.close()
            self.assertIn("skills_used", cols)

    def test_record_session_persists_skills_used_json(self):
        from server.harness.ledger import record_session

        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "ledger.db"
            session = _make_session_stub(
                "s-001",
                {"strategist": ["pricing_research"], "researcher": ["jtbd_interview"]},
            )

            record_session(session, config_version=1, db_path=db)

            conn = sqlite3.connect(str(db))
            try:
                row = conn.execute(
                    "SELECT skills_used FROM session_outcomes WHERE session_id = ?",
                    ("s-001",),
                ).fetchone()
            finally:
                conn.close()

            self.assertIsNotNone(row)
            parsed = json.loads(row[0])
            self.assertEqual(
                parsed,
                {"strategist": ["pricing_research"], "researcher": ["jtbd_interview"]},
            )

    def test_record_session_empty_skills_used_is_empty_json_object(self):
        from server.harness.ledger import record_session

        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "ledger.db"
            session = _make_session_stub("s-002", {})

            record_session(session, config_version=1, db_path=db)

            conn = sqlite3.connect(str(db))
            try:
                row = conn.execute(
                    "SELECT skills_used FROM session_outcomes WHERE session_id = ?",
                    ("s-002",),
                ).fetchone()
            finally:
                conn.close()

            self.assertEqual(json.loads(row[0]), {})

    def test_record_session_missing_skills_attr_writes_empty_json(self):
        """A session WITHOUT a `skills` attribute (legacy code path) must
        not crash record_session; it writes an empty JSON object."""
        from server.harness.ledger import record_session
        from server.board.metrics import SessionMetrics

        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "ledger.db"
            session = SimpleNamespace(
                session_id="s-003",
                classification={},
                verification={},
                memory={},
                metrics=SessionMetrics(),
                stage1_responses=[],
                stage2_responses=[],
                delegation_plan={},
                clarification={},
                # No `skills` attr at all.
            )

            record_session(session, config_version=1, db_path=db)

            conn = sqlite3.connect(str(db))
            try:
                row = conn.execute(
                    "SELECT skills_used FROM session_outcomes WHERE session_id = ?",
                    ("s-003",),
                ).fetchone()
            finally:
                conn.close()

            self.assertEqual(json.loads(row[0]), {})


if __name__ == "__main__":
    unittest.main()
```

- [ ] Step 2: Run; expect FAIL with `AssertionError: 'skills_used' not found in {...}`.

```bash
uv run pytest tests/test_ledger_skills_used.py -x
```

Expected first failure line: `AssertionError: 'skills_used' not found in {...existing columns...}`.

- [ ] Step 3: Modify `server/harness/ledger.py`.

3a. In `_ensure_columns`, find the `additions` dict:

```python
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
    }
```

Add one entry:

```python
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
        "skills_used": "TEXT",
    }
```

3b. In `record_session`, find the INSERT statement and the trailing `_active_review_id(conn),` parameter. Replace the entire INSERT block (current lines ~154–208):

Find this:

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

Replace with (one extra column + one extra placeholder + one extra value):

```python
        skills_record = getattr(session, "skills", None) or {}
        skills_used_map = skills_record.get("used", {}) if isinstance(skills_record, dict) else {}

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
                verifier_model, verifier_provider, chairman_provider, applied_review_id,
                skills_used
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                json.dumps(skills_used_map),
            ),
        )
```

Note the `members_routed` line near the top — it must remain unchanged. The change is at the bottom of the column list (one extra `skills_used` column name + one extra `?` placeholder + one extra `json.dumps(skills_used_map)` value) and a `?` count change from 34 to 35.

3c. Account for the orchestrator writing `session.skills`. Modify `server/board/deliberation/orchestrator.py`:

Find the `BoardSession` dataclass (around lines 453–528). Locate this final field:

```python
    conversation: dict = field(default_factory=lambda: {
        "messages": [],
        "routing_trace": [],
    })
```

Insert AFTER `auto_promoted_rebuttals: list[dict] = field(default_factory=list)` and BEFORE `conversation`:

```python
    # Phase 3 skills (spec §6). Populated by the orchestrator at __init__ from
    # each member's declared skills list. Shape:
    #   {"used": {member_id: [skill_names_successfully_loaded]},
    #    "missing": {member_id: [skill_names_not_found_or_malformed]}}
    skills: dict = field(default_factory=lambda: {"used": {}, "missing": {}})
```

Also add `"skills": self.skills,` to `BoardSession.to_dict()` right after the `"auto_promoted_rebuttals": self.auto_promoted_rebuttals,` entry:

```python
            "auto_promoted_rebuttals": self.auto_promoted_rebuttals,
            "skills": self.skills,
            "conversation": self.conversation,
```

- [ ] Step 4: Run the ledger test; expect PASS.

```bash
uv run pytest tests/test_ledger_skills_used.py -x
```

Expected last line: `4 passed in <time>s`.

- [ ] Step 5: Run the existing ledger contract tests to confirm no regression.

```bash
uv run pytest tests/test_ledger_contract.py -x
```

Expected: all pass.

- [ ] Step 6: Commit.

```bash
git add server/harness/ledger.py server/board/deliberation/orchestrator.py tests/test_ledger_skills_used.py
git commit -m "$(cat <<'EOF'
feat(skills): persist skills_used to ledger + session JSON

Adds `skills_used TEXT` column to session_outcomes via the existing
_ensure_columns pattern (no migration). The column carries a JSON
map {member_id: [skill_names]} of skills that successfully loaded.
BoardSession gains a `skills` field that round-trips through to_dict()
so session JSON also exposes used + missing skills per spec §6.3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task T18: Populate `session.skills.used` + `session.skills.missing` in the orchestrator

**Files**
- Modify: `server/board/deliberation/orchestrator.py`
- Modify: `tests/test_board_skills_injection.py`

**Steps**

- [ ] Step 1: Append the failing test.

Append to `tests/test_board_skills_injection.py`:

```python
class SessionSkillsRecordTest(unittest.TestCase):
    def test_used_skills_recorded_on_session_after_query(self):
        import asyncio
        from unittest.mock import AsyncMock, patch
        from pathlib import Path

        from server.board.config import BoardMember
        from server.board.deliberation.orchestrator import (
            BoardDeliberation,
            BoardSession,
        )
        from server.harness.skills import Skill

        member = BoardMember(
            id="strategist",
            title="Strategist",
            role="CSO",
            expertise=[],
            system_prompt="BASE",
            skills=["pricing_research"],
        )
        session = BoardSession(session_id="s-x", user_query="q")

        with patch(
            "server.board.deliberation.orchestrator.query_llm",
            new_callable=AsyncMock,
        ) as mock_llm, patch(
            "server.board.deliberation.orchestrator._load_skills_for_member"
        ) as mock_load:
            mock_llm.return_value = type(
                "Resp",
                (),
                {
                    "content": "ok",
                    "model": "test/model",
                    "latency_seconds": 0.01,
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cost_estimate": 0.0,
                },
            )()
            mock_load.return_value = [
                Skill(name="pricing_research", description="d",
                      body="body", path=Path("/tmp/p")),
            ]

            board = BoardDeliberation(
                council=[member],
                chairman=member,
                model_assignments={member.id: "test/model"},
                session=session,
            )
            asyncio.run(board._query_member(member, prompt="P", stage=1))

            self.assertEqual(
                session.skills["used"],
                {"strategist": ["pricing_research"]},
            )
            self.assertEqual(session.skills["missing"], {})

    def test_missing_skills_recorded_on_session(self):
        import asyncio
        from unittest.mock import AsyncMock, patch

        from server.board.config import BoardMember
        from server.board.deliberation.orchestrator import (
            BoardDeliberation,
            BoardSession,
        )

        member = BoardMember(
            id="strategist",
            title="Strategist",
            role="CSO",
            expertise=[],
            system_prompt="BASE",
            skills=["pricing_research", "ghost_skill"],
        )
        session = BoardSession(session_id="s-y", user_query="q")

        with patch(
            "server.board.deliberation.orchestrator.query_llm",
            new_callable=AsyncMock,
        ) as mock_llm, patch(
            "server.board.deliberation.orchestrator._load_skills_for_member"
        ) as mock_load:
            mock_llm.return_value = type(
                "Resp",
                (),
                {
                    "content": "ok",
                    "model": "test/model",
                    "latency_seconds": 0.01,
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cost_estimate": 0.0,
                },
            )()
            from server.harness.skills import Skill
            from pathlib import Path
            # Loader returns only the resolvable skill; the other is "missing".
            mock_load.return_value = [
                Skill(name="pricing_research", description="d",
                      body="body", path=Path("/tmp/p")),
            ]

            board = BoardDeliberation(
                council=[member],
                chairman=member,
                model_assignments={member.id: "test/model"},
                session=session,
            )
            asyncio.run(board._query_member(member, prompt="P", stage=1))

            self.assertEqual(
                session.skills["used"],
                {"strategist": ["pricing_research"]},
            )
            self.assertEqual(
                session.skills["missing"],
                {"strategist": ["ghost_skill"]},
            )

    def test_member_without_skills_writes_nothing_to_session(self):
        import asyncio
        from unittest.mock import AsyncMock, patch

        from server.board.config import BoardMember
        from server.board.deliberation.orchestrator import (
            BoardDeliberation,
            BoardSession,
        )

        member = BoardMember(
            id="critic",
            title="Critic",
            role="Red Team",
            expertise=[],
            system_prompt="BASE",
            skills=[],
        )
        session = BoardSession(session_id="s-z", user_query="q")

        with patch(
            "server.board.deliberation.orchestrator.query_llm",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = type(
                "Resp",
                (),
                {
                    "content": "ok",
                    "model": "test/model",
                    "latency_seconds": 0.01,
                    "input_tokens": 1,
                    "output_tokens": 1,
                    "cost_estimate": 0.0,
                },
            )()

            board = BoardDeliberation(
                council=[member],
                chairman=member,
                model_assignments={member.id: "test/model"},
                session=session,
            )
            asyncio.run(board._query_member(member, prompt="P", stage=1))

            self.assertEqual(session.skills["used"], {})
            self.assertEqual(session.skills["missing"], {})
```

- [ ] Step 2: Run; expect FAIL — `BoardDeliberation.__init__` does not accept `session=` yet, OR the session field never receives any data because T14's skill-cache code path doesn't write to `session.skills`.

```bash
uv run pytest tests/test_board_skills_injection.py::SessionSkillsRecordTest -x
```

Expected first failure line: probably `TypeError: __init__() got an unexpected keyword argument 'session'` (if `BoardDeliberation` doesn't accept a session kwarg) OR `AssertionError: {} != {'strategist': ['pricing_research']}` (if it does, but T14's code doesn't populate the session).

If `BoardDeliberation` already accepts a `session` keyword (or stores one as `self.session`), the test wiring is sound; if not, adapt the test or store the session on the orchestrator. Inspect the constructor before proceeding.

```bash
grep -n "class BoardDeliberation\|def __init__" server/board/deliberation/orchestrator.py | head -10
```

If `BoardDeliberation.__init__` does NOT accept `session`, replace `session=session` in both tests with attaching it after construction:

```python
            board = BoardDeliberation(
                council=[member],
                chairman=member,
                model_assignments={member.id: "test/model"},
            )
            board._session = session  # type: ignore[attr-defined]
            asyncio.run(board._query_member(member, prompt="P", stage=1))
```

…and in step 3 below, read the session from `getattr(self, "_session", None)`.

- [ ] Step 3: Modify `server/board/deliberation/orchestrator.py`.

Locate the T14 skill-loading block in `_query_member` (added in Task 14):

```python
        # Spec §6.4: append member-declared skill bodies at Stage 1 and Stage 2.
        skill_bodies: list[str] = []
        if stage in (1, 2) and getattr(member, "skills", []):
            skill_cache = getattr(self, "_skill_cache", None)
            if skill_cache is None:
                skill_cache = {}
                self._skill_cache = skill_cache  # type: ignore[attr-defined]
            cached = skill_cache.get(member.id)
            if cached is None:
                cached = _load_skills_for_member(list(member.skills))
                skill_cache[member.id] = cached
            skill_bodies = [s.body for s in cached]
```

Extend the `if cached is None:` branch to record used and missing skill names onto the session:

```python
        # Spec §6.4: append member-declared skill bodies at Stage 1 and Stage 2.
        skill_bodies: list[str] = []
        if stage in (1, 2) and getattr(member, "skills", []):
            skill_cache = getattr(self, "_skill_cache", None)
            if skill_cache is None:
                skill_cache = {}
                self._skill_cache = skill_cache  # type: ignore[attr-defined]
            cached = skill_cache.get(member.id)
            if cached is None:
                cached = _load_skills_for_member(list(member.skills))
                skill_cache[member.id] = cached
                # Spec §6.3 / §6.6: record used and missing onto the session
                # so they round-trip via BoardSession.to_dict() and feed the
                # ledger `skills_used` column.
                session = getattr(self, "_session", None) or getattr(self, "session", None)
                if session is not None and hasattr(session, "skills"):
                    loaded_names = [s.name for s in cached]
                    if loaded_names:
                        session.skills.setdefault("used", {})[member.id] = loaded_names
                    missing_names = [
                        n for n in member.skills if n not in set(loaded_names)
                    ]
                    if missing_names:
                        session.skills.setdefault("missing", {})[member.id] = missing_names
            skill_bodies = [s.body for s in cached]
```

If `BoardDeliberation.__init__` does not already accept a `session=` kwarg (verify via the grep in step 2), add one. Find the `__init__` signature and add `session: "BoardSession | None" = None,` to the parameter list, then add `self._session = session` to the body. Keep all existing parameters intact.

- [ ] Step 4: Run; expect PASS.

```bash
uv run pytest tests/test_board_skills_injection.py::SessionSkillsRecordTest -x
```

Expected last line: `3 passed in <time>s`.

- [ ] Step 5: Run the full skills suite to make sure earlier tests still pass.

```bash
uv run pytest tests/test_board_skills_injection.py tests/test_harness_skills.py tests/test_member_skills_frontmatter.py tests/test_ledger_skills_used.py -x
```

Expected: all pass.

- [ ] Step 6: Run a broader regression set to catch fallout.

```bash
uv run pytest tests/test_board_core_contracts.py tests/test_board_contract.py tests/test_ledger_contract.py tests/test_harness_config.py -x
```

Expected: all pass.

- [ ] Step 7: Commit.

```bash
git add server/board/deliberation/orchestrator.py tests/test_board_skills_injection.py
git commit -m "$(cat <<'EOF'
feat(skills): record used + missing skills on BoardSession

Each member's declared skills are loaded once per orchestrator and the
result is partitioned into 'used' (successfully loaded) and 'missing'
(absent or malformed) maps on the session. Both maps survive into
session JSON via to_dict() and the 'used' map feeds the ledger
skills_used column. Members with no declared skills contribute nothing.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task T19: Final PR5 regression sweep + smoke

**Files**
- (no file changes; verification only)

**Steps**

- [ ] Step 1: Run the full PR5 test surface.

```bash
uv run pytest tests/test_board_skills_injection.py tests/test_harness_skills.py tests/test_member_skills_frontmatter.py tests/test_ledger_skills_used.py -v
```

Expected: every test in the four files passes. No skips. No warnings about deprecation related to the new code.

- [ ] Step 2: Run the broader contract suites that touch the changed files.

```bash
uv run pytest tests/test_board_core_contracts.py tests/test_board_contract.py tests/test_ledger_contract.py tests/test_harness_config.py tests/test_member_intake_frontmatter_contract.py -x
```

Expected: every test passes.

- [ ] Step 3: Manual smoke — confirm the CLI loads cleanly with the new field.

```bash
uv run python -m server.cli --list-members
```

Expected: prints the board member table including `strategist` and `researcher`; exits 0. The output need not show skills (the CLI list view is unchanged), but the loader must not raise.

- [ ] Step 4: Confirm one extra invariant — `compose_system_prompt` is in the prompts module's public surface (no `_` prefix; no `__all__` regression).

```bash
uv run python -c "from server.board.deliberation.prompts import compose_system_prompt; print(compose_system_prompt('A', ['B']))"
```

Expected output (exact):

```
A

---

B
```

- [ ] Step 5: Confirm the example skills round-trip via `list_skills`.

```bash
uv run python -c "from server.harness.skills import list_skills; print([s.name for s in list_skills()])"
```

Expected output (exact):

```
['jtbd_interview', 'pricing_research']
```

- [ ] Step 6: Commit a no-op marker (skip if no untracked debug files exist).

```bash
git status --short
```

If `git status` shows clean working tree → skip the commit, this is a verification-only step.

**PR5 done.** Push the branch and open the PR linked to PR4's. Together they deliver Phase 3 of the harness cross-cutting expansion per spec §6.

---

## Post-merge cleanup

None. Both PRs are additive; no flag-flip and no follow-up migration required.

## Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Member-level cache leaks across orchestrator instances in long-lived processes | Low | Low | Cache is instance-scoped (`self._skill_cache`), not module-global. Test T16 locks this. |
| Skill body overflows blow the LLM context window even with 8000-char cap | Low | Medium | Cap is per-skill, not aggregate. If a member declares 5 skills × 8000 chars = 40k chars, prompt context could balloon. Mitigation: spec §6.5 only ships 2 skills wired to 2 members declaring 1 each. If usage grows, add an aggregate cap as a follow-up. |
| `BoardDeliberation.__init__` doesn't accept `session=` and Task T18 has to bolt one on | Medium | Low | Task T18 step 2 explicitly checks the signature and gives a conditional fallback (attach `board._session` after construction). |
| Session JSON `skills` field schema diverges from ledger `skills_used` column | Low | Low | Both share the `used` map; T17 + T18 tests cross-check shape. |
| Existing tests assume `BoardSession.to_dict()` has a fixed key set | Medium | Low | The added `"skills"` key is purely additive; no existing test asserts an exhaustive key set (per the existing pattern of incremental fields like `auto_promoted_rebuttals`). T19 step 2 regression-tests confirm. |
