---
name: social-scan
description: Capture pain-point posts from logged-in social platforms via the agent's browser and drop them into the discovery store.
version: 0.1.0
platforms: [linux, darwin, windows]
metadata:
  hermes:
    tags: [discovery, social, pain-points, browser, venture]
    category: research
    requires_toolsets: [browser, terminal, files]
---

# Social Scan Skill (Layer B)

Drive a real, logged-in browser to search social platforms for pain points, then
import the captures into Agentic Board's discovery store. Prefer this over the
scheduled `browser` channel for hostile platforms (TikTok, 小红书, IG, FB).

## When To Use

- The user wants to search social media for pain points / venture signals.
- HTTP/API channels are blocked (Reddit 403, no yt-dlp, no X API, etc.).
- The agent can open the user's logged-in browser (Claude Code computer-use,
  Codex browser, Cursor `computerUse`, or Playwright MCP).

## When Not To Use

- Pure analysis of already-captured posts — use `/venture-scan` or the board.
- Scheduled weekly fetch on stable-DOM platforms — use
  `uv run python -m server.discovery fetch` with the `browser:` watchlist
  section (Layer A) instead.
- Cloud VMs with empty Chrome profiles and no imported cookies — capture
  locally, then analyze anywhere.

## Schema (authoritative)

Each captured post is a `RawPost` (`server/discovery/channels/base.py`):

```json
{
  "id": "platform-unique-stable-id",
  "channel": "browser",
  "source": "browser-<platform>",
  "title": "short title or caption",
  "body": "post text / description",
  "url": "https://...",
  "author": "handle or display name",
  "score": 0,
  "comments": 0,
  "created_at": "2026-07-13T00:00:00Z",
  "extra": { "platform": "xiaohongshu" }
}
```

**Dedup key is `channel:id`.** Use the platform's native note/video/post id —
never a random UUID — or weekly dedup breaks.

## Procedure

1. Read watchlist targets from `server/discovery/watchlist.yaml` under `browser:`
   (or ask the user for platform + search query).
2. Open each search URL in the logged-in browser. Wait for results to render.
3. Capture up to `max_items` (default 20) visible posts per query. For each:
   - Extract a stable platform id (note id, video id, post id).
   - Title, body/caption, author, URL, optional score/comments/created_at.
4. Write a JSON array of `RawPost` objects to a temp file, e.g.
   `/tmp/social-scan-<platform>.json`.
5. Import into the discovery store (keeps `status` + dedup accurate):

   ```bash
   uv run python scripts/import_browser_capture.py /tmp/social-scan-<platform>.json \
     --platform <platform>
   ```

   Optional: `--week 2026-W28` to pin the ISO week; `--store-root data/discovery`.

6. Confirm the drop path:

   ```text
   data/discovery/raw/<ISO-week>/browser-<platform>.json
   ```

   ISO week = `datetime.now(timezone.utc).strftime("%G-W%V")` (see
   `server/discovery/store.py` → `iso_week()`).

7. Report counts: imported vs skipped (already seen). Suggest
   `uv run python -m server.discovery status` and then `/venture-scan` analysis.

## Platform tips

| Platform | Prefer | Notes |
|----------|--------|-------|
| 小红书 / Xiaohongshu | Layer B | Highest API-wall pain; use note id |
| TikTok | Layer B | Video id from `/video/<id>` |
| Instagram / Facebook | Layer B | DOM hostile; human-in-the-loop |
| Reddit | Layer A or B | Browser sidesteps datacenter 403 |
| Twitter/X | Layer B | `agent_reach` remains a phase-2 stub |

## Failure Modes

- Empty profile / not logged in → stop and ask the user to log in locally.
- Captcha / challenge wall → hand control back to the user; do not brute-force.
- Selector / layout change → still write whatever posts you can extract; note
  gaps in the summary. Layer A parsers are disposable; Layer B is free-form.
- Duplicate re-import → `import_browser_capture` skips via `filter_new`; this is
  success, not an error.
- ToS risk → prefer human-in-the-loop capture; do not schedule aggressive
  scraping of logged-in sessions.
