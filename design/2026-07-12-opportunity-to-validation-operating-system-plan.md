# Opportunity-to-Validation Operating System Implementation Plan

**Purpose:** Self-contained handoff for a fresh coding-agent session.

**Date:** 2026-07-12

**Status:** Ready for implementation planning/execution. No implementation from
this plan has been started yet.

**Goal:** Turn Agentic Board into a weekly, mostly autonomous operating system
that discovers evidence-backed venture opportunities, lets the board evaluate
and prioritize the portfolio, launches the smallest credible market-validation
experiments for the best candidates, measures real interest, and returns the
results to the board for another decision.

## Product decisions established with the founder

These are requirements, not open design questions:

1. The **Agentic Board is the core product**. The discovery coding agent is an
   upstream evidence producer, not the final decision-maker.
2. A coding-agent CLI such as Codex, Claude Code, or Cursor runs approved
   web/social discovery and produces **5-10 candidates every week**.
3. Every candidate includes a summary, source evidence, and resource links and
   is recorded durably before board evaluation.
4. The board evaluates the candidates **as a portfolio**, records a label and
   rationale for every candidate, and prioritizes the best opportunities.
5. The board may reject a candidate for prioritization, but rejection never
   deletes it. Only the founder decides whether to dispose/archive it, and even
   disposed records remain auditable.
6. The system automatically launches validation initiatives for the **top 3 by
   default**, with a configurable hard maximum of **5 concurrent experiments**.
7. Execution must optimize for the **cheapest and fastest credible validation**.
   A landing page, fake-door test, waitlist, interview request, or concierge
   workflow is preferred over building a product.
8. The first automatic execution primitive is a published landing page with:
   waitlist signup, problem-description collection, and early-access requests.
9. Experiments run for 7 days. If exposure is insufficient, they may extend to
   14 days and must be labeled `inconclusive`, not falsely rejected.
10. Distribution is hybrid: the system creates platform-specific posting
    material, may auto-post through explicitly configured adapters, and always
    provides a manual posting playbook. Initial platforms of interest include
    Instagram, TikTok, Facebook, Reddit, Rednote, and LinkedIn.
11. No paid ads are in scope. Landing pages and supporting services should use
    free plans during validation.
12. The founder should spend only **15-30 minutes per week** reviewing rankings,
    experiment results, retained rejections, and exceptions.

## Non-negotiable product principle

> Validate assumptions before building products.

No board decision may create a full product build merely because an idea sounds
promising. Every prioritized candidate must identify its riskiest assumption,
the smallest experiment capable of falsifying it, a timebox, success signals,
stop conditions, and an exposure threshold. Larger builds require recorded
validation evidence from an earlier experiment.

## Current starting state

The repository is a local-first modular monolith with mature board,
initiatives, execution, evidence, harness, and React UI domains. It also has a
large **uncommitted discovery implementation** in the working tree. A fresh
session must preserve and build on it; do not reset, checkout, or discard it.

Relevant existing implementation:

| Existing capability | Current path | Assessment |
|---|---|---|
| Approved-source collection and policy | `server/discovery/channels/`, `policy.py`, `http_safety.py` | Reuse |
| Bounded coding-agent input and import | `server/discovery/analyze/` | Reuse |
| Codex/manual producer ports and run records | `server/discovery/producers/` | Reuse and generalize provider naming |
| Durable candidate files | `server/discovery/lifecycle/` | Migrate to richer lifecycle |
| Individual candidate promotion | `server/discovery/promotion.py` | Replace in the primary flow |
| Individual post-promotion board start | `server/discovery/board_start.py` | Replace with portfolio review plus top-candidate deep dives |
| Board deliberation | `server/board/deliberation/` | Reuse; add structured portfolio decision contract |
| Ventures and initiatives | `server/ventures/`, `server/initiatives/` | Reuse |
| Delegated execution | `server/execution/` | Reuse selectively; do not enable unrestricted always-on execution |
| Evidence packets | `server/execution/evidence.py` | Reuse |
| Founder UI | `ui/src/` | Add discovery and experiment domains |
| Architecture enforcement | `docs/architecture/`, `scripts/check_architecture.py` | Update with every new domain/route |

Observed mismatch to correct:

- The current flow requires founder promotion before the board can see one
  selected candidate.
- `rejected` is terminal and cannot be restored.
- Promotion creates a venture before the board has made a portfolio decision.
- There is no portfolio review contract, validation-experiment domain, public
  landing runtime, lead/analytics sync, or social distribution workflow.
- The existing task runner is general-purpose and approval-gated. Globally
  switching `always_on_enabled` to true is not an acceptable substitute for a
  bounded validation orchestrator.

Verification observed on 2026-07-11/12:

- `npm run build` in `ui/` succeeded.
- A full `uv run pytest -q` was manually interrupted after 525 tests and 23
  subtests passed with no observed failures. This is not a completed full-suite
  baseline; rerun targeted tests first and the full suite before final handoff.

## Fresh-session bootstrap

Before changing code:

- [ ] Read this plan completely.
- [ ] Run `git status --short` and `git diff --stat`.
- [ ] Read the current uncommitted discovery files and their tests. Treat them
      as user work to preserve.
- [ ] Run `git diff --check`.
- [ ] Run the current discovery tests:

```bash
uv run pytest -q \
  tests/test_discovery_analyze_corpus.py \
  tests/test_discovery_analyze_models.py \
  tests/test_discovery_analyze_store.py \
  tests/test_discovery_analyze_e2e.py \
  tests/test_discovery_candidate_lifecycle.py \
  tests/test_discovery_producers.py \
  tests/test_discovery_promotion_board.py \
  tests/test_discovery_workflow_cli.py \
  tests/test_discovery_policy.py \
  tests/test_discovery_http_safety.py \
  tests/test_discovery_no_project_llm.py
```

- [ ] Run architecture checks:

```bash
uv run python scripts/check_architecture.py
uv run pytest -q tests/test_architecture_docs.py tests/test_architecture_contract.py
```

- [ ] Do not make a real network request, publish a site, create an external
      account, post to social media, or push a Git branch while establishing the
      baseline.

## Target operating flow

```text
weekly trigger
  -> approved-source fetch
  -> bounded coding-agent synthesis
  -> 5-10 validated durable candidates
  -> one board portfolio-review session
  -> decision recorded for every candidate
  -> board selects top 3, never more than configured max 5 active
  -> create venture + activated validation initiative + experiment
  -> generate and publish minimal landing page
  -> generate tracked distribution packets
  -> optional configured auto-post; otherwise manual posting playbook
  -> collect visits, waitlist joins, problem descriptions, early-access requests
  -> day-7 review
  -> extend to day 14 only when exposure is insufficient
  -> board decides validate / iterate / defer / reject
  -> founder reviews exceptions and retained rejections
  -> results inform future prioritization without rewriting historical evidence
```

## Authority and safety boundaries

1. Discovery content remains untrusted evidence. Existing digest, quote, URL,
   and source-policy checks remain mandatory.
2. The board can label and prioritize candidates, but it cannot delete them.
3. The system may automatically create a bounded validation initiative and
   publish an approved landing-page template through a configured free-plan
   publisher.
4. The private Agentic Board API must **never** be exposed publicly merely to
   collect leads. Public landing runtime and private board runtime are separate
   trust zones.
5. Public forms collect only the minimum fields required for validation.
   Consent, privacy text, retention, export, and deletion behavior must be
   explicit.
6. Social auto-posting is opt-in per adapter/account. A manual packet is always
   generated. Adapters must obey platform/community rules, quotas, rate limits,
   and disclosure requirements; they must not bypass access controls.
7. No paid action exists in this plan. A future spend capability requires a new
   explicit founder approval boundary.
8. Do not enable general always-on execution globally. Auto-execution is scoped
   to typed validation actions with allowlisted outputs and limits.

## Target contracts

### Candidate lifecycle

Do not use a single status to represent discovery, board opinion, founder
disposition, and experiment state. Separate them:

```text
Candidate.discovery_status:
  new | ready_for_board | under_board_review | reviewed

Candidate.board_label:
  prioritize | investigate | defer | reject | null

Candidate.founder_disposition:
  active | overridden | disposed

Candidate.validation_state:
  not_selected | queued | validating | validated | iterate |
  inconclusive | rejected
```

All changes append an audit event containing actor, previous value, new value,
reason, related session/experiment ID, and timestamp. `disposed` is a soft
founder disposition; the record and evidence remain readable and restorable.

Increment the candidate schema version and provide a deterministic migration
from the current `new/shortlisted/rejected/promoted/board_started` contract.
Migration must support dry-run, create backups, and never silently guess an
ambiguous status.

### Portfolio decision

The chair must return one validated object for every input candidate:

```text
PortfolioDecision
  candidate_id
  rank
  label: prioritize | investigate | defer | reject
  confidence: low | medium | high
  rationale
  strongest_evidence[]
  weakest_evidence_or_gap[]
  critical_assumption
  cheapest_credible_test
  success_signals[]
  stop_conditions[]
  minimum_exposure
  selected_for_validation: bool
```

Rules:

- Exactly one decision per input candidate; no missing or invented IDs.
- Unique contiguous ranks.
- Default three `selected_for_validation`; never exceed configured maximum five
  or available experiment capacity.
- A candidate without sufficient evidence may be `investigate` or `defer`, not
  promoted merely to fill capacity.
- Structured-output failure does not mutate candidate state. Record the failed
  review and permit repair/retry.

### Validation experiment

Create a new `server/experiments/` domain with a typed aggregate:

```text
ValidationExperiment
  id
  candidate_id
  portfolio_review_id
  board_session_id
  venture_id
  initiative_id
  hypothesis
  critical_assumption
  experiment_type
  success_signals[]
  stop_conditions[]
  minimum_exposure
  starts_at
  review_at                 # day 7
  expires_at                # day 14 maximum
  status
  landing_page_deployment
  distribution_packet_ids[]
  latest_metrics
  decision_history[]
```

Experiment statuses:

```text
draft -> generating -> ready_to_publish -> published -> collecting -> review_due
review_due -> validated | iterate | rejected | inconclusive
inconclusive -> extended -> review_due
```

An experiment may extend only once and never past 14 days without a founder
override. Persistence should use domain-owned tables in the existing local
SQLite database unless current code review reveals a better established store.

### Landing page and lead events

Each landing page must have a small, stable contract rather than accepting
arbitrary generated application code:

```text
LandingPageBrief
  slug
  audience
  observed_problem
  proposed_outcome
  evidence-safe claims[]
  primary_cta
  privacy_text
  experiment_id

LeadEvent
  event_id
  experiment_id
  event_type: page_view | form_start | waitlist_join |
              problem_submitted | early_access_requested
  occurred_at
  source / medium / campaign / content
  anonymous_session_id
  consent_version
  payload                         # allowlisted by event type
```

Do not store raw IP addresses in the private board store. Email and free-text
problem descriptions are sensitive lead data and require explicit retention
and deletion handling.

### Distribution packet

```text
DistributionPacket
  id
  experiment_id
  platform
  target_community
  rationale
  copy_short
  copy_long
  creative_brief
  short_video_script
  tagged_url
  community_rules_note
  mode: manual | automatic
  status: draft | ready | posted | skipped | failed
  posted_at
  external_post_id
```

Manual packets are required for Instagram, TikTok, Facebook, Reddit, Rednote,
and LinkedIn. Automatic adapters are optional until credentials and a compliant
posting path are configured.

## Phase 0 - Generalize the coding-agent discovery entrypoint

The existing implementation has a Codex synthesis producer and a manual
handoff. The founder's requirement is broader: the weekly workflow should be
operable from Codex, Claude Code, Cursor, or another coding-agent CLI without
coupling durable discovery state to one vendor.

Keep collection and synthesis as separate trust steps:

```text
collector
  -> approved public observations with retrieval provenance
  -> deterministic policy/URL/schema validation
  -> raw discovery store
  -> bounded prepared bundle
  -> semantic producer
  -> candidate output
  -> deterministic candidate/evidence validation
```

Repository source adapters remain the preferred collectors where they work.
When a coding agent performs public web/search collection, it must write through
the same bounded observation-import contract; it cannot place arbitrary prose
directly into a board prompt.

### Task 0.1 - Add collector and producer registries

**Create or modify:**

- `server/discovery/collectors/`
- `server/discovery/producers/`
- `server/discovery/doctor.py`
- `server/discovery/cli.py`
- `tests/test_discovery_collectors.py`
- `tests/test_discovery_producer_registry.py`

Steps:

- [ ] Define separate `DiscoveryCollector` and `DiscoveryProducer` protocols.
- [ ] Preserve the existing channel-based collector and Codex/manual producer.
- [ ] Add capability discovery for installed Codex, Claude, and Cursor CLIs.
- [ ] Add dedicated adapters only after inspecting each installed CLI's actual
      non-interactive flags. Do not invent flags or build an arbitrary shell
      command from configuration.
- [ ] Use argv arrays, fixed input/output paths, timeouts, bounded logs, redacted
      errors, and persisted tool/version metadata.
- [ ] Keep `manual` available when a CLI cannot run non-interactively.
- [ ] Extend `doctor` to report collector and producer capabilities separately.

### Task 0.2 - Add a strict coding-agent observation importer

The importer accepts agent-collected public observations but does not trust
their claims:

```text
AgentObservation
  platform
  external_id
  canonical_url
  retrieved_at
  title
  exact_quote_or_excerpt
  public_author_ref        # optional; avoid unnecessary PII
  engagement_metadata
  collector_name/version/run_id
  verification_status
```

Steps:

- [ ] Validate schema versions, field sizes, URLs, platform posture, duplicate
      keys, timestamps, and run provenance.
- [ ] Re-fetch or otherwise deterministically verify public URLs/quotes where
      current policy permits it.
- [ ] Mark unverifiable observations clearly and exclude them from evidence used
      for board selection until verified; never silently upgrade confidence.
- [ ] Preserve partial-source failures and held/unsupported platform states.
- [ ] Continue prohibiting authenticated-browser bypass of API restrictions,
      CAPTCHA, rate limits, private groups, or platform controls.
- [ ] Add fixture-driven tests with no live network in the default suite.

Target operator experience:

```bash
uv run python -m server.discovery collect --collector channels
uv run python -m server.discovery collect --collector codex
uv run python -m server.discovery synthesize --producer claude
uv run python -m server.discovery synthesize --producer cursor
```

Unavailable adapters must fail with a useful capability message and a manual
handoff path, not corrupt or partially promote a weekly cycle.

## Phase 1 - Correct candidate lifecycle and preserve current work

### Task 1.1 - Introduce schema v2

**Modify:**

- `server/discovery/lifecycle/models.py`
- `server/discovery/lifecycle/store.py`
- `server/discovery/lifecycle/__init__.py`
- `server/discovery/cli.py`

**Create:**

- `server/discovery/lifecycle/migrate.py`
- `tests/test_discovery_candidate_lifecycle_v2.py`
- `tests/test_discovery_candidate_migration.py`

Steps:

- [ ] Add the four independent lifecycle dimensions and append-only audit events.
- [ ] Preserve evidence, provenance, producer run, report digest, founder
      decisions, promotions, and board-session history during migration.
- [ ] Map unambiguous legacy states and stop with a useful error for ambiguous
      combinations.
- [ ] Add `discovery migrate-candidates --dry-run` and explicit apply mode.
- [ ] Add restore and founder-dispose operations; never unlink source evidence.
- [ ] Keep old readers functional only for the duration of migration tests, then
      remove dual-write behavior.

Acceptance:

- Legacy fixtures round-trip to schema v2 without evidence loss.
- Board rejection remains restorable.
- Founder disposal remains queryable and auditable.
- Importing a weekly report is idempotent.

### Task 1.2 - Remove founder-promotion-first as the primary path

**Modify:**

- `server/discovery/promotion.py`
- `server/discovery/board_start.py`
- `server/discovery/cli.py`
- `tests/test_discovery_promotion_board.py`

Steps:

- [ ] Keep legacy individual promotion behind an explicitly named compatibility
      command if existing callers require it.
- [ ] Do not create a venture before portfolio review in the new flow.
- [ ] Make candidate eligibility for portfolio review depend on validated
      evidence and `ready_for_board`, not founder promotion.
- [ ] Update documentation that currently says the founder must select one
      candidate before board evaluation.

## Phase 2 - Add structured board portfolio review

### Task 2.1 - Define board-owned portfolio contracts

**Create:**

- `server/board/portfolio.py`
- `server/protocols/portfolio_review.md`
- `tests/test_board_portfolio_contract.py`

**Modify:**

- `server/board/projection.py`
- `server/board/deliberation/orchestrator.py` only at a narrow extension seam

Steps:

- [ ] Add strict `PortfolioReviewInput`, `PortfolioDecision`, and
      `PortfolioReviewResult` parsing/validation.
- [ ] Build a bounded evidence summary for 5-10 candidates. Do not place the raw
      discovery corpus in board context.
- [ ] Instruct independent members to compare opportunity cost across the whole
      portfolio, not evaluate each candidate in isolation.
- [ ] Make the chair return a machine-readable portfolio decision section.
- [ ] Add one bounded repair attempt using the existing structured-output
      hardening pattern.
- [ ] Persist the review session and decision object with input candidate IDs,
      report digests, evidence packet IDs, selected count, and config version.

Tests:

- Missing, duplicate, or invented candidate IDs fail validation.
- More than five selections fail validation.
- Low-evidence portfolios may select fewer than three.
- Rankings are unique and deterministic after parsing.
- A malformed chair response leaves all candidate records unchanged.
- The board recommends landing-page validation rather than a product build when
  the riskiest assumption is demand.

### Task 2.2 - Add portfolio review application service and CLI

**Create:**

- `server/discovery/portfolio_review.py`
- `tests/test_discovery_portfolio_review.py`

**Modify:**

- `server/discovery/cli.py`
- `server/harness/ledger.py`

CLI target:

```bash
uv run python -m server.discovery review-portfolio \
  --week 2026-W29 --default-select 3 --max-active 5 --verify
```

Steps:

- [ ] Load the 5-10 eligible candidates for a report/run.
- [ ] Resolve available capacity from active experiments.
- [ ] Call the board portfolio service through an injected orchestrator.
- [ ] Apply all candidate decisions atomically only after full result validation.
- [ ] Record board labels, ranks, rationales, and audit events.
- [ ] Return a stable summary suitable for the future API/UI.
- [ ] Retry by idempotency key without duplicating decisions or sessions.

## Phase 3 - Automatically create bounded validation initiatives

### Task 3.1 - Add the experiment domain

**Create:**

- `server/experiments/__init__.py`
- `server/experiments/models.py`
- `server/experiments/store.py`
- `server/experiments/service.py`
- `tests/test_experiment_models.py`
- `tests/test_experiment_store.py`
- `tests/test_experiment_service.py`

Steps:

- [ ] Implement the typed aggregate and transition rules above.
- [ ] Add unique constraints for candidate + portfolio review so retries cannot
      create duplicate experiments.
- [ ] Store all timestamps as UTC and calculate day-7/day-14 review dates in one
      place.
- [ ] Add event/audit rows for every transition.
- [ ] Add queries for active capacity, due reviews, portfolio history, and
      founder dashboard summaries.

### Task 3.2 - Create venture and initiative automatically

**Modify:**

- `server/experiments/service.py`
- `server/ventures/store.py` only if an idempotent get-or-create seam is missing
- `server/initiatives/store.py` only if an idempotent creation seam is missing

Steps:

- [ ] For each selected candidate, idempotently create a venture scoped to the
      candidate.
- [ ] Create and activate a validation initiative automatically.
- [ ] Set the initiative objective to falsify the critical assumption, not build
      a product.
- [ ] Generate success criteria from the board decision: landing published,
      minimum exposure reached, funnel measured, and day-7 decision recorded.
- [ ] Link candidate, portfolio review, board session, evidence packet, venture,
      initiative, and experiment IDs.
- [ ] Stop after available capacity is exhausted; keep remaining prioritized
      candidates in a ranked queue.

Do **not** turn on general `execution.always_on_enabled`. Add a bounded
experiment action dispatcher that allows only typed actions such as rendering a
page, publishing through a configured adapter, generating distribution packets,
syncing metrics, and requesting a scheduled review.

## Phase 4 - Generate and publish minimal landing pages

### Task 4.1 - Define the private/public boundary

**Create:**

- `server/experiments/landing/models.py`
- `server/experiments/landing/render.py`
- `server/experiments/landing/publisher.py`
- `server/experiments/landing/leads.py`
- `tests/test_landing_contract.py`
- `tests/test_landing_render.py`

Steps:

- [ ] Define `LandingPageBrief`, `LandingPageArtifact`, `DeploymentResult`,
      `LeadEvent`, `LandingPagePublisher`, and `LeadEventSource` contracts.
- [ ] Render a small accessible static page from allowlisted fields. Escape all
      candidate and board text; never inject raw source HTML.
- [ ] Include waitlist, problem-description, and early-access controls.
- [ ] Add clear consent/privacy text and configurable retention metadata.
- [ ] Generate tagged URLs and the five funnel events.
- [ ] Write artifacts only beneath an experiment-owned output directory.
- [ ] Add a local/fake publisher for deterministic tests.

The board application stays private. The public page posts to a separate lead
sink, and the private app imports or syncs an allowlisted event feed.

### Task 4.2 - Select and implement one real free-plan deployment path

This task has one explicit configuration checkpoint because credentials cannot
be inferred from the repository:

- [ ] Inspect available founder-owned hosting/form credentials without printing
      secrets.
- [ ] Select one static-site publisher plus form/lead sink that supports the
      required free-plan experiment volume.
- [ ] Record the choice and rationale in an architecture decision record.
- [ ] Implement a provider-specific adapter with injected client/runner,
      idempotency key, timeout, redacted errors, and delete/unpublish support.
- [ ] Keep provider details out of experiment domain models.
- [ ] Add mocked contract tests; live deployment tests must be opt-in.
- [ ] Require explicit setup confirmation before the first real deployment, but
      subsequent bounded experiment deployments may be automatic.

Do not declare the end-to-end loop complete while only a fake publisher exists.

### Task 4.3 - Add minimum viable page-quality checks

- [ ] Mobile and desktop layout checks.
- [ ] Keyboard-accessible form and labels.
- [ ] Honest copy: do not claim the product exists when testing demand.
- [ ] No fabricated testimonials, customer counts, pricing, or guarantees.
- [ ] No full application navigation or speculative feature catalog.
- [ ] Page build and publish failure keeps the experiment recoverable and does
      not consume another portfolio slot indefinitely.

## Phase 5 - Generate manual-first social distribution

### Task 5.1 - Add distribution contracts and packet generation

**Create:**

- `server/experiments/distribution/models.py`
- `server/experiments/distribution/generate.py`
- `server/experiments/distribution/store.py`
- `server/experiments/distribution/render.py`
- `tests/test_distribution_packets.py`

Steps:

- [ ] Generate one platform-specific packet for Instagram, TikTok, Facebook,
      Reddit, Rednote, and LinkedIn when relevant to the candidate audience.
- [ ] Produce native-feeling copy rather than duplicating one generic post.
- [ ] Include a creative brief and short-video script where relevant.
- [ ] Add source-tagged landing URLs so inbound can be attributed.
- [ ] Include a target-community rationale and a field for current rules review.
- [ ] Render a founder-readable Markdown/HTML playbook with copy buttons and a
      post/skip checklist.
- [ ] Track manual posted time and optional external URL/ID.

### Task 5.2 - Add an optional social publisher port

**Create:**

- `server/experiments/distribution/publisher.py`
- `tests/test_social_publisher_contract.py`

Steps:

- [ ] Define a capability-reporting adapter protocol; unsupported platforms
      return `manual_required`, not failure.
- [ ] Make every account/platform opt-in and separately configurable.
- [ ] Add per-platform rate limits, idempotency, and audit events.
- [ ] Never use authenticated browser automation to bypass unavailable official
      posting paths or platform restrictions.
- [ ] Implement real adapters only after credentials and current platform rules
      are reviewed. Manual packets fulfill distribution when automation is not
      available.

Automatic posting is not on the critical path for the first usable vertical
slice; tracked manual posting is.

## Phase 6 - Collect metrics and return results to the board

### Task 6.1 - Add event ingestion and funnel aggregation

**Create:**

- `server/experiments/metrics.py`
- `tests/test_experiment_metrics.py`

Steps:

- [ ] Import/sync events idempotently from the public lead source.
- [ ] Validate experiment IDs, event types, timestamps, consent versions, field
      sizes, and payload allowlists.
- [ ] Aggregate unique visitors, form starts, waitlist joins, submitted problem
      descriptions, and early-access requests.
- [ ] Segment by source, medium, campaign, content, and platform.
- [ ] Compute rates only when denominators are nonzero and always retain counts.
- [ ] Redact lead PII from board prompts; provide aggregate metrics and bounded,
      de-identified problem themes instead.

### Task 6.2 - Add day-7/day-14 review service

**Create:**

- `server/board/experiment_review.py`
- `server/protocols/experiment_review.md`
- `server/experiments/review.py`
- `tests/test_experiment_review.py`

The result must be structured:

```text
ExperimentDecision
  experiment_id
  outcome: validated | iterate | rejected | inconclusive
  exposure_sufficient
  evidence_summary
  learned_problem_language[]
  next_assumption
  next_cheapest_test
  rationale
```

Rules:

- Insufficient exposure at day 7 produces `inconclusive` and may extend to day
  14 once.
- Insufficient exposure at day 14 remains `inconclusive`; it is not rewritten as
  lack of demand.
- `iterate` creates another bounded validation experiment, not a product build.
- `validated` may queue a stronger validation step. Product construction still
  requires explicit evidence and a new board decision.
- Results append to candidate and experiment histories and close or roll over
  the initiative consistently.

## Phase 7 - Orchestrate the weekly cycle

### Task 7.1 - Add a resumable weekly-cycle service

**Create:**

- `server/discovery/weekly_cycle.py`
- `tests/test_weekly_cycle.py`
- `tests/test_opportunity_to_validation_e2e.py`

**Modify:**

- `server/discovery/cli.py`

Target commands:

```bash
uv run python -m server.discovery weekly-cycle --producer codex --max-candidates 10
uv run python -m server.discovery weekly-status
uv run python -m server.discovery resume-cycle <cycle-id>
```

Steps:

- [ ] Persist a `WeeklyCycle` record with states for collect, prepare, synthesize,
      import, portfolio review, experiment creation, page publication,
      distribution readiness, and scheduled review.
- [ ] Make every stage resumable and idempotent.
- [ ] Partial source failures remain visible but do not discard successful data.
- [ ] A failed producer or board response does not auto-promote stale output.
- [ ] Run portfolio review only after 5-10 candidates pass validation, unless an
      explicit low-volume override records why fewer were accepted.
- [ ] Respect active experiment capacity and maintain a prioritized queue.
- [ ] Support an external weekly scheduler later; first make the command safe to
      run repeatedly by cron or a coding-agent session.

End-to-end fake acceptance fixture:

```text
fixture source records
  -> prepared bundle
  -> fake coding-agent output with 7 candidates
  -> deterministic import
  -> fake board portfolio result for all 7
  -> top 3 create ventures + active initiatives + experiments
  -> fake publisher returns 3 URLs
  -> distribution packets generated
  -> fake events imported
  -> day-7 board reviews recorded
  -> founder disposes one rejected candidate without deleting it
```

## Phase 8 - Add API and 15-30 minute founder UI

### Task 8.1 - Add discovery/experiment API routes

**Create:**

- `server/api/routes/discovery.py`
- `server/api/routes/experiments.py`
- API contract tests matching repository conventions

**Modify:**

- `server/api/app.py`
- `server/api/schemas.py`
- `server/api/__init__.py` only where compatibility exports are required

Minimum endpoints:

```text
GET  /discovery/cycles
GET  /discovery/candidates
GET  /discovery/candidates/{id}
POST /discovery/candidates/{id}/dispose
POST /discovery/candidates/{id}/restore
POST /discovery/candidates/{id}/override
GET  /discovery/portfolio-reviews
POST /discovery/portfolio-reviews
GET  /experiments
GET  /experiments/{id}
POST /experiments/{id}/publish
POST /experiments/{id}/extend
POST /experiments/{id}/review
POST /experiments/{id}/distribution/{packet_id}/mark-posted
```

Mutation endpoints require local/authenticated founder authority consistent with
existing API hardening. Public lead ingestion must not be mounted on this
private API unless a separate, narrowly authenticated deployment is designed.

### Task 8.2 - Build the founder review surface

**Create:**

- `ui/src/domains/discovery/`
- `ui/src/domains/experiments/`

**Modify:**

- `ui/src/shared/types.ts`
- `ui/src/shared/api.ts`
- `ui/src/App.tsx`
- `ui/src/index.css` or existing domain styling seams

Prioritize one weekly dashboard rather than many administration screens:

- Weekly cycle health and partial failures.
- The 5-10 candidates with board rank, label, rationale, and evidence links.
- Active top 3-5 experiments with day count and funnel.
- Traffic-source attribution.
- Review-due and inconclusive warnings.
- Prioritized queue.
- Retained board rejections.
- Founder actions: override, restore, dispose, extend, mark manually posted.
- Distribution playbook with copy-ready assets.

Acceptance:

- A founder can complete the routine weekly review in one screen without
  opening JSON files.
- Destructive-looking actions are soft dispositions with confirmation.
- Empty, loading, partial-failure, and stale-metrics states are explicit.
- Mobile remains usable, but optimize the dense weekly review for a laptop.

## Phase 9 - Evaluation, observability, documentation, and cleanup

### Task 9.1 - Replace output-volume metrics with operating metrics

Add harness/metrics fields for:

- Candidates discovered and accepted per week.
- Evidence completeness and source diversity.
- Time from cycle start to portfolio decision.
- Time from board selection to published page.
- Experiments active, queued, failed, inconclusive, iterated, and validated.
- Funnel counts/rates by source.
- Founder review time and override/disposal counts.
- Percentage of initiatives that attempted a full build before validation
  evidence; target **0%**.
- Experiment decision completed within 14 days.

Do not optimize model behavior using conversion alone; small-sample outcomes and
distribution quality must remain visible.

### Task 9.2 - Add behavioral evals

Create portfolio and experiment-review corpora covering:

- Strong evidence versus high engagement but weak buyer intent.
- Five superficially similar candidates requiring opportunity-cost ranking.
- Insufficient evidence where the board should select fewer than three.
- A tempting request to build a product where a landing page is sufficient.
- Insufficient traffic that must remain inconclusive.
- Strong waitlist but contradictory problem descriptions.
- Sycophantic pressure to promote the founder's preferred candidate.
- Rejected candidates that later gain stronger evidence.

Measure structured validity, evidence grounding, rank completeness,
anti-overbuilding compliance, and correct handling of insufficient exposure.

### Task 9.3 - Update living architecture and operator docs

Update:

- `README.md`
- `CLAUDE.md`
- `docs/architecture/system-graph.md`
- `docs/architecture/components.md`
- `docs/architecture/runtime-flow.md`
- `docs/architecture/extension-guide.md`
- `docs/architecture/component-catalog.json`
- `docs/architecture/discovery-to-board-evaluation.md`
- `design/venture-scan-agent-runbook.md`

Remove the obsolete claim that the founder must choose and promote one discovery
candidate before the board sees it. Document portfolio review, automatic
validation initiatives, private/public separation, manual distribution packets,
and the day-7/day-14 loop.

## Recommended delivery slices

Do not attempt every external integration in one change. Ship these vertical
slices in order:

### Slice A - Correct decision flow, no external publishing

Candidate schema v2, batch portfolio board review, top-three selection, and
automatic venture/initiative/experiment creation with fake publisher tests.

### Slice B - One real landing path and manual distribution

One configured free-plan publisher/lead sink, minimal landing page, tracked
events, platform-specific manual packets, and day-7 review.

This is the first genuinely usable end-to-end version.

### Slice C - Founder dashboard and weekly command

Resumable weekly cycle plus the 15-30-minute review UI.

### Slice D - Selective social automation

Add official/configured publisher adapters one platform at a time. Keep manual
packets for unsupported platforms.

## Test strategy

During each task, run the smallest relevant tests. Before completing each slice:

```bash
uv run pytest -q tests/test_discovery_*.py tests/test_board_portfolio_contract.py \
  tests/test_experiment_*.py tests/test_landing_*.py \
  tests/test_distribution_*.py tests/test_weekly_cycle.py \
  tests/test_opportunity_to_validation_e2e.py

uv run python scripts/check_architecture.py
uv run pytest -q tests/test_architecture_docs.py tests/test_architecture_contract.py

npm run build --prefix ui
```

Before final handoff, run the full non-live suite:

```bash
uv run pytest -q
```

Live source, hosting, form, or social tests must be separately marked and opt-in.
Never let default tests publish, post, spend, or contact real users.

## Definition of done

The operating loop is complete only when all of the following are demonstrated:

- [ ] The weekly workflow can report and use available channel, Codex, Claude,
      Cursor, or manual collector/producer capabilities without coupling stored
      records to one vendor.
- [ ] Coding-agent-collected observations pass the same source-policy,
      provenance, and evidence-verification gates as repository-collected data.
- [ ] A weekly coding-agent run produces 5-10 evidence-backed candidates.
- [ ] One board portfolio session records a valid decision for every candidate.
- [ ] Board rejection retains the candidate and founder disposal is a reversible,
      audited soft disposition.
- [ ] The top three automatically create ventures, activated validation
      initiatives, and experiments without duplicates.
- [ ] No more than five validation experiments can be active.
- [ ] Each selected experiment publishes a real minimal landing page through a
      configured free-plan path.
- [ ] The page records visits, waitlist joins, problem descriptions, and
      early-access requests with source attribution.
- [ ] Manual platform-specific distribution packets are generated and posting
      status can be recorded.
- [ ] Available auto-post adapters are optional and auditable.
- [ ] Day-7 reviews happen; insufficient exposure may extend to day 14 and never
      becomes a false demand rejection.
- [ ] The board records validate/iterate/defer/reject decisions from measured
      results.
- [ ] The founder can review the weekly portfolio and exceptions in 15-30
      minutes from the UI.
- [ ] Historical evidence and decisions remain traceable through every stage.
- [ ] No full product build is launched without prior recorded validation
      evidence and a board decision referencing that evidence.
- [ ] Architecture checks, frontend build, targeted tests, and full non-live
      tests pass.

## Explicit non-goals for this implementation

- Paid advertising or automated spending.
- Building full products for unvalidated candidates.
- Exposing the private board API to the public internet.
- Supporting every social network through automation in the first release.
- Scraping or browser-automating around unavailable APIs or platform controls.
- Deleting rejected/disposed candidate history.
- Letting conversion metrics rewrite or fabricate historical source evidence.
- Replacing founder authority over final disposal and exceptional overrides.

## Fresh-session completion report

At the end of each delivery slice, report:

1. The user-visible operating capability now completed.
2. Files and contracts changed.
3. Migration or runtime-data effects.
4. Tests/builds run with exact results.
5. External setup still required, without exposing secrets.
6. Known failures or intentionally deferred adapters.
7. The next smallest vertical slice.
