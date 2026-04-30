# Critical Analysis — `msitarzewski/agency-agents`

**Date:** 2026-04-22
**Subject repo:** [github.com/msitarzewski/agency-agents](https://github.com/msitarzewski/agency-agents) — 147 agent markdown files across 12 divisions, plus a multi-tool conversion pipeline.
**Viewpoint:** Written from the perspective of the Agentic Board project (7-member council, 4-stage deliberation runtime, SOTB memory) considering what is adoptable and how a solo founder could gradually build up an agent team.
**Method:** Six parallel sub-agents, model and effort scoped per cluster size (Sonnet for the five content clusters, Haiku for the lighter ops cluster, general-purpose Sonnet for the infrastructure/scripts audit). Each sub-agent deep-read 4–8 representative files, skimmed the rest, and returned a critical report under a word cap. Findings below are synthesized from those reports and from my own read of the top-level `README.md` and `CONTRIBUTING.md`.

---

## 1. Executive Summary

Agency-agents is a **prompt-template library with a bash distribution layer**, not an orchestration framework. Calling it "a complete AI agency" is marketing; the runtime claim is unfounded. There is no orchestrator, no message bus, no shared state, no inter-agent protocol. Each "agent" is a markdown persona that activates when the user says the right words inside Claude Code, Cursor, Aider, etc. The celebrated `examples/nexus-spatial-discovery.md` is a retrospective narrative, not a runnable demo — there are no session IDs, no timestamps, no handoff protocol anywhere in the repo.

That said, **the persona library itself is uneven but contains real gold.** A minority of agents (perhaps 20–30 of the 147) are genuine productivity force-multipliers because they encode hard-won domain procedure. The rest range from useful-but-generic to outright persona-paint over advice a competent Googler would produce.

For Agentic Board specifically:
- **Architectures solve different problems.** Agency-agents optimizes for "summon one expert inside whatever tool you're already in." Agentic Board optimizes for "synthesize across multiple experts under an enforced protocol." Don't try to make Agentic Board into agency-agents.
- **The canonical-markdown-plus-converter model is cheap to adopt.** Emitting `server/members/*.md` as Claude Code / Cursor standalone agents is ~1 week of work and opens the members up as a standalone value layer for users outside the boardroom context.
- **Three specific patterns are worth lifting** into Agentic Board: the trust-scorer model from `specialized/agentic-identity-trust.md` applied to Stage 3 synthesis weighting; the observable-states handoff contracts from `specialized-workflow-architect.md` applied to inter-stage compaction; the proposal-before-mutation model from `specialized/identity-graph-operator.md` applied to SOTB writes.

---

## 2. Complexity Assessment & Approach

| Dimension | Value |
|---|---|
| Total files | 281 (235 agent `.md`, rest docs/scripts/integration READMEs) |
| Total size | ~2.7 MB of markdown |
| Top-level directories | 18 |
| Biggest single dir | `specialized/` — 41 files, 702 KB |
| README size | 56 KB |
| Agent count claimed | 147 across 12 "divisions" |

**Decision:** Too large for a single context window to carry deep opinions about all clusters. Domains are naturally independent (marketing agents share no state with engineering) — ideal for fan-out/gather. I allocated:

| Sub-agent | Cluster | Files | Model | Effort |
|---|---|---|---|---|
| A | `engineering/` | 29 | Sonnet | Very thorough |
| B | `specialized/` | 41 | Sonnet | Very thorough (orchestration focus) |
| C | GTM: marketing + sales + paid-media + product | 50 | Sonnet | Thorough |
| D | Creative: design + game-development + spatial-computing | 34 | Sonnet | Medium |
| E | Ops: strategy + PM + finance + support + testing + academic | 46 | Haiku | Quick |
| F | Infra: scripts + integrations + examples | ~20 | Sonnet (general-purpose, all tools) | Thorough — read actual scripts |

I read `README.md` and `CONTRIBUTING.md` in the main thread myself because they are the backbone of any synthesis and can't be delegated without losing conceptual grip.

---

## 3. What the Repo Actually Is (Honest Architecture)

### 3.1 The canonical agent format

Each agent is a `.md` file with YAML frontmatter (`name`, `description`, `color`, `emoji`, `vibe`, optional `services`) plus sections that `CONTRIBUTING.md` groups into "Persona" (Identity & Memory, Communication Style, Critical Rules) and "Operations" (Core Mission, Technical Deliverables, Workflow Process, Success Metrics, Advanced Capabilities).

### 3.2 The distribution pipeline (verified by reading `scripts/convert.sh`)

`convert.sh` is **pure bash string manipulation** — no AST, no plugin registry, no schema. Three `awk` one-liners (`get_field`, `get_body`, `slugify`) plus nine bash functions, one per target tool. `cat` heredocs emit per-tool output. OpenClaw's "split persona from operations" is a line-by-line loop that assigns `##` headers by substring match against seven hardcoded keywords; it silently fails for non-standard section names.

**Concrete bug found:** The `--parallel` branch omits `kimi` from both `parallel_tools` and the sequential fallback loop, so parallel runs silently skip Kimi conversion. Progress counter is hardcoded and mismatched with the tool array.

### 3.3 Activation per target tool — and what's lost

Each target tool has a different activation model, so "one format, all tools" is a polite fiction:

| Tool | Output | Activation | Lost fields |
|---|---|---|---|
| Claude Code | `.md` copied verbatim | Named invocation in prompt | Nothing (native) |
| GitHub Copilot | `.md` copied verbatim | Named invocation | Nothing (native) |
| Cursor | `.mdc` with `alwaysApply: false`, `globs: ""` | Manual `@agent-slug` | emoji, vibe, tools, no glob scoping |
| Aider | **All 147 agents concatenated** into one `CONVENTIONS.md` | Narrative self-selection by the LLM | emoji, vibe, tools |
| Windsurf | **All 147 concatenated** into `.windsurfrules` | Narrative self-selection | emoji, vibe, tools |
| Gemini CLI / Antigravity | `SKILL.md` per agent | Extension invocation | Everything except name + description |
| OpenClaw | `SOUL.md`/`AGENTS.md`/`IDENTITY.md` triple | Workspace per agent | Partial (header-classification fragile) |
| Qwen | SubAgent YAML | Project-scoped | **Only target that preserves `tools` field** |

**The Aider/Windsurf concatenation is the most alarming.** At a generous 500 tokens/agent, 147 agents = 70K+ tokens of system prompt on every turn. The LLM must self-select the right persona from a 70K-token menu. Whether this works reliably is untested and undocumented in the repo.

### 3.4 The absent runtime

There is no orchestrator. There is no message bus. There is no shared state file. There is no agent-to-agent protocol. The celebrated multi-agent example (`examples/nexus-spatial-discovery.md`) is a post-hoc write-up of what a skilled human prompter produced across multiple sessions, then described as "8 agents in parallel in 10 minutes." No session IDs, no execution trace, no timestamps. Section 10 ("Cross-Agent Synthesis") is hand-authored narrative overlay, not a runtime arbitration.

This is not necessarily a gap — the library may intentionally limit scope to "persona distribution." But the README's scenarios and the examples file both imply orchestration the codebase does not provide. This is the single biggest honesty problem in the repo.

---

## 4. Cluster-by-Cluster Critical Analysis

### 4.1 Engineering (29 agents)

**Exemplars** — agents that earn their keep:
- `engineering-minimal-change-engineer.md`: the cluster's best. Teeth in the rules (`three similar lines beats a premature abstraction`), code examples that illustrate the exact failure mode (bloated 47-line diff vs. one-line fix), operationally useful Scope Self-Check template.
- `engineering-codebase-onboarding-engineer.md`: three-level output format (one-liner → 5-minute → deep dive) is a cognitive contract, not decoration. Workspace framework recognition (Nx, Turborepo, Bazel, Lerna) is genuine.
- `engineering-autonomous-optimization-architect.md`: shadow testing, LLM-as-Judge grading, SRE-style burn-rate semantics adapted to token cost FinOps. Genuinely original.
- `engineering-incident-response-commander.md`: 14.4× short-window burn-rate math, concrete SLO YAML. Practitioner-grade.

**Persona paint** — dressed-up generalists:
- `engineering-frontend-developer.md`: React/Vue/Angular/Svelte in one sentence; Core Web Vitals copy-pasted from Google spec without trade-off insight.
- `engineering-backend-architect.md`: "sub-20ms query times" stated as authority with no framing for when this is achievable.
- `engineering-devops-automator.md`: ten tools in the first paragraph — signal of breadth-over-depth.

**Broken / unfit for publication:**
- `engineering-senior-developer.md`: references `ai/system/premium-style-guide.md` — paths that **don't exist in this repo**. A leaked private-repo artifact.
- `engineering-filament-optimization-specialist.md`: single-framework persona for one PHP admin panel; should never have been a standalone agent in a general library.

**Overlaps that would confuse a user:** `engineering-software-architect.md` vs `engineering-backend-architect.md` (both own system design + APIs); `autonomous-optimization-architect` vs `sre` vs `security-engineer` (overlapping reliability/anomaly patterns).

**Missing roles:** dedicated test/QA strategy owner, data/analytics engineer with real depth, API design specialist (schema evolution, versioning), platform/DevEx engineer for internal tooling.

---

### 4.2 Specialized (41 agents) — the dumping ground

This is where slop accumulates. My sub-agent organized it into six real subgroups:

| Subgroup | Count | Verdict |
|---|---|---|
| Orchestration & Governance (`agents-orchestrator`, `workflow-architect`, `mcp-builder`, `agentic-identity-trust`, `identity-graph-operator`) | 5 | The meta-layer. Contains the repo's best thinking and its biggest contradictions. |
| Operations Coordination (`chief-of-staff`, `automation-governance-architect`, `report-distribution-agent`) | 3 | Useful Stage-1 adoption material. |
| Customer-Facing Verticals (`healthcare-customer-service`, `hospitality-guest-services`, `retail-customer-returns`, `customer-service`, `loan-officer-assistant`, `real-estate-buyer-seller`, `hr-onboarding`, `recruitment-specialist`, `study-abroad-advisor`) | 9 | Mostly persona paint. Cut at least half. |
| Professional Services (`legal-*`, `specialized-civil-engineer`, `specialized-salesforce-architect`, `compliance-auditor`, country navigators) | 8 | Mixed. The legal cluster and Salesforce architect are genuine practitioner-grade. |
| Data & Sales Pipeline (extraction, consolidation, AP, outreach, gov-presales) | 5 | Functional. Focused. |
| Wildcard miscellany (`zk-steward`, `blockchain-security-auditor`, `model-qa`, `developer-advocate`, `document-generator`, `cultural-intelligence`, `corporate-training`, `language-translator`, `lsp-index-engineer`, etc.) | 11 | Genuine dumping ground. |

#### The orchestration meta-layer — critical read

- **`agents-orchestrator.md`** is an operationally honest *to-do list*. Four-phase pipeline (PM → ArchitectUX → Dev↔QA loop → Integration), max 3 retries per task, status report templates. It explicitly depends on the human user manually spawning agents in whatever tool. **Not orchestration — very detailed prompting instructions.**
- **`specialized-workflow-architect.md`** is the sharpest specification instrument in the entire repo. Four-view workflow registry, handoff contract schema (payload / success / failure / timeout / recovery), discovery audit checklist. Build-ready artifacts. Gap: never addresses concurrency; two agents running discovery simultaneously produce divergent registries with no merge protocol.
- **`specialized-mcp-builder.md`** is the **least aspirational and most usable**. Hard rules on tool naming (verb-noun like `search_tickets_by_status`), descriptions that explain *when to call*, `isError: true` on every failure return. Practitioner wisdom about how LLMs actually pick tools.
- **`agentic-identity-trust.md`** is the most technically sophisticated and the most disconnected. Penalty-based `AgentTrustScorer`, `DelegationVerifier` with scope-escalation detection, hash-chained `EvidenceRecord` — genuine zero-trust infrastructure. **But nothing else in this repo implements or references any of it.** It's design documentation for infrastructure the repo does not build.
- **`identity-graph-operator.md`** has real engineering specificity: probabilistic matching with field-level scoring, blocking keys to avoid full scans, optimistic locking for concurrent mutations, decision table for merge-directly vs propose-for-review. **The closest thing in the folder to genuine multi-agent consensus mechanics.**

#### The core conflict

`agents-orchestrator` assumes agents can be freely spawned and implicitly trusted. `agentic-identity-trust` assumes no agent should be trusted without cryptographic proof. **These cannot coexist as described.** They do not conflict like two opinions — they conflict like blueprint vs. implementation, where the blueprint assumes infrastructure the implementation does not build.

#### Signal vs. noise in the verticals

| Agent | Verdict | Evidence |
|---|---|---|
| `legal-document-review.md` | **Genuine depth** | Liability-cap carve-outs that swallow the cap, state-by-state non-compete enforceability, market-standard vs unusual risk classification |
| `specialized-salesforce-architect.md` | **Genuine depth** | Governor limits with headroom math, bulkification as hard rule, ADR format with governor-limit impact column — only a practitioner writes this |
| `zk-steward.md` | **Genuine depth** (narrow audience) | Luhmann four-principle validation gate, companion skill architecture |
| `healthcare-customer-service.md` | **Persona paint** | HIPAA + 988 routing correct but at the level of an employee handbook |
| `real-estate-buyer-seller.md` | **Noise** | Fair Housing disclosure is legally required knowledge, not agent value |

**Cut candidates:** `real-estate-buyer-seller.md`, `hospitality-guest-services.md`, `retail-customer-returns.md`, `customer-service.md`, `study-abroad-advisor.md`, `language-translator.md`. These provide zero leverage beyond a single sentence in a system prompt.

**Promote candidates:** `workflow-architect` and `agentic-identity-trust` belong in a separate `infrastructure/` or `platform/` directory. The `legal-*` cluster should become its own `legal/` division.

---

### 4.3 Go-To-Market Bundle (Marketing 30 + Sales 8 + Paid Media 7 + Product 5 = 50)

**Cluster thesis:** Implied user is an **operator running active GTM at an agency or Series-A-ish startup**, not a solo founder at day zero. China depth (12+ agents, ~24% of cluster) further narrows this — you're either a mainland brand or a cross-border e-commerce operator, or the China agents are dead weight to you.

**Best agents:**
- `sales-deal-strategist.md`: MEDDPICC as a reasoning framework (each element gets a paragraph on what "not answered" means in deal-risk terms). Scored deliverable template with verdicts like `BATTLING — winnable if gaps close in 14 days`. Hand it a live deal, get something useful back.
- `marketing-china-market-localization-strategist.md`: signal triangulation across 7 platforms, four-mental-model framework (Signal Detection / MECE / Counter-Intuitive / Triangulation), phase-gated GTM checklists.
- `marketing-private-domain-operator.md`: actual YAML SCRM config, SQL queries for BI dashboards, lifecycle automation code.

**Weakest:** `marketing-content-creator.md`, `marketing-social-media-strategist.md`, `marketing-growth-hacker.md` — structurally identical, feel template-generated, aspirational metrics ("300% increase in content-driven lead generation") without baselines. `social-media-strategist` explicitly defers to Twitter Engager and Reddit Community Builder — a routing note, not an agent.

**On the China slant:** 2 of 12+ Chinese-platform agents are transferable wholesale to Western users — `china-market-localization-strategist` (methodology, not platform) and `private-domain-operator` (lifecycle automation generalizes to any CRM). The remaining 10 require mainland platform access, Chinese copywriting, and distribution infrastructure — effectively dead weight for a Western-only user.

**Coverage gaps:** lifecycle/retention marketer (no owner of email sequences, onboarding flows, churn intervention — arguably the highest-ROI GTM motion for a product with existing users); pricing strategist; PR/earned media; category design; community manager distinct from Reddit builder; RevOps/territory/quota architect.

**Overlap traps:** `growth-hacker` vs `social-media-strategist` vs `content-creator` (~60% capability overlap); `tiktok-strategist` vs `douyin-strategist` vs `short-video-editing-coach` (three agents for one content format); `sales-coach` vs `sales-deal-strategist` (both do MEDDPICC/deal inspection).

---

### 4.4 Creative Cluster (Design 8 + Game-Dev 20 + Spatial-Computing 6 = 34)

**Cohesion verdict: the three sub-clusters do not hang together.** Design + game-dev + spatial share a visual-output bias and nothing else. The overlap user — a game studio shipping a visionOS port with brand identity work — is a narrow audience. There are no cross-referencing agents (no "motion designer" bridging brand animation and game VFX).

**Engine-specific game-dev earns its specificity.** `unity-architect.md` goes deep into ScriptableObject event channels, `RuntimeSet<T>`, `EditorUtility.SetDirty()` serialization hygiene, DOTS/ECS, Addressables groups, Burst Compiler usage. `unreal-systems-engineer.md` names the 16M-instance Nanite hard cap, UPROPERTY/UFUNCTION boundaries, GAS module setup in `.Build.cs`. These are real engine gotchas, not docs summaries.

**The Whimsy Injector is theater that occasionally becomes functional.** `design-whimsy-injector.md` is celebrated in the README as the personality exemplar. Reality: its deliverables (CSS micro-interaction system, gamification achievement class, Konami easter egg) are the same artifact categories as `design-ui-designer.md` — just with a playfulness filter applied to framing. Personality ≠ functional-capability difference. The "40%+ engagement improvement" success metric is stated as universal and is actually marketing.

**Weakest sub-cluster: spatial-computing.** `visionos-spatial-engineer.md` is ~50 lines — one-fifth the length of the engine-specific game-dev agents — with no code deliverables, no workflow process, no anti-pattern watchlist. The other five spatial files follow the same thin pattern.

**Gaps:** 3D motion designer (rigs, blend trees); motion graphics (After Effects / Cavalry / Rive); sound designer outside game-audio (brand audio, app spatial audio); design-to-engineering handoff (Figma-to-engine pipeline).

---

### 4.5 Operations Cluster (Strategy 16 + PM 6 + Finance 5 + Support 6 + Testing 8 + Academic 5 = 46)

**Strongest: Testing (8).** `testing-reality-checker.md` + `testing-evidence-collector.md` encode a real **two-gate QA doctrine**: Evidence Collector produces visual proof (screenshots, perf metrics); Reality Checker defaults to skeptical and requires overwhelming evidence to ship. "Zero issues found" is an explicit red flag. This pattern is directly adoptable.

**Weakest: Academic (5).** Anthropologist, Geographer, Historian, Narratologist, Psychologist. The agents *themselves* are rigorous (peer-reviewed grounding — Structuralism, Braudel/Annales, Luhmann, etc.). But **they are positioned for "world-building, storytelling, narrative design" and wedged into an ops cluster**, where no solo founder reaches for them. Either move them into a creative-writing bundle or reframe them as research consultants ("validate our market-positioning narrative the way a historian validates period authenticity"). Currently: padding.

**Strategy (16) is not bloat — it's orchestration infrastructure.** The sub-agent identified 7 phase-gated playbooks + 4 runbooks + coordination files. That's a product lifecycle, not competing personas. Onboarding friction is high; most solo founders will only use Phase 0–3.

**Highest-leverage early adoptions:** `finance/finance-fpa-analyst.md` (rolling forecasts + variance analysis = stopping flying blind) and `project-management/project-management-studio-producer.md` (portfolio orchestration).

**Gap:** no **decision-integrator** agent. Nothing synthesizes across FP&A forecast + testing defect rate + PM timeline into "launch or slip 4 weeks." NEXUS playbooks orchestrate within divisions; nothing sits above them.

---

### 4.6 Infrastructure & Distribution

See §3 for the architecture. The critical findings are:

1. **`convert.sh` is bash string manipulation** — maintainable at 147 agents, starts to hurt at 500, fragile at any size for non-standard section headings.
2. **`kimi` parallel-omission bug** is a real silent failure.
3. **Aider/Windsurf concatenation** puts all 147 agents into one context window — untested at scale; LLM self-selection from a 70K-token menu is the structural weak point of the whole distribution story.
4. **Only Qwen preserves the `tools` field.** All other targets lose most of the YAML frontmatter.
5. **`nexus-spatial-discovery.md` is retrospective narrative**, not a runnable demo. Section 10 ("Cross-Agent Synthesis") is a hand-authored overlay. No session IDs, no execution trace, no protocol.

---

## 5. The Gradual Build-Up Path

This is the core of what you asked for. Below is a staged adoption plan synthesized from all six cluster reports, sequenced by **leverage delivered per agent added**.

### Stage 0 — Before you add any agent (prerequisites)

- Decide which **host tool** you are standardizing on (Claude Code vs Cursor vs Aider…). This single choice determines whether you get native-`.md` fidelity (Claude Code, Copilot) or degraded formats (all others). If ambiguous, default to **Claude Code** — it is the only tool the repo treats as first-class and the conversion pipeline is bypassed entirely for it.
- Decide your **activation discipline**. The repo has no orchestrator; you are the orchestrator. Write a one-page rule for your own use: when you invoke an agent, when you chain agents, when you manually arbitrate.

### Stage 1 — First 3–5 agents (governance layer, not execution layer)

The most common mistake is to start with execution agents (frontend developer, growth hacker). Don't. Execution agents amplify whatever direction you point them in, including the wrong direction. Start with **context and guardrails**:

1. **`engineering-codebase-onboarding-engineer.md`** — no other agent can do good work in an unfamiliar codebase without a reliable map. The three-level output format is the most operationally useful template in the entire repo.
2. **`engineering-minimal-change-engineer.md`** — behavioral guardrail that runs concurrently with every implementation agent. Counteracts AI coding tools' default over-production. Its Scope Self-Check template prevents an entire class of slop.
3. **`specialized/specialized-chief-of-staff.md`** — the single non-technical role that solves coordination pain for a solo operator. Document dependency maps, cascading update discipline, "purpose before busy-work" test.
4. **`testing/testing-reality-checker.md`** (paired with `testing-evidence-collector.md` once something is shippable) — the two-gate QA doctrine. Skepticism as default. Most teams skip this middle step and regret it.
5. **`engineering-code-reviewer.md`** — three-tier severity (blocker / suggestion / nit) is cognitively lightweight enough to apply consistently.

Rationale: three of these five slow you down on purpose. That is correct for a solo operator whose main failure mode is not "too slow" but "too much of the wrong thing, ambitiously done."

### Stage 2 — Small team (agents 6–10): add a thin execution layer

Now start adding specialists — but narrowly:

6. **`engineering-software-architect.md`** (*not* `backend-architect` — pick one; they overlap ~60%). System-design thinking when you need to make a decision that will take more than a week to reverse.
7. **`engineering-incident-response-commander.md`** — once anything is running in production. Burn-rate alerting, SEV escalation.
8. **`sales/sales-outbound-strategist.md`** — the foundation of any pipeline motion. ICP definition and signal-based sequencing feed everything else GTM.
9. **`sales/sales-deal-strategist.md`** — once early deals are live, MEDDPICC stops you wasting cycles on deals that can't fund.
10. **`design/design-ui-designer.md`** OR **`design/design-ux-architect.md`** — design tokens and IA discipline before brand-level polish. Skip the Whimsy Injector at this stage.

### Stage 3 — Maturity (agents 11–15): operations and distribution

Unlocked only once Stage 2 agents have a track record (several weeks of observed output quality):

11. **`finance/finance-fpa-analyst.md`** — once cash-flow visibility matters more than velocity.
12. **`marketing/marketing-seo-specialist.md`** — durable organic channel. Slow compounding; start early so the compounding has time to work.
13. **`paid-media/paid-media-ppc-strategist.md`** — only after ICP is validated by Stage 2 deal flow. Starting paid before ICP clarity burns cash.
14. **`product/product-manager.md`** — PRD template with explicit Non-Goals, staged launch plan with rollback triggers. Avoid before you have a beachhead segment.
15. **`project-management/project-management-studio-producer.md`** — portfolio orchestration when you have three-plus concurrent initiatives.

### Stage 4 — Orchestration tier (agents 16+): only if genuinely needed

Most teams do not need this tier. Trigger: you find yourself manually keeping notes on which agent owns which handoff.

16. **`specialized/specialized-workflow-architect.md`** — codify handoff contracts (payload / success / failure / timeout / recovery) before drift becomes technical debt.
17. **`specialized/specialized-mcp-builder.md`** — if you start building tools for the agents to call, this is the only sober voice in the repo about naming, descriptions, and `isError: true` contracts.
18. **`specialized/agentic-identity-trust.md`** — **only** once your agents take real-world actions (API calls, data writes, external mutations). Before that, it is premature architecture.

### Skip or cut

- `engineering-senior-developer.md` (broken private-path references)
- `engineering-filament-optimization-specialist.md` (single-framework artifact)
- Any China-platform agent unless you operate in China — the exceptions are `marketing-china-market-localization-strategist.md` (methodology) and `marketing-private-domain-operator.md` (system design), both transferable wholesale
- `specialized/real-estate-buyer-seller.md`, `hospitality-guest-services.md`, `retail-customer-returns.md`, `customer-service.md`, `study-abroad-advisor.md`, `language-translator.md` — persona paint
- `design-whimsy-injector.md` — keep on the shelf; invoke only when you are deliberately investing in playful differentiation

### China-specific track (only if you operate in China)

Sequence: `marketing-china-market-localization-strategist.md` → `marketing-private-domain-operator.md` → pick the two platform specialists that match your acquisition channel (Xiaohongshu, Douyin, Zhihu, Bilibili, etc.) → `marketing-china-ecommerce-operator.md` or `marketing-cross-border-ecommerce.md` depending on flow direction.

### Game developer track (different tree entirely)

Sequence: `game-development/game-designer.md` → `game-development/<your-engine>/architect.md` (Unity, Unreal, Godot — pick one) → `game-development/technical-artist.md` once asset pipeline discipline matters.

---

## 6. Lessons for Agentic Board

Concretely adoptable patterns, ordered by cost-to-adopt:

### 6.1 Low-cost (days to a week)

- **Three-level disclosure format for Stage 3 synthesis.** The `engineering-codebase-onboarding-engineer.md` output format (one-liner → 5-minute → deep dive) maps directly onto the Chairperson's synthesis problem. Currently Stage 3 produces a single blob. Mandating the three-level structure makes the output consumable at different attention levels without changing the deliberation logic.
- **Scope self-check / "tempted to add but won't" discipline** from `engineering-minimal-change-engineer.md`, applied to Stage 2 peer review. Each member files what they considered raising but deliberately declined — surfaces implicit reasoning without bloating the response.
- **Non-Goals section in Stage 3 output**, lifted from `product/product-manager.md`. Anti-scope-creep mechanism. The board currently produces recommendations that trend toward feature maximalism; explicit "what we are NOT recommending and why" is a cheap discipline.
- **Comment-track and signal-tiering patterns** from `marketing-china-market-localization-strategist.md` and `sales-outbound-strategist.md`, lifted into the Strategist member's procedures for evidence assessment.

### 6.2 Medium-cost (1–2 weeks)

- **Canonical-markdown + converter model**, adapted for `server/members/*.md` → Claude Code / Cursor standalone agents. Write a `convert_claude_code` that copies members after stripping boardroom-specific frontmatter (`priority`, any board-specific keys). Write a `convert_cursor` equivalent for `.mdc`. Risk: semantic drift — a member written to hand off to a Chairperson will behave oddly as a standalone Cursor rule. Mitigation: emit a "standalone mode" rewrite or strip boardroom-specific instructions in the converter. **Do not adopt** the Aider/Windsurf concatenation pattern (context contamination at scale) or the `--parallel` branch as written (`kimi` silent-omission bug).
- **Observable-states / handoff-contract schema** from `specialized-workflow-architect.md`, applied to the inter-stage compaction. Explicitly specify: what is in session state at end of Stage 1; what format Stage 2 receives; what shape is expected on Stage 2 output; what happens if a member's Stage 2 response fails to parse. The board currently compacts but does not enforce the handoff contract, so Stage 3 synthesis quality depends on format compliance nothing checks.

### 6.3 Higher-cost (multi-week, requires design review)

- **Penalty-based trust scorer** from `agentic-identity-trust.md`, applied to member Stage-3 synthesis weighting. Start each member at 1.0, penalize for verifiable failures (Stage 4 verifier catching issues a member's Stage 2 critique missed), track outcome accuracy over time. Lower-trust members get lower Stage 3 synthesis weight. Compatible with existing SOTB memory.
- **Proposal-before-mutation** from `identity-graph-operator.md`, applied to SOTB writes. Currently SOTB is written directly after sessions. Instead, Stage 3 proposes SOTB updates → lightweight verification step → commit. Audit trail for memory changes. Prevents a single bad synthesis from silently corrupting institutional memory — the highest-consequence long-run failure mode.
- **Shadow-testing / promotion-gate pattern** from `engineering-autonomous-optimization-architect.md`, applied to the harness's tuner. Don't change a member's model config until N sessions of shadow comparison pass a quality threshold. Makes the tuner less risky than live A/B with real deliberations.

### 6.4 Board-seat gaps this repo surfaces

- **Design seat** — Agentic Board has none. Current product/strategy decisions launder design trade-offs through `product` or `architect`, under-investing in delight and coherence. Minimum viable: a governance-layer "design strategist" (not the implementation-level `design-ui-designer` and *not* the Whimsy Injector). Borrow the information-architecture thinking from `design-ux-architect` and the consistency-enforcement posture from `design-brand-guardian`. Its deliverable is risk flags and trade-off framing, not CSS specs.
- **Finance seat** (eventually) — adapt `finance-fpa-analyst.md`'s rolling-forecast + variance methodology. Minimum viable: "8 rules for financial planning" + scenario template. Defer until the board has at least 2–3 other expansions.
- **Decision-integrator / CEO-counsel** — the gap the ops cluster surfaced. Synthesizes across finance / PM / testing / legal signals into a single trade-off frame. Agentic Board's Chairperson does some of this but under a different framing (synthesis of opinions, not integration of operational signals). Defer until multiple non-technical seats exist.

### 6.5 What Agentic Board should NOT adopt from agency-agents

- **The Aider/Windsurf concatenated-rules distribution model.** 147 personas in one context is a poison pattern at any scale.
- **OpenClaw's section-header-keyword classification.** Too fragile — breaks silently on any non-standard heading.
- **The nexus-spatial-discovery "orchestration" framing.** It is narrative, not runtime. Don't let this repo's honesty problem migrate into Agentic Board's documentation.
- **Persona-first maximalism.** Agency-agents has 147 agents because contribution is low-friction PRs. Agentic Board is a protocol runtime; member count should be driven by deliberation diversity needs, not catalog completeness. A 30-member board would be strictly worse than a 7-member board.

---

## 7. Architecture Verdict: When to Use Which

| Problem | Agency-agents | Agentic Board |
|---|---|---|
| "I want a specific expert's voice inside Cursor right now" | ✅ Native fit | ✗ Overkill |
| "I don't control the infrastructure, just my IDE" | ✅ Zero-runtime = zero friction | ✗ Needs the server |
| "I want to standardize a shared agent vocabulary across my team's tools" | ✅ Canonical `.md` + converter | ✗ Not the target use case |
| "I need synthesized judgment across multiple domains on one decision" | ✗ No synthesis mechanism | ✅ The core use case |
| "I need auditability — session transcripts, memory state, cost tracking" | ✗ Nothing exists | ✅ First-class |
| "I need to prevent prompt contamination between perspectives" | ✗ Concatenated-rules tools actively leak | ✅ Stage 1 isolation, anonymized Stage 2 |
| "I need a Devil's Advocate that sees the same problem the Strategist saw, from a different angle" | ✗ Would need two separate sessions + manual arbitration | ✅ Enforced by the protocol |
| "I'm building a long-running council with institutional memory" | ✗ No state | ✅ SOTB |

The two architectures are complementary, not substitutes. Agentic Board wraps a structured deliberation runtime around a small number of members. Agency-agents publishes a large library of personas with no runtime. Both approaches are legitimate; confusing them is what produces the dishonest parts of agency-agents' marketing (the "8 agents in parallel in 10 minutes" claim).

---

## 8. Appendix — Concrete Defects Found

For the record, issues my sub-agents surfaced that the repo maintainer may want to fix:

1. **`scripts/convert.sh` parallel branch omits `kimi`** from `parallel_tools` array and from the subsequent sequential fallback loop — silent failure in `--parallel` mode.
2. **`scripts/convert.sh` progress counter** is hardcoded (`idx=7` start) and mismatched with the actual tool array length (`n_tools=9`), producing wrong display regardless.
3. **`engineering/engineering-senior-developer.md`** references `ai/system/premium-style-guide.md` and `ai/system/component-library.md` — paths that do not exist in the repo. Leaked private-repo artifact.
4. **`specialized/specialized-workflow-architect.md`** references a "Reality Checker agent" collaboration; Reality Checker lives in `testing/` but is never cross-referenced with workspace path.
5. **OpenClaw converter** classifies `##` headers by substring match against seven hardcoded keywords. Non-standard section names silently fall through to `AGENTS.md`.
6. **Aider / Windsurf concatenation** produces a 70K-token rules file containing all 147 agents. Context contamination at scale is untested and undocumented.
7. **`examples/nexus-spatial-discovery.md`** is framed as "8 agents running in parallel in 10 minutes" but contains no session IDs, timestamps, or execution trace. Section 10 ("Cross-Agent Synthesis") is hand-authored narrative overlay.

---

## 9. Bottom Line

For anyone reading this looking for the one-line takeaway:

**Agency-agents is a persona library with honest value at ~20–30 of its 147 agents and a distribution pipeline that works at present scale but hides architectural dishonesty about orchestration.** Use it as a curated menu, not a shopping list; adopt agents in the governance-first order in §5; ignore the "multi-agent in parallel" framing entirely. For Agentic Board, the canonical-markdown + converter model is cheap to adopt and would meaningfully extend reach; the trust-scorer, handoff-contract, and proposal-before-mutation patterns from the specialized orchestration agents are worth lifting. Everything else is inspiration, not infrastructure.
