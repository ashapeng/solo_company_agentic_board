# Plan 3 — Board Core Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove two brittleness sources in the board core — hardcoded member-id literals inside the orchestrator, and regex-only compaction of Stage 1/2 markdown. Replace with member-frontmatter-driven intake metadata and JSON-first structured output for Stage 1/2 (regex retained as fallback with warning).

**Architecture:** Additive data on each council member markdown file; loader parses it; orchestrator reads from member objects instead of embedded dict literals. Stage 1/2 prompts ask for a fenced JSON block conforming to a Pydantic schema; compaction parses JSON first, falls back to the existing regex path on failure and records a structured-output warning onto the session.

**Tech Stack:** Python 3.12, Pydantic v2, PyYAML, unittest.

**Spec:** `docs/superpowers/specs/2026-04-20-plan-3-board-core-contracts-design.md`

---

## Cross-cutting execution policy

1. Phase 0 before code.
2. Root-cause only.
3. 3-attempt cap → `git reset --hard` to last green commit.
4. YAGNI. Pydantic already a dependency.
5. Done criteria: all new tests green; full suite green; manual deliberation with a fake provider produces either structured JSON (preferred) or a warning-tagged markdown fallback — never a silent empty compaction.

## Sub-agent usage

- **Explore agent** (thoroughness: `very thorough`) before Task 3 — map every `server/members/*.md`, every caller of `_build_intake_card`, `_should_pause_for_clarification`, `compact_stage1_responses`, `compact_stage2_responses`. Also list every test fixture that constructs a fake `MemberResponse.content`.
- **superpowers:code-reviewer** after Task 7 — verify JSON extraction handles common model oddities (multiple fences, no language tag, leading prose).

## File structure map

| File | Action | Responsibility |
|---|---|---|
| `server/board/config.py` | **Modify** | Add `MemberIntake` dataclass; extend `BoardMember` |
| `server/board/loader.py` | **Modify** | Parse `intake:` frontmatter; raise on council member with missing block |
| `server/members/strategist.md`, `product.md`, `researcher.md`, `critic.md`, `architect.md`, `builder.md` | **Modify** | Add `intake:` frontmatter block |
| `server/board/roster/roster.yaml` | **Modify** | New `clarification_gate` block |
| `server/board/roster/registry.py` | **Modify** | Expose gate config reader |
| `server/board/deliberation/orchestrator.py` | **Modify** | `_build_intake_card` reads from member; `_should_pause_for_clarification` reads from roster |
| `server/board/deliberation/structured.py` | **Create** | Pydantic schemas `Stage1Response`, `Stage2Response`, `Risk` |
| `server/board/deliberation/compaction.py` | **Modify** | JSON-first parse; regex fallback; emit warning |
| `server/board/deliberation/prompts.py` | **Modify** | Stage 1/2 prompts request fenced JSON |
| `tests/test_member_intake_frontmatter_contract.py` | **Create** | Member-frontmatter contract |
| `tests/test_board_core_contracts.py` | **Create** | Phase 0 + post-fix assertions |
| `tests/test_context_compaction_contract.py` | **Modify** | Add JSON-preferred and drift-fallback cases |

---

## Task 1: Phase 0 repro tests

**Files:**
- Create: `tests/test_board_core_contracts.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_board_core_contracts.py
"""Phase 0 repro: board core contracts (member IDs hardcoded; drift breaks compaction)."""

from __future__ import annotations

import pathlib
import re
import unittest


class OrchestratorHardcodedIdsTest(unittest.TestCase):
    def test_no_literal_council_member_ids(self):
        text = pathlib.Path("server/board/deliberation/orchestrator.py").read_text()
        for mid in ("strategist", "product", "researcher",
                    "critic", "architect", "builder"):
            pattern = rf"""["']{mid}["']"""
            self.assertIsNone(
                re.search(pattern, text),
                f"orchestrator still hardcodes member id literal: {mid!r}",
            )


class DriftedMarkdownCompactionTest(unittest.TestCase):
    def test_drifted_stage1_header_still_compacts(self):
        from server.board.deliberation.compaction import _compact_single_stage1
        drifted = "**TL;DR:** alpha wins\n\n**Recommendation:** ship it\n"
        out = _compact_single_stage1(drifted)
        self.assertIn("alpha", out)
        self.assertIn("ship", out)


class Stage1JsonPreferredTest(unittest.TestCase):
    def test_json_block_is_parsed_first(self):
        from server.board.deliberation.compaction import _compact_single_stage1
        payload = (
            "Some preamble.\n\n"
            "```json\n"
            '{"confidence":"High","tldr":"alpha","analysis":"a","recommendation":"beta",'
            '"risks":[{"severity":"High","description":"r1"}],"open_questions":[]}\n'
            "```\n"
            "Some trailer."
        )
        out = _compact_single_stage1(payload)
        self.assertIn("alpha", out)
        self.assertIn("beta", out)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run; confirm FAILs**

Run: `uv run python -m unittest tests.test_board_core_contracts -v`

Expected: three FAILs.

- [ ] **Step 3: Commit**

```bash
git add tests/test_board_core_contracts.py
git commit -m "test: phase 0 repro for board core contracts (hardcoded ids; compaction drift)"
```

---

## Task 2: Extend `BoardMember` with `intake`

**Files:**
- Modify: `server/board/config.py`

- [ ] **Step 1: Add `MemberIntake` dataclass**

In `server/board/config.py`, above the `BoardMember` dataclass:

```python
@dataclass
class MemberIntake:
    clarifying_question: str
    immediate_concern: str
    proposed_path: str
    required_execution_unit: str
```

- [ ] **Step 2: Extend `BoardMember`**

Add field:

```python
intake: MemberIntake | None = None
```

- [ ] **Step 3: Run existing test suite**

Run: `uv run python -m unittest discover -s tests -v`

Expected: no regressions (intake is optional so default-construction is safe).

- [ ] **Step 4: Commit**

```bash
git add server/board/config.py
git commit -m "feat(board): add MemberIntake dataclass and optional intake field on BoardMember"
```

---

## Task 3: Loader parses intake frontmatter

**Files:**
- Modify: `server/board/loader.py`

- [ ] **Step 1: Open `loader.py`; find the block that maps frontmatter fields into `BoardMember`**

- [ ] **Step 2: Add a helper and wire it in**

After other field extractions, add:

```python
def _parse_member_intake(raw: object) -> "MemberIntake | None":
    from .config import MemberIntake
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError(f"member intake must be a mapping, got {type(raw).__name__}")
    required = ("clarifying_question", "immediate_concern",
                "proposed_path", "required_execution_unit")
    missing = [k for k in required if not str(raw.get(k, "")).strip()]
    if missing:
        raise ValueError(f"intake missing fields: {missing}")
    return MemberIntake(
        clarifying_question=str(raw["clarifying_question"]).strip(),
        immediate_concern=str(raw["immediate_concern"]).strip(),
        proposed_path=str(raw["proposed_path"]).strip(),
        required_execution_unit=str(raw["required_execution_unit"]).strip(),
    )
```

In the member-construction call, add `intake=_parse_member_intake(frontmatter.get("intake"))`.

- [ ] **Step 3: Loader contract — require `intake` on council members**

After constructing the `BoardMember`, if `member.id != "chairperson"` AND the
member is not shelved AND `member.intake is None`, raise a clear error:

```python
if member.id != "chairperson" and member.intake is None and member.id not in shelved_ids:
    raise ValueError(
        f"Council member '{member.id}' is missing required 'intake:' frontmatter block."
    )
```

Adapt variable names to the existing loader; the guard is the important part.

- [ ] **Step 4: Add member intake contract test**

```python
# tests/test_member_intake_frontmatter_contract.py
from __future__ import annotations

import unittest


class MemberIntakeContract(unittest.TestCase):
    def test_all_council_members_have_intake(self):
        from server.board.config import get_board_members
        members = [m for m in get_board_members() if m.id != "chairperson"]
        self.assertGreaterEqual(len(members), 6)
        for m in members:
            self.assertIsNotNone(
                m.intake,
                f"member {m.id!r} is missing intake frontmatter",
            )
            for attr in ("clarifying_question", "immediate_concern",
                         "proposed_path", "required_execution_unit"):
                value = getattr(m.intake, attr)
                self.assertTrue(value, f"member {m.id!r} has empty intake.{attr}")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 5: Run. Will FAIL until Task 4 lands**

Run: `uv run python -m unittest tests.test_member_intake_frontmatter_contract -v`

Expected: FAIL with ValueError from loader.

- [ ] **Step 6: Commit loader + test**

```bash
git add server/board/loader.py tests/test_member_intake_frontmatter_contract.py
git commit -m "feat(board): parse intake frontmatter; enforce on council members"
```

---

## Task 4: Add `intake:` frontmatter to each council member

**Files:**
- Modify: `server/members/strategist.md`, `product.md`, `researcher.md`, `critic.md`, `architect.md`, `builder.md`

Values are copied verbatim from the existing `_build_intake_card` defaults
in `server/board/deliberation/orchestrator.py` to preserve behavior.

- [ ] **Step 1: Add to `server/members/strategist.md` frontmatter**

```yaml
intake:
  clarifying_question: "Which seller segment and market wedge should this target first?"
  immediate_concern: "Market and competitive assumptions are not yet grounded."
  proposed_path: "Define the wedge and evidence threshold before spend."
  required_execution_unit: "strategy"
```

- [ ] **Step 2: Add to `server/members/product.md` frontmatter**

```yaml
intake:
  clarifying_question: "Who is the exact buyer and what painful job are they hiring this for?"
  immediate_concern: "The request describes a solution before validating the problem."
  proposed_path: "Run problem validation before feature scoping."
  required_execution_unit: "product"
```

- [ ] **Step 3: Add to `server/members/researcher.md` frontmatter**

```yaml
intake:
  clarifying_question: "Which customers have already shown this pain through behavior or spend?"
  immediate_concern: "No customer evidence has been supplied."
  proposed_path: "Collect customer discovery evidence before the final decision."
  required_execution_unit: "research"
```

- [ ] **Step 4: Add to `server/members/critic.md` frontmatter**

```yaml
intake:
  clarifying_question: "What would make this decision obviously wrong within 30 days?"
  immediate_concern: "The failure criteria and disconfirming evidence are undefined."
  proposed_path: "Set explicit kill criteria and dissent checks."
  required_execution_unit: "legal"
```

- [ ] **Step 5: Add to `server/members/architect.md` frontmatter**

```yaml
intake:
  clarifying_question: "What input images, output quality bar, and integration surface are required?"
  immediate_concern: "Technical feasibility depends on unstated product constraints."
  proposed_path: "Run a feasibility memo after customer constraints are known."
  required_execution_unit: "engineering"
```

- [ ] **Step 6: Add to `server/members/builder.md` frontmatter**

```yaml
intake:
  clarifying_question: "What is the smallest manual or prototype test that proves demand?"
  immediate_concern: "Execution could expand before the validation path is clear."
  proposed_path: "Sequence a small validation slice before implementation."
  required_execution_unit: "engineering"
```

- [ ] **Step 7: Run contract test**

Run: `uv run python -m unittest tests.test_member_intake_frontmatter_contract -v`

Expected: PASS.

- [ ] **Step 8: Run full suite**

Run: `uv run python -m unittest discover -s tests -v`

Expected: all green.

- [ ] **Step 9: Commit**

```bash
git add server/members/
git commit -m "feat(members): add intake frontmatter block to all council members"
```

---

## Task 5: Move clarification gate config to roster

**Files:**
- Modify: `server/board/roster/roster.yaml`
- Modify: `server/board/roster/registry.py`

- [ ] **Step 1: Add gate block to `roster.yaml`**

Append:

```yaml
clarification_gate:
  ambiguous_terms: ["business", "product", "ai", "search", "e-commerce", "ecommerce"]
  min_terms_present: 2
  max_query_words: 14
  gating_capabilities:
    - product_strategy
    - user_research
    - market_strategy
    - technical_feasibility
```

(Capability names must match values already used in member frontmatter
`capabilities:` fields; confirm with a quick grep before writing.)

- [ ] **Step 2: Expose a reader in registry**

In `server/board/roster/registry.py`, add:

```python
def get_clarification_gate(roster: dict | None = None) -> dict:
    roster = roster or load_roster()
    gate = roster.get("clarification_gate") or {}
    return {
        "ambiguous_terms": list(gate.get("ambiguous_terms") or []),
        "min_terms_present": int(gate.get("min_terms_present", 2)),
        "max_query_words": int(gate.get("max_query_words", 14)),
        "gating_capabilities": list(gate.get("gating_capabilities") or []),
    }
```

Export it from `server/board/roster/__init__.py`.

- [ ] **Step 3: Commit**

```bash
git add server/board/roster/
git commit -m "feat(roster): move clarification gate config into roster.yaml"
```

---

## Task 6: Refactor orchestrator to read from member + roster

**Files:**
- Modify: `server/board/deliberation/orchestrator.py`

- [ ] **Step 1: Replace `_build_intake_card`**

```python
def _build_intake_card(member: BoardMember, user_query: str, *, blocking: bool) -> dict:
    intake = member.intake
    if intake is None:
        # Non-council (e.g., chairperson) path: safe fallback.
        return {
            "member_id": member.id,
            "member_title": member.title,
            "clarifying_question": "What missing fact would change this board member's recommendation?",
            "immediate_concern": "The prompt lacks enough context for a fully accountable decision.",
            "proposed_path": "Name the assumption and verify it before execution.",
            "required_execution_unit": "strategy",
            "confidence": "medium",
            "blocking": blocking,
        }
    return {
        "member_id": member.id,
        "member_title": member.title,
        "clarifying_question": intake.clarifying_question,
        "immediate_concern": intake.immediate_concern,
        "proposed_path": intake.proposed_path,
        "required_execution_unit": intake.required_execution_unit,
        "confidence": "medium",
        "blocking": blocking,
    }
```

- [ ] **Step 2: Replace `_should_pause_for_clarification`**

```python
def _should_pause_for_clarification(user_query: str, council: list[BoardMember]) -> bool:
    from server.board.roster import get_clarification_gate
    gate = get_clarification_gate()

    words = [w for w in user_query.replace("-", " ").split() if w.strip()]
    if len(words) > gate["max_query_words"]:
        return False

    gating = set(gate["gating_capabilities"])
    if gating:
        from server.board.roster import load_roster
        roster_members = load_roster().get("members", {})
        has_gating_member = any(
            any(cap in gating for cap in roster_members.get(m.id, {}).get("capabilities", []))
            for m in council
        )
        if not has_gating_member:
            return False

    ambiguous = set(gate["ambiguous_terms"])
    lower = user_query.lower()
    hits = sum(1 for term in ambiguous if term in lower)
    return hits >= gate["min_terms_present"]
```

- [ ] **Step 3: Run hardcoded-ids repro; confirm PASS**

Run: `uv run python -m unittest tests.test_board_core_contracts.OrchestratorHardcodedIdsTest -v`

Expected: PASS.

- [ ] **Step 4: Run full suite; fix any fallout**

Run: `uv run python -m unittest discover -s tests -v`

If a fake member used in tests has empty `capabilities` list, the gate
returns False — existing clarification tests may need seeded capabilities
or adjusted expectations. Root-cause: do not re-introduce id literals.

- [ ] **Step 5: Commit**

```bash
git add server/board/deliberation/orchestrator.py
git commit -m "refactor(board): drive intake/clarification from member + roster config"
```

---

## Task 7: Structured Stage 1/2 Pydantic schemas

**Files:**
- Create: `server/board/deliberation/structured.py`

- [ ] **Step 1: Write schemas**

```python
# server/board/deliberation/structured.py
"""Pydantic schemas for Stage 1 / Stage 2 structured output."""

from __future__ import annotations

import json
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError


class Risk(BaseModel):
    severity: Literal["Critical", "High", "Medium", "Low"]
    description: str


class Stage1Response(BaseModel):
    confidence: Literal["High", "Medium", "Low"]
    tldr: str
    analysis: str
    recommendation: str
    risks: list[Risk] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


class Stage2Response(BaseModel):
    confidence: Literal["High", "Medium", "Low"]
    updated_position: str
    peer_challenges: list[str] = Field(default_factory=list)
    ranking: list[str] = Field(default_factory=list)


_FENCE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def parse_stage1(content: str) -> Stage1Response | None:
    return _parse(content, Stage1Response)


def parse_stage2(content: str) -> Stage2Response | None:
    return _parse(content, Stage2Response)


def _parse(content: str, model: type[BaseModel]):
    block = _extract_json_block(content)
    if not block:
        return None
    try:
        return model.model_validate_json(block)
    except (ValidationError, ValueError):
        return None


def _extract_json_block(content: str) -> str | None:
    """Return the first JSON object found inside ```json ... ``` or bare {...}."""
    match = _FENCE.search(content)
    if match:
        return match.group(1)
    # Fallback: the first top-level { ... } JSON object.
    start = content.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(content)):
        if content[i] == "{":
            depth += 1
        elif content[i] == "}":
            depth -= 1
            if depth == 0:
                candidate = content[start:i + 1]
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    return None
    return None
```

- [ ] **Step 2: Unit-test schema parsing**

Append to `tests/test_board_core_contracts.py`:

```python
class StructuredParseTest(unittest.TestCase):
    def test_parse_stage1_from_fenced_json(self):
        from server.board.deliberation.structured import parse_stage1
        payload = '```json\n{"confidence":"High","tldr":"t","analysis":"a","recommendation":"r","risks":[],"open_questions":[]}\n```'
        out = parse_stage1(payload)
        self.assertIsNotNone(out)
        self.assertEqual(out.confidence, "High")
        self.assertEqual(out.tldr, "t")

    def test_parse_stage1_fails_gracefully_on_invalid(self):
        from server.board.deliberation.structured import parse_stage1
        self.assertIsNone(parse_stage1("no json here"))
```

- [ ] **Step 3: Run; confirm green**

Run: `uv run python -m unittest tests.test_board_core_contracts.StructuredParseTest -v`

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add server/board/deliberation/structured.py tests/test_board_core_contracts.py
git commit -m "feat(board): add Stage1/Stage2 pydantic schemas and JSON extractor"
```

---

## Task 8: JSON-first compaction with regex fallback

**Files:**
- Modify: `server/board/deliberation/compaction.py`

- [ ] **Step 1: Add JSON paths in Stage 1 compaction**

At the top of `compaction.py`, add:

```python
from .structured import parse_stage1, parse_stage2

_STAGE1_JSON_WARNING = "stage1_json_parse_failed"
_STAGE2_JSON_WARNING = "stage2_json_parse_failed"
```

Rewrite `_compact_single_stage1` to try JSON first:

```python
def _compact_single_stage1(
    content: str,
    *,
    sections: list[str] | None = None,
    detail_sections: list[str] | None = None,
) -> str:
    parsed = parse_stage1(content)
    if parsed is not None:
        return _render_stage1_from_json(parsed, sections or ["confidence", "tldr", "recommendation", "top_risk"])
    return _compact_single_stage1_markdown(
        content, sections=sections, detail_sections=detail_sections,
    )


def _render_stage1_from_json(parsed, sections: list[str]) -> str:
    parts = []
    if "confidence" in sections:
        parts.append(f"> Confidence: {parsed.confidence}")
    if "tldr" in sections and parsed.tldr:
        parts.append(f"## TL;DR\n{parsed.tldr}")
    if "analysis" in sections and parsed.analysis:
        parts.append(f"## Analysis\n{parsed.analysis}")
    if "recommendation" in sections and parsed.recommendation:
        parts.append(f"## Recommendation\n{parsed.recommendation}")
    if "top_risk" in sections and parsed.risks:
        severity_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
        top = min(parsed.risks, key=lambda r: severity_order.get(r.severity, 99))
        parts.append(f"## Top Risk\n- **{top.severity}** {top.description}")
    if "open_questions" in sections and parsed.open_questions:
        parts.append("## Open Questions\n" + "\n".join(f"- {q}" for q in parsed.open_questions))
    return "\n\n".join(parts)
```

Rename the old regex-based implementation to `_compact_single_stage1_markdown`:

```python
def _compact_single_stage1_markdown(
    content: str,
    *,
    sections: list[str] | None = None,
    detail_sections: list[str] | None = None,
) -> str:
    # ...existing body of original _compact_single_stage1 verbatim...
```

Add a markdown-drift rescue path. Inside `_compact_single_stage1_markdown`,
after the existing logic, if the compact output is empty but the raw
content is non-trivial, extract bold headers as a last resort:

```python
    if not any(parts):
        bold_tldr = re.search(r"\*\*TL;DR:?\*\*\s*(.+)", content, re.IGNORECASE)
        bold_rec = re.search(r"\*\*Recommendation:?\*\*\s*(.+)", content, re.IGNORECASE)
        if bold_tldr:
            parts.append(f"## TL;DR\n{bold_tldr.group(1).strip()}")
        if bold_rec:
            parts.append(f"## Recommendation\n{bold_rec.group(1).strip()}")

    return "\n\n".join(p for p in parts if p)
```

(Note: if `parts` was constructed as `list[str]`, the rescue keeps the same
variable; keep the existing top-of-function `parts: list[str] = []`.)

- [ ] **Step 2: Same for Stage 2**

Replace `_compact_single_stage2`:

```python
def _compact_single_stage2(content: str) -> str:
    parsed = parse_stage2(content)
    if parsed is not None:
        return _render_stage2_from_json(parsed)
    return _compact_single_stage2_markdown(content)


def _render_stage2_from_json(parsed) -> str:
    parts = [f"> Confidence: {parsed.confidence}"]
    if parsed.updated_position:
        parts.append(f"### Updated Position\n{parsed.updated_position}")
    if parsed.peer_challenges:
        parts.append("### Peer Challenges\n" + "\n".join(f"- {c}" for c in parsed.peer_challenges))
    if parsed.ranking:
        parts.append("### Ranking\n" + "\n".join(f"- {r}" for r in parsed.ranking))
    return "\n\n".join(parts)


def _compact_single_stage2_markdown(content: str) -> str:
    # ...existing body of original _compact_single_stage2 verbatim...
```

- [ ] **Step 3: Plumb warnings from compaction caller**

Warnings live on the session already (`BoardSession.structured_output_warnings`).
Compaction is pure; it cannot write to the session directly. Instead, the
orchestrator already checks parse_warnings downstream. Add a public helper:

```python
def compact_stage1_with_warnings(
    responses, *, query_type=None, config=None,
):
    from .orchestrator import MemberResponse
    from .compaction import compact_stage1_responses
    warnings: list[str] = []
    compacted = []
    sections, detail_sections = resolve_stage1_compaction_policy(
        query_type=query_type, config=config,
    )
    for resp in responses:
        parsed = parse_stage1(resp.content)
        if parsed is None:
            warnings.append(f"{_STAGE1_JSON_WARNING}:{resp.member_id}")
        compacted.append(
            MemberResponse(
                member_id=resp.member_id,
                stage=resp.stage,
                content=_compact_single_stage1(
                    resp.content,
                    sections=sections,
                    detail_sections=detail_sections,
                ),
                model=resp.model,
                elapsed_seconds=resp.elapsed_seconds,
            )
        )
    return compacted, warnings
```

And analogous `compact_stage2_with_warnings`.

- [ ] **Step 4: Wire into orchestrator**

In `orchestrator.py`, replace the call to `compact_stage1_responses` with
`compact_stage1_with_warnings` and append returned warnings into
`session.structured_output_warnings`. Same for Stage 2 compaction used by
verification prep.

- [ ] **Step 5: Run compaction tests**

Run: `uv run python -m unittest tests.test_board_core_contracts.DriftedMarkdownCompactionTest tests.test_board_core_contracts.Stage1JsonPreferredTest tests.test_context_compaction_contract -v`

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add server/board/deliberation/compaction.py server/board/deliberation/orchestrator.py
git commit -m "feat(board): JSON-first stage1/stage2 compaction with markdown fallback"
```

---

## Task 9: Stage 1/2 prompts request structured output

**Files:**
- Modify: `server/board/deliberation/prompts.py`

- [ ] **Step 1: Find `format_stage1` and append instruction**

After the existing content, append a strict-schema suffix:

```python
STAGE1_JSON_SUFFIX = """

---
Return your response as a single fenced JSON object matching this schema,
followed by any prose you want to include:

```json
{
  "confidence": "High | Medium | Low",
  "tldr": "...",
  "analysis": "...",
  "recommendation": "...",
  "risks": [{"severity": "Critical|High|Medium|Low", "description": "..."}],
  "open_questions": ["..."]
}
```

If you cannot produce JSON, respond in the previous markdown format and
keep ## headers exact.
"""
```

In `format_stage1`, return `base_prompt + STAGE1_JSON_SUFFIX`.

- [ ] **Step 2: Same for `format_stage2`**

```python
STAGE2_JSON_SUFFIX = """

---
Return a single fenced JSON object:

```json
{
  "confidence": "High | Medium | Low",
  "updated_position": "...",
  "peer_challenges": ["..."],
  "ranking": ["..."]
}
```

Markdown fallback uses the same ### section names as before.
"""
```

- [ ] **Step 3: Run protocol contract**

Run: `uv run python -m unittest tests.test_protocol_contract -v`

Expected: PASS. If it asserts the exact prompt body, update the assertion to
tolerate the new suffix (do not drop the suffix).

- [ ] **Step 4: Commit**

```bash
git add server/board/deliberation/prompts.py tests/
git commit -m "feat(board): prompt stage1/stage2 members for fenced JSON responses"
```

---

## Task 10: Integration + review

- [ ] **Step 1: Run full suite**

Run: `uv run python -m unittest discover -s tests -v`

Expected: fully green.

- [ ] **Step 2: Manual smoke**

```bash
uv run python -m server.cli --members strategist --full-board "Should we add a new pricing tier?"
```

Inspect `data/sessions/<id>.json`:
- `structured_output_warnings` should be empty if the model returned JSON,
  or populated with `stage1_json_parse_failed:<member_id>` entries.
- `decision` section non-empty.

- [ ] **Step 3: code-reviewer audit**

Dispatch `superpowers:code-reviewer` on Tasks 7–9 focusing on JSON
extraction edge cases (fence without language tag, multiple fences,
prose-interleaved JSON, trailing commas).

- [ ] **Step 4: Address findings; final commit if needed**

---

## Definition of done

- All tasks committed.
- Full unittest suite green.
- Manual smoke confirms either structured JSON compaction or a tagged warning on fallback.
- code-reviewer audit clean.
- No literal council-member-id strings remain in `orchestrator.py`.
