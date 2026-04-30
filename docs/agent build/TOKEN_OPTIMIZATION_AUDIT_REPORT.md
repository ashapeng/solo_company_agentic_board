# Token Optimization Audit Report

Date: 2026-04-13

Scope:

- Agentic Board prompts: `server/members/*.md`, `server/protocols/*.md`, `server/board/prompts.py`
- Board runtime controls: routing, compaction, verification, metrics, memory, LLM client
- Hermes integration: `hermes/skills/*.md`, `hermes/plugins/agentic_board/*`
- Token optimizer skill: `.claude/skills/token-optimizer/*`
- Caveman reference: https://github.com/JuliusBrussee/caveman

## Executive Finding

The current system has the right foundation: adaptive routing, parser-based inter-stage compaction, metrics, local-only API boundaries, and human-gated memory. But token optimization is still mostly prompt-level and passive. The largest waste now comes from output shape, handoff shape, tool-result shape, and runtime budget policy rather than from wording alone.

Caveman should be used as a precision compression reference, not copied stylistically. Its transferable pattern is: remove low-information language, preserve technical substance, validate preservation of structural artifacts, and measure against a terse-control baseline rather than a verbose baseline.

## Baseline Measurements

Prompt/input inventory from local word counts:

| Surface | Words |
|---|---:|
| Active board member prompts, pre-PMF | 6,318 |
| Shelved member prompts | 1,587 |
| Protocol prompts | 921 |
| Hermes skills | 1,120 |
| `CLAUDE.md` | 690 |
| New token optimizer skill + reference | 1,346 |

Active pre-PMF members load 36 operating procedures: the chair has 6; the other 6 active members have 5 each. Live-product profile would load 46 procedures with Guardian and Operator.

There are no saved `data/sessions/*.json` runs in the current workspace, so this audit cannot quantify live token savings yet. The next step should be a three-arm eval run.

## Caveman Reference Model

Useful Caveman ideas:

- `rules/caveman-activate.md` uses a terse contract: remove filler, preserve technical terms and code, use fragments only where clear, and drop compression for safety/ambiguity cases.
- `caveman-compress` treats file compression as a preservation problem: preserve headings, code blocks, URLs, file paths, and commands, then use targeted fixes if validation fails.
- Caveman evals use a three-arm design: baseline, terse control, and skill output. This prevents claiming generic concision as skill-specific gain.
- Caveman’s project notes distinguish output-token reduction from prompt/input compression and track benchmark numbers from real runs.

What not to copy:

- Do not use the caveman voice for board output.
- Do not apply ultra-terse mode to final decisions, security warnings, irreversible actions, or financial/legal risk.
- Do not claim Caveman’s benchmark savings for this repo until Agentic Board runs its own evals.

## Strengths

1. Parser-based compaction already exists.

   `server/board/compaction.py` extracts Stage 1 TL;DR, recommendation, top risk, and confidence for Stage 2. It also extracts Stage 2 updated position, peer challenges, and ranking for Stage 3. This matches the Caveman-style principle of preserving decision-bearing artifacts instead of summarizing everything with another LLM call.

2. Routing can reduce member count.

   `server/board/classifier.py` and `server/board/roster.py` select members by capability rather than always using the full board.

3. Metrics are captured.

   `server/board/metrics.py` records input tokens, output tokens, latency, and estimated cost per call. `server/cli.py --budget` surfaces totals.

4. Memory writes are gated.

   Hermes skills and the board API keep `memory.proposed_sotb_update` as a proposal. This avoids hidden write loops and unnecessary durable context pollution.

5. Tool trust boundary is mostly local.

   The FastAPI app is local-only by default, and the Hermes plugin rejects non-local base URLs.

## Weaknesses And Improvements

### 1. Stage 1 reads Stage 2-only format rules

Evidence:

- `server/protocols/output_format.md` contains base output and Stage 2 additions.
- `server/protocols/stage1_independent.md` injects `{{output_format}}`.

Impact:

- Every Stage 1 member reads irrelevant peer-review instructions.
- Stage 1 may learn that Stage 2 sections exist even though they are not valid for Stage 1.
- This is recurring input waste across every member call.

Improve:

- Split into `stage1_output_format.md` and `stage2_delta_format.md`.
- Keep only Stage 1 fields in Stage 1.
- Update `server/board/prompts.py` to load stage-specific formats.

### 2. Stage 2 generates full analysis that downstream code discards

Evidence:

- `server/protocols/stage2_peer_review.md` tells members to follow the base output format plus Stage 2 additions.
- `server/board/compaction.py` keeps mainly `Peer Challenges`, `Updated Position`, and `Ranking` from Stage 2.

Impact:

- Stage 2 output tokens are spent on sections that the chair does not need.
- Saved session JSON gets larger.
- Verification context uses compacted Stage 2, so the full Stage 2 base analysis is mostly audit-only.

Improve:

- Make Stage 2 delta-only:
  - header,
  - `Peer Challenges`,
  - `Updated Position`,
  - `Ranking`.
- Cap peer challenges at the top 3 material issues.
- Keep raw Stage 1 in session JSON for audit if needed.

### 3. Stage 3 still receives raw Stage 1 responses

Evidence:

- `stage3()` compacts Stage 2 but passes `_format_identified_responses(stage1_responses)` directly into `format_stage3()`.
- Tests verify Stage 2 receives compacted Stage 1 and Stage 3 receives compacted Stage 2, but there is no equivalent Stage 3 compacted-Stage-1 test.

Impact:

- The chair receives full Stage 1 member outputs even though many decisive fields already exist in the compacted version.
- Full-board decisions duplicate Stage 1 content in Stage 2-derived deltas.

Improve:

- Pass `compact_stage1_responses(stage1_responses)` into Stage 3 by default.
- Add an audit/high-impact mode that includes raw Stage 1 only when verification or the user requires traceability.
- Add a contract test ensuring verbose Stage 1 analysis does not reach Stage 3 default context.

### 4. Member prompts are procedure-heavy and not trigger-gated enough

Evidence:

- Each active specialist prompt contains 5 procedures; the chair has 6.
- Procedure text explains multi-step workflows even when the query only triggers one lens.
- The member template requires 3-5 procedures, reinforcing prompt growth.

Impact:

- Stable system prompts dominate recurring input tokens.
- Models may run every procedure instead of selecting the relevant checks.
- Member differentiation is good, but the implementation is closer to a procedure encyclopedia than a compact role lens.

Improve:

- Rewrite member prompts from full procedures to triggered checks:
  - core question,
  - max 2 triggered checks per response,
  - boundaries,
  - evidence standard,
  - Stage 2 lens.
- Update `tests/test_full_council_contract.py` so it does not require 3+ verbose procedures if the new contract is stronger.
- Keep detailed playbooks in optional references only if a member truly needs them.

### 5. Output budgets are too broad and not stage-aware

Evidence:

- `query_llm()` defaults to `max_tokens=4096`.
- `_query_member()` does not pass a stage-specific `max_tokens`, so Stage 1 and Stage 2 council calls inherit 4096.
- Chair synthesis and revision use 8192.

Impact:

- Prompt wording says "max bullets," but the runtime allows long outputs.
- One failed verification can trigger another 8192-token chair call.
- Metrics are recorded after the fact, but no global budget stops an expensive session early.

Improve:

- Add a `StageBudget` config, for example:
  - classifier: 250,
  - Stage 1 member: 900-1200,
  - Stage 2 member: 500-800 after delta-only format,
  - Stage 3 chair: 2500-4000 depending on query complexity,
  - verifier: 500,
  - revision: smaller targeted patch budget unless full rewrite required.
- Add session-level budget checks before optional verification and revision.
- Record input/output separately in session metrics, not just aggregate by stage.
- Treat unknown token counts as "unknown" in cost displays instead of silently treating them as zero.

### 6. Structured output guardrails are incomplete

Evidence:

- The classifier and verifier prompt for exact text/JSON, but the LLM client does not request schema-constrained output.
- `verify_synthesis()` defaults to `score=7, passed=True` on parse or verification errors.

Impact:

- A broken verifier response can pass a decision.
- JSON repair is handled with best-effort parsing, but not with a controlled retry or fail-closed result.
- This is a quality risk and can also waste tokens via revision loops that are not grounded in reliable verifier output.

Improve:

- If the active provider supports strict structured output, use it for classifier and verifier calls.
- If not, use one bounded JSON-repair retry.
- On verifier parse failure, return `passed=False` or `passed=None` with `status="indeterminate"` rather than passing.
- Keep verifier output fields short and bounded.

### 7. Focused routing conflicts with fixed minimum response thresholds

Evidence from local routing check:

- `strategic` in `pre_pmf` selects `chairperson`, `strategist`, `critic`; only 2 non-chair members run Stage 1.
- `security` in `pre_pmf` selects `chairperson`, `critic`, `architect`; only 2 non-chair members run Stage 1.
- `operational` in `pre_pmf` selects `chairperson`, `builder`; only 1 non-chair member runs Stage 1.
- `MIN_STAGE1_RESPONSES = 3`.

Impact:

- Focused routing can fail instead of saving tokens.
- Users may overuse `--full-board` to avoid failures, which negates adaptive routing.

Improve:

- Make minimum thresholds dynamic:
  - `min_stage1 = min(3, len(council))`, with a floor of 1 for intentionally narrow routes.
  - Skip or compress Stage 2 when only one non-chair member participates.
- Alternatively, have routing include enough active members to satisfy thresholds explicitly.
- Add tests for every decision type under each stage profile.

### 8. Caching is not implemented

Evidence:

- `server/board/llm.py` sends only `model`, `messages`, `temperature`, and `max_tokens`.
- There is no local response cache, prompt hash, cache key, or provider-specific caching option.

Impact:

- Stable system prompts and protocol text are resent for every member and every session.
- Repeated classification or identical board benchmark queries cannot reuse prior results.
- No cache hit/miss data exists for cost analysis.

Improve:

- Add a provider-options layer in `query_llm()` so caching knobs can be passed after verifying support for the chosen provider path.
- Add local exact-match cache only for deterministic, low-risk steps such as classification benchmarks, not for final decisions by default.
- Hash stable prompt prefixes: member prompt version, protocol version, SOTB version, stage profile.
- Track cache hit/miss metrics separately from token totals.

### 9. Hermes tool results can inject too much context

Evidence:

- `agentic_board_deliberate()` calls `/deliberate`, which returns the full session with raw Stage 1 and Stage 2 outputs.
- The API already has `/sessions/{session_id}/adapter`, which returns a compact integration contract.
- The `agentic-board` Hermes skill instructs the agent to read the saved full session JSON, then manually present selected fields.

Impact:

- Hermes can pull full deliberation transcripts into context when it only needs the decision, risks, next steps, verification, classification, and memory proposal.
- This is tool-result stuffing, not prompt wording waste.

Improve:

- Make the Hermes plugin return the adapter contract by default.
- Add a `compact` or `include_raw` option for full session retrieval.
- In the skill, prefer adapter endpoint or `jq` field selection over loading entire session JSON.
- Keep raw session files as audit artifacts, not default tool output.

### 10. Hermes verification defaults increase cost

Evidence:

- `hermes/skills/agentic-board/SKILL.md` tells Hermes to run `--verify --budget`.
- `hermes/plugins/agentic_board/schemas.py` defaults `verify=True`.

Impact:

- Every Hermes-invoked board session pays for verifier overhead by default.
- Failed verification can trigger a chair revision and second verification.

Improve:

- Default `verify=False`.
- Enable verification by policy:
  - high-impact strategic decision,
  - user asks for verification,
  - memory update likely,
  - role-gap or irreversible recommendation,
  - broad full-board decision.
- Keep `--budget` default on; it is observability, not an LLM call.

### 11. Tool approval policy is cost-blind

Evidence:

- `agentic_board_deliberate` has `requires_approval=False`.
- The same tool can trigger multiple expensive LLM calls.
- `agentic_board_propose_sotb_update` correctly has `requires_approval=True`.

Impact:

- The highest-cost tool can run without approval while a lower-cost diff-review tool requires approval.
- This is inconsistent from a token-budget perspective.

Improve:

- Keep `list_members` and `read_sotb` approval-free.
- Require approval for `agentic_board_deliberate` when:
  - `full_board=True`,
  - `verify=True`,
  - estimated participant count exceeds a threshold,
  - query is long,
  - no explicit budget has been accepted.
- Return an estimated call count before execution when possible.

### 12. SOTB memory is compact today but fragile as it grows

Evidence:

- `read_sotb()` returns the full memory file for every Stage 3.
- `apply_sotb_update()` truncates by word count and can break Markdown structure, though the review path is more careful.

Impact:

- Today SOTB is tiny, but future sessions will make it a recurring Stage 3 input cost.
- Word-based truncation can corrupt section boundaries if used.

Improve:

- Keep the human-reviewed `memory_review.py` section-aware path as the primary path.
- Add section retrieval for Stage 3: active decisions and relevant open questions first, full SOTB only for broad/high-impact decisions.
- Replace word truncation with section-aware compaction.

### 13. Metrics are not sufficient for optimization loops

Evidence:

- `SessionMetrics.summary()` reports total tokens and stage tokens, but not a serialized per-call ledger in session JSON.
- There are no current session files to analyze.

Impact:

- You cannot identify which member or stage causes excess output from saved session JSON alone.
- Caveman-style honest evals require repeatable snapshots and ratios.

Improve:

- Persist per-call metrics in session JSON:
  - member id,
  - stage,
  - model,
  - input tokens,
  - output tokens,
  - cost estimate,
  - latency.
- Add a small benchmark suite with 5-10 board queries.
- Run three arms:
  - current prompts,
  - terse-control prompts,
  - token-optimized prompts.
- Compare against terse-control, not only against current verbose prompts.

## Priority Plan

### P0: Fix Waste That Is Structurally Obvious

1. Split Stage 1 and Stage 2 output formats.
2. Make Stage 2 delta-only.
3. Pass compacted Stage 1 to Stage 3 by default.
4. Make focused routing thresholds dynamic.
5. Change verifier parse failure from pass to indeterminate/fail.

### P1: Add Runtime Budget Controls

1. Add stage-specific `max_tokens`.
2. Add session-level budget gates before verification and revision.
3. Persist per-call metrics.
4. Make Hermes plugin return adapter contracts by default.
5. Change Hermes `verify` defaults to false with policy-based escalation.

### P2: Add Caching And Evals

1. Add provider-options support for prompt/cache controls after verifying support in the active provider path.
2. Add exact-match cache for deterministic eval/classifier workflows only.
3. Build a Caveman-style three-arm eval harness for board prompts.
4. Add section-aware SOTB retrieval/compaction.
5. Refactor member prompts into trigger-gated compact checks.

## Target Architecture

Token optimization should sit at four layers:

1. **Prompt layer:** concise stage/member prompts, no duplicate instructions, trigger-gated procedures.
2. **Handoff layer:** compact Stage 1/2 context by default, raw artifacts retained outside the model context.
3. **Runtime layer:** stage-specific output caps, global budget gate, verifier fail-closed behavior, routing thresholds aligned to selected council size.
4. **Tool layer:** compact Hermes adapter returns, approval for high-cost tool calls, cache-aware provider options, metrics for evals.

Caveman’s lesson is not "make text weird." The lesson is: compression must be a contract with preservation rules and evals. Agentic Board should apply that contract to member prompts, intermediate outputs, memory, tool returns, and budget controls before changing final user-facing board prose.

## References

- Caveman repository: https://github.com/JuliusBrussee/caveman
- Caveman always-on rule: https://raw.githubusercontent.com/JuliusBrussee/caveman/main/rules/caveman-activate.md
- Caveman Compress skill: https://raw.githubusercontent.com/JuliusBrussee/caveman/main/caveman-compress/SKILL.md
- Caveman eval notes: https://raw.githubusercontent.com/JuliusBrussee/caveman/main/evals/README.md
- Caveman project notes: https://raw.githubusercontent.com/JuliusBrussee/caveman/main/CLAUDE.md
