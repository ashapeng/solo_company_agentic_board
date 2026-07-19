# Venture Topic Summary — Design Spec

**Date:** 2026-07-10  
**Status:** Revised for IDE-agent execution (scope locked to item 1 of discovery analysis follow-up)
**Companion plan:** `design/superpowers/plans/2026-07-10-venture-topic-summary.md`

## Problem

`server/discovery/` already fetches weekly raw posts from Reddit, HN, YouTube,
GitHub, and gov sources into `data/discovery/raw/{ISO-week}/`. Nothing in-repo
turns those posts into a **venture idea topic list** with evidence citations and
resource links. `CLAUDE.md` names `/venture-scan` as the analysis step, but that
command does not exist.

## Goal (this slice only)

Given one ISO week of discovery raw JSON, have the IDE coding agent produce a
**ranked topic summary** without invoking any model through this project's
provider clients:

1. A short list of venture-relevant **pain / opportunity topics**
2. Each topic includes a **summary**, **evidence** (cited posts), and **resources** (URLs + channel metadata)
3. Output is persisted next to the raw week and printable via CLI

Out of scope for this slice: board auto-deliberation, initiative creation,
watchlist auto-tuning, UI, cron scheduling, full product/MVP specs, RICE scoring
of build features.

## Non-goals

- Implementing new Reddit or YouTube API adapters without platform approval
- Putting LLM calls inside `channels/` (keep that domain LLM-free)
- Replacing board deliberation — this only prepares a human/LLM-readable brief
- Cross-week trend analysis (single-week first)

## Architecture

```
data/discovery/raw/{week}/*.json
        │
        ▼
  load_week_posts()          # store helper, pure I/O
        │
        ▼
  prepare_agent_bundle()     # truncate, rank, and write a portable input bundle
        │
        ▼
  IDE coding agent           # reads bundle and writes candidate topics JSON
        │
        ▼
  validate_agent_output()    # deterministic schema and citation validation
        │
        ▼
  write analyzed/{week}/     # topics.json + topics.md
```

Analysis lives in a new package `server/discovery/analyze/` so fetch stays
LLM-free and analysis can grow (clustering, multi-pass) without touching
channels.

## Output schema

### `topics.json`

```json
{
  "schema_version": 1,
  "week": "2026-W28",
  "generated_at": "2026-07-10T00:00:00+00:00",
  "producer": {
    "kind": "ide_coding_agent",
    "name": "codex",
    "run_id": "optional-agent-run-id"
  },
  "bundle_digest": "sha256-of-canonical-selected-records",
  "post_count": 120,
  "selected_post_count": 80,
  "topics": [
    {
      "id": "yarn-inventory-chaos",
      "title": "Yarn / material inventory is unmanageable",
      "summary": "Makers track stock across photos, notes, and broken spreadsheets…",
      "who": "Independent knitters and small Etsy sellers",
      "pain_class": "hair_on_fire",
      "signal_strength": 0.82,
      "evidence": [
        {
          "post_key": "reddit:abc123",
          "channel": "reddit",
          "title": "I wish there was a tool for tracking yarn inventory",
          "url": "https://reddit.com/…",
          "score": 42,
          "comments": 18,
          "normalized_engagement": 0.94,
          "created_at": "2026-07-08T12:00:00Z",
          "retrieved_at": "2026-07-10T00:00:00Z",
          "quote": "Spreadsheets keep breaking, photos everywhere"
        }
      ],
      "resources": [
        {
          "label": "r/knitting thread",
          "url": "https://reddit.com/…",
          "kind": "discussion"
        }
      ]
    }
  ],
  "discarded_noise_notes": "Optional short note on what was ignored"
}
```

### `topics.md`

Human-readable mirror of the same data: ranked list, each topic with summary,
who, pain class, evidence bullets (linked), and resources.

### Constraints

- Max **8** topics per week (default; CLI override `--max-topics`)
- Each topic must cite **≥ 2** evidence posts when the corpus has ≥ 2 posts;
  if the week has only 1 post, allow 1 citation
- Every `post_key` / URL in evidence must exist in the loaded corpus; the
  validator rejects hallucinated citations and never repairs them with a model
- `pain_class` ∈ `{hair_on_fire, important, nice_to_solve, opportunity}`
- `signal_strength` ∈ `[0, 1]` — IDE-agent estimate; also recompute a deterministic
  `engagement_score` from cited posts for sorting tie-break

## Ranking

Primary sort: `signal_strength` desc, then sum of cited within-channel
normalized engagement desc, then topic ID. Persist score so humans can re-sort.

## IDE agent boundary

- Discovery code MUST NOT import `server.board.llm`, provider SDKs, or call a
  model endpoint.
- `prepare` writes a self-contained JSON bundle plus agent instructions. The
  founder invokes the IDE coding agent to read that bundle and write candidate
  `topics.json`.
- `import` performs deterministic schema, post-key, URL, and quote validation
  before accepting the agent output. Invalid citations are rejected rather
  than repaired by another model.
- The bundle caps input to the top N posts by normalized engagement (default
  80), truncates bodies to 400 characters, and uses a soft cap of about 60k
  characters.
- Board models may later deliberate on an accepted topic, but they are not part
  of collection or topic generation.

## CLI

```bash
uv run python -m server.discovery prepare [--week ISO-Wxx] [--data-dir PATH] \
  [--max-posts 80]
uv run python -m server.discovery import-topics CANDIDATE.json \
  [--week ISO-Wxx] [--data-dir PATH] [--max-topics 8] [--dry-run]
```

- Default week: latest week with a `manifest.json`
- `prepare` never calls a model; it prints the bundle path for the IDE agent.
- `--dry-run`: print validated markdown to stdout, do not write files.
- Exit non-zero if no posts exist or candidate output fails validation.

Also extend `status` to mention whether `analyzed/{week}/topics.json` exists.

## Storage layout

```
data/discovery/
├── seen_ids.json
├── raw/{week}/…
├── prepared/{week}/
│   ├── agent_bundle.json
│   └── AGENT_INSTRUCTIONS.md
└── analyzed/{week}/
    ├── topics.json
    └── topics.md
```

## Testing strategy

- Unit: corpus prep, schema validation, citation repair, markdown render
- Integration: `prepare` + `import-topics` over fake-channel fixtures
- Architecture guard: every module under `server/discovery/` remains free of
  project/provider LLM imports

## Success criteria

1. After `fetch` (or with fixture raw data), `prepare` plus an IDE-agent
   candidate and `import-topics` writes valid `topics.json` + `topics.md`
2. Every evidence URL resolves to a post in that week’s raw files
3. Markdown is readable as a founder brief without opening JSON
4. All discovery modules remain free of project/provider LLM imports
5. Topic generation is attributable to an IDE coding-agent run
