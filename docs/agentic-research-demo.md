# Agentic Research Loop — Demo

Phase 1 demo of board members running real research with tool-use loops.

## Prerequisites

```bash
uv sync
uv run playwright install chromium
```

Set API keys in `.env`:
- `MOONSHOT_API_KEY` (Kimi, chair)
- `DEEPSEEK_API_KEY` (DeepSeek, council)
- `TAVILY_API_KEY` (web search)
- (Optional) `GEMINI_API_KEY` (free fallback)

Set browser mode (default is `chrome`):
- `AGENTIC_BOARD_BROWSER=chrome` — local Chrome (close any running Chrome with the same profile first)
- `AGENTIC_BOARD_BROWSER=tavily` — fallback when Playwright/Chrome aren't usable
- `AGENTIC_BOARD_BROWSER_HEADED=0` — run headless

## Run the demo

```bash
uv run python -m server.cli --live-research --depth deep \
    --members strategist,researcher \
    "Should I build an AI campaign brief tool for digital marketing agencies?"
```

You should see:

1. **Chair intake** — restates your question; may ask 1–3 clarifying
   questions.
2. **Strategist** — runs `web_search`, possibly `open_browser` (Chrome
   opens) or `validate_claim`, produces analysis with `[SEARCH_EVIDENCE]`
   tags and inline citations.
3. **Researcher** — same; may also call `ask_user_clarifying_question`
   if running in `deep` mode.
4. **Secretary brief** — Agreements / Conflicts / Open Questions.

## Troubleshooting

- *"Chrome launch failed"* — Chrome is already running with this profile.
  Close it, OR set `AGENTIC_BOARD_BROWSER=tavily`.
- *Member doesn't call any tools* — the model decided it had enough
  domain knowledge. Re-run with a more specific factual question, or
  raise `--depth deep`.
- *`MOONSHOT_API_KEY` errors* — chair model lookup fails; check `.env`.

## Mid-deliberation follow-ups

While the council is running, you can type a follow-up at any time to
deepen a specific member's analysis:

```
strategist: search for Indian agency tooling spend trends
critic: pre-mortem the privacy and MSA legal exposure
researcher: do agencies actually pay for ops tools, or are they bundled?
```

Format: `<member_id>: <text>`. Lines without a `member_id:` prefix are
ignored. Press Ctrl-D when you're done — the runtime drains the queue
between rounds, re-invokes each targeted member with a fresh `deep`
budget plus their previous analysis as context, then regenerates the
secretary brief. Maximum 10 follow-up rounds per session.

The follow-up channel only activates in interactive (TTY) sessions.
Scripted runs and CI ignore it.

## validate_claim tool

In addition to `web_search`, `fetch_url`, and `open_browser`, members
can call `validate_claim(claim, context)`. The tool runs a fresh web
search, asks a fast judge LLM to score the claim against the evidence,
and returns one of:

- `SUPPORTED` — at least 2 sources directly affirm the claim
- `CONTRADICTED` — at least 1 credible source directly contradicts
- `UNVERIFIED` — evidence is insufficient or off-topic

Use this before staking a recommendation on a specific number, vendor
claim, or policy fact. The judge model defaults to
`gemini/gemini-2.5-flash` (free tier) and can be overridden via the
`VALIDATE_CLAIM_MODEL` env var.

## Recording

```bash
asciinema rec docs/agentic-research-demo.cast
# run the demo command above, exit shell
```

## Verifier-decouple carve-out for chair fallback

The default chair is Kimi (`kimi/kimi-k2.6`); the verifier defaults to
DeepSeek. If Day-1 smoke shows Kimi's tool-calling has issues and you
swap the chair to DeepSeek:

```bash
export CHAIRMAN_MODEL=deepseek/deepseek-v4-pro
export AGENTIC_BOARD_ALLOW_SAME_VERIFIER=1   # required because
                                              # chair == verifier provider
```

Phase 1 demos run without verification (Stage 4 is opt-in), but the
guard in `server/board/config.py:_assert_verifier_decoupled` runs at
import time, so the env var is needed for `import server` to succeed.
