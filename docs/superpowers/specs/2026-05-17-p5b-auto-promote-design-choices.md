# P5b — Auto-Promote-to-Live: Design Choices Supplement

**Status:** pinned 2026-05-17.
**Scope:** This is a *supplement* to spec §9.2 in
`docs/superpowers/specs/2026-05-15-board-hardening-design.md` (lines 909–1093).
The architecture is already specified there. This document pins the five
implementer-facing choices §9.2 leaves open, with rationale, so the P5b
implementation plan has unambiguous inputs.

It does **not** re-specify the sub-pipeline shape, the chair-as-moderator
prompt, the summarizer prompt, the tool restriction, or the tier behaviour
— see §9.2.1 through §9.2.7 for those.

---

## What §9.2 already pins (do not re-decide)

- Sub-pipeline shape: disagreement-score gate → top-2 picker → ≤2 round
  rebuttal → summarizer → REBUTTAL OUTCOME injected into Stage 3.
- Tool restriction during rebuttal: `validate_claim` only, max 1 call per
  member per round.
- HEAVY-only tier gating (proxied via `verify=True`).
- Fallback when contradictions list is empty but score still exceeds
  threshold: pick the two members with the most `[Challenge]` deltas; topic
  becomes the highest-severity challenge text (§9.2.7 dependency note).
- Chair-as-moderator prompt (§9.2.3), summarizer prompt (§9.2.5),
  REBUTTAL OUTCOME block format (§9.2.6).

## What this supplement pins

| # | Choice | Decision | Config key |
|---|---|---|---|
| 1 | Disagreement-score threshold | **4** (spec default) | `hardening.disagreement_threshold` |
| 2 | Summarizer model | **Fall back to `atomizer_model`** | `hardening.auto_promote_summarizer_model` (None → atomizer) |
| 3 | Hard cap on auto-promoted pairs per session | **2** | `hardening.auto_promote_max_pairs` |
| 4 | Persistence shape on `BoardSession` | **Summary + raw transcript** (mirrors `tool_call_results`) | n/a — field shape, not config |
| 5 | Launch gate | **Dark-launch (default-off)** | `hardening.auto_promote_enabled: False` |

---

## 1. Disagreement-score threshold = 4

**Decision:** Ship with the spec default. Expose
`hardening.disagreement_threshold: 4` in `HarnessConfig.hardening`.

**Rationale.** The threshold is the main cost dial: lower → more pairs fire
→ more tokens. We have no calibration data on the actual distribution of
pair scores in live runs yet, so the spec default is the only honest
starting point. Once dark-launch produces signal, the tuner can move it.

**Plan implication.** A single read in the orchestrator just before the
gate (`score = compute_disagreement(stage2_responses)`), compared against
`get_config().hardening["disagreement_threshold"]`.

## 2. Summarizer model — fall back to `atomizer_model`

**Decision.** Expose `hardening.auto_promote_summarizer_model: None`.
`None` falls back to `hardening.atomizer_model`
(currently `qwen/qwen3.6-plus-2026-04-02`).

**Rationale.** Three existing slots already follow this pattern —
`contradiction_judge_model`, `sotb_judge_model`, and the atomizer itself.
The summarizer is a structured-output-from-transcript job, which is exactly
what qwen-plus has been doing reliably for atomization, contradiction
judging, and SOTB conflict judging. Reusing the slot keeps the surface
area small and lets us swap one model and have it apply everywhere if
needed.

**Plan implication.** A helper like the one already used elsewhere:
```python
model = cfg.hardening.get("auto_promote_summarizer_model") \
        or cfg.hardening["atomizer_model"]
```

## 3. Hard cap on auto-promoted pairs per session = 2

**Decision.** Expose `hardening.auto_promote_max_pairs: 2`.

**Rationale.** Spec §10 Risk R3 explicitly flags cost runaway as the
primary failure mode. The cap is the safety net behind the threshold. Two
pairs × roughly 4 LLM calls per pair (2 members × ~1.5 turns + 1
summarizer) ≈ 8 added calls per HEAVY session — bounded, observable, and
matches the restraint elsewhere in `hardening`
(`max_revision_attempts: 1`, `max_forced_revisions_per_member: 2`).

**Plan implication.** After ranking pairs by disagreement score (or the
fallback `[Challenge]`-count picker), slice to `[:max_pairs]` before
firing. The cap is a separate concept from the threshold — both apply.

## 4. Persistence shape — summary + raw transcript

**Decision.** New `BoardSession.auto_promoted_rebuttals: list[dict]`. Each
entry:

```python
{
    "pair_member_ids": [str, str],          # the two debaters
    "disagreement_score": int,              # observed score for this pair
    "topic": str,                           # contested-claim text
    "transcript": [                         # raw rebuttal turns
        {"role": "chair" | "member_a" | "member_b",
         "member_id": str | None,           # None for chair
         "content": str,
         "tool_calls": [ ... ]              # mirror tool_call_results shape
        },
        ...
    ],
    "summary": str,                         # full REBUTTAL OUTCOME block
    "resolution": "RESOLVED" | "PARTIAL" | "UNRESOLVED" | None,
    "summarizer_model": str,
    "tokens_in": int,
    "tokens_out": int,
    "cost_usd": float,
    "started_at": str,                      # ISO timestamp
    "elapsed_seconds": float,
}
```

**Rationale.** The chair sees only `summary` during Stage 3 (that's how the
rebuttal influences synthesis). But this codebase already keeps both
structured fields *and* full raw text for `tool_call_results`; the same
debug ergonomics matter more for live rebuttals because (a) they're the
most expensive thing in the pipeline and (b) when one goes off the rails
("why did the chair concede?"), the raw turns are the only way to tell
what happened. Eval signals can lean on
`len(getattr(session, "auto_promoted_rebuttals", []))` and the parsed
`resolution` field.

**Plan implication.**
- Add `auto_promoted_rebuttals: list[dict] = field(default_factory=list)`
  to `BoardSession`.
- Touch `to_dict()`/`from_dict()` for round-trip.
- Add corresponding eval signal:
  `auto_promoted_rebuttals_count = len(...)` plus an
  `auto_promoted_resolutions: list[str]` for distribution tracking.
- All consumers must use `hasattr(session, "auto_promoted_rebuttals")` or
  `getattr(..., [])` guards, matching the established back-compat pattern
  for new session fields.

## 5. Launch gate — dark-launch (default-off)

**Decision.** Expose `hardening.auto_promote_enabled: False` in
`HarnessConfig.hardening`. When `False`, the sub-pipeline is skipped
entirely regardless of disagreement score; when `True`, the normal HEAVY
gating from §9.2.7 applies.

**Rationale.** This mirrors P4 SOTB exactly: ship the cheap orchestration
(disagreement scoring, pair picking, persistence scaffolding) so live runs
can compute the score and we get telemetry on "would this have fired?",
but keep the expensive live-rebuttal loop dark until calibration data
exists. Spec §10 Risk R3 is the same concern that drove
`sotb_judge_enabled: False` in P4; the same answer applies.

**Plan implication.**
- Gate the entire sub-pipeline call site on
  `cfg.hardening.get("auto_promote_enabled", False)`.
- When dark, still compute the disagreement score and persist it on the
  session (e.g., `session.disagreement_score: int`) so we collect the
  "would-have-fired" telemetry for tuning the threshold later.
- Tests exercise both the dark path (score computed, no LLM calls) and
  the live path (flag flipped, fires under HEAVY).

---

## Eval signal additions (out of scope for the implementation plan, but
## flagged here so the plan stays honest)

P5b ships behind a default-off flag, so live eval needles will not move
until the flag is flipped and a separate manual baseline is run. The plan
should add the *signals* (`auto_promoted_rebuttals_count`,
`auto_promoted_resolutions`, `disagreement_score`) but should not promise
movement on `clean_baseline` or any existing eval category as part of the
P5b PR. That promise belongs to a separate "P5b live calibration" step
the user kicks off manually.

## Out of scope for P5b (do not implement in this plan)

- Auto-supersession of SOTB entries (P4.1).
- Tier promotion of STANDARD → HEAVY based on disagreement score.
- Per-query-type override of `auto_promote_enabled` (Option C from the
  brainstorm — declined; can be added later if calibration shows
  category-specific value).
- Rebuttal-driven Stage 2 revision of the non-debating members'
  responses. The REBUTTAL OUTCOME is read by the chair only, per §9.2.6.
