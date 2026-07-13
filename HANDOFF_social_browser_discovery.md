# Handoff — Browser-driven social discovery for pain-point sourcing

Status: design + environment ready. No feature code written yet.
Branch: `cursor/set-up-dev-environment-3c8e`.
Audience: the next session (human or agent) that will implement and test this.

---

## 1. Goal

The product's first step is "search social media for pain points." The existing
`server/discovery/` pipeline fetches via HTTP/CLI APIs, but the most valuable
social channels are blocked or unsupported in practice:

- **Reddit** → `403 Blocked` from datacenter/cloud IPs.
- **YouTube** → needs the `yt-dlp` binary.
- **Twitter/X** → only a phase-2 stub (`agent_reach`).
- **Instagram / Facebook / TikTok / 小红书 (Xiaohongshu)** → not implemented at all.

The chosen direction: **drive a real, logged-in browser** (the user's own Chrome
profile, or the coding agent's browser in Claude Code / Codex / Cursor) to search
social platforms directly, then feed captured posts into the existing discovery
store so the board can analyze them. This bypasses API walls and anti-bot blocks
because requests come from a genuine logged-in session.

---

## 2. Environment is already set up

See `AGENTS.md` → "Cursor Cloud specific instructions". Quick reference:

- Python deps: `uv sync`. UI deps: `npm install --prefix ui`. (Both are in the
  startup update script.)
- Tests: `uv run pytest` (live tests deselected by default via `-m 'not live'`).
- Web app: `./start.sh` → `http://127.0.0.1:8000`.
- Discovery CLI: `uv run python -m server.discovery {doctor,fetch,status}`.

Verified facts from setup (2026-07-13, this cloud VM):

- Egress is **allow-all** (unrestricted).
- `google-chrome` / `google-chrome-stable` are installed on PATH.
- `open_browser` (Playwright) **runs headless** here and extracted Hacker News
  successfully (see §4). `gh` CLI is authenticated (github channel works).
- `yt-dlp` is **not** installed; no `SAM_GOV_API_KEY` / `PRODUCTHUNT_TOKEN`.
- **Cloud caveat:** this VM's Chrome profile has **no logged-in social
  accounts** and there is no display for headed mode. So "open *my* accounts"
  only truly works on the **user's local machine** (Claude Code / Codex / Cursor
  Desktop). In cloud, use imported cookies, a proxy, or keep capture local and
  let the board do only the analysis.

⚠️ **Gotcha:** the discovery CLI does **not** call `load_dotenv()` (only
`server/cli.py` and `server/api/app.py` do). Any keys (`SAM_GOV_API_KEY`, etc.)
must be real env vars / Cloud Agent Secrets, not just `.env` entries.

---

## 3. Existing building block: `open_browser`

`server/board/tools.py` already drives the user's real Chrome profile:

- `_resolve_chrome_user_data_dir()` (tools.py ~L361) → OS Chrome profile dir,
  overridable via `AGENTIC_BOARD_CHROME_USER_DATA_DIR`.
- `_open_browser_via_playwright()` (tools.py ~L435) uses
  `pw.chromium.launch_persistent_context(user_data_dir=..., channel="chrome",
  headless=not headed)` → inherits logged-in cookies; returns rendered
  markdown/text/html (capped at `_OPEN_BROWSER_MAX_CHARS = 12000`).
- Env controls: `AGENTIC_BOARD_BROWSER=chrome|tavily|disabled`,
  `AGENTIC_BOARD_BROWSER_HEADED=1|0`.
- Concurrency: `_BROWSER_SEMAPHORE = Semaphore(1)` (one browser at a time).
- This tool is **async** and lives in the board domain; discovery channels are
  **sync** and never call it today. Bridging the two is the core of the work.

---

## 4. Design

Two layers; ship both, start with Layer B.

### Layer A — in-repo `browser` discovery channel (scheduled, local machine)
A new channel that opens a platform's logged-in search-results URL and parses the
DOM into `RawPost`s. Fits the weekly `fetch` pipeline. Best for platforms with
stable markup. Runs on the user's local machine (real profile, headed or headless).

### Layer B — agent-driven capture (interactive; what the user asked for)
The coding agent (Claude Code computer-use / Playwright MCP, Codex browser tool,
Cursor `computerUse`) drives its browser while the user is logged in, then writes
results into the discovery store using the **drop-folder contract** (§5.4). No new
fetch code required — `status` and the downstream `/venture-scan` analysis consume
the JSON unchanged. Best for hostile platforms (TikTok, 小红书, IG, FB).

### Recommended sequencing
1. Layer B drop contract + a `hermes/skills/social-scan/` capture skill (fastest
   value, works for any platform via whichever agent the user runs).
2. Layer A `browser` channel for stable-DOM platforms (enables scheduled `fetch`).
3. Optional: expose `open_browser` as an MCP tool (repo already supports
   `AGENTIC_BOARD_MCP_SERVERS`) so any agent can call it directly.

---

## 5. Implementation plan

### 5.1 Data contract (already exists — reuse, don't change)
`server/discovery/channels/base.py`:
```python
@dataclass
class RawPost:
    id: str
    channel: str
    source: str        # the query / seed that produced this post
    title: str
    body: str
    url: str
    author: str = ""
    score: int = 0
    comments: int = 0
    created_at: str = ""     # ISO 8601 UTC
    extra: dict = field(default_factory=dict)
    def key(self) -> str: return f"{self.channel}:{self.id}"
```
Dedup key is `channel:id`, so give each post a stable, platform-unique `id`
(e.g. the note/video id), NOT a random UUID, or dedup across weeks breaks.

### 5.2 Layer A — new channel file
Create `server/discovery/channels/browser.py` implementing the `Channel`
protocol (`name`, `fetch(item)->list[RawPost]`, `health()`). Mirror the existing
dependency-injection test pattern (like `youtube.py`'s `runner` and `rss.py`'s
`parse`) so unit tests can inject fake HTML without launching Chrome:

```python
class BrowserChannel:
    name = "browser"
    def __init__(self, fetch_html=None):
        # fetch_html(url, wait_for) -> str (rendered HTML); default drives Chrome
        self._fetch_html = fetch_html or _default_render

    def fetch(self, item: dict) -> list[RawPost]:
        html = self._fetch_html(item["url"], item.get("wait_for"))
        return _parse[item["platform"]](html, item)   # per-platform parser

    def health(self) -> ChannelHealth:
        # ok if playwright importable AND channel=chrome resolvable, else unconfigured
        ...
```

Key design decisions:
- **Sync, not async.** The `Channel.fetch` protocol is synchronous. Use
  `playwright.sync_api.sync_playwright` with `launch_persistent_context`, OR wrap
  the async `_open_browser_via_playwright` with `asyncio.run(...)`. Prefer sync
  Playwright to avoid nested-loop issues. Reuse `_resolve_chrome_user_data_dir`
  logic (consider moving it to a shared helper, e.g.
  `server/discovery/browser_session.py`, to avoid importing from the board domain).
- **Per-platform parsers** keyed by `item["platform"]` (`xiaohongshu`, `tiktok`,
  `instagram`, `facebook`, `twitter`, generic). Each maps DOM → `RawPost`.
  Keep selectors isolated and small; expect breakage and make them easy to patch.
- Respect the single-browser semaphore idea (don't launch many Chromes at once).

### 5.3 Registry + watchlist + loader edits (Layer A)
1. `server/discovery/channels/__init__.py`: import `BrowserChannel`, add to the
   `CHANNELS` tuple.
2. `server/discovery/watchlist.py`: add `"browser": "url"` (or `"query"`) to
   `_REQUIRED_FIELD`. New non-gov channels are auto-allowed via `KNOWN_SECTIONS`.
3. `server/discovery/watchlist.yaml`: add a `browser:` section, e.g.
   ```yaml
   browser:
     - platform: xiaohongshu
       query: "手作 卖不出去"
       url: "https://www.xiaohongshu.com/search_result?keyword=%E6%89%8B%E4%BD%9C"
       max_items: 20
       wait_for: ".note-item"        # optional CSS selector
     - platform: tiktok
       query: "etsy shop struggles"
       url: "https://www.tiktok.com/search?q=etsy%20shop%20struggles"
   ```
4. ⚠️ **Test that WILL fail until updated:**
   `tests/test_discovery_registry.py::test_registry_contains_all_channels`
   asserts `set(CHANNELS) == EXPECTED`. Add `"browser"` to its `EXPECTED` set.

### 5.4 Layer B — drop-folder contract (no fetch code)
The agent writes captured posts to:
```
data/discovery/raw/<ISO-week>/browser-<platform>.json
```
Format: a JSON array of `RawPost` dicts (same shape as §5.1). ISO week =
`datetime.now(timezone.utc).strftime("%G-W%V")` (see `store.iso_week()`).
To integrate cleanly with dedup/status, prefer writing via `DiscoveryStore`
(`server/discovery/store.py`): `filter_new()` → `write_raw(week, "browser",
label, posts)` → `mark_seen()`. A tiny helper script
(`scripts/import_browser_capture.py`) that reads an agent-produced JSON and runs
it through the store would make this robust and keep `status` accurate.

Then author `hermes/skills/social-scan/SKILL.md` (mirror the structure of the
existing skills under `hermes/skills/`) instructing the agent: which watchlist
URLs to open, how many items to capture, and to serialize into the `RawPost`
shape at the drop path. Keep the schema authoritative in one place.

---

## 6. Testing plan

Follow the existing offline-first test style (see `tests/test_discovery_rss.py`,
`tests/test_discovery_registry.py`): inject fakes, no network in default runs.

- **Unit (offline, default suite):**
  - `BrowserChannel(fetch_html=lambda url, wait_for: FIXTURE_HTML)` → assert the
    per-platform parser yields correct `RawPost` fields (id/title/url/author).
  - `health()` returns `ok` when Playwright is importable, `unconfigured`/`error`
    otherwise (mirror `test_producthunt_unconfigured_without_token`).
  - Watchlist: `load_watchlist` accepts a `browser:` section and rejects items
    missing the required field (mirror existing watchlist tests).
  - Update `test_discovery_registry.py` `EXPECTED` (see §5.3.4).
  - Layer B: a store round-trip test — write a fixture `RawPost[]`, run through
    `filter_new`/`write_raw`/`mark_seen`, assert dedup on re-import.
- **Live (opt-in, `@pytest.mark.live`, needs a logged-in local profile):** add a
  `tests/test_discovery_browser_live.py` mirroring `test_discovery_live.py` that
  hits one real platform. Will NOT run in the default suite or in cloud.
- **Manual / smoke:**
  - `uv run python scripts/smoke_browser.py` (proves the Chrome plumbing; works
    in cloud headless on public pages).
  - Local, logged-in: `uv run python -m server.discovery fetch --watchlist
    <custom.yaml>` then `... status` and inspect
    `data/discovery/raw/<week>/browser-*.json`.
- **Full regression:** `uv run pytest` must stay green (1089 passing at handoff;
  3 known pre-existing failures documented in `AGENTS.md` — do not "fix" them).

---

## 7. Where things run (local vs cloud)

| Task | Local agent (Claude Code/Codex/Cursor Desktop) | This cloud agent |
|---|---|---|
| Drive **logged-in** social accounts | ✅ real profile/cookies | ❌ empty profile, no display |
| `open_browser` on public pages | ✅ | ✅ (headless, verified) |
| Layer A scheduled `fetch` (browser channel) | ✅ | ⚠️ only public/anonymous pages |
| Layer B agent capture → drop JSON | ✅ (primary) | ⚠️ needs imported cookies/proxy |
| Board **analysis** of captured posts | ✅ | ✅ (needs LLM provider keys) |

Bottom line: capture on the user's local machine; analyze anywhere.

---

## 8. Risks / decisions to confirm before/while building

- **ToS & anti-bot:** automating logged-in social sessions may violate platform
  ToS and can trigger account flags. Confirm the user accepts this; prefer
  human-in-the-loop (Layer B) for the most hostile platforms.
- **Selector brittleness:** social DOMs change often. Keep per-platform parsers
  tiny and independently testable; treat them as disposable.
- **Auth/session in cloud:** decide whether to support a cookie-import path
  (`AGENTIC_BOARD_CHROME_USER_DATA_DIR` pointing at an imported profile) or keep
  capture strictly local.
- **Priority order of platforms** — recommend starting with 小红书 + TikTok
  (highest API-wall pain), then Reddit-via-browser (sidesteps the 403), then
  IG/FB/Twitter.
- **Analysis step** needs LLM provider keys (`DEEPSEEK_API_KEY`, `MOONSHOT_API_KEY`,
  `GEMINI_API_KEY`, `ZAI_API_KEY`, `DASHSCOPE_API_KEY`) — none set yet.

---

## 9. File map (quick reference)

Read/modify:
- `server/discovery/channels/base.py` — `RawPost`, `ChannelHealth`, `Channel`, `slugify` (reuse).
- `server/discovery/channels/__init__.py` — `CHANNELS` registry, `build_channel`.
- `server/discovery/watchlist.py` — `_REQUIRED_FIELD`, `KNOWN_SECTIONS`, loader.
- `server/discovery/watchlist.yaml` — add `browser:` section.
- `server/discovery/store.py` — `DiscoveryStore`, `iso_week` (dedup + write).
- `server/discovery/cli.py` — `fetch`/`doctor`/`status` (no change needed for Layer A).
- `server/board/tools.py` — `open_browser` / `_open_browser_via_playwright` /
  `_resolve_chrome_user_data_dir` (reference implementation to reuse).
- `scripts/smoke_browser.py` — existing browser smoke test.

Create:
- `server/discovery/channels/browser.py` — new `BrowserChannel` (Layer A).
- `server/discovery/browser_session.py` — optional shared Chrome-launch helper.
- `scripts/import_browser_capture.py` — optional Layer B importer.
- `hermes/skills/social-scan/SKILL.md` — Layer B agent capture skill.
- `tests/test_discovery_browser.py` — offline unit tests.
- `tests/test_discovery_browser_live.py` — opt-in live test.

Update:
- `tests/test_discovery_registry.py` — add `"browser"` to `EXPECTED`.
