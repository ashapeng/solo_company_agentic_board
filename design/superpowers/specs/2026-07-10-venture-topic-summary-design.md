# Venture Topic Summary — Design Spec

**Date:** 2026-07-10  
**Status:** Approved for planning (scope locked to item 1 of discovery analysis follow-up)  
**Companion plan:** `design/superpowers/plans/2026-07-10-venture-topic-summary.md`

## Problem

`server/discovery/` already fetches weekly raw posts from Reddit, HN, YouTube,
GitHub, and gov sources into `data/discovery/raw/{ISO-week}/`. Nothing in-repo
turns those posts into a **venture idea topic list** with evidence citations and
resource links. `CLAUDE.md` names `/venture-scan` as the analysis step, but that
command does not exist.

## Goal (this slice only)

Given one ISO week of discovery raw JSON, produce a **ranked topic summary**:

1. A short list of venture-relevant **pain / opportunity topics**
2. Each topic includes a **summary**, **evidence** (cited posts), and **resources** (URLs + channel metadata)
3. Output is persisted next to the raw week and printable via CLI

Out of scope for this slice: board auto-deliberation, initiative creation,
watchlist auto-tuning, UI, cron scheduling, full product/MVP specs, RICE scoring
of build features.

## Non-goals

- Changing channel fetchers or watchlist schema
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
  prepare_corpus()           # truncate, rank by engagement, budget tokens
        │
        ▼
  synthesize_topics()        # one LLM call via board.query_llm
        │
        ▼
  validate + attach evidence # ensure every citation maps to a real post id
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
  "week": "2026-W28",
  "generated_at": "2026-07-10T00:00:00+00:00",
  "model": "gemini/gemini-2.5-flash",
  "post_count": 120,
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
- Every `post_key` / URL in evidence must exist in the loaded corpus (validator
  drops or repairs hallucinated citations)
- `pain_class` ∈ `{hair_on_fire, important, nice_to_solve, opportunity}`
- `signal_strength` ∈ `[0, 1]` — model estimate; also recompute a deterministic
  `engagement_score` from cited posts for sorting tie-break

## Ranking

Primary sort: `signal_strength` desc, then sum of cited post `score+comments`
desc. Persist both so humans can re-sort.

## LLM usage

- Reuse `server.board.llm.query_llm`
- Default model: classifier-class cheap model via new
  `get_discovery_analyze_model()` → env `DISCOVERY_ANALYZE_MODEL` defaulting to
  `get_classifier_model()` (`gemini/gemini-2.5-flash`)
- Single synthesis call with structured JSON instruction; temperature `0.2`
- Corpus prep caps input: top N posts by `score+comments` (default 80), body
  truncated to 400 chars, total prompt soft-cap ~60k chars

## CLI

```bash
uv run python -m server.discovery analyze [--week ISO-Wxx] [--data-dir PATH] \
  [--max-topics 8] [--max-posts 80] [--model MODEL] [--dry-run]
```

- Default week: latest week with a `manifest.json`
- `--dry-run`: print markdown to stdout, do not write files
- Exit non-zero if no posts for the week or LLM/parse hard-fails

Also extend `status` to mention whether `analyzed/{week}/topics.json` exists.

## Storage layout

```
data/discovery/
├── seen_ids.json
├── raw/{week}/…
└── analyzed/{week}/
    ├── topics.json
    └── topics.md
```

## Testing strategy

- Unit: corpus prep, schema validation, citation repair, markdown render
- Integration: CLI `analyze` with mocked `query_llm` over fake-channel fixtures
- No live LLM in default CI

## Success criteria

1. After `fetch` (or with fixture raw data), `analyze` writes valid
   `topics.json` + `topics.md`
2. Every evidence URL resolves to a post in that week’s raw files
3. Markdown is readable as a founder brief without opening JSON
4. Discovery channel modules remain free of LLM imports
