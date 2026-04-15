# Context Engineering: The Definitive Guidebook for Building Production AI Agents

**Context engineering is the single most important discipline for building reliable AI agents in production.** It represents a paradigm shift from crafting clever prompts to designing dynamic systems that assemble the right information, in the right format, at the right time for every LLM inference call. The difference between a demo that impresses and a product that works at scale is almost always context quality -- not model quality. Anthropic, Manus, OpenAI, Google, Cognition, and dozens of production teams have independently converged on this conclusion, and their hard-won lessons reveal a comprehensive discipline with shared vocabulary, documented patterns, and production-validated strategies.

This guidebook covers not only what context engineering is (strategies and patterns), but how to systematically design, build, evaluate, and operate context systems -- the structural methodology that separates production systems from prototypes.

---

## Table of Contents

- [Part 1: Foundations](#part-1-foundations)
- [Part 2: The Context Assembly Pipeline](#part-2-the-context-assembly-pipeline)
- [Part 3: Eight Core Strategies](#part-3-eight-core-strategies)
- [Part 4: How Industry Leaders Architect Context](#part-4-how-industry-leaders-architect-context)
- [Part 5: Design Methodology](#part-5-design-methodology)
- [Part 6: Evaluation and Operations](#part-6-evaluation-and-operations)
- [Part 7: Anti-Patterns and Adversarial Concerns](#part-7-anti-patterns-and-adversarial-concerns)
- [Part 8: Conclusion](#part-8-conclusion)
- [Appendix: Sources and References](#appendix-sources-and-references)

---

## Part 1: Foundations

### What context engineering actually means

Context engineering emerged in mid-2025 as the successor to prompt engineering. Where prompt engineering focuses on how you phrase a single instruction, context engineering encompasses **everything the model sees**: system prompts, conversation history, tool definitions, retrieved documents, memory files, structured outputs, and environmental metadata. Andrej Karpathy gave the term its most viral definition on June 25, 2025:

> "Context engineering is the delicate art and science of filling the context window with just the right information for the next step."

His analogy -- **an LLM is like a CPU and its context window is like RAM** -- has become the field's foundational mental model. Your job as an engineer is akin to an operating system: load that working memory with just the right code and data for the task. "Too little or of the wrong form and the LLM doesn't have the right context for optimal performance. Too much or too irrelevant, and the LLM costs might go up, and performance might come down."

The term gained rapid traction through a cascade of influential voices:

- **June 12, 2025** -- Walden Yan (Cognition/Devin) published "Don't Build Multi-Agents," declaring context engineering "effectively the #1 job of engineers building AI agents."
- **June 18, 2025** -- Shopify CEO Tobi Lutke endorsed the shift: "I really like the term 'context engineering' over prompt engineering. It describes the core skill better: the art of providing all the context for the task to be plausibly solvable by the LLM."
- **June 23, 2025** -- Harrison Chase (LangChain) formalized a definition: "Context engineering is building dynamic systems to provide the right information and tools in the right format such that the LLM can plausibly accomplish the task."
- **June 25, 2025** -- Andrej Karpathy endorsed it with the CPU/RAM analogy.
- **June 27, 2025** -- Simon Willison declared the term would stick: "Most people's inferred definition of prompt engineering is that it's a laughably pretentious term for typing things into a chatbot. I think the inferred definition of 'context engineering' is likely to be much closer to the intended meaning."
- **September 2025** -- Anthropic published the field's most comprehensive institutional treatment: "Effective Context Engineering for AI Agents."
- **July 2025** -- Manus shared production lessons from serving millions of users.
- **Mid-2025 onward** -- Philipp Schmid (Google DeepMind) formalized a seven-component framework.

### Context engineering versus prompt engineering

| Dimension | Prompt Engineering | Context Engineering |
|---|---|---|
| **Focus** | How you phrase the instruction | Everything the model sees |
| **Scope** | Single input-output pair | Memory, history, tools, system prompts, retrieved data, structured output |
| **Nature** | Static, one-shot | Dynamic, iterative, runtime-assembled |
| **Mindset** | Crafting clear text | Designing information architecture |
| **Relationship** | Subset | Superset that includes prompt engineering |
| **Temporal scope** | Single request | Across turns, sessions, and agent lifetimes |
| **Optimization target** | Phrasing clarity | Token efficiency, cache hit rates, attention allocation |

Harrison Chase captures the relationship precisely: "Prompt engineering is a subset of context engineering. Even if you have all the context, how you assemble it in the prompt still absolutely matters."

### Why context failures dominate

The core insight driving this shift is that **most agent failures in production are context failures, not model failures**. As Schmid puts it: "Most agent failures are not model failures anymore, they are context failures."

Even with 200K-1M+ token context windows, models suffer from what researchers call **context rot** -- performance degradation as token count increases, because transformer attention creates n-squared pairwise relationships that stretch the model's "attention budget" thin. Chroma's research across 18 state-of-the-art models found:

- Models lose **20-50% accuracy** as input grows from 10K to 100K+ tokens on retrieval tasks.
- Adding related but irrelevant information (distractors) **amplifies errors non-uniformly** -- the impact grows with input length.
- Low-similarity queries (requiring semantic reasoning) degrade **faster** than high-similarity ones.
- GPT models show the highest rates of hallucination, often generating confident but incorrect responses when distractors are present.

Schmid identifies two distinct failure modes. **Context rot**: performance degrades as the window fills, even within technical limits -- the "effective context window" is often around 256K tokens regardless of the advertised maximum. **Context pollution**: too much irrelevant, redundant, or conflicting information distracts the LLM and degrades reasoning accuracy.

Good context engineering means finding the smallest possible set of high-signal tokens that maximize the likelihood of a desired outcome.

### The evolution of the discipline

The field has progressed through distinct eras:

| Era | Period | Focus |
|---|---|---|
| **Prompt Engineering** | 2023-2024 | Crafting static instructions |
| **Context Engineering** | Mid-2025+ | Dynamic systems for context assembly |
| **Harness Engineering** | Feb 2026+ | Scaffolding, feedback loops, architectural constraints |

OpenAI's "harness engineering" (February 2026) represents the latest evolution: a methodology where agents generate, test, and deploy code at scale within engineered scaffolding. In a five-month internal experiment, a team of 3 engineers merged ~1,500 PRs (3.5 PRs/engineer/day), producing ~1 million lines of code. The key insight: "Building software still demands discipline, but the discipline shows up more in the scaffolding rather than the code."

---

## Part 2: The Context Assembly Pipeline

Context engineering is not just about what to put in the context window -- it's about the **systematic process** of assembling context before every LLM call. This section covers the structural architecture that production systems use.

### The compiler metaphor

Google's Agent Development Kit (ADK) provides the clearest architectural metaphor: **context assembly is a build process, not a prompt-writing exercise.**

| Compiler Concept | Context Engineering Equivalent |
|---|---|
| Source code | Sessions, memory, artifacts (durable state) |
| Compiler pipeline | Flows and processors (named, ordered transformation passes) |
| Compiled binary | Working context (the actual prompt sent to the LLM) |

Three design principles follow:

1. **Separate storage from presentation** -- What the agent "knows" (session state) is distinct from what the LLM "sees" (working context).
2. **Explicit transformations** -- Named, ordered processors, not ad-hoc string concatenation. Each processor builds on the previous step's output. This is observable, testable, and maintainable.
3. **Scope by default** -- Every model call sees only the minimum required context. Agents reach for more information explicitly via tools.

### Pipeline stages

The context assembly pipeline runs through six stages before each LLM call:

**Stage 1: Collection/Retrieval.** Gather context from multiple sources: tool results, memory lookups, knowledge base searches, file reads, API responses. Use parallelized data fetching -- execute retrieval steps concurrently, with total time dictated by the single longest task.

**Stage 2: Filtering/Selection.** Apply schema-based filtering to include only fields relevant to the current operation. Use semantic search, recency weighting, task-specific filtering, and progressive loading. Cognition (Devin) uses a **fine-tuned model specifically for context selection** -- underscoring how much investment goes into choosing what enters the window.

**Stage 3: Prioritization/Ordering.** Position critical information at the beginning and end of the context window due to the U-shaped attention curve (the "lost in the middle" problem -- see Strategy 7). Information in the middle receives up to **30% less attention**. Anthropic recommends placing system instructions and critical rules at the top, recent state at the bottom.

**Stage 4: Compression/Truncation.** Apply three levels in order of preference:
1. **Raw** -- Keep original content when possible
2. **Compaction** -- Strip redundant information that exists elsewhere in the environment (reversible)
3. **Summarization** -- Use LLM to condense content (lossy, last resort)

Anthropic's priority ordering: **prefer raw content > compaction > summarization**, escalating only when the lighter approach no longer yields enough space.

**Stage 5: Assembly.** Combine all components into the final prompt with proper formatting. Format preferences vary by model: Claude is specifically tuned for **XML tags**, GPT-4 favors **Markdown**, GPT-3.5-turbo prefers **JSON**. Research shows variations in whitespace, bulleting, and role headers can produce up to **40% accuracy swings** on certain tasks.

**Stage 6: Caching Optimization.** Divide context into two zones (Google ADK's "zone architecture"):
- **Stable prefixes** -- System instructions, agent identity, tool definitions, long-lived summaries. A `static_instruction` primitive guarantees immutability, preserving cache validity across invocations.
- **Variable suffixes** -- Latest user turn, new tool outputs, incremental updates.

Any modification to the stable prefix invalidates the KV cache from that point forward.

### Context budgeting

A token budget is a predefined allocation of the context window across categories. You programmatically decide how to "spend" available tokens while never exceeding the model's limit.

**Recommended allocation ranges:**

| Component | Typical Allocation | Notes |
|---|---|---|
| System Instructions | 10-15% | Disproportionate influence; justify premium allocation |
| Tool Definitions | 10-20% | Static per session; cached via prefix caching |
| Retrieved Context (RAG/files) | 20-40% | Varies by query complexity |
| Conversation History | 15-25% | Subject to sliding window or summarization |
| User Query + Working Memory | 5-15% | Current turn + scratchpad content |
| Reserved for Output | 25-50% | Always reserve space for generation |

**Concrete example -- Claude Code's budget:** The system prompt consumes ~23,000 tokens (~11% of a 200K window). Claude Code's documentation notes this is "nearly a third of the instructions your agent can reliably follow," suggesting a practical ceiling of ~50-70 discrete instructions before instruction-following degrades.

**Context utilization rate:** Optimal range is **60-80%** of budget actively used. Below 60% indicates over-provisioning. Above 80% risks capacity limits and attention degradation.

**Task-specific budgets:** Budget per task type, not per product:
- Simple factual queries -- allocate more to retrieved documents, reduce conversation history
- Multi-turn reasoning (analysis, legal, financial) -- 4,000-8,000 tokens for working memory
- Creative generation (ads, stories) -- 500-1,500 tokens, minimize constraints

---

## Part 3: Eight Core Strategies

The original six strategies plus two "bonus techniques" have been reorganized into eight equal-status strategies based on production evidence. Error preservation and attention management are no longer secondary -- they are fundamental to reliable agent operation.

### Strategy 1: Compaction and compression

Compaction distills the contents of a growing context window into a high-fidelity summary, enabling an agent to continue working with minimal performance degradation. Anthropic calls it "the first lever in context engineering to drive better long-term coherence."

**Two critical sub-types.** Schmid distinguishes between *context compaction* (reversible -- replacing a 500-line file output with "Output saved to /src/main.py" since the agent can re-read the file later) and *summarization* (lossy -- using an LLM to condense history).

**How Claude Code implements compaction.** Claude Code operates within a ~200K-1M token context window. Auto-compaction triggers when total token usage crosses approximately **95% of capacity**. The system passes message history to the model for summarization, preserving architectural decisions, unresolved bugs, file paths, function names, and error messages while discarding redundant tool outputs. Measured results show compaction reducing 208,838 tokens to 86,446 tokens -- a **58.6% reduction**. CLAUDE.md files survive compaction because they are re-read from disk and re-injected fresh.

**Anthropic's server-side compaction API** (`compact-2026-01-12`) supports Claude Opus 4.6 and Sonnet 4.6, with a default trigger at 150,000 tokens (configurable, minimum 50,000). It returns encrypted compaction blocks that carry forward key state, and automatically drops all messages prior to the compaction block on subsequent requests.

**OpenAI's compaction API** (`POST /responses/compact`) is stateless -- you send the full context, it returns a compressed version with encrypted, opaque items that preserve the model's latent understanding. Auto-compaction can be enabled via `context_management.compact_threshold` in the Responses API.

**Factory.ai's anchored incremental approach** avoids re-summarizing the entire conversation each time. They maintain a persistent structured summary with explicit sections (files modified, decisions made, next steps). When context reaches the fill-line threshold (T_max), only the newly dropped span is summarized and merged into the persistent summary. Evaluation across 36,000+ production messages showed Factory scoring **3.70 overall vs. Anthropic's 3.44 and OpenAI's 3.35**, with a 0.61-point accuracy gap on technical detail preservation.

**Google ADK's invocation-count approach** uses `compaction_interval` (e.g., every 3 events) with configurable `overlap_size` (e.g., 1 event overlap between windows). A cheaper model (e.g., Gemini Flash) can be specified for the summarization step.

**Sourcegraph Amp retired compaction entirely.** They found that repeated compression made it harder for agents to maintain continuity -- "recursive summaries (summaries of summaries) distorted earlier reasoning." They switched to a **hand-off mechanism**: when context fills, the agent analyzes the session, generates a draft prompt with relevant artifacts, and spawns a new agent instance with a fresh context window. This reframes context exhaustion from a compression problem to a coordination problem.

**The art of compaction**, as Anthropic notes, "lies in the selection of what to keep versus what to discard, as overly aggressive compaction can result in the loss of subtle but critical context whose importance only becomes apparent later."

### Strategy 2: Externalized memory

Externalized memory persists critical information outside the context window -- to files, databases, or storage systems -- so agents can access it across turns and sessions. Manus elevates this to a core philosophy: "We treat the file system as the ultimate context: unlimited in size, persistent by nature, and directly operable by the agent itself."

**The instruction file ecosystem.** Every major AI coding tool has adopted persistent instruction files:

| Tool | File | Format |
|---|---|---|
| Claude Code | `CLAUDE.md` | Markdown, hierarchical (global → project → subdirectory) |
| OpenAI Codex | `AGENTS.md` | Markdown, root-to-leaf directory traversal |
| Gemini CLI | `GEMINI.md` | Markdown, global + upward + downward traversal |
| Cursor | `.cursor/rules/*.mdc` | MDC (Markdown + YAML frontmatter) |
| Windsurf | `.windsurfrules` | Project-level permanent context |
| GitHub Copilot | `copilot-instructions.md` | Markdown |

**The CLAUDE.md ecosystem** operates at multiple levels: managed policy (system-wide, cannot be excluded), user-level (`~/.claude/CLAUDE.md`), parent directories (loaded upward from CWD), project root, and subdirectories (lazily loaded on demand). CLAUDE.md is **not part of the system prompt** -- it is delivered as a user message after the system prompt. Best practice: keep under **200 lines / ~2,000 tokens**, using direct instructions in list form.

**Vercel's surprising finding about AGENTS.md vs. skills**: A compressed 8KB docs index in AGENTS.md achieved **100%** on their Next.js 16 API evals, while dynamically loaded skills maxed at **79%**. In 56% of eval cases, available skills were never invoked. Three factors favor always-loaded instruction files: no decision point required, consistent availability in every turn, and no ordering issues.

**OpenAI Codex's philosophy**: "Give Codex a map, not a 1,000-page instruction manual." A short AGENTS.md (~100 lines) serves as a map with pointers to deeper sources of truth.

**Claude Code's auto-memory system** accumulates knowledge across sessions automatically. When Claude discovers something useful, it saves notes to `~/.claude/projects/<project>/memory/`. The main `MEMORY.md` index (first 200 lines loaded every session) stays concise by offloading detailed notes to topic files.

**Database-backed memory systems** serve production agents at scale:

- **MemGPT/Letta** introduced an OS-inspired architecture with four tiers: core memory (always in context, like registers), recall memory (searchable conversation log), archival memory (vector-indexed knowledge), and message buffer (recent conversation window). The agent uses tool calls (`core_memory_append`, `archival_memory_search`, etc.) to page data between tiers -- self-directed memory management.

- **Zep/Graphiti** implements temporal knowledge graphs that outperform MemGPT on Deep Memory Retrieval: **94.8% vs 93.4%** accuracy with **90% latency reduction**. Its bi-temporal model tracks when events occurred AND when they were ingested, with explicit validity intervals for every edge. Retrieval at P95 latency of **300ms** uses zero LLM calls.

- **ChatGPT's four-layer system** is surprisingly simple: (1) session metadata (device, timezone), (2) long-term saved facts (all loaded with every message), (3) lightweight conversation summaries, (4) current session messages. No RAG, no vector databases -- OpenAI relies on growing context windows and model capability to focus on relevant items.

**Manus's key design principle**: compression should always be restorable. Drop web page content from context, but preserve the URL. Omit document contents, but keep the file path. The agent can always re-read what it needs. This is analogous to virtual memory paging: swap out the data, keep the page table entry.

### Strategy 3: Just-in-time loading

Just-in-time (JIT) context loading maintains lightweight identifiers -- file paths, URLs, stored queries -- and dynamically loads full content only when the agent actually needs it. Anthropic's framing mirrors human cognition: "We generally don't memorize entire corpuses of information, but rather introduce external organization and indexing systems like file systems, inboxes, and bookmarks to retrieve relevant information on demand."

**Claude Code implements a hybrid retrieval model.** CLAUDE.md files are eagerly loaded at session start (stable, essential context). Rules in `.claude/rules/` with `paths` YAML frontmatter load conditionally when the agent reads matching files. Skills load descriptions at session start so the model knows what's available, but full skill content loads only when invoked. Everything else -- file contents, search results, database records -- loads lazily through tools.

**RAG is a form of JIT loading**, but production teams increasingly favor direct file-system navigation over vector-search pipelines. Claude Code bypasses traditional RAG entirely by giving the agent primitives to explore the codebase directly -- searching file names, grepping for patterns, reading specific files. This avoids the chunking, embedding, and staleness problems of vector-based retrieval.

**LangChain's retrieval-augmented tool descriptions** -- fetching only tool names initially, then full details as needed -- reduced total agent tokens by **46.9%** while maintaining or improving quality.

**Anthropic's Tool Search Tool** scales to **10,000+ tools** in your catalog, returning 3-5 relevant tools per search. Deferred tools (with `defer_loading: true`) are excluded from the initial prompt entirely, preserving **191,300 tokens** vs. 122,800 with the traditional approach -- an **85% reduction** in tool token usage. Performance improved: Opus 4 from 49% to 74%, Opus 4.5 from 79.5% to 88.1% on MCP evaluations.

**The layered hybrid approach:**

| Layer | Loading Strategy | Example |
|---|---|---|
| Always-loaded | Eagerly at session start | System prompt, identity, core rules |
| Conditionally loaded | Triggered by file patterns or state | Path-scoped rules, domain skills |
| JIT-loaded | On-demand via tool calls | File reads, grep results, database queries |
| RAG-retrieved | Vector search for knowledge bases | Documentation, support articles |
| Never pre-loaded | Too large, accessed through navigation | Full databases, entire codebases |

### Strategy 4: Context isolation

Context isolation gives each agent in a multi-agent system its own scoped, focused context window rather than sharing a monolithic context. Manus applies a principle from Go concurrency: **"Share memory by communicating, don't communicate by sharing memory."**

**Claude Code's subagent system** exemplifies this pattern. Each subagent runs in its own fresh context window (200K-1M tokens), completely isolated from the main conversation. Intermediate tool calls and results stay inside the subagent; only a condensed summary (typically 1,000-2,000 tokens) returns to the parent. Key constraints: subagents cannot spawn other subagents (preventing infinite nesting) and cannot exchange information with each other directly.

**Why isolation matters quantitatively.** Research from Chroma shows that even state-of-the-art model performance can drop **20-50%** based on irrelevant information in context. LangChain confirms that subagents process **67% fewer tokens overall** compared to single-agent patterns due to context isolation.

**Google ADK's narrative casting** prevents a subtle failure mode in agent handoffs. When transferring control between agents, prior assistant messages are re-cast as narrative context (e.g., `[For context]: Agent B said...`) rather than appearing as the new agent's own outputs. Without this, the receiving agent halluccinates that it performed those earlier actions. ADK also provides an `include_contents` knob: default mode passes full history, `none` mode gives the sub-agent a blank slate.

**Cognition (Devin) argues against isolation.** Walden Yan's "Don't Build Multi-Agents" makes the case for a single excellent agent with context engineering over multiple agents with isolated windows. Two principles: (1) always share full context and agent traces between components -- splitting context creates a "telephone game" where critical details are lost, and (2) track decisions to prevent conflicts -- when agents operate independently, they make conflicting choices without realizing it.

**The trade-off is real.** Subagents add latency (one extra model call per delegation) and communication overhead. For tightly coupled tasks where changes are deeply interdependent, isolation creates more problems than it solves. LangChain's production pattern: sub-agents that **only read and don't make decisions** -- they list files, examine imports, look for patterns, then report back. Decision-making stays in the main agent's context.

**The sweet spot** for isolation: tasks that can be cleanly divided without interdependencies -- parallel searches, test execution, documentation generation, log analysis, codebase exploration.

### Strategy 5: Tool design and management

How tools are designed directly impacts context efficiency and agent reliability. Anthropic states the counterintuitive finding clearly: "More tools don't always lead to better outcomes." The **paradox of choice** applies -- as the action space grows, models are more likely to select suboptimal actions.

**Vercel's landmark experiment** proved this dramatically. They removed 80% of their d0 agent's tools, replacing ~15 specialized tools with a single bash execution tool in a secure sandbox. Results: accuracy jumped from 80% to **100%**, execution was **3.5x faster**, and token usage fell **40%**. Their insight: "We were constraining reasoning because we didn't trust the model to reason." The semantic layer providing structure mattered more than clever tooling.

**Microsoft Research** analyzed 1,470 MCP servers and found large tool spaces lower performance by **up to 85%** for some models. Root causes: tool name collisions (semantic overlap like "search" vs "web_search" vs "google_search"), excessive tool counts (OpenAI recommends well below 20), and long tool responses (some returning 128,000+ tokens, overflowing the entire context window).

**Manus's logit masking** is an elegant solution to tool management. Rather than dynamically adding or removing tools from the prompt (which invalidates the KV cache), Manus keeps all tool definitions stable and masks token logits during decoding to prevent or enforce selection of certain tools based on current state. Tool names use consistent prefixes -- `browser_` for web tools, `shell_` for CLI tools -- enabling efficient group-level masking.

The mechanism works by modifying raw logits at each decoding step: unwanted tokens' logits are set to negative infinity. Three modes:
- **Auto** -- model chooses freely between tools and text response
- **Required** -- must use a tool (text response path blocked)
- **Specified** -- must use a specific tool (only that tool's name tokens allowed)

**Tool design best practices (from Anthropic):**
- Build **task-oriented tools** (`schedule_event`) rather than API wrappers (`list_users` + `list_events` + `create_event`)
- Tools should be "self-contained, robust to error, and extremely clear with respect to their intended use"
- Descriptions should read as if written "for a new hire on your team"
- Each tool should return information that is **token-efficient** -- don't return a full database row when three fields suffice
- "If a human engineer can't definitively say which tool should be used in a given situation, an AI agent can't be expected to do better"

**Claude Code's approach**: 28 built-in tools, with CLI tools (gh, aws, gcloud) preferred over MCP servers because they "don't add persistent tool definitions." Each MCP server adds tool definitions to every request, and the `/mcp` command shows per-server context costs.

### Strategy 6: Cache architecture

**KV cache hit rate is the single most important operational metric for production AI agents**, according to Manus. The KV (Key-Value) cache stores intermediate attention matrices computed during transformer inference so they don't need recomputation for previously seen tokens.

The economics are stark:

| Provider | Cached Cost | Uncached Cost | Savings |
|---|---|---|---|
| Anthropic (Claude Sonnet) | $0.30/MTok | $3.00/MTok | 10x |
| OpenAI (automatic) | 50% of standard | Standard | 2x |
| Google (implicit, Gemini 2.5+) | 25% of standard | Standard | 4x |
| Google (explicit) | 10% of standard | Standard | 10x |

Given Manus's average input-to-output token ratio of ~100:1 across ~50 tool calls per task, cache optimization is the difference between viable and uneconomical.

**The append-only pattern** is the primary strategy for maximizing cache hits. Each agent step adds new content to the end of the context, never modifying earlier content. Manus identifies three rules:

1. **Keep the prompt prefix stable** -- never include timestamps at the beginning of system prompts
2. **Make context append-only** -- never modify previous actions or observations
3. **Ensure deterministic serialization** -- many languages don't guarantee stable JSON key ordering, silently breaking cache. Even a single token difference invalidates the cache from that point forward.

**Benchmarked impact**: Stable prefixes achieve **71.3% cost reduction** compared to perturbed prefixes ($0.009556 vs. $0.033306 per request).

**Anthropic's prompt caching** offers explicit cache control with `cache_control` fields, two TTL options (5-minute at 1.25x write cost, 1-hour at 2x), and cache reads at **10% of base input price**. Latency reductions reach up to **85%** for long prompts (100K-token request: 11.5s to 2.4s). Maximum 4 explicit breakpoints per request, with a 20-block lookback window from each breakpoint.

**OpenAI's caching** is fully automatic -- no code changes needed, cached tokens at 50% discount, active for 5-10 minutes of inactivity. Extended cache retention up to 24 hours.

**Google's implicit caching** (Gemini 2.5+) requires zero configuration -- 75% token discount on cache hits. Explicit caching offers 90% discount with configurable TTL (default 60 minutes).

**The critical tension: compaction and caching work against each other.** Compaction rewrites history (breaking cache), while caching requires stable prefixes. The solution: design compaction to occur at natural breakpoints and rebuild cache-friendly prefixes after compaction. OpenAI's Codex team warns to "carefully consider the impact of caching from context engineering techniques like compaction."

### Strategy 7: Attention management

The **"lost in the middle" problem**, documented by Liu et al. (2023) at Stanford and UC Berkeley, shows that LLM performance follows a **U-shaped curve**: highest when relevant information appears at the beginning or end of context, **degraded by more than 30%** when it sits in the middle. The root cause is structural -- Rotary Position Embedding (RoPE), commonly used in modern LLMs, introduces a long-term decay effect that de-emphasizes middle content.

Google's follow-up research, **"Found in the Middle"** (June 2024), developed a calibration mechanism that improves middle-position accuracy by **up to 15 percentage points**. Multi-scale Positional Encoding (Ms-PoE) further improves middle-position accuracy by **20-40%** without requiring fine-tuning. But no production model has fully eliminated position bias -- it remains structural.

**Manus's todo.md approach**: The agent creates a `todo.md` file and continuously updates it as tasks progress. "By constantly rewriting the todo list, Manus is reciting its objectives into the end of the context. This pushes the global plan into the model's recent attention span." Without this, goal drift is common across the ~50 tool calls in an average task.

**The evolution to planner sub-agents**: Manus discovered that todo.md consumed **~30% of all actions** just updating the file. Their evolved approach: a dedicated planner sub-agent returns a structured Plan object, injected into context only when needed -- achieving the same attention-anchoring benefit at lower token cost.

**Augment Code's typed task state machines** formalize this pattern further. Tasks are first-class typed entities with strict lifecycles (`todo` -> `in_progress` -> `finished`/`cancelled`). The tasklist carries the long-horizon plan while each individual task stays within a manageable context window. Real-time UI streaming shows status changes as they happen.

**Practical attention management principles:**

1. **Position critical information at the beginning and end** of the context window (exploit the U-shaped curve)
2. **Periodically re-inject goals and plans** near the end of context (recency bias)
3. **Use structured formats** (tables, XML tags, numbered lists) to create clear information boundaries
4. **Separate reference material from active instructions** -- put reference in the middle, active instructions at beginning and end

### Strategy 8: Error preservation and learning signals

One of the most counterintuitive but effective practices: **leave failed actions and error traces in the context.** Manus states: "When the model sees a failed action -- and the resulting observation or stack trace -- it implicitly updates its internal beliefs, shifting its prior away from similar actions and reducing the chance of repeating the same mistake."

**Academic validation -- the Reflexion framework** (NeurIPS 2023) demonstrated that agents using verbal self-reflection on errors improved dramatically: **91% pass@1 on HumanEval** coding benchmarks (surpassing GPT-4's 80%), with significant improvements across sequential decision-making, coding, and reasoning tasks. The process: attempt task -> receive feedback -> generate verbal reflection on failure -> store reflection in episodic memory -> use reflections on next attempt.

**JetBrains research** found that deleting conversation turns containing errors "can interrupt reasoning, as well as hurt performance."

**Implementation principles:**

- **Don't retry silently** -- preserve the failed action and its error in context
- **Don't clear error outputs** -- they are negative examples that prevent repetition
- **Annotate errors with structured context** about what went wrong and why
- **Distinguish genuine errors from hallucinated ones** -- preserve real error signals (stack traces, API failures, validation errors) while correcting hallucinated errors that could poison context
- **Errors are data about the environment** -- "file not found" tells the model the file doesn't exist at that path

Manus considers error recovery "one of the clearest indicators of true agentic behavior."

**The "don't get few-shotted" warning** relates directly to error preservation. Manus warns: when conversation history is filled with uniform, repetitive patterns, the model falls into **repetitive mimicry** -- it gets "few-shotted" by its own prior actions. If an agent has executed 10 steps all following "think -> search -> read -> respond," the 11th step will almost certainly follow the same pattern even if a completely different approach is needed.

Mitigation: diversity in early actions, explicit strategy-switching prompts, and breaking patterns through varied formatting. Errors naturally introduce variety into the conversation pattern, which is another reason they help.

---

## Part 4: How Industry Leaders Architect Context

### Anthropic's production philosophy

Anthropic's approach centers on **progressive minimalism**: start with the smallest possible set of high-signal tokens and expand only when needed. Their four pillars:

1. **System prompts at the "right altitude"** -- between brittle hardcoded logic and vague guidance. "Specific enough to guide behavior effectively, yet flexible enough to provide the model with strong heuristics."
2. **Minimal viable tool sets** -- every tool justifies its existence
3. **Diverse canonical examples over exhaustive edge-case lists** -- "For an LLM, examples are the 'pictures' worth a thousand words."
4. **Cyclically refined message history** during agentic loops

**Claude Code's modular system prompt** consists of 110+ strings conditionally assembled based on environment and configuration, consuming ~23,000 tokens (~11% of a 200K window). This is delivered in the order: `tools` -> `system` -> `messages`. Context includes: core instructions (~156 tokens base), 28+ built-in tool definitions, CLAUDE.md files (full), auto-memory MEMORY.md (first 200 lines), conditional rules, MCP server tool definitions, skill descriptions (names only until invoked), and conversation history.

**For long-running agents** spanning multiple context windows, Anthropic recommends a **two-agent architecture**: an Initializer Agent creates comprehensive feature requirements in JSON (not Markdown -- models are less likely to inappropriately overwrite JSON), progress files, and an initial git commit. A Coding Agent reads progress files and git history at each session start, implementing one feature at a time. The key insight: "Finding a way for agents to quickly understand the state of work when starting with a fresh context window."

**Extended thinking integration**: Previous thinking blocks are automatically stripped from context window calculations -- they don't consume the window for future turns. When tool results are posted, the full thinking block (with cryptographic signatures) must be included, but after the tool cycle completes, thinking blocks can be dropped. Adaptive thinking offers four effort levels (low/medium/high/max) with a default budget of 31,999 tokens.

### Manus's battle-tested principles

Manus rebuilt their agent framework **five times** since March 2025. Their principles distill millions of user interactions into six rules:

1. **Design around the KV cache** -- append-only, deterministic serialization, 54-62% hit rates
2. **Mask don't remove tools** -- logit masking preserves cache while controlling tool availability
3. **Use the file system as context** -- unlimited, persistent, directly operable by the agent
4. **Manipulate attention through recitation** -- push critical context to the end via todo.md or planner sub-agents
5. **Keep errors in context** -- they are the agent's learning signals
6. **Don't get few-shotted** -- break repetitive patterns to prevent mimicry

Their strategic bet: **context engineering over fine-tuning**. "This allows us to ship improvements in hours instead of weeks, and kept our product orthogonal to the underlying models." This portability -- the ability to swap underlying models while maintaining agent quality -- proved to be a decisive competitive advantage.

### OpenAI's first-class primitives

OpenAI treats compaction as infrastructure, not a hack. Their approach is uniquely layered:

**Three agentic primitives for long-running agents:**
1. **Skills** -- Reusable, versioned instructions for reliable task execution. Codex can implicitly choose a skill when a task matches the description.
2. **Upgraded shell tool** -- Container with controlled internet access
3. **Server-side compaction** -- Automatic during long runs, encrypted compaction items carry forward state

**Agents SDK architecture** distinguishes:
- **Local context** (`RunContextWrapper`) -- Developer-defined Python objects for dependencies, database connections, etc. Critical: **never sent to the LLM**. Purely local.
- **Agent context** -- System prompts, inputs, tool results, retrieved data. This is what the model sees.

**Session memory management**: `OpenAIResponsesCompactionSession` wraps sessions and auto-compacts after each turn based on `should_trigger_compaction`. State-based memory for personalization uses structured authoritative fields with clear precedence (global vs session), supports belief updates instead of fact accumulation, and enables deterministic decision-making without fragile semantic search. Memory injection uses YAML frontmatter + Markdown notes.

**Handoff mechanisms**: `RunConfig.nest_handoff_history` collapses prior transcripts into a single summary wrapped in `<CONVERSATION HISTORY>` blocks, reducing token usage across multi-agent handoffs.

**ChatGPT's four-layer context system:**
1. **Session metadata** -- Device, browser, timezone, subscription level (injected once per session)
2. **Long-term facts** -- All stored user facts appear in every message
3. **Conversation summaries** -- Lightweight digests of recent conversations
4. **Current session messages** -- Full history of the current conversation

When space runs low, current session messages are trimmed first. Permanent facts and recent summaries are prioritized.

### Google ADK's compiler metaphor

Google ADK formalizes context assembly as a compiler pipeline with the strongest architectural separation in the industry:

**Zone architecture** divides the context window into stable prefixes (cached) and variable suffixes (latest turn, new outputs). The `static_instruction` primitive guarantees immutability for system prompts.

**State scoping** uses prefixes: no prefix = session-scoped, `user:` = user-scoped, `app:` = app-scoped, `temp:` = temporary (never persisted).

**Artifacts as durable state** -- named, versioned binary data with ephemeral expansion. Loaded into working context via `LoadArtifactsTool` only when needed, then offloaded after the model call completes.

**Multi-agent patterns provide three workflow primitives:**
- **SequentialAgent** -- Sub-agents execute in order, output saved to shared state
- **ParallelAgent** -- Concurrent execution in separate threads, write to unique state keys
- **LoopAgent** -- Sequential loop until `max_iterations` or `escalate=True`

Plus two interaction patterns: agents-as-tools (specialist treated as function) and agent transfer (full hierarchical handoff with session view inheritance).

**Compaction** is invocation-count-based with configurable overlap: `compaction_interval=3` triggers every 3 events, `overlap_size=1` ensures continuity at boundaries. A cheaper model (e.g., Gemini Flash) can handle summarization.

### Cognition (Devin) -- Single agent, superior context

Cognition represents the counter-position to multi-agent architectures:

**Core thesis**: Multi-agent architectures produce fragile systems. Invest in making a single agent excellent through context engineering instead.

**Key innovations:**
- **Fine-tuned compression model** -- A domain-specific model trained to compress action history and conversation into key details, events, and decisions. Not generic summarization but purpose-built context compression.
- **Fine-tuned context selection model** -- Determines what enters the context window, underscoring how much investment goes into the selection stage of the pipeline.
- **Sonnet 4.5 context awareness discovery** -- Cognition found that Claude Sonnet 4.5 was "the first model that is aware of its own context window" -- it burns through parallel tool calls faster early and takes a cautious approach as it nears the limit.

### Other production implementations

**Cursor** uses a workspace semantic index (built on first project open), `.cursor/rules/` with MDC format (Markdown + YAML frontmatter with `description`, `globs`, and `alwaysApply` fields), and three context modes: Composer (cross-cutting changes), Inline Edit (surgical modifications), and Codebase (semantic search across the full project).

**Windsurf (Codeium)** runs every interaction through a six-stage pipeline: load rules -> load memories -> read open files -> run codebase retrieval (vector search) -> read recent actions (edits, commands, clipboard, terminal) -> assemble final prompt. Its "Flows" feature maintains deep awareness of actions and development patterns over time. When you correct Windsurf's output, it stores that correction as a persistent memory.

**Augment Code** provides a Context Engine that emphasizes typed task state machines with strict lifecycles. Tasks are first-class data entities, enabling cross-session persistence, sub-agent verification, and programmatic analytics.

---

## Part 5: Design Methodology

This section addresses the most common gap in context engineering writing: not what strategies exist, but **how to systematically design, build, and evolve a context system**.

### Step-by-step context system design

**Step 1: Define purpose and constraints.** Before writing code, articulate:
- What is the agent's goal? (Coding, customer service, research, general purpose)
- What is the target context window? (200K, 1M, or smaller model windows)
- What is the latency budget? (Interactive chat vs. background processing)
- What is the cost budget per task? (Determines caching and compaction aggressiveness)

**Step 2: Map context sources.** Identify all information the agent might need:
- Static instructions (system prompt, identity, rules)
- Dynamic instructions (conditional rules, loaded skills)
- User input (current turn, conversation history)
- Environmental context (file contents, search results, tool outputs)
- Persistent memory (cross-session knowledge, user preferences)
- Retrieved knowledge (RAG, knowledge bases, documentation)
- Tool definitions (available actions)
- Output format constraints (structured output schemas)

**Step 3: Classify by loading strategy.** For each source, decide: always-loaded, conditionally-loaded, JIT-loaded, or never-pre-loaded. Use the budget allocation table from Part 2 as a guide.

**Step 4: Design the assembly pipeline.** Build the six-stage pipeline (collection -> filtering -> prioritization -> compression -> assembly -> caching) with named processors at each stage. Make the pipeline observable: log what enters and exits each stage.

**Step 5: Define compaction and eviction policies.** Decide:
- When does compaction trigger? (Token threshold, invocation count, or manual)
- What gets compacted first? (Tool outputs before conversation, compaction before summarization)
- What is always preserved? (Active goals, unresolved errors, architectural decisions)
- Is hand-off preferable to compaction? (For very long tasks)

**Step 6: Implement isolation boundaries.** For multi-agent systems:
- Which agents share context? Which get fresh windows?
- What flows between parent and child? (Full context, summary, or just instructions)
- How are handoffs narrated to prevent hallucination?
- Can sub-agents spawn further sub-agents? (Usually no -- prevent infinite nesting)

**Step 7: Configure caching.** Structure prompts for maximum cache hits:
- System instructions and tool definitions at the top (stable prefix)
- Memory and retrieved context in the middle
- Current turn and recent history at the end (variable suffix)
- Ensure deterministic serialization throughout

### Trade-off analysis framework

Context engineering involves fundamental tensions. Use this decision framework:

| Trade-off | When to favor A | When to favor B |
|---|---|---|
| Compaction vs. Full history | Long sessions (>50 turns), cost-sensitive | Short sessions, accuracy-critical tasks |
| Isolation vs. Shared context | Parallelizable tasks, clean task boundaries | Tightly coupled tasks, decisions with dependencies |
| Many tools vs. Few tools | Diverse task types, clear tool boundaries | Single domain, tools with semantic overlap |
| RAG vs. Direct navigation | Large knowledge bases, stable content | Dynamic codebases, frequently changing content |
| Eager loading vs. JIT | Small, critical context (<2K tokens) | Large, conditionally-needed context |
| Summarization vs. Hand-off | Continuous task requiring full history awareness | Task naturally decomposes into phases |

### Context governance

For teams building production agents, context requires governance:

**Version control for prompts.** Use semantic versioning (major.minor.patch):
- **Major**: Breaking or structural change in prompt behavior
- **Minor**: Additive or behavioral improvements
- **Patch**: Small refinements or wording tweaks

**Ownership.** Assign stewards to major context domains with defined approval thresholds. Domain experts edit prompts through a UI while engineers maintain deployment governance.

**Security classification.** Enforce PII, regulated, and confidential classifications on context components. Never load sensitive data into context without explicit authorization.

**Audit trail.** Maintain full auditability of who changed what, when, and why. Platforms like MLflow Prompt Registry, PromptLayer, and LangFuse provide this.

**The 12-Factor Agent framework** (Dex Horthy, HumanLayer) adapts 12-Factor App principles to LLM systems. Key principles: own your prompts (version-control all prompts), control your control flow (don't hand execution to opaque framework loops), treat context as the new memory, keep agents stateless with external state management. Core insight: "Most AI agents that succeed in production aren't magical autonomous beings -- they're mostly well-engineered traditional software, with LLM capabilities carefully sprinkled in at key points."

---

## Part 6: Evaluation and Operations

### Testing context quality

**Metrics for context engineering:**

| Metric | What it measures | Target |
|---|---|---|
| **Task completion rate** | Percentage of tasks successfully completed | >90% for production |
| **Tokens per task** | Total tokens consumed (not per request) | Minimize while maintaining quality |
| **KV cache hit rate** | Percentage of tokens served from cache | 54-62% (Manus production baseline) |
| **Context utilization rate** | Percentage of budget actively used | 60-80% |
| **Compaction-to-requery ratio** | How often compacted info must be re-fetched | Lower is better |
| **Hallucination rate** | Frequency of fabricated information | <5% for production |
| **Context relevancy** | How relevant retrieved context is to the query | Measure via automated evaluators |
| **Contextual precision** | Whether relevant items are ranked higher than irrelevant ones | Higher is better |

**Eval-driven development.** Anthropic recommends building evals to define planned capabilities before agents can fulfill them: "Start with 20-50 simple tasks drawn from real failures. Early changes have large effect sizes, so small sample sizes suffice."

**A/B testing for context strategies:**
1. Version prompts and define hypotheses tied to measurable outcomes
2. Generate representative synthetic scenarios across personas and edge cases
3. Run evaluators on session and span levels with human checks for ambiguous tasks
4. Compare variants on completion rate, instruction adherence, and hallucination detection
5. Use multi-armed bandit (MAB) for dynamic traffic allocation if scale permits

### Debugging context failures

**Start with "what did the model see?" not "what did the model do wrong?"** Most agent failures in production are context failures.

**Microsoft's AgentRx framework** provides systematic debugging with a nine-category failure taxonomy:
- Plan adherence failure (agent ignored its steps)
- Invention of new information (hallucination)
- Tool execution errors
- Context window overflow
- And five additional categories

Each failure is diagnosed step-by-step with evidence, and an LLM judge predicts the critical failure step and root-cause category.

**Practical debugging techniques:**

1. **Context diff analysis** -- Compare the exact context sent on successful vs. failed runs
2. **Temporal analysis** -- Compare executions for similar queries to find where decision points diverge
3. **Token usage monitoring** -- Track context utilization per request to detect bloat
4. **Session correlation** -- Attach user IDs and session IDs to spans to track how failures emerge from accumulated context
5. **Self-healing** -- When a tool call fails, capture the error and feed it back (see Strategy 8)

**Observability tools:** LangSmith, LangFuse, MLflow capture the exact prompt sent, model response, token usage, latency, and tool/retrieval steps. Context attributes (user_id, session_id, metadata) propagate to every observation.

### The context development lifecycle (CDLC)

Four stages forming a continuous loop:

1. **Generate** -- Convert implicit organizational knowledge into structured specifications agents can act on
2. **Evaluate** -- Measure whether the context produces desired outcomes using evals
3. **Distribute** -- Deploy context to agents and systems
4. **Observe** -- Capture detailed traces of production runs (inputs, reasoning steps, tools called, outputs)

### The context flywheel

The CDLC becomes a compounding advantage when run iteratively: better context -> better agent output -> better signals -> better context. Each cycle compounds.

By the tenth cycle, agents follow instructions better and the team codes differently -- faster, more consistent, with fewer corrections. The flywheel "is what CI/CD was for deployment: the mechanism that turns a good practice into a compounding advantage."

### Evolution stages

Context systems evolve through distinct phases:

| Stage | Characteristics |
|---|---|
| **1. Static prompts** | Hand-written, rarely updated |
| **2. Dynamic context assembly** | RAG, tool integration, conditional loading |
| **3. Memory-augmented** | Persistent state across sessions |
| **4. Self-optimizing** | Agent-driven context management with compaction |
| **5. Multi-agent orchestrated** | Distributed context with isolation boundaries |
| **6. Harness-engineered** | Scaffolding, feedback loops, architectural constraints |

---

## Part 7: Anti-Patterns and Adversarial Concerns

### Anti-patterns

Seven recurring failure modes emerge across production systems:

1. **Context dumping** -- Placing massive payloads directly into context rather than using file-system references. Solution: externalize and keep pointers.

2. **Timestamp poisoning** -- Including precise timestamps at the beginning of system prompts, which invalidates the cache on every request. Solution: move volatile data to the end of context.

3. **Tool sprawl** -- Wrapping every API endpoint as a separate tool instead of building task-oriented interfaces. Microsoft found tool spaces can degrade performance by **up to 85%**. Solution: consolidate to <20 tools, use tool search for larger catalogs.

4. **Premature compaction** -- Compacting mid-complex-task and losing intricate state dependencies. Solution: compact at natural breakpoints, or use hand-off instead.

5. **Serialization non-determinism** -- Non-deterministic JSON key ordering silently breaking cache across requests. Solution: enforce stable serialization throughout the codebase.

6. **Few-shot self-poisoning** -- Uniform conversation patterns causing the model to fall into repetitive mimicry. Solution: introduce early diversity, explicit strategy-switching, and pattern-breaking formatting.

7. **Dynamic tool modification** -- Adding or removing tools mid-conversation, invalidating the KV cache. Solution: keep all tools in the prompt, use logit masking or tool search for selection control.

### Adversarial concerns

**Context poisoning** occurs when compromised, outdated, or irrelevant information enters the context window, leading to degraded responses, hallucinations, or perpetuated errors.

**Attack mechanisms:**
- Adversarial embeddings that pull retrieval toward poisoned documents
- Memory poisoning that corrupts persistent memory feeding future windows
- Prompt injection via tool results that contain adversarial instructions
- Context pollution in multi-agent systems where irrelevant details accumulate

**Defense techniques:**

1. **Architectural defenses** -- External AI gateways, vector-level RBAC, input/output guardrails that function independently of the LLM
2. **Knowledge base enrichment** -- More diverse and redundant correct-answer texts passively reduce poisoning impact
3. **Memory integrity enforcement** -- Real-time runtime controls triggered by metric monitoring, adversarial tests, snapshots/rollback, version control, human review for high-risk actions
4. **Controlled variation** -- Alternate phrasing and formatting changes to break problematic repetitive patterns
5. **Trust scores for context entries** -- Weight context sources by reliability, age, and provenance
6. **Per-tenant namespaces** -- Isolate context in multi-tenant systems to prevent cross-contamination

---

## Part 8: Conclusion

Context engineering has matured from an informal collection of tricks into a genuine engineering discipline with shared vocabulary, documented patterns, production-validated strategies, and systematic design methodologies. The field's trajectory is clear: as models grow more capable, the bottleneck shifts from model intelligence to **information architecture** -- what the model sees matters more than what the model knows.

### Key insights from this research

**1. The eight strategies form a complementary stack, not a menu.** Production systems combine all eight based on workload characteristics. LangChain's four operations (Write, Select, Compress, Isolate) map cleanly onto them, but attention management and error preservation add dimensions that pure information management doesn't capture.

**2. Compaction and caching are fundamentally in tension**, and the most sophisticated production systems (Manus, OpenAI Codex) design their entire architecture around managing this trade-off rather than treating them as independent optimizations. Sourcegraph Amp's decision to retire compaction entirely in favor of hand-off suggests this tension may be irreconcilable at scale.

**3. The shift from inline planning to dedicated planner sub-agents** (Manus's evolution from ~30% token overhead to structured Plan objects, Augment Code's typed task state machines) suggests that many "context engineering" problems are better solved by architectural changes than by prompt-level interventions.

**4. Context engineering's portability advantage** -- the ability to swap underlying models while maintaining agent quality -- may be its most strategically important property. Manus: "This allows us to ship improvements in hours instead of weeks, and kept our product orthogonal to the underlying models."

**5. Harness engineering represents the next frontier.** OpenAI's February 2026 methodology -- where custom linters inject remediation instructions directly into agent context, and architectural layering is enforced by tooling -- points toward a future where context engineering is not just about what information to include, but about engineering the entire environment that produces that information.

**6. The Context Flywheel is the compounding mechanism.** Better context -> better agent output -> better signals -> better context. Teams that operationalize this cycle -- through the Context Development Lifecycle of Generate -> Evaluate -> Distribute -> Observe -- turn a good practice into a sustainable competitive advantage.

**7. Simplicity wins.** The most counterintuitive finding across all production teams: reducing tools (Vercel), removing management agents (Schmid's Part 2), using static AGENTS.md over dynamic skills (Vercel), and treating the file system as the context store (Manus) -- simplification consistently outperforms sophistication. The right amount of complexity is the minimum needed for the current task.

The teams that master context engineering -- treating it as systems engineering with formal design processes, evaluation frameworks, and operational lifecycles -- will build the agents that actually work in production.

---

## Appendix: Sources and References

### Foundational Publications

- Karpathy, A. (June 25, 2025). [Context engineering definition](https://x.com/karpathy/status/1937902205765607626). X/Twitter.
- Anthropic. (September 2025). [Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents).
- Anthropic. (December 2024). [Building effective AI agents](https://www.anthropic.com/research/building-effective-agents).
- Anthropic. (2026). [Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents).
- Ji, Y. "Peak" (July 18, 2025). [Context engineering for AI agents: Lessons from building Manus](https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus). Manus Blog.
- Schmid, P. (2025). [The new skill in AI is not prompting, it's context engineering](https://www.philschmid.de/context-engineering). Part 1 and [Part 2](https://www.philschmid.de/context-engineering-part-2).
- Chase, H. (June 23, 2025). [Context engineering for agents](https://blog.langchain.com/context-engineering-for-agents/). LangChain Blog.
- Yan, W. (June 12, 2025). [Don't build multi-agents](https://cognition.ai/blog/dont-build-multi-agents). Cognition Blog.
- Willison, S. (June 27, 2025). [Context engineering](https://simonwillison.net/2025/jun/27/context-engineering/).

### Platform Documentation

- [Claude Code -- How it works](https://code.claude.com/docs/en/how-claude-code-works)
- [Claude Code -- Memory](https://code.claude.com/docs/en/memory)
- [Claude Code -- Sub-agents](https://code.claude.com/docs/en/sub-agents)
- [Claude API -- Prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching)
- [Claude API -- Compaction](https://platform.claude.com/docs/en/build-with-claude/compaction)
- [Claude API -- Context windows](https://platform.claude.com/docs/en/build-with-claude/context-windows)
- [Claude API -- Tool search tool](https://platform.claude.com/docs/en/agents-and-tools/tool-use/tool-search-tool)
- [OpenAI Codex -- AGENTS.md](https://developers.openai.com/codex/guides/agents-md/)
- [OpenAI -- Compaction API](https://developers.openai.com/api/docs/guides/compaction/)
- [OpenAI -- Prompt caching](https://platform.openai.com/docs/guides/prompt-caching)
- [OpenAI -- A practical guide to building agents](https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/)
- [OpenAI Agents SDK -- Context management](https://openai.github.io/openai-agents-python/context/)
- [OpenAI -- Harness engineering](https://openai.com/index/harness-engineering/)
- [OpenAI -- Shell + Skills + Compaction tips](https://developers.openai.com/blog/skills-shell-tips/)
- [AGENTS.md specification](https://agents.md/)
- [Google ADK Documentation](https://google.github.io/adk-docs/)
- [Google ADK -- Context](https://google.github.io/adk-docs/context/)
- [Google ADK -- Compaction](https://google.github.io/adk-docs/context/compaction/)
- [Google ADK -- Multi-agent systems](https://google.github.io/adk-docs/agents/multi-agents/)
- [Gemini -- Context caching](https://ai.google.dev/gemini-api/docs/caching)
- [Gemini -- Long context](https://ai.google.dev/gemini-api/docs/long-context)
- [Gemini CLI -- GEMINI.md](https://geminicli.com/docs/cli/gemini-md/)

### Research Papers

- Liu, N. F., et al. (2023). [Lost in the middle: How language models use long contexts](https://arxiv.org/abs/2307.03172). Stanford/UC Berkeley.
- Google Research. (2024). [Found in the middle: Calibrating positional attention bias](https://arxiv.org/abs/2406.16008).
- Shinn, N., et al. (NeurIPS 2023). [Reflexion: Language agents with verbal reinforcement learning](https://arxiv.org/abs/2303.11366).
- Gemini Team. (2024). [Gemini 1.5 technical report](https://arxiv.org/abs/2403.05530).
- Packer, C., et al. (2023). [MemGPT: Towards LLMs as operating systems](https://arxiv.org/abs/2310.08560).
- Chroma. (2025). [Context rot: How increasing input tokens impacts LLM performance](https://research.trychroma.com/context-rot).
- Microsoft Research. (2025). [Tool-space interference in the MCP era](https://www.microsoft.com/en-us/research/blog/tool-space-interference-in-the-mcp-era-designing-for-agent-compatibility-at-scale/).
- Microsoft Research. (2025). [AgentRx: Systematic debugging for AI agents](https://www.microsoft.com/en-us/research/blog/systematic-debugging-for-ai-agents-introducing-the-agentrx-framework/).

### Production Case Studies and Additional Sources

- [Spotify: Context engineering for background coding agents](https://engineering.atspotify.com/2025/11/context-engineering-background-coding-agents-part-2)
- [Vercel: We removed 80% of our agent's tools](https://vercel.com/blog/we-removed-80-percent-of-our-agents-tools)
- [Vercel: AGENTS.md outperforms skills](https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals)
- [Factory.ai: Compressing context](https://factory.ai/news/compressing-context) and [Evaluating compression](https://factory.ai/news/evaluating-compression)
- [Sourcegraph Amp: Compaction retired for handoff](https://tessl.io/blog/amp-retires-compaction-for-a-cleaner-handoff-in-the-coding-agent-context-race/)
- [Augment Code: How we built Tasklist](https://www.augmentcode.com/blog/how-we-built-tasklist)
- [Cognition: Rebuilding Devin for Sonnet 4.5](https://cognition.ai/blog/devin-sonnet-4-5-lessons-and-challenges)
- [Zep/Graphiti: Temporal knowledge graphs](https://arxiv.org/abs/2501.13956)
- [12-Factor Agents](https://github.com/humanlayer/12-factor-agents)
- [Context Development Lifecycle (CDLC)](https://jedi.be/blog/2026/context-development-lifecycle/)
- [The Context Flywheel](https://jedi.be/blog/2026/context-flywheel/)
- [Martin Fowler: Context engineering for coding agents](https://martinfowler.com/articles/exploring-gen-ai/context-engineering-coding-agents.html)
- [Jeremy Daly: Context engineering for commercial agent systems](https://www.jeremydaly.com/context-engineering-for-commercial-agent-systems/)
- [Awesome Context Engineering (GitHub)](https://github.com/Meirtz/Awesome-Context-Engineering)
- [Google Developers Blog: Architecting context-aware multi-agent framework](https://developers.googleblog.com/architecting-efficient-context-aware-multi-agent-framework-for-production/)
- [Google Developers Blog: Developer's guide to multi-agent patterns in ADK](https://developers.googleblog.com/developers-guide-to-multi-agent-patterns-in-adk/)
- [KV-Cache aware prompt engineering](https://ankitbko.github.io/blog/2025/08/prompt-engineering-kv-cache/)
