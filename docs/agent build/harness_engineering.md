# The Harness Engineering Playbook

## A Comprehensive Guide to Designing Reliable Systems Around AI Agents

*Synthesized from OpenAI, Anthropic, LangChain, Thoughtworks (Martin Fowler), HumanLayer, Mitchell Hashimoto, and the Latent Space interview with Ryan Lopopolo — April 2026*

---

## Part I: Philosophy — Why Harness Engineering Exists

### The Core Insight

The strongest AI model in the world will still fail on real engineering tasks if you don't build a proper environment around it. This isn't a model problem — it's a harness problem.

The term "harness engineering" was coined by Mitchell Hashimoto (co-founder of HashiCorp) in February 2026 and crystallized days later when OpenAI published their landmark report on building a million-line codebase with zero human-written code. The core definition:

> **Anytime you find an agent makes a mistake, you take the time to engineer a solution such that the agent never makes that mistake again.**

The metaphor is deliberate and borrowed from equestrian equipment. A horse is powerful but unpredictable without reins, saddle, and bridle to channel its energy. The AI model is the horse. The harness is everything that directs its power productively. The engineer is the rider providing direction.

### The Canonical Formula

**Agent = Model + Harness**

If you're not the model, you're the harness. The harness is every piece of code, configuration, and execution logic that isn't the model itself. A raw model is not an agent. It becomes one when a harness gives it state, tool execution, feedback loops, and enforceable constraints.

### Three Concentric Levels of Engineering

Understanding harness engineering requires distinguishing it from its predecessors:

1. **Prompt Engineering** — *What to ask*. Crafting the text input to get the best single-turn response. This is still valuable, but it has a ceiling.

2. **Context Engineering** — *What to send*. Managing what the model sees and when — curating the context window as a working memory budget rather than a dumping ground. Context engineering lives *inside* harness engineering.

3. **Harness Engineering** — *How the whole system operates*. Not just the words in the prompt, not just the tokens in context, but the complete environment: tools, permissions, state, tests, logs, retries, checkpoints, guardrails, reviews, and evals that prevent drift into nonsense.

### The Evidence Is Overwhelming

The case for harness engineering is backed by hard numbers:

- **OpenAI's Codex Experiment**: A team built and shipped an internal beta product with zero manually-written code over five months — roughly 1 million lines across ~1,500 pull requests. They estimated 10x speed compared to manual coding. Early progress was slower than expected not because the model was incapable, but because the environment was underspecified.

- **Anthropic's Controlled Experiment**: Same model (Claude Opus 4.5), same prompt ("build a 2D retro game editor"). Without a harness, it spent $9 in 20 minutes and produced something that didn't work. With a full harness (planner + generator + evaluator), it spent $200 in 6 hours and built a game you could actually play.

- **LangChain's DeepAgent**: By changing *only* the harness and keeping the model fixed (GPT-5.2-Codex), their coding agent jumped from 52.8% to 66.5% on Terminal Bench 2.0 — moving from outside the Top 30 to Top 5.

- **Can.ac's Hashline Experiment**: Merely changing the harness's tool format (edit method) improved coding benchmark scores by up to 10x across 16 models. One model went from 6.7% to 68.3% without changing any model weights.

Same model. Different harness. Dramatically different results.

### The Fundamental Paradigm Shift

Traditional engineering: **Human writes code → Machine executes code**

Harness engineering: **Human designs constraints → Agent writes code → Machine executes code**

The engineer's output shifts from *code* to a *constraint system* — AGENTS.md files, architectural rules, custom linters, verification scripts, and feedback loops. Code itself becomes disposable output.

---

## Part II: Core Principles

### Principle 1: Design the Environment, Don't Write the Code

When something fails, the fix is almost never "try harder." The right question is always: *"What capability is missing, and how do I make it both legible and enforceable for the agent?"*

OpenAI's team found that every failed task pointed to an environmental gap — missing tools, missing abstractions, missing feedback loops. They stopped fixing agent output and started fixing the conditions that produced bad output.

### Principle 2: The Repository Is the Single Source of Truth

From the agent's perspective, anything it can't access in-context while running effectively doesn't exist. Knowledge that lives in Google Docs, Slack threads, or people's heads is invisible to the system. Repository-local, versioned artifacts (code, markdown, schemas, executable plans) are all the agent can see.

That Slack discussion aligning the team on an architectural pattern? If it isn't discoverable to the agent, it's as unknown as it would be to a new hire joining three months later.

### Principle 3: Enforce Mechanically, Not Rhetorically

Instead of telling the agent "write good code," you mechanically enforce what good code looks like. Writing "CRITICAL: always do XYZ" in a system prompt is not harness engineering. Building a linter that fails the build when XYZ is violated — that's harness engineering.

In human-first workflows, strict linting rules feel pedantic. With agents, they become multipliers — once encoded, they apply everywhere at once, preventing drift across a million-line codebase.

### Principle 4: Progressive Disclosure Over Information Dumping

Give the agent a map, not a 1,000-page instruction manual. OpenAI tried the "one big AGENTS.md" approach. It failed because:

- Context is a scarce resource — a giant file crowds out the task, the code, and relevant docs
- When everything is "important," nothing is — agents pattern-match locally instead of navigating intentionally
- Monolithic manuals rot instantly — agents can't tell what's still true
- Verification becomes impossible

The solution: cascading AGENTS.md files scoped to directories, with a short map at the top level and deeper information pulled in only when needed.

### Principle 5: Every Harness Component Encodes an Assumption That Will Expire

This is Anthropic's key insight: every component in a harness exists because the model can't do something on its own. Those assumptions are worth stress-testing because they may be incorrect, and because they go stale as models improve.

When Anthropic used the same harness designed for Claude Sonnet 4.5 on Claude Opus 4.5, behaviors they had built workarounds for (like "context anxiety" — premature task completion near context limits) simply didn't exist anymore. The best harnesses are designed knowing their components will eventually become unnecessary.

Build with the goal of simplification: *Find the simplest solution possible, and only increase complexity when needed.*

### Principle 6: Humans on the Loop, Not in the Loop

The harness engineer's job is not to inspect individual outputs, but to design and maintain agent environments. Place human judgment at high-leverage decision points where the cost of a mistake is highest, not on every commit.

Over time, push review effort toward being handled agent-to-agent. Human QA becomes the bottleneck at high throughput — delegate by equipping agents with QA capabilities.

### Principle 7: Treat Entropy as a First-Class Problem

Agent-generated code accumulates cruft differently than human-written code. Technical debt compounds faster because agents generate more code faster. Run periodic "garbage collection" — background agents that scan for deviations from golden principles, update quality grades, and open targeted refactoring pull requests.

Human taste is captured once, then enforced continuously on every line of code.

---

## Part III: The Anatomy of an Agent Harness

Synthesizing across OpenAI, Anthropic, LangChain, and the broader practitioner community, a production agent harness has the following core components:

### Component 1: The Agent Loop (Runtime)

The heartbeat of the system. It implements the Thought-Action-Observation (TAO) cycle:

1. Assemble prompt
2. Call LLM
3. Parse output
4. Execute any tool calls
5. Feed results back
6. Repeat until done

Mechanically, it's a `while` loop. The complexity lives in everything the loop manages, not the loop itself. Anthropic describes their runtime as a "dumb loop" where all intelligence lives in the model.

**Design decision**: Keep the loop simple. Push intelligence into the model and structure into everything the loop connects to.

### Component 2: Context Assembly (The Working Memory Manager)

This assembles what the model actually sees at each step. It's hierarchical:

1. System prompt (highest priority)
2. Tool definitions
3. Developer instructions (cascading AGENTS.md files)
4. Memory files (progress logs, feature lists)
5. Conversation history
6. Current user message / task

**The critical rule**: Context is a precious, scarce resource. The goal is the *smallest possible set of high-signal tokens* that maximize likelihood of the desired outcome.

**Context rot** is a serious problem — models become worse at reasoning as their context window fills up. Strategies include:

- **Compaction**: Intelligently summarize existing context when approaching limits
- **Tool call offloading**: Reduce impact of large tool outputs that clutter the context window
- **Sub-agent isolation**: Use sub-agents as "context firewalls" that return only results, keeping intermediate noise out of the parent thread

### Component 3: Tool Orchestration

An agent's capability is defined by the tools it can access. Tool orchestration means defining:

- Which tools are available
- How they are invoked
- What permissions they require
- What error surfaces look like

This includes file system access, shell commands, API calls, database queries, browser automation, and external service integrations via MCP (Model Context Protocol).

**Key design principle**: Tool design is agent UX. Good naming, clear schemas, and helpful error messages are more important for agents than they are for human developers.

### Component 4: Planning & Task Decomposition

Complex projects need to be broken into subtasks with planning and verification at each step. Approaches include:

- **Feature lists**: JSON-formatted lists of specific, testable requirements that expand on a high-level prompt into hundreds of discrete items
- **Sprint contracts**: Defined scopes of work that agents commit to completing
- **Initializer agents**: Separate prompts for the very first context window that set up the environment

OpenAI's approach: Work depth-first, breaking larger goals into smaller building blocks, prompting the agent to construct those blocks, and using them to unlock more complex tasks.

### Component 5: Verification & Feedback Loops

The harness must verify that the agent did the work correctly. This includes:

- **Automated testing**: Unit tests, integration tests, end-to-end tests
- **Linting & structural tests**: Enforce architectural boundaries mechanically
- **Browser automation**: Puppeteer/Playwright for visual verification
- **Agent self-review**: Instruct agents to review their own changes
- **Agent-to-agent review**: Have separate agents critique work
- **Pre-completion checklists**: Intercept the agent before it exits and force a verification pass

**The Ralph Wiggum Loop**: A harness mechanism that intercepts the model's attempt to exit. It reinjects the original prompt in a clean context window, forcing the agent to continue working against a completion goal using persisted state. Named after the pattern of repeatedly restarting agents until work is truly done.

### Component 6: Memory & State Persistence

Agents have no memory between sessions. The harness must bridge this gap:

- **`claude-progress.txt`** / progress files: Session-to-session logs of completed work
- **Feature list files (JSON)**: Structured tracking of what's done and what isn't. JSON is better than Markdown because agents are less likely to improperly edit structured data.
- **Git commits**: Each coherent unit of work committed as a checkpoint
- **`init.sh` scripts**: Define how to start the development server and run the application
- **Filesystem as memory**: Files serve as durable cross-session state

### Component 7: Architectural Constraints

Mechanical enforcement of code quality and structure:

- **Dependency layering**: e.g., `Types → Config → Repo → Service → Runtime → UI` where each layer can only import from layers to its left
- **Custom linters**: Codified rules that fail the build on violations
- **Structural tests**: Validate modular boundaries
- **Import restrictions**: Prevent cross-layer dependencies
- **Shared utility packages**: Prefer centralized invariants over hand-rolled helpers

### Component 8: Observability & Telemetry

You cannot improve what you cannot see. This means:

- Logging every agent action
- Tracking token usage and costs
- Recording decision points
- Surfacing anomalies
- Tracing which tools were used and why
- Measuring how many attempts it took to pass the test suite

Give agents access to observability tools — logs, metrics, traces, LogQL/PromQL — so they can self-diagnose and fix issues autonomously.

### Component 9: Safety & Sandboxing

Isolation and protection:

- **Sandboxed execution environments**: Same as human dev environments but isolated from production and the internet
- **Permission systems**: Structured authorization rather than natural-language permission text
- **Approval gates**: Explicit human approval for destructive operations
- **Credential isolation**: Auth tokens stored in secure vaults, never exposed to the agent's sandbox
- **Defense-in-depth**: Multiple layers of safety rather than single points of control

### Component 10: Sub-Agent Architecture

Sub-agents are not "frontend engineer" and "backend engineer" personas. That approach doesn't work. What works is using sub-agents for **context control**:

- Each sub-agent encapsulates an entire session's worth of work
- The dispatching agent only sees the prompt it writes and the sub-agent's final result
- None of the intermediate tool calls or messages pollute the parent thread
- This keeps the primary agent in the "smart zone" by preventing context rot

Effective multi-agent patterns:
- **Planner → Generator → Evaluator**: Inspired by GANs, separating the agent doing the work from the agent judging it
- **Initializer Agent + Coding Agent**: Different prompts for first vs. subsequent sessions
- **Garbage Collection Agents**: Periodic sweeps for entropy and drift

### Component 11: Skills & Progressive Disclosure

Skills are modular instruction sets that provide specialized knowledge on demand:

- Small, focused files scoped to specific tasks or domains
- Loaded into context only when relevant
- Prevent context bloat from unnecessary instructions
- Can be community-shared or repo-specific

**Warning**: Skill registries have been caught distributing malicious skills. Treat skills like `npm install random-package` — read what you're installing.

---

## Part IV: Implementation Playbook

### Phase 0: Foundation Setup

**Step 1: Initialize Repository Structure**

Create a well-organized repository optimized for agent legibility:

```
project/
├── AGENTS.md                    # Top-level map (short, links to deeper docs)
├── docs/
│   ├── architecture.md          # System design, dependency rules
│   ├── conventions.md           # Coding standards, naming conventions
│   └── plans/                   # Execution plans, feature specs
├── skills/                      # Progressive disclosure modules
│   ├── testing/SKILL.md
│   ├── deployment/SKILL.md
│   └── database/SKILL.md
├── scripts/
│   ├── init.sh                  # Environment setup
│   ├── verify.sh                # Automated verification
│   └── lint-custom/             # Custom linters
├── src/                         # Application code (layered architecture)
├── tests/                       # Test suites
├── feature-list.json            # Structured feature tracking
├── claude-progress.txt          # Cross-session state
└── .github/
    └── workflows/               # CI/CD with agent-friendly checks
```

**Step 2: Write the Root AGENTS.md**

Keep it short — a map, not a manual:

```markdown
# AGENTS.md

## Project Overview
[2-3 sentence description of what this project is]

## Architecture
This project uses a strict layered architecture:
Types → Config → Repo → Service → Runtime → UI
Each layer may only import from layers to its left.
See: docs/architecture.md

## Key Conventions
- All API endpoints follow REST conventions defined in docs/conventions.md
- Tests are required for all new features
- Run `./scripts/verify.sh` before marking any task complete

## Directory Guide
- `src/types/` — Shared type definitions
- `src/config/` — Configuration management
- `src/service/` — Business logic
- `src/ui/` — Frontend components
- `skills/` — Detailed guidance for specific tasks (read on demand)

## Current State
See `feature-list.json` for what's done and what's pending.
See `claude-progress.txt` for recent session history.
```

**Step 3: Create the Feature List (JSON)**

```json
{
  "project": "MyApp",
  "features": [
    {
      "id": "F001",
      "name": "User Authentication",
      "status": "complete",
      "subtasks": [
        {"id": "F001.1", "name": "Login form", "status": "complete"},
        {"id": "F001.2", "name": "JWT token management", "status": "complete"},
        {"id": "F001.3", "name": "Password reset flow", "status": "in_progress"}
      ]
    },
    {
      "id": "F002",
      "name": "Dashboard",
      "status": "pending",
      "subtasks": [
        {"id": "F002.1", "name": "Layout skeleton", "status": "pending"},
        {"id": "F002.2", "name": "Data visualization widgets", "status": "pending"}
      ]
    }
  ]
}
```

Use JSON, not Markdown. Agents are less likely to improperly edit or overwrite structured data.

**Step 4: Create init.sh**

```bash
#!/bin/bash
# init.sh — Environment setup for agent sessions
set -euo pipefail

echo "Installing dependencies..."
npm install

echo "Starting development server..."
npm run dev &
DEV_PID=$!

echo "Running initial health check..."
sleep 5
curl -sf http://localhost:3000/health || {
  echo "FAIL: Dev server not responding"
  kill $DEV_PID
  exit 1
}

echo "Environment ready. Dev server PID: $DEV_PID"
```

### Phase 1: Architectural Constraints

**Step 5: Enforce Dependency Layers Mechanically**

Create custom lint rules that fail on import violations:

```javascript
// scripts/lint-custom/check-imports.js
const LAYER_ORDER = ['types', 'config', 'repo', 'service', 'runtime', 'ui'];

function checkImport(sourceLayer, targetLayer) {
  const sourceIdx = LAYER_ORDER.indexOf(sourceLayer);
  const targetIdx = LAYER_ORDER.indexOf(targetLayer);
  if (targetIdx >= sourceIdx) {
    throw new Error(
      `Architectural violation: ${sourceLayer} cannot import from ${targetLayer}. ` +
      `Allowed: ${LAYER_ORDER.slice(0, sourceIdx).join(', ')}`
    );
  }
}
```

**Step 6: Structural Tests**

Write tests that validate architecture, not just behavior:

```javascript
// tests/structural/architecture.test.js
describe('Architectural Boundaries', () => {
  test('UI layer does not import from repo layer directly', () => {
    const uiFiles = getAllFiles('src/ui/');
    for (const file of uiFiles) {
      const imports = extractImports(file);
      const repoImports = imports.filter(i => i.includes('/repo/'));
      expect(repoImports).toEqual([]);
    }
  });

  test('All API endpoints have corresponding test files', () => {
    const endpoints = getAllFiles('src/service/routes/');
    for (const endpoint of endpoints) {
      const testFile = endpoint.replace('src/', 'tests/').replace('.ts', '.test.ts');
      expect(fileExists(testFile)).toBe(true);
    }
  });
});
```

### Phase 2: Verification Loops

**Step 7: Build a Verification Script**

```bash
#!/bin/bash
# scripts/verify.sh — Run before marking any task complete
set -euo pipefail

echo "=== Step 1: Lint Check ==="
npm run lint || { echo "FAIL: Lint errors found"; exit 1; }

echo "=== Step 2: Type Check ==="
npx tsc --noEmit || { echo "FAIL: Type errors found"; exit 1; }

echo "=== Step 3: Structural Tests ==="
npx jest tests/structural/ || { echo "FAIL: Structural violations"; exit 1; }

echo "=== Step 4: Unit Tests ==="
npx jest tests/unit/ || { echo "FAIL: Unit test failures"; exit 1; }

echo "=== Step 5: Integration Tests ==="
npx jest tests/integration/ || { echo "FAIL: Integration test failures"; exit 1; }

echo "=== Step 6: Custom Architecture Check ==="
node scripts/lint-custom/check-imports.js || { echo "FAIL: Import violations"; exit 1; }

echo "=== ALL CHECKS PASSED ==="
```

**Step 8: Browser-Based Verification**

For frontend work, use Puppeteer or Playwright to let agents visually verify their own work:

```javascript
// scripts/visual-check.js
const puppeteer = require('puppeteer');

async function verifyPage(url, checks) {
  const browser = await puppeteer.launch();
  const page = await browser.newPage();
  await page.goto(url, { waitUntil: 'networkidle2' });

  for (const check of checks) {
    const element = await page.$(check.selector);
    if (!element) {
      console.error(`FAIL: Element not found: ${check.selector}`);
      process.exit(1);
    }
    if (check.text) {
      const text = await page.evaluate(el => el.textContent, element);
      if (!text.includes(check.text)) {
        console.error(`FAIL: Expected "${check.text}" in ${check.selector}`);
        process.exit(1);
      }
    }
  }
  
  await browser.close();
  console.log('Visual verification passed');
}
```

### Phase 3: Long-Running Agent Sessions

**Step 9: Implement the Initializer/Coding Agent Pattern**

For the first session (Initializer Agent), use a specialized prompt:

```markdown
You are an initializer agent. Your job is to set up the project environment
for future coding sessions. You must:

1. Read the user's project description
2. Create a comprehensive feature-list.json expanding the description
   into hundreds of specific, testable requirements
3. Set up the repository structure following AGENTS.md conventions
4. Create init.sh for environment setup
5. Make an initial git commit establishing the baseline
6. Create claude-progress.txt documenting what was set up

Do NOT attempt to implement features. Your only job is preparation.
```

For subsequent sessions (Coding Agent):

```markdown
You are a coding agent. Before starting work:

1. Read claude-progress.txt to understand what's been done
2. Read feature-list.json to find the next pending feature
3. Run git log --oneline -20 to see recent history
4. Run init.sh to set up the environment

Then implement the next pending feature. When done:
1. Run ./scripts/verify.sh — do not proceed if it fails
2. Update feature-list.json to mark the feature complete
3. Update claude-progress.txt with what you accomplished
4. Make a clean git commit
```

**Step 10: Cross-Session State Handoff**

The progress file is the "shift handoff" between agents:

```markdown
# claude-progress.txt

## Session 7 — 2026-04-14

### Completed
- F001.3: Password reset flow (email sending + token validation)
- Fixed: Login redirect was broken due to missing auth middleware

### Current State
- Dev server runs on localhost:3000
- All 47 tests passing
- Feature-list: 12/30 features complete

### Known Issues
- Email templates render differently in Outlook (tracked in F001.3 notes)
- Database migration for F002 not yet created

### Next Steps
- F002.1: Dashboard layout skeleton
- Need to create migration for dashboard_widgets table first
```

### Phase 4: Entropy Management

**Step 11: Automated Garbage Collection**

Run periodic background agents that scan for problems:

```markdown
You are a quality assurance agent. Scan the entire codebase for:

1. Architectural violations (imports crossing layer boundaries)
2. Dead code and unused imports
3. Inconsistencies between code and documentation
4. Tests that aren't testing anything meaningful
5. Duplicated logic that should be centralized
6. Deviations from conventions defined in AGENTS.md

For each issue found:
- Rate severity (critical/warning/info)
- Create a targeted fix
- Open a pull request with a clear description
- These PRs should be reviewable in under one minute
```

Schedule this on a regular cadence — daily or per-N-commits.

**Step 12: Documentation Freshness**

```bash
# scripts/check-docs-freshness.sh
# Flag docs that haven't been updated relative to code changes

for doc in docs/*.md; do
  doc_modified=$(git log -1 --format="%at" -- "$doc")
  related_code=$(grep -l "See: $doc" AGENTS.md src/**/*.ts 2>/dev/null | head -5)
  for code_file in $related_code; do
    code_modified=$(git log -1 --format="%at" -- "$code_file")
    if [ "$code_modified" -gt "$doc_modified" ]; then
      echo "STALE: $doc (code changed after doc)"
    fi
  done
done
```

### Phase 5: Observability

**Step 13: Agent Action Logging**

Track everything the agent does for post-mortem analysis:

```javascript
// Wrap agent actions with telemetry
function logAgentAction(action) {
  const entry = {
    timestamp: new Date().toISOString(),
    action: action.type,
    tool: action.tool || null,
    tokens_used: action.tokens,
    duration_ms: action.duration,
    success: action.success,
    error: action.error || null,
    files_modified: action.files || [],
  };
  fs.appendFileSync('agent-telemetry.jsonl', JSON.stringify(entry) + '\n');
}
```

**Step 14: Cost & Performance Dashboards**

Answer these questions:
- Why did the agent choose this tool?
- How many attempts did it take to pass the test suite?
- Where in the workflow did it spend the most tokens?
- When did it last require human intervention?
- What's the cost per feature implemented?

---

## Part V: Advanced Patterns

### Pattern 1: The Planner-Generator-Evaluator Architecture

Anthropic's three-agent system, inspired by GANs:

1. **Planner**: Decomposes a high-level spec into a structured task plan with acceptance criteria
2. **Generator**: Implements each task, producing code and artifacts
3. **Evaluator**: Navigates the live application, interacts with it, scores against criteria, provides detailed feedback

The generator and evaluator iterate in cycles (5–15 per run, sometimes 4+ hours), producing progressively refined outputs. The key insight: separating the agent doing the work from the agent judging it is a powerful lever for quality.

### Pattern 2: The Ralph Wiggum Loop

A hook or script that repeatedly restarts the agent in a clean context window, forcing it to continue working against a completion goal:

```bash
#!/bin/bash
# ralph-loop.sh — Keep the agent working until the spec is satisfied
while true; do
  # Run the agent with fresh context
  claude-code --prompt "Continue working on the current feature. \
    Read claude-progress.txt and feature-list.json for state. \
    Run verify.sh when done."
  
  # Check if the feature is actually complete
  if ./scripts/verify.sh && node scripts/check-feature-complete.js; then
    echo "Feature verified complete!"
    break
  fi
  
  echo "Not done yet. Restarting with fresh context..."
  sleep 2
done
```

### Pattern 3: Doom Loop Detection

Agents can get stuck making small variations to the same broken approach 10+ times:

```javascript
// middleware/loop-detection.js
class LoopDetector {
  constructor(threshold = 5) {
    this.editCounts = new Map();
    this.threshold = threshold;
  }

  trackEdit(filePath) {
    const count = (this.editCounts.get(filePath) || 0) + 1;
    this.editCounts.set(filePath, count);

    if (count >= this.threshold) {
      return {
        inject: `WARNING: You have edited ${filePath} ${count} times. ` +
          `Consider reconsidering your approach entirely. ` +
          `Try a different algorithm, architecture, or strategy.`
      };
    }
    return null;
  }
}
```

### Pattern 4: Spec-Driven Reproducibility (Ghost Libraries)

From the Latent Space interview with Ryan Lopopolo: a coding agent can reproduce complex systems from a high-fidelity specification rather than shared source code. Write detailed specs and the agent regenerates the implementation. Code becomes disposable; the spec is the artifact of value.

### Pattern 5: Harness Templates for Common Topologies

Greenfield teams should bake harnessability in from day one. Many mature organizations have standard service topologies — business APIs, event processors, data dashboards. These can become harness templates: a bundle of guides, linters, structural tests, and agent instructions scoped to a specific topology.

Teams may start choosing tech stacks partly based on what harnesses are already available for them.

---

## Part VI: Applying Harness Engineering to Product Design

### For Agentic Board

Agentic Board is not a generic workflow engine, chat app, coding swarm, or
automation platform. Its product goal is to be the governance council for a solo
company: a compact board of specialist AI members that helps the founder make
high-leverage decisions, preserves institutional memory, surfaces dissent, and
returns an auditable recommendation. Hermes is the operating runtime around the
board. Hermes should gather evidence, load skills, search sessions, use tools,
execute workflows, and carry approved decisions into follow-up work.

That boundary is the product design center of gravity:

```text
Hermes runtime
  -> gathers evidence and operating context
  -> invokes Agentic Board only for governance decisions
  -> presents decision, risks, dissent, memory proposal, and next actions

Agentic Board service
  -> classifies the decision
  -> routes to the smallest useful council for the current business stage
  -> runs independent analysis, anonymized peer review, and chair synthesis
  -> verifies decision quality when needed
  -> proposes memory updates without applying them automatically

Human founder
  -> approves durable memory
  -> approves roster evolution
  -> approves high-impact execution
```

**1. Design the input as a decision packet**

The primary product input is not a backlog ticket. It is a decision packet:

- one-sentence decision question
- business stage and decision type
- relevant company context and evidence quality
- constraints, deadlines, and non-goals
- available options, if any
- requested decision format
- SOTB facts that should be read
- memory facts that may need an update proposal

The harness should make this packet explicit before the board runs. A weak input
should produce a clarification request or a scoped provisional decision. It
should not produce a confident board answer from vague context.

**2. Design the output as a decision record**

The primary product artifact is a durable decision record, not a transcript. A
useful record answers:

- what the board decided
- why this decision is better than the alternatives
- what dissent remains unresolved
- what assumptions must be validated
- what risks and reversal conditions matter
- what Hermes or the founder should do next
- what memory update is proposed, if any
- what it cost in time, tokens, and member calls

The session JSON and adapter projection are the integration contract. The UI,
CLI, Hermes skill, and future plugin should all consume the same decision
record shape rather than scraping rich terminal text.

**3. Keep governance separate from execution**

The board service should do a small number of things well:

- classify the decision
- select the right active members
- run Stage 1 independent analysis without cross-contamination
- run Stage 2 anonymized peer review
- synthesize a final chair decision with dissent and risks
- optionally run Stage 4 verification
- propose SOTB memory updates without writing them automatically

Do not make every recurring process a board member. Customer discovery,
competitive research, sprint planning, implementation, QA, deployment, and
follow-up work belong in Hermes skills, tools, or operating workflows. Add or
activate a board member only when the company has a durable governance gap that
the current seats cannot cover.

**4. Make deliberation quality mechanically visible**

Verification for this product is not just "tests pass." The harness should
measure whether the board process produced a useful governance decision:

- selected members match decision type and business stage
- role gaps and unavailable capabilities are explicit
- Stage 1 responses are independent and differentiated by seat
- Stage 2 reviews challenge specific peer claims
- the chair resolves conflicts instead of averaging opinions
- dissent, assumptions, risks, next actions, and reversal conditions are explicit
- SOTB proposals are separated from approved memory
- token, latency, model, and cost budgets are recorded per stage

These checks map to existing files such as `server/board/orchestrator.py`,
`server/board/classifier.py`, `server/board/roster.py`,
`server/board/compaction.py`, `server/board/schemas.py`,
`server/board/verification.py`, `server/board/memory_review.py`, and
`server/board/metrics.py`.

**5. Keep the interface founder-first**

The product experience should feel like consulting a board, not operating an
agent swarm. The founder should be able to see:

- who was invited and why
- which capabilities were missing or shelved
- what each member independently believed
- where members disagreed
- how the chair resolved the conflict
- what changed because of SOTB context
- which memory updates require approval
- what Hermes or the human should do next

This is a product-design constraint, not just UI polish. If the harness hides
routing, dissent, role gaps, cost, or memory changes, the board loses trust.

**6. Use progressive context for company knowledge**

Keep company knowledge small, versioned, and scoped:

- `server/memory/sotb.md` for approved board memory
- `server/members/*.md` for durable governance roles
- `server/board/roster.yaml` for stage and capability routing
- `server/protocols/*.md` for stage contracts
- Hermes skills for repeatable operating procedures
- session JSON for audit history, not authoritative truth

The board should receive enough context to decide, not every historical detail.
Hermes can gather and summarize evidence before invoking the board, but the
board should still show which evidence actually influenced the decision.

**7. Let business stage shape the board**

The default product stage is `pre_pmf`. The active council should stay focused
on market, product, customer, feasibility, risk, and validation:

```text
chairperson, strategist, product, researcher, critic, architect, builder
```

`guardian` and `operator` belong in the live-product stage when users, data,
uptime, release process, integrations, or incident response become recurring
governance concerns. `finance` and `legal` should remain future placeholders
until member files, roster metadata, benchmark queries, and role-gap evidence
exist. Stage profiles are a product mechanism, not just routing config.

**8. Iterate the board harness, not just member prompts**

When the board makes a bad decision, identify the failing harness layer:

- bad routing -> adjust classifier labels, roster capabilities, or stage profiles
- missing perspective -> run role-gap review before adding a new member
- weak dissent -> revise critic/chair protocols or Stage 2 requirements
- stale memory -> improve memory proposal review and SOTB approval flow
- vague output -> update `server/protocols/*` and schema projection
- hidden evidence -> improve the decision packet and adapter fields
- cost blowout -> tighten compaction, member selection, or verification gates

Prompt edits are allowed, but the durable fix should usually be a contract,
router, protocol, parser, metric, benchmark, or approval gate.

---

## Part VII: The Harness Engineering Mindset

### What Changes About Being an Engineer

The primary job of your engineering team becomes enabling agents to do useful work. In practice, this means:

- **Specifying intent clearly** — Writing detailed specs, not code
- **Building feedback loops** — Tests, linters, CI, observability
- **Designing environments** — Repository structure, documentation, tool access
- **Capturing taste** — Encoding quality standards into enforceable rules
- **Managing entropy** — Running periodic cleanup and consistency checks

### The Steering Loop

Birgitta Böckeler (Thoughtworks) frames harness engineering as a continuous steering loop:

1. **Observe**: Agent makes a mistake or produces suboptimal output
2. **Diagnose**: Is this a context problem? A tool problem? A constraint problem?
3. **Improve**: Update the appropriate harness component (guide, sensor, or constraint)
4. **Verify**: Confirm the improvement prevents recurrence
5. **Repeat**: The harness gets better with every iteration

### What Harnesses Cannot Catch (Yet)

Be honest about limitations:

- **Computational sensors** (linters, structural tests) reliably catch: duplicate code, complexity, missing coverage, architectural drift, style violations
- **LLM-based sensors** partially catch: semantic duplication, redundant tests, brute-force fixes, over-engineering — but expensively and probabilistically
- **Neither reliably catches**: Misdiagnosis of issues, unnecessary features, misunderstood instructions
- **Nothing catches**: Correctness failures when the human didn't clearly specify what they wanted

Harness engineering reduces supervision needs but does not eliminate the need for human judgment on what to build and why.

### The Future Trajectory

As Ryan Lopopolo described in the Latent Space interview, the frontier is moving toward:

- **Zero human-reviewed code before merge** — agent-to-agent review pipelines
- **Symphony-style orchestration** — coordinating large numbers of agents across repos and tickets
- **Harnesses thinning over time** — as models improve, harness components become unnecessary
- **Spec-driven development** — high-fidelity specs replace shared codebases as the primary artifact

The harness is not permanent infrastructure. It's scaffolding that evolves as models do. The discipline is knowing which scaffolding to build now, and when to tear it down.

---

## Appendix: Key Sources

| Source | Title | Key Contribution |
|--------|-------|-----------------|
| Mitchell Hashimoto | "My AI Adoption Journey" (Feb 2026) | Named the discipline; "engineer the harness" |
| OpenAI (Ryan Lopopolo) | "Harness engineering: leveraging Codex in an agent-first world" (Feb 2026) | Million-line experiment; repository-as-truth; architectural constraints |
| OpenAI (Latent Space) | "Extreme Harness Engineering for Token Billionaires" (Apr 2026) | Symphony orchestration; ghost libraries; zero-review merging |
| Anthropic | "Effective harnesses for long-running agents" (Nov 2025) | Initializer/coding agent pattern; feature lists; cross-session state |
| Anthropic | "Harness design for long-running application development" (Mar 2026) | Planner-Generator-Evaluator architecture; harness simplification |
| Anthropic | "Scaling Managed Agents" (Apr 2026) | Meta-harness design; assumptions that expire; credential isolation |
| LangChain (Vivek Trivedy) | "The Anatomy of an Agent Harness" (Mar 2026) | Agent = Model + Harness; eleven core components |
| LangChain | "Improving Deep Agents with harness engineering" (Feb 2026) | Terminal Bench 2.0 results; middleware architecture |
| Thoughtworks (Birgitta Böckeler) | "Harness engineering for coding agent users" (Feb–Apr 2026) | Guides vs. sensors; computational vs. inferential controls; harness templates |
| HumanLayer | "Skill Issue: Harness Engineering for Coding Agents" (Mar 2026) | Sub-agents for context control; skills as progressive disclosure |

---

*This playbook represents the state of the art as of April 2026. The field is evolving rapidly. The principles will endure; the specific implementations will change as models improve.*
