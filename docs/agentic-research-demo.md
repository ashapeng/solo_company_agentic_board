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
   opens), produces analysis with `[SEARCH_EVIDENCE]` tags and inline
   citations.
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
