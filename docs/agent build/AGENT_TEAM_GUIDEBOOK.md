# Agent Team Guidebook — Building Efficient, Robust Multi-Agent Systems

**Version:** 2.1
**Date:** 2026-02-19
**Purpose:** Guide for designing and coordinating multi-agent teams — when to use them, which patterns to apply, how to manage context across agents, and how to prevent cascading failures. For individual agent design, prompt engineering, and context architecture, see the [Companion Guides](#companion-guides) below. Synthesized from 100+ authoritative sources (2024-2026).

---

## Table of Contents

1. [Philosophy: Why Agent Teams](#1-philosophy-why-agent-teams)
2. [Key Concepts: Teams vs. Swarms vs. Orchestration](#2-key-concepts-teams-vs-swarms-vs-orchestration)
3. [Design Principles](#3-design-principles)
4. [Architecture Patterns](#4-architecture-patterns)
5. [Context Engineering for Agent Teams](#5-context-engineering-for-agent-teams)
6. [Communication and Coordination](#6-communication-and-coordination)
7. [Error Handling and Resilience](#7-error-handling-and-resilience)
8. [Human-in-the-Loop](#8-human-in-the-loop)
9. [Observability and Evaluation](#9-observability-and-evaluation)
10. [Anti-Patterns and Failure Modes](#10-anti-patterns-and-failure-modes)
11. [Framework Landscape (2026)](#11-framework-landscape-2026)
12. [Source Index](#12-source-index)

---

## Companion Guides

This guidebook focuses on **multi-agent team design and coordination**. For deep dives into specific topics, see the companion files in this directory:

| Guide | What It Covers | Reference From |
|-------|---------------|----------------|
| [`Agent_Architecture_Guidebook.md`](./Agent_Architecture_Guidebook.md) | **Single-agent fundamentals** — what defines an agent, the simplicity imperative, workflows vs agents, three pillars (model/tools/instructions), memory architecture, guardrails & safety, evaluation (CLASSIC framework), cost optimization | Sections 3, 4, 7, 9 |
| [`Agent_build_guide.md`](./Agent_build_guide.md) | **Practical agent building** — core design principles, orchestration patterns (manager, handoff, pipeline, concurrent), tool design (categories, naming, limits), security (prompt injection, layered defense), common failures & anti-patterns, operational best practices | Sections 4, 7, 8, 10 |
| [`comprehensive-prompt-framework.md`](./comprehensive-prompt-framework.md) | **Prompt engineering** — universal template (9-section structure), model-specific optimizations (Claude, GPT, Grok), advanced techniques (CoT, ToT, chaining, self-critique), domain-specific patterns, prompt development lifecycle | Section 12 (agent prompts) |
| [`context_engineering_framework.md`](./context_engineering_framework.md) | **Context engineering** — 5-layer context architecture (system → domain → task → instance → interaction), progressive disclosure, semantic chunking, attention guidance, compression, complete code review agent example | Section 5 |

**How to use together:** Start here for team-level decisions (when to use multi-agent, how to coordinate, which patterns to apply). Consult the companion guides when implementing individual agents within the team.

---

## 1. Philosophy: Why Agent Teams

### The Core Thesis

The shift from single agents to multi-agent systems mirrors the shift from individual contributors to engineering teams. Just as no single engineer can efficiently handle all aspects of a complex project, no single AI agent can optimally manage diverse tasks requiring different tools, contexts, and domain knowledge.

**But this analogy has limits.** Unlike human teams, agent teams face unique constraints:
- **Context windows are finite.** Each agent has a hard ceiling on what it can "hold in mind."
- **Coordination has token cost.** Every message between agents consumes budget.
- **Errors compound, not average out.** A wrong output from Agent A becomes corrupted input for Agent B.

The art of agent team design is finding the **minimum viable coordination** that achieves the task — not the maximum possible parallelism.

### The State of the Field (February 2026)

| Metric | Value | Source |
|--------|-------|--------|
| Organizations with agents in production | 57% | LangChain State of Agent Engineering 2025 |
| Large enterprises (10K+) with agents in production | 67% | LangChain |
| Organizations deploying multi-step agent workflows | 57% | Anthropic 2026 Agentic Coding Trends |
| Multi-agent system inquiry growth (Q1 2024 → Q2 2025) | 1,445% | Gartner |
| Predicted agentic AI project cancellations by 2027 | >40% | Gartner |
| Multi-agent LLM system failure rate in production | 41-87% | UC Berkeley MAST Study (arXiv:2503.13657) |
| AI agents market size 2025 → 2030 | $7.8B → $52.6B | Multiple (46.3% CAGR) |

**Key takeaway:** The field is simultaneously exploding in adoption and plagued by high failure rates. The difference between the 57% that succeed and the 43% that fail is **engineering discipline** — the same principles in this guidebook.

### First Principles

These five principles are the foundation. Everything else in this guidebook derives from them.

1. **Start with one agent. Add agents only when the single agent demonstrably fails.** Not every problem needs a fleet. The best design is as simple as possible but no simpler. (Anthropic, OpenAI, Redis, Microsoft all converge on this.)

2. **The orchestrator's job is coordination, not execution.** The lead agent plans, delegates, and synthesizes. It never does the actual work. Mixing coordination and execution in one agent is the #1 architectural mistake.

3. **Context is the scarcest resource.** Treat context windows like memory in systems programming — allocate carefully, free promptly, never assume infinite capacity. (Anthropic: "Context engineering is the discipline of providing the right information in the right format.")

4. **Structured communication beats natural language between agents.** JSON schemas, typed messages, and explicit contracts reduce coordination failures. PwC reported 7x accuracy improvement when switching from prose to structured inter-agent communication.

5. **External artifacts are memory.** Files, databases, git history, progress trackers persist across context windows. Agent context does not. Design systems where the source of truth lives outside any single agent's context.

---

## 2. Key Concepts: Teams vs. Swarms vs. Orchestration

### Agent Team

A **structured group** of specialized agents with predefined roles, coordinated by a lead/orchestrator agent.

- **Control:** Centralized — orchestrator assigns and monitors
- **Roles:** Explicit, predefined (e.g., "Spec Interpreter," "Milestone Planner," "Milestone Reviewer")
- **Communication:** Through orchestrator or defined channels
- **Scale:** 2-10 agents (sweet spot: 3-5 per Anthropic)
- **Best for:** Complex cognitive tasks requiring expertise decomposition
- **Examples:** Claude Agent Teams, CrewAI Crews, AutoGen Group Chat

### Agent Swarm

A **decentralized collection** of interchangeable agents that self-organize based on local information.

- **Control:** Decentralized — agents self-organize
- **Roles:** Emergent or dynamically assigned; agents are often interchangeable
- **Communication:** Direct peer-to-peer, shared signals, or environment markers
- **Scale:** 10-100+ agents (Kimi K2.5 supports up to 100)
- **Best for:** Parallel execution of similar tasks, search, exploration
- **Examples:** Kimi K2.5 Agent Swarm, OpenAI Swarm (experimental)

### Orchestration

The **meta-pattern** for coordinating any multi-agent system — whether team or swarm.

- **Orchestrator types:** LLM-based (dynamic routing) or rule-based (deterministic routing)
- **Key function:** Task decomposition, assignment, progress tracking, result synthesis
- **Patterns:** Hierarchical, hub-and-spoke, pipeline, graph-based

### When to Use What

| Condition | Approach |
|-----------|----------|
| Tasks are diverse, require different tools/expertise | **Agent Team** (specialized roles) |
| Tasks are similar, parallelizable, "read-oriented" | **Agent Swarm** (parallel workers) |
| Tasks are sequential with clear dependencies | **Pipeline** (no team needed) |
| Task is simple, one domain, no tool conflicts | **Single Agent** (no multi-agent needed) |
| Tasks cross security/compliance boundaries | **Agent Team** (isolated contexts) |
| Future growth expected, multiple teams involved | **Agent Team** (extensible architecture) |

**Critical distinction (Redis):** The important question isn't "single vs. multi-agent" — it's whether the task primarily involves **reading** (research, analysis, information gathering) or **writing** (code generation, content creation). Read tasks are better suited for parallelization. Write tasks favor single agents due to coordination problems on shared artifacts.

---

## 3. Design Principles

### Principle 1: Single Responsibility per Agent

Each agent should have one job with clearly defined boundaries. This mirrors the Single Responsibility Principle from software engineering.

**What "one job" means:**
- One domain (spec analysis, milestone planning, submission evaluation — not all three)
- One phase of the pipeline (interpret, plan, review — not all three)
- One set of tools (web search + data parsing, or JSON editing + build verification — not everything)

**Why it matters:** When agents have too many responsibilities, they get confused about which tools to use, which context to prioritize, and when they're "done." Anthropic found that spawning 50 subagents for simple queries was a common early mistake — the fix was fewer agents with clearer roles.

### Principle 2: Detailed Task Specifications as API Contracts

Each agent needs four things clearly defined:
1. **An objective** — what success looks like
2. **An output format** — exactly what to return (JSON schema, markdown template, etc.)
3. **Tool and source guidance** — which tools to use and which to avoid
4. **Clear task boundaries** — what is in scope and what is NOT

**Without these, agents duplicate work, leave gaps, or search endlessly for nonexistent information.** Treat agent specifications like API contracts, not prose documentation. Agents cannot read between lines, infer context, or ask clarifying questions during execution.

### Principle 3: Minimal Viable Coordination

Every coordination mechanism adds cost:
- **Token cost:** Messages between agents consume context
- **Latency cost:** Waiting for other agents to respond
- **Error surface:** Each communication point is a potential failure

**The "4-agent threshold":** Research shows accuracy gains saturate or fluctuate beyond 4 agents without structured topology. Adding a 5th agent often decreases net performance unless the topology is carefully designed.

**Decision framework:**
```
Can one agent do this well?
├── Yes → Use one agent
├── No, but tasks are independent → Parallel agents (no coordination needed)
├── No, tasks have dependencies → Pipeline (sequential handoff)
└── No, tasks require real-time collaboration → Team with orchestrator
```

### Principle 4: Context Isolation

**"Share memory by communicating, don't communicate by sharing memory."** (Manus, borrowing from Go concurrency philosophy)

If every sub-agent shares the same context:
- You pay a massive KV-cache penalty
- The model gets confused with irrelevant details
- One agent's garbage becomes another agent's input

**Instead:** Each agent gets its own clean context window with only what it needs. The orchestrator passes targeted instructions, not full history. Sub-agents return condensed summaries (1,000-2,000 tokens), not raw results.

### Principle 5: External State > Internal Context

Things that should live **outside** agent context windows:
- Progress tracking files
- Task lists with completion status
- Data artifacts (JSON files, spreadsheets)
- Git history and commit logs
- Verification checklists

Things that belong **inside** agent context:
- Current task specification
- Relevant schema definitions
- Tool descriptions
- Immediate results being processed

**Anthropic's C compiler project** demonstrated this at scale: 16 agents, 2,000 sessions, 100,000 lines of code — coordinated entirely through git-based state, lock files, and progress trackers. No shared context windows.

### Principle 6: Fail Loudly, Not Silently

Unlike traditional software where errors trigger immediate exceptions, **failures in one agent can silently corrupt the state of others**, leading to subtle hallucinations rather than obvious failures.

**Required safeguards:**
- Circuit breakers that halt processing when consistency checks fail
- Formal assertion mechanisms where agents state assumptions in structured format
- Independent judge agents evaluating outputs
- Immutable logs of every tool call and decision

---

## 4. Architecture Patterns

> **Companion guides:**
> - For **single-agent patterns** (ReAct, tool selection, model sizing), see [`Agent_Architecture_Guidebook.md`](./Agent_Architecture_Guidebook.md) Part 2.
> - For **practical orchestration patterns** (manager, handoff, pipeline, concurrent) with implementation guidance, see [`Agent_build_guide.md`](./Agent_build_guide.md) Section III.
>
> This section focuses on **multi-agent team patterns** — how to coordinate multiple agents working together.

### Pattern 1: Orchestrator-Worker (Recommended Starting Point)

```
┌─────────────────────┐
│   Master Orchestrator│
│   (Plans, Delegates, │
│    Synthesizes)      │
└──────┬──────┬───────┘
       │      │
  ┌────▼──┐ ┌─▼────┐
  │Worker │ │Worker │  ...
  │Agent A│ │Agent B│
  └───────┘ └──────┘
```

**How it works:** The orchestrator receives the high-level task, decomposes it into subtasks, delegates to specialized workers, collects results, and synthesizes the final output.

**When to use:** Most scenarios. This is the default pattern recommended by Anthropic, OpenAI, Google, and Microsoft.

**Key design rules:**
- The orchestrator NEVER does execution work
- Workers operate independently with no inter-worker communication
- Workers return structured results to the orchestrator
- Use model mixing: Opus/GPT-4 for orchestrator, Sonnet/GPT-4-mini for workers

**Real-world example:** Anthropic's multi-agent research system uses a Lead Researcher (orchestrator) spawning 3-5 SearchAgent and CitationAgent subagents in parallel. The lead never searches directly.

### Pattern 2: Pipeline (Sequential Handoff)

```
Agent A → Agent B → Agent C → Agent D
(Scan)   (Draft)   (Verify)  (Commit)
```

**How it works:** Each agent's output becomes the next agent's input. Linear, deterministic, easy to debug.

**When to use:** When tasks have clear sequential dependencies and each stage requires different expertise.

### Pattern 3: Parallel Fan-Out / Gather

```
        Orchestrator
       / | | | \
      A  B  C  D  E   (parallel)
       \ | | | /
        Synthesizer
```

**How it works:** Multiple agents work simultaneously on independent subtasks. A synthesizer aggregates results.

**When to use:** When subtasks are independent and can be parallelized. Cuts execution time proportionally (Anthropic reports up to 90% faster for complex research queries).

### Pattern 4: Planner-Worker-Judge (Cursor's Production Pattern)

```
┌──────────┐
│ Planner  │ (explores codebase, creates task list)
└────┬─────┘
     │ tasks
┌────▼─────┐
│ Workers  │ (execute tasks independently, push when done)
│ (1..N)   │
└────┬─────┘
     │ results
┌────▼─────┐
│  Judge   │ (evaluates, decides to continue or stop)
└──────────┘
```

**How it works:** Planners continuously explore and create tasks. Workers execute without coordinating with each other. Judges evaluate results and decide whether to continue.

**Why it works:** Cursor tried equal-status agents with locking (agents held locks too long, 20 agents slowed to throughput of 2-3) and optimistic concurrency control (agents became risk-averse). The three-role separation solved both problems.

### Pattern 5: Generator-Critic (Evaluator-Optimizer)

```
┌───────────┐    output    ┌──────────┐
│ Generator │ ──────────▶  │  Critic  │
│  Agent    │ ◀──────────  │  Agent   │
└───────────┘   feedback   └──────────┘
        (iterate until quality threshold)
```

**How it works:** One agent creates content, another evaluates it. They iterate until quality meets a threshold.

**Critical design rule:** Always implement an exit mechanism. Use `max_iterations` for hard limits AND allow early exit when quality thresholds are met. Without limits, agents loop indefinitely.

### Pattern 6: Hierarchical Delegation

```
        Executive Orchestrator
        /                    \
  Domain Lead A          Domain Lead B
  /     |     \          /     |     \
Worker Worker Worker  Worker Worker Worker
```

**How it works:** Multi-level hierarchy. Top-level orchestrator delegates to domain leads, who further delegate to specialists.

**When to use:** Large-scale operations with distinct domains.

### Choosing a Pattern

| Scenario | Recommended Pattern |
|----------|-------------------|
| Single milestone regeneration | Single agent or Pipeline |
| Full project spec → milestones generation | Pipeline (7-stage sequential) |
| Quality-critical output (milestone criteria) | Generator-Critic (Planner → Reviewer) |
| Multi-submission batch evaluation | Orchestrator-Worker with parallel fan-out |
| Independent evaluators (code, doc, video) | Parallel Fan-Out/Gather |

---

## 5. Context Engineering for Agent Teams

> **Companion guide:** For the full context engineering methodology — the 5-layer architecture (system → domain → task → instance → interaction), semantic chunking, attention guidance, compression patterns, and a complete worked example — see [`context_engineering_framework.md`](./context_engineering_framework.md).
>
> This section focuses on **team-specific context challenges** — how to manage context across multiple cooperating agents.

Context engineering is the **#1 engineering discipline** that separates successful agent teams from failures. Anthropic defines it as "the discipline of designing a system that provides the right information and tools, in the right format, to give an LLM everything it needs to accomplish a task."

### Why Context is Harder in Multi-Agent Systems

- **Models get worse as context grows.** LLMs have an "attention budget" — every new token depletes it. (Andrej Karpathy)
- **Cost and latency grow with context.** Time-to-first-token increases with context size.
- **Agents use 4x more tokens than chat; multi-agent systems use 15x more.** (Anthropic)
- **Context pollution compounds across agents.** One agent's verbose output becomes irrelevant noise in the next agent's context — a problem unique to multi-agent systems.

### Five Team-Level Context Strategies

#### Strategy 1: Context Isolation (Agent Boundaries)

Each sub-agent gets its own clean context with ONLY what it needs. This is the team-level equivalent of the "information scoping" principle in the [context engineering framework](./context_engineering_framework.md).

**Bad:** Passing the entire project spec + all milestones + all roles to an agent that only needs to evaluate one milestone's acceptance criteria.
**Good:** Extracting the single milestone with its rubric and the relevant project context, passing only those.

**Anthropic's rule:** Sub-agents return condensed summaries (1,000-2,000 tokens), not full raw results.

#### Strategy 2: Progressive Disclosure Across Pipeline Stages

Show only essential information upfront; reveal details on demand. For the per-agent version of this pattern (within a single prompt), see the [context engineering framework](./context_engineering_framework.md) Principle 1.

**Team-level implementation:**
- Orchestrator passes only the task specification to workers, not the full pipeline state
- Workers request additional context from shared storage only when needed
- Gate agents receive just enough to make go/no-go decisions, not full upstream outputs

#### Strategy 3: External Memory (Pipeline State)

For multi-stage or resumable pipelines, maintain external state files that persist across agent context windows:

```
pipeline_state/
├── pipeline-state.json         # Current pipeline stage + all agent outputs
├── checkpoint-data.json        # Resumable checkpoint for recovery
├── evaluation-cache.json       # Per-project context cache (rubric, project details)
└── clarification-responses.md  # User Q&A for spec clarity resumption
```

**Why:** When starting a fresh context window (after compaction or new session), the agent can quickly understand the state of work by reading progress files, rather than needing the entire conversation history.

#### Strategy 4: Compaction at Handoff Points

When passing results between agents, summarize rather than forwarding raw output. This is the team-level version of the compaction principle.

**At each pipeline stage boundary:**
- **Preserve:** Structured outputs (Pydantic models), key decisions, unresolved issues
- **Discard:** Intermediate reasoning, verbose tool outputs, exploration dead-ends
- **Compress:** Raw LLM responses → validated schema objects

**JetBrains Research finding (NeurIPS 2025):** Simple observation masking (hiding raw environment outputs while preserving action/reasoning history) halves cost while matching the solve rate of LLM summarization.

#### Strategy 5: Shared Artifacts over Shared Context

Instead of passing large results between agents via context, write them to shared storage and pass references:

```
# Bad: Evaluation agent holds full project spec + all submissions in context
# Good: Agent caches project context externally, holds only per-submission summary

evaluation_summary = {
  "submission_id": "sub-12345",
  "quick_scan_bucket": "PASS",
  "confidence": 0.87,
  "deep_dive_triggered": True,
  "scores_file": "evaluation-results/sub-12345.json"
}
```

---

## 6. Communication and Coordination

### Structured Message Format

Agents should communicate via structured formats, NOT natural language prose.

**Between pipeline orchestrator and agent:**
```json
{
  "task_type": "milestone_planning",
  "inputs": {
    "project_spec": "Full project specification text...",
    "spec_understanding": {
      "generated_title": "E-Commerce Platform Redesign",
      "objectives": ["Improve checkout conversion", "Mobile-first responsive design"],
      "assumptions": ["React/TypeScript stack", "3-month timeline"]
    },
    "refined_roles": {
      "identified_roles": [
        {"name": "Frontend Engineer", "seniority": "mid", "core_skills": ["React", "TypeScript", "CSS"]}
      ],
      "skills_tags": ["react", "typescript", "css", "responsive-design"]
    }
  },
  "output_format": {
    "milestones": [{"title": "string", "description": "string", "days_allocated": "int", "acceptance_criteria": ["string"], "evaluation_rubric": {"dimension": "float (weight, must sum to 100)"}}]
  },
  "constraints": {
    "milestone_count": 4,
    "total_days": 90,
    "rubric_weights_sum": 100,
    "temperature": 0.2
  }
}
```

### Coordination Mechanisms

| Mechanism | When to Use | Example |
|-----------|-------------|---------|
| **File-based locking** | Preventing duplicate work | Claude Agent Teams uses lock files in `current_tasks/` |
| **Task list with status** | Tracking what's done/pending | JSON or markdown task tracker |
| **Git-based coordination** | Code/data changes | Each agent works in own worktree, pushes when done |
| **Message passing** | Real-time coordination | Orchestrator sends structured task messages |
| **Shared artifact store** | Passing large results | Write to file, pass reference |

### Communication Anti-Patterns

| Anti-Pattern | Problem | Fix |
|-------------|---------|-----|
| **Natural language between agents** | Ambiguity, misinterpretation | Use JSON schemas |
| **Full context sharing** | Context pollution, cost explosion | Context isolation + summaries |
| **Excessive status updates** | Distract other agents | Update only on completion or failure |
| **Unstructured handoffs** | Lost context, duplicated work | Explicit handoff format with task state |

---

## 7. Error Handling and Resilience

> **Companion guides:**
> - For **per-agent guardrails** (input/output/tool guardrails, layered defense), see [`Agent_Architecture_Guidebook.md`](./Agent_Architecture_Guidebook.md) Part 5.
> - For **security-specific concerns** (prompt injection, data exfiltration, sandboxing), see [`Agent_build_guide.md`](./Agent_build_guide.md) Section V.
>
> This section focuses on **team-level resilience** — how failures propagate between agents and how to prevent cascading failures.

### The Failure Landscape

- **41-87% of multi-agent LLM systems fail in production** (UC Berkeley MAST study)
- **79% of failures originate from specification and coordination issues**, not technical implementation
- **Tool calling fails 3-15% of the time** even in well-engineered systems
- **67.3% of AI-generated PRs get rejected** vs 15.6% for manual code (LinearB)

### Required Resilience Patterns

#### Circuit Breaker

Monitor failure patterns and automatically cut off traffic to unhealthy components.

```
If >40% of requests to [component] fail in 60 seconds:
  → Route to fallback
  → Alert human
  → Retry after 20 minutes
```

**Key distinction:** Retries try to recover from failures. Circuit breakers prevent a bad situation from spiraling.

#### Retry with Exponential Backoff

```
Attempt 1: immediate
Attempt 2: 1s + jitter
Attempt 3: 4s + jitter
Attempt 4: 16s + jitter
Give up → escalate to human
```

**Critical:** Use idempotency keys. Agents can timeout and retry, causing duplicate processing without them.

#### Independent Judge Agent

Add a dedicated agent whose sole job is evaluating other agents' outputs. This agent:
- Never produces content
- Only validates, scores, and flags issues
- Has access to source data for verification
- Can halt the pipeline if quality drops below threshold

#### Cascading Failure Prevention

Hallucinated facts don't stay contained — they become inputs for subsequent decisions.

**Prevention:**
- Validate outputs at each stage, not just the final result
- Implement formal assertion mechanisms where agents state assumptions
- Use Standard Operating Procedures (SOPs) that transform unstructured chat into rigorous workflow
- Circuit breakers between pipeline stages

### Error Handling Decision Tree

```
Error detected
├── Transient (network timeout, rate limit)
│   → Retry with exponential backoff
├── Data quality (broken URL, missing field)
│   → Flag entry, continue with remaining items
├── Agent confusion (wrong tool, off-task)
│   → Restart agent with clearer instructions
├── Cascading failure (corrupted state propagating)
│   → Circuit break, halt pipeline, alert human
└── Unknown error
    → Log full context, escalate to human
```

---

## 8. Human-in-the-Loop

> **Companion guide:** For general human-in-the-loop design (triggers, risk classification, confirmation patterns), see [`Agent_build_guide.md`](./Agent_build_guide.md) Section IX. This section focuses on **where to place human gates within multi-agent pipelines**.

Human-in-the-loop is NOT a fallback — it's a design pattern. The most reliable production systems integrate human oversight at critical decision points.

### When to Require Human Review

| Trigger | Action |
|---------|--------|
| Spec Clarity gate flags unclear spec | Enterprise user answers clarification questions before pipeline resumes |
| Quick Scan bucket = FLAG (borderline) | Enterprise reviewer manually evaluates submission |
| Deep dive confidence below threshold | Human reviews AI evaluation before sharing with applicant |
| Milestone rubric weights seem misaligned | Enterprise user reviews and adjusts before publishing |
| Role identification for novel project domain | Human validates roles match project needs |
| First-time execution of new agent | Human reviews initial outputs |

### Approval Gate Pattern

```
Agent produces output
  → Automated validation (schema, URLs, required fields)
    → Pass? → Queue for human review
    → Fail? → Return to agent with specific errors
      → Human reviews
        → Approve → Commit to main
        → Request changes → Agent revises
        → Reject → Discard, log reason
```

### Best Practices

1. **Only require confirmation for actions with meaningful consequences.** Don't ask humans to approve every scan result.
2. **Provide detailed context** showing exactly what will change, including all arguments and sources.
3. **Implement timeouts** — escalate or auto-reject after reasonable periods.
4. **Record every human decision** with timestamps, reasoning, and outcomes for learning.
5. **Use escalation** — if primary reviewer doesn't respond, notify backup owners.

---

## 9. Observability and Evaluation

> **Companion guides:**
> - For the **CLASSIC evaluation framework** (Cost, Latency, Accuracy, Stability, Security) and per-agent metrics, see [`Agent_Architecture_Guidebook.md`](./Agent_Architecture_Guidebook.md) Part 6.
> - For **operational monitoring** (debugging, logging, error handling), see [`Agent_build_guide.md`](./Agent_build_guide.md) Section VIII-IX.
>
> This section focuses on **team-level observability** — tracing across multiple agents and evaluating the pipeline as a whole.

### Why Observability is Non-Negotiable

- **94% of successful production teams have observability** (LangChain survey)
- **71.5% have full tracing** that inspects individual agent steps and tool calls
- Without visibility into how agents reason and act, debugging is impossible

### What to Observe

| Layer | Metrics |
|-------|---------|
| **Agent decisions** | Which tools used, what order, what was skipped |
| **Token usage** | Per-agent, per-task, per-session token consumption |
| **Latency** | Time per agent, time per tool call, total pipeline time |
| **Error rates** | Per agent, per tool, per data source |
| **Quality scores** | Verification pass rate, human approval rate, rejection reasons |
| **Cost** | API cost per task, per section, per update cycle |

### Evaluation Strategy

**Start small:** Begin with ~20 representative test cases to spot major improvements before building comprehensive evals.

**LLM-as-judge evaluation:** Score outputs (0.0-1.0) on:
- Factual accuracy (do milestones reflect the project spec? do evaluation scores match evidence?)
- Schema compliance (does the JSON match the Pydantic response model?)
- Rubric integrity (do weights sum to 100? do days sum to total?)
- Criteria quality (are acceptance criteria measurable and unambiguous?)
- Completeness (are all required fields present? are all roles covered by milestones?)

**Human evaluation remains essential.** Catches edge cases like SEO-optimized content farms being cited over authoritative sources.

### Cost Monitoring

Multi-agent systems consume 15x more tokens than standard chat. Set:
- **Per-task budget caps** (e.g., max $5 per weekly news scan)
- **Per-session limits** (e.g., max 200K tokens per agent session)
- **Automated alerts** when costs exceed thresholds
- **Hard limits** that kill runaway agents

---

## 10. Anti-Patterns and Failure Modes

> **Companion guide:** For **single-agent anti-patterns** (excessive autonomy, hallucinations without verification, context overload, vague goals), see [`Agent_build_guide.md`](./Agent_build_guide.md) Section VI. This section focuses on **multi-agent-specific failure modes** — problems that only emerge when agents interact.

### The "Bag of Agents" Problem (17x Error Trap)

Simply throwing multiple agents at a problem without structured coordination creates **17x error amplification** (DeepMind's Science of Scaling research). Without structural constraints, unstructured systems scale noise rather than capability.

**Fix:** Implement a Centralized Control Plane (Orchestrator) that acts as a single point of verification between every agent interaction.

### The Seven Deadly Anti-Patterns

| Anti-Pattern | What Goes Wrong | Fix |
|-------------|-----------------|-----|
| **Kitchen-sink agent** | One agent with 20 tools and 10 responsibilities | Split into specialists with 3-5 tools each |
| **Natural language handoffs** | Ambiguity, lost context, misinterpretation | JSON schemas, typed messages, explicit contracts |
| **Shared context soup** | All agents share one giant context; pollution, confusion | Context isolation; each agent gets only what it needs |
| **No exit conditions** | Generator-Critic loops iterate forever | `max_iterations` + quality threshold exit |
| **Silent failures** | Agent errors corrupt downstream agents quietly | Circuit breakers, formal assertions, independent judges |
| **Premature multi-agent** | Using 5 agents for a task one agent handles fine | Start with 1 agent; add only when measured outcomes improve |
| **Vague delegation** | "Research this topic" without output format or scope | Treat specs as API contracts: objective, format, tools, boundaries |

### Warning Signs of Agent Team Dysfunction

| Symptom | Likely Cause |
|---------|-------------|
| Agents doing duplicate work | Vague task boundaries, no ownership model |
| Token costs spiraling | Context pollution, excessive inter-agent chatter |
| Quality dropping with more agents | "Bag of agents" — no structured topology |
| One agent always slow | Overloaded with too many responsibilities |
| Random, hard-to-reproduce failures | Silent error propagation between agents |
| Human reviewers rejecting most output | Inadequate verification stage, no judge agent |

---

## 11. Framework Landscape (2026)

### Major Frameworks

| Framework | Org | Architecture | Agents | Production Ready | Language |
|-----------|-----|-------------|--------|-----------------|----------|
| **Claude Agent Teams** | Anthropic | Team Lead + Teammates | 2-16 | Experimental | TypeScript |
| **OpenAI Agents SDK** | OpenAI | Handoffs + Guardrails | N/A | Yes | Python, TS |
| **Microsoft Agent Framework** | Microsoft | Graph workflows + Events | N/A | GA Q1 2026 | Python, .NET |
| **CrewAI** | CrewAI Inc | Role-based Crews/Flows | N/A | Yes + Enterprise | Python |
| **Google ADK** | Google | 8 composable patterns | N/A | Yes | Python, TS |
| **LangGraph** | LangChain | Graph state machines | N/A | Yes | Python, JS |
| **Kimi K2.5** | Moonshot AI | Self-directed swarm | Up to 100 | Yes | API |
| **Strands Agents** | AWS | Model-driven autonomous | N/A | Yes (v1.0) | Python |

### Interoperability Protocols

| Protocol | Layer | Function |
|----------|-------|----------|
| **MCP** (Model Context Protocol) | Capability access | How agents connect to tools and data sources |
| **A2A** (Agent-to-Agent Protocol) | Collaboration | How agents communicate with each other |
| **ACP** (Agent Communication Protocol) | Messaging | REST-native multi-part messaging |
| **ANP** (Agent Network Protocol) | Global discovery | Decentralized agent marketplaces |

**MCP + A2A are complementary and converging** — both under Linux Foundation governance as of 2025. MCP handles tool integration; A2A handles agent-to-agent communication.

### Landmark Case Studies

| Project | Scale | Result |
|---------|-------|--------|
| **Anthropic C Compiler** | 16 Claude agents, 2,000 sessions, $20K | 100K-line Rust compiler, compiles Linux kernel, 99% test pass |
| **Rakuten** | Claude Code on 12.5M-line codebase | 7 hours autonomous work, 99.9% numerical accuracy |
| **TELUS** | Multi-agent AI solutions | 13,000+ solutions, 30% faster engineering |
| **Kimi K2.5 Benchmark** | 100 sub-agents, 1,500 tool calls | HLE score 50.2% (surpassing GPT-5.2) |

## 12. Source Index

### Primary Engineering Sources

| Source | URL | Key Contribution |
|--------|-----|-----------------|
| Anthropic — Building Effective Agents | https://www.anthropic.com/research/building-effective-agents | Foundational agent design patterns |
| Anthropic — Multi-Agent Research System | https://www.anthropic.com/engineering/multi-agent-research-system | Production multi-agent architecture |
| Anthropic — Context Engineering for Agents | https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents | Context management discipline |
| Anthropic — Harnesses for Long-Running Agents | https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents | Progress files, multi-session patterns |
| Anthropic — Building a C Compiler | https://www.anthropic.com/engineering/building-c-compiler | 16-agent parallel collaboration at scale |
| Anthropic — 2026 Agentic Coding Trends | https://resources.anthropic.com/2026-agentic-coding-trends-report | Industry trends, statistics |
| OpenAI — Agents SDK | https://openai.github.io/openai-agents-python/ | Handoffs, guardrails, tracing |
| OpenAI — Practical Guide to Building Agents | https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf | 34-page production guide |
| Google — Multi-Agent Patterns in ADK | https://developers.googleblog.com/developers-guide-to-multi-agent-patterns-in-adk/ | 8 essential design patterns |
| Microsoft — AI Agent Orchestration Patterns | https://learn.microsoft.com/en-us/azure/architecture/ai-ml/guide/ai-agent-design-patterns | Enterprise patterns |
| AWS — Evaluating AI Agents at Amazon | https://aws.amazon.com/blogs/machine-learning/evaluating-ai-agents-real-world-lessons-from-building-agentic-systems-at-amazon/ | Production lessons from thousands of agents |
| LangChain — State of Agent Engineering 2025 | https://www.langchain.com/state-of-agent-engineering | Survey data from 1,340 respondents |
| Lance Martin — Agent Design Patterns | https://rlancemartin.github.io/2026/01/09/agent_design/ | Practitioner patterns |

### Framework Documentation

| Framework | URL |
|-----------|-----|
| Claude Agent Teams | https://code.claude.com/docs/en/agent-teams |
| Claude Agent SDK — Subagents | https://platform.claude.com/docs/en/agent-sdk/subagents |
| OpenAI Swarm (experimental) | https://github.com/openai/swarm |
| CrewAI Agents | https://docs.crewai.com/en/concepts/agents |
| CrewAI Memory | https://docs.crewai.com/en/concepts/memory |
| LangGraph Multi-Agent | https://docs.langchain.com/oss/python/langchain/multi-agent |
| AutoGen v0.4 | https://www.microsoft.com/en-us/research/blog/autogen-v0-4-reimagining-the-foundation-of-agentic-ai-for-scale-extensibility-and-robustness/ |
| Microsoft Agent Framework | https://learn.microsoft.com/en-us/agent-framework/overview/agent-framework-overview |
| Google ADK | https://google.github.io/adk-docs/ |
| Kimi K2.5 Agent Swarm | https://www.kimi.com/blog/agent-swarm.html |
| Strands Agents (AWS) | https://strandsagents.com/latest/ |

### Academic Papers

| Paper | Citation | Key Finding |
|-------|----------|-------------|
| Why Do Multi-Agent LLM Systems Fail? | arXiv:2503.13657 (NeurIPS 2025) | 14 failure modes, 79% from specification issues |
| Multi-Agent Collaboration Mechanisms | arXiv:2501.06322 | Taxonomy: cooperation, competition, coopetition |
| Survey of Agent Interoperability Protocols | arXiv:2505.02279 | MCP, ACP, A2A, ANP comparison |
| The Complexity Trap | arXiv:2508.21433 (NeurIPS 2025) | Observation masking matches LLM summarization at half cost |
| MultiAgentBench | arXiv:2503.01935 | Graph structure performs best among coordination protocols |
| Beyond the Strongest LLM | arXiv:2509.23537 | Orchestration rivals strongest single LLM |
| LLMDR: Deadlock Detection | arXiv:2503.00717 | LLM-driven deadlock resolution in multi-agent systems |
| Blackboard Architecture for LLM Agents | arXiv:2507.01701 | 13-57% improvement over baselines |

### Failure Analysis and Anti-Patterns

| Source | URL | Key Insight |
|--------|-----|-------------|
| 17x Error Trap | https://towardsdatascience.com/why-your-multi-agent-system-is-failing-escaping-the-17x-error-trap-of-the-bag-of-agents/ | Functional planes architecture |
| 7 Agent Failure Modes (Galileo) | https://galileo.ai/blog/agent-failure-modes-guide | Ambiguity, memory corruption, cascading failures |
| Multi-Agent Reliability (Getmaxim) | https://www.getmaxim.ai/articles/multi-agent-system-reliability-failure-patterns-root-causes-and-production-validation-strategies/ | Root causes and validation strategies |
| Cascading Failures OWASP (Adversa) | https://adversa.ai/blog/cascading-failures-in-agentic-ai-complete-owasp-asi08-security-guide-2026/ | Security guide for cascading failures |
| Gartner — 40% Failure Prediction | https://www.gartner.com/en/newsroom/press-releases/2025-06-25-gartner-predicts-over-40-percent-of-agentic-ai-projects-will-be-canceled-by-end-of-2027 | Cost, value, risk factors |
| Failover Design (Salesforce) | https://www.salesforce.com/blog/failover-design/ | Provider-level failover architecture |
| Guardrails for Agentic Orchestration (Camunda) | https://camunda.com/blog/2026/01/guardrails-and-best-practices-for-agentic-orchestration/ | Production guardrails |
| AI Coding Agents 2026 (Mike Mason) | https://mikemason.ca/writing/ai-coding-agents-jan-2026/ | Coherence through orchestration |

---

## Appendix: Quick Reference Card

### Before Building an Agent Team

```
[ ] Can a single agent do this? (If yes, don't build a team — see Agent_Architecture_Guidebook.md)
[ ] Are tasks independent? (If yes, use parallel workers, not coordination)
[ ] Is the task read-oriented or write-oriented?
[ ] Have you defined each agent's objective, output format, tools, and boundaries?
[ ] Have you written each agent's prompt using the template in comprehensive-prompt-framework.md?
[ ] Have you layered each agent's context per context_engineering_framework.md?
[ ] Have you set token budgets and cost limits?
[ ] Do you have observability in place?
```

### Agent Specification Template

> For the **prompt template** to use when writing the agent's actual system prompt, see [`comprehensive-prompt-framework.md`](./comprehensive-prompt-framework.md) Section II (Master Template Structure). For **context layering** within the prompt, see [`context_engineering_framework.md`](./context_engineering_framework.md).

```markdown
## Agent: {pipeline}:{agent-name}

### Purpose
[One sentence describing what this agent does]

### Inputs
- Task type: [spec_interpretation | milestone_planning | quick_scan | code_evaluation | ...]
- Required data: [project spec, prior agent outputs, submission content, etc.]
- Constraints: [temperature, max_tokens, timeout, output schema]

### Output Format
[Pydantic schema name and key fields]

### LLM Configuration
- Temperature: [0.1-0.7]
- Max tokens: [1500-3000]
- Requires reasoning: [yes/no]
- Cost class: [economy | standard | reasoning]

### Does NOT Do
- [Explicit list of things outside scope]

### Quality Checks
- [What must pass before output is accepted]
- [Schema validation, constraint compliance, etc.]

### Cost Budget
- Max tokens per call: [number]
- Timeout: [seconds]
- Max retries: [number]
```

### The Five Rules of Agent Teams

1. **One agent, one job.** No exceptions.
2. **Structured communication.** JSON, not prose.
3. **Isolate context.** Each agent gets only what it needs.
4. **State lives outside.** Files, git, databases — not context windows.
5. **Fail loudly.** Circuit breakers, assertions, judges.
