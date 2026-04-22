# Focused Boardroom UI — Design Spec

**Date:** 2026-04-21
**Status:** Proposed
**Scope:** UI redesign + Phase A-lite routing signal capture

## Context

The Agentic Board UI has iterated through three states:

1. **Original light-theme prototype** — three stacked columns, borders, generic SaaS shell. Flagged in prior critique as "cluttered", "brand mismatch."
2. **Obsidian Gallery dark theme** (shipped prior to this spec) — deep obsidian surfaces, gold accents, Noto Serif headlines. Fixed brand alignment and hierarchy, but introduced new problems: hard to read over long sessions, three-column layout still visually fragmented, round table pre-populates all 7 members at low opacity (visual noise), CEO appears at both the top avatar slot and the bottom chair slot (duplicate identity).
3. **This spec — focused boardroom** — flip to warm cream editorial, collapse peripheral panels into edge drawers that auto-reveal on state change, empty round table at idle that fills only when the classifier routes members, and a lightweight routing-signal capture that feeds the existing harness ledger for future Phase D consumption.

## Goals

- Make the round table the unambiguous focal zone. Strip competing chrome from first-launch view.
- Restore long-session legibility with a warm cream palette that retains editorial / premium feel.
- Stop pre-populating the round table with shaded members. Members appear only when the classifier pulls them in (stage-gated) or the CEO manually adds them.
- Remove the top CEO avatar (keep only the bottom CEO chair icon as the user's own seat).
- Capture routing-quality signals into the existing harness ledger so Phase D (roster capability adjustments) has historical data when it ships.
- Prevent visual overcrowding as the meeting progresses: drawers, member counts, and done-states all have density rules.

## Non-Goals

- Phase D implementation (routing accuracy scoring → roster weight adjustments). This spec only captures the signal; the consumer is future work.
- Classifier or orchestrator changes. Backend routing logic is unchanged.
- Mobile layout (< 1280px). Web-first only. Existing `MobileMember` fallback remains as-is, not redesigned.
- Auto-tuner (Phases B / C from the self-evolving-harness spec).
- New pages, new domain concepts, new board members.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Theme | Warm cream editorial (`#FAF7F2` bg, `#1A1614` ink, brass `#B8860B`, navy `#1E3A5F`) | User reported dark theme hard to read. Cream keeps premium feel while achieving WCAG AAA contrast. |
| Layout | 72px permanent icon rail + hero canvas + two edge drawers hidden by default | Focal round table. Drawers slide in only on state change (left when question submitted, right at Stage 3). |
| Member appearance | Empty at idle, sticky within session, stage-gated arrival + manual override | Matches mental model "the board convenes for this question." No pre-populated avatars. |
| Density caps | Max 5 visible seats, done-members shrink to 70%, drawers mutually exclusive unless pinned | Prevents orbit crowding + chrome creep as meeting progresses. |
| Signal capture | "Missing voice?" row post-synthesis + implicit manual-add tracking | B + D from Q6 clarification. Two sources, one ledger column. |
| Top CEO avatar | Removed | User flagged as duplicate; bottom chair icon is the CEO's seat. |
| Scope boundary | UI + ledger signal capture only; Phase D consumer deferred | Ships value now; signal accrues for Phase D. |

---

## Component 1: Palette & Typography Tokens

### File: `ui/src/index.css`

Rewrite the `@theme` block to swap obsidian tokens for cream tokens. Token *names* are unchanged (consumers don't need to update) — only values.

```css
@theme {
  /* Surfaces */
  --color-background:              #FAF7F2;
  --color-surface:                 #FAF7F2;
  --color-surface-container-lowest:#FFFFFF;
  --color-surface-container-low:   #F4EFE6;
  --color-surface-container:       #EFE8DB;
  --color-surface-container-high:  #E8DFCC;
  --color-surface-container-highest:#DDD2BA;
  --color-surface-variant:         #DDD2BA;

  /* Text */
  --color-on-surface:              #1A1614;
  --color-on-surface-variant:      #5C5348;
  --color-on-background:           #1A1614;

  /* Primary (brass / gold) */
  --color-primary:                 #B8860B;
  --color-primary-container:       #8C6608;
  --color-primary-fixed-dim:       #A87C3E;
  --color-primary-fixed:           #C9A04C;
  --color-on-primary:              #FFFFFF;
  --color-on-primary-container:    #FFFFFF;

  /* Secondary (navy — active / interactive) */
  --color-secondary:               #1E3A5F;
  --color-secondary-container:     #1E3A5F;
  --color-secondary-fixed:         #4A6B8E;
  --color-on-secondary:            #FFFFFF;

  /* Error (burgundy — dissent / fail) */
  --color-error:                   #9B2C2C;
  --color-error-container:         #FCE8E6;
  --color-on-error:                #FFFFFF;
  --color-on-error-container:      #4A1212;

  /* Outline */
  --color-outline:                 #9E8F78;
  --color-outline-variant:         #C9BFAE;

  /* Fonts (unchanged) */
  --font-headline: 'Noto Serif', serif;
  --font-body:     'Manrope', sans-serif;
  --font-label:    'Manrope', sans-serif;
}
```

### Utility updates

- `.speaking-halo` — radial gradient `rgba(184, 134, 11, 0.28)` → transparent (gold pulse on cream).
- `.glass-panel` — `background: rgba(255, 255, 255, 0.72); backdrop-filter: blur(20px); box-shadow: inset 1px 1px 0 rgba(255,255,255,0.9), 0 8px 32px rgba(26, 22, 20, 0.08);`
- `.metallic-gradient` — `background: linear-gradient(135deg, #B8860B 0%, #8C6608 100%)` (brass).
- `.accent-bar-left` — `border-left: 2px solid var(--color-secondary-container)` (navy).
- `.prose-lite` — text `var(--color-on-surface)`, links `var(--color-primary)`, code blocks bg `var(--color-surface-container-low)` with `var(--color-on-surface)` text.
- Body bg → `var(--color-background)`; body color → `var(--color-on-surface)`.

### Contrast targets

| Pair | Ratio | Standard |
|------|-------|----------|
| `#1A1614` on `#FAF7F2` | 14.1:1 | WCAG AAA |
| `#5C5348` on `#FAF7F2` | 6.8:1 | WCAG AA |
| `#B8860B` on `#FAF7F2` | 4.6:1 | WCAG AA (CTA only, not body) |
| `#1E3A5F` on `#FAF7F2` | 10.2:1 | WCAG AAA |
| `#9B2C2C` on `#FCE8E6` | 7.1:1 | WCAG AAA |

### Semantic rules

- **Gold** = system / ambient (headline accents, CTA gradient, speaking halo, stage pip filled).
- **Navy** = user-driven active (pressed toggle, selected nav, pinned drawer, manual-add ring).
- **Burgundy** = dissent / failure (failed member, "missing voice" flagged chip, error state).
- No all-caps except micro-kickers ≤ 14 chars.
- `.accent-bar-left` remains the only allowed border (selection states).
- Filled-input focus bottom border (`border-b-2 border-b-secondary-container`) remains allowed as the filled-input exception.

---

## Component 2: Shell — Icon Rail

### File: `ui/src/App.tsx`

Replace the existing side-nav (280px) with a permanent 72px icon rail. Remove the fixed top bar; its icons (settings, account) move into the icon rail bottom section.

### Layout

```
┌──┐
│EA│  ← wordmark monogram, click to expand rail to 240px with labels
│  │
│👥│  ← Portfolio (Users icon)
│🏛│  ← Governance (Landmark icon) — default active
│🛡│  ← Compliance (ShieldCheck icon)
│  │
│  │  (flex-grow spacer)
│  │
│⚙️│  ← Settings
│👤│  ← Account
└──┘
```

### Behavior

- Active page item: 2px navy `.accent-bar-left`, bg `surface-container-high`, icon `on-surface` (full ink).
- Inactive: icon `on-surface-variant` at 50% opacity. Hover: 100% opacity + bg `surface-container-low`.
- Tooltip on hover (right side, offset 12px) shows label in Manrope.
- Wordmark click toggles expanded rail (240px) with inline labels. Expanded state persists in `localStorage.boardroom.railExpanded`.
- No top bar. Session status chip (previously in top bar right) moves into the icon rail between the page icons and the settings section, rendered as a small horizontal dot + label.

### Constraints

- Rail uses `position: fixed; top: 0; left: 0; height: 100vh`.
- Main content area offset `ml-[72px]` (or `ml-[240px]` when expanded).
- No existing routing logic changes. Preserve the tab-state hook that currently drives page switches.

---

## Component 3: Hero Canvas — Round Table + Composer

### File: `ui/src/domains/board/GovernancePage.tsx`

Redesign the `CenterArena` section. Strip all non-canvas chrome (insights + outlook panels move to edge drawers — Component 4).

### Round table

Keep the existing `.board-orbit` CSS custom property (`--orbit-radius`) and polar-coordinate positioning math. Restyle:

- Table surface: `bg-gradient-to-b from-surface-container-low to-surface-container` (cream gradient, not dark).
- Texture overlay: existing `council-table-texture.png` at 12% opacity, `mix-blend-multiply` (not overlay on cream).
- Ambient central glow: `bg-primary/5 blur-[100px]` — gold ambient on cream.
- Table shadow: `shadow-[0_20px_60px_-20px_rgba(184,134,11,0.25)]` (soft brass bloom, no hard border).

### Seat rendering rules

- **Idle (no active session):** zero seats rendered. Only the bottom CEO chair icon (decorative, non-interactive) + holo card.
- **Routed members (stage-gated arrival):** fade in at polar positions, 120ms stagger. Navy ring (`ring-2 ring-secondary-container ring-offset-2 ring-offset-background`) indicates "routed and arriving."
- **Speaking member:** ring switches to gold `ring-2 ring-primary ring-offset-4 ring-offset-background`. `.speaking-halo` wrapper active. Mic badge bottom-right (gold dot pulsing).
- **Done member:** ring settles to member-tone color (`MEMBER_TONES[id]`) at 90% opacity. Avatar shrinks from 64px → 48px. ✓ micro-badge bottom-right. Opacity drops to 70%.
- **Failed member:** ring burgundy. ✗ micro-badge. Opacity 55%.
- **Manual-add member:** arrives with navy ring (same as routed) but also receives a tiny "+" badge top-right for the first 2 seconds, then fades. Distinguishes the manual origin subtly without permanent marking.
- **Overflow seats (> 5 routed):** visible seats = chairperson (always) + top 4 by `priority` (the `priority` integer from each member's YAML frontmatter in `server/members/<id>.md`). Overflow compressed into a single "+N" pill at an empty slot. Hover expands popover listing them. User can promote any overflow member to a visible seat (swaps with the lowest-priority visible non-chair member).

### Remove

- The top-of-table CEO avatar seat (flagged by user). Only the bottom CEO chair icon remains — purely decorative, not clickable.

### Holo topic card (center of table)

Minimum 280px × 140px. Glass treatment:

- `bg-white/72 backdrop-blur-[20px]` (cream-glass on cream).
- Inner highlight `shadow-[inset_1px_1px_0_rgba(255,255,255,0.9)]`.
- Outer drop shadow `shadow-[0_8px_32px_rgba(26,22,20,0.08)]` + gold bloom `shadow-[0_0_40px_-10px_rgba(184,134,11,0.25)]`.
- No border.

Content states:

| State | Content |
|-------|---------|
| Idle | "Awaiting board question" in `font-headline italic text-xl`, gold pulsing waveform icon. |
| Active (T1–T4) | User's query as serif quote, 2-line clamp. 4-dot stage pip row beneath. |
| Drafting (T4 chair synthesizing) | "Drafting memo…" + live character count. |
| Done (T6) | "Decision ready" in `font-headline text-lg` + gold verified check if Stage 4 passed. |

### Composer

Below the table, centered, max-w-2xl:

- `bg-surface-container-lowest rounded-xl p-6 flex flex-col gap-4` (card elevation via tonal shift, no border).
- Textarea: filled style, `bg-surface-container-highest`, focus `border-b-2 border-b-secondary-container`. Placeholder "Ask the board…" in serif italic.
- Send button: circular 40px, absolute-positioned inside textarea right edge, `.metallic-gradient` + `text-on-primary` + Send lucide icon. Disabled state uses `bg-surface-container-high` + `text-on-surface-variant`.
- Toggle row below: "Full board" + "Verify" as pill toggles (navy fill when on, neutral bg off).
- Right side of toggle row: single chip showing active routing mode + est. budget (`⚡ Adaptive · ~$0.02`). During deliberation, chip shows spinner + "Deliberating · $0.04".

---

## Component 4: Edge Drawers

### File: `ui/src/domains/board/GovernancePage.tsx` (new sub-components inline)

### `<BriefingDrawer>` (left, 320px)

Slides in from left edge when the user submits the first question of a session. Uses Framer Motion `AnimatePresence` + `motion.aside` with `initial={{ x: -320 }} animate={{ x: 0 }} exit={{ x: -320 }} transition={{ ease: "easeOut", duration: 0.28 }}`.

Contents (top → bottom):

1. Header row: serif "Briefing Room" title + kicker "Strategic Materials" + pin icon (toggles `localStorage.boardroom.pinLeft`) + close X.
2. Stage Digest — 4-pip progress rail with stage names + member counts.
3. Live Conversation feed — last 5 items visible, "View all N events" link to expand. Each item bg `surface-container-lowest`, rounded-lg, no border, tonal tint per event kind (speaking → gold/5, done → neutral, failed → burgundy/10, stage → navy/10, phase → surface-container-low).
4. Board Memory (SotbCard) — prose card with serif "Board Memory" heading + last-updated chip.

### `<OutlookDrawer>` (right, 384px)

Slides in from right when Stage 3 (synthesis) begins OR manually toggled. Same motion pattern reversed.

Contents (top → bottom):

1. Header row: serif "Strategic Outlook" + pin + close.
2. At the Table — compact list of active members: avatar 32px + title + tone-colored tiny status chip.
3. **Latest Decision** (open by default) — the synthesis. Serif heading, first 6 lines of markdown, "Read full" expander. Gold verified check if Stage 4 passed, burgundy warn if failed.
4. **Execution Roadmap** (collapsed accordion, click to expand) — `AgentExecutionPanel`.
5. **Run Settings** (collapsed accordion) — `Fact` rows: Routing, Manual seats, Verify.

### Drawer behavior rules

- Mutual exclusion (Rule 1): opening one auto-collapses the other to a 40px edge tab (with unread-dot indicator). Pinning overrides exclusion.
- Dismiss: `Esc` closes the currently-active drawer, or click outside drawer bounds.
- Edge tab affordance: when drawer closed but session active, a 40px vertical tab with a chevron icon appears at the edge. Click to open.
- At idle (no active session), no drawers + no edge tabs. Zero chrome.
- When canvas width would squeeze below 600px (viewport - icon rail - both drawers), drawers become floating overlays (z-50, backdrop-blur on content behind) instead of push-resizing.

### `<MissingVoiceRow>` (inside OutlookDrawer)

Appears below Latest Decision after Stage 3 completes. Row label: "Should any voice have been at the table?" in `text-on-surface-variant text-xs italic`. Below: horizontal chip strip of member IDs NOT routed for this session (excluding chairperson). Each chip:

- Avatar 24px + title in `text-xs`.
- Default state: `bg-surface-container-low text-on-surface-variant`, 60% opacity.
- On click: fires `POST /sessions/{session_id}/routing-signal {member_id, source: "missing_voice_flag"}`, chip turns burgundy (`bg-error-container text-error`), shows "Flagged" text, 100% opacity. Unclickable afterward (prevent double-fire per session).
- Toast confirmation: "Flagged · logged for future routing" bottom-left, auto-dismiss 2s.

---

## Component 5: Manual Member Add (Override)

### Location

- Primary affordance (idle state): a single compact "+ Add members" button below the composer. No chip strip by default (keeps idle chromeless). Click expands into a horizontal 7-chip roster for direct toggle.
- Primary affordance (active deliberation): a small "+" button appears when user hovers near an empty orbit slot (desktop only). Click opens the popover anchored to that slot, and the newly added member fades into *that specific seat*.
- Fallback affordance (always available): the "+ Add members" button stays reachable below the composer throughout deliberation. When invoked without a specific seat target, the new member fades into the first available empty polar slot (iterate `MEMBER_ORDER` to find the first unoccupied angle).

### Popover

- Opens on "+" click, anchored near the target seat.
- Lists all board members not currently seated + not already done-participated.
- Each row: avatar + title + short dossier line ("Strategic market + evidence framing").
- Click a row: popover closes, member fades in at the hovered/clicked seat position with navy ring + transient "+" badge.
- Fires `POST /sessions/{session_id}/routing-signal {member_id, source: "manual_add"}`.
- If no session_id yet (user adds before submitting question), no POST — just local state.

### Interaction with classifier

Manual-add members participate in subsequent stages the same as classifier-routed members. They receive Stage 1 query, Stage 2 peer review input, etc. This matches existing `manualMemberIds` wiring.

### Idempotency with classifier routing

If the user manually adds a member the classifier had already routed, the UI no-ops (no duplicate avatar, no additional POST). The "+" popover filters out any member whose `SeatState.status !== 'idle'` in the current session. The routing-signal POST only fires when the member was NOT already seated.

### Signal queuing when session_id is not yet ledger-persisted

The ledger row for a session is written after synthesis completes (per existing `orchestrator.py` order). Manual-add events can occur before then. The frontend buffers routing signals locally (in-memory array keyed by `sessionId`) and flushes to the API after the `T6` completion event fires. This avoids 404s on in-flight sessions. If the session fails/aborts before T6, buffered signals are dropped (no dangling writes).

---

## Component 6: Ledger Extension

### File: `server/board/ledger.py`

Add a new column and API function. Schema migration on first open: `ALTER TABLE session_outcomes ADD COLUMN routing_misses TEXT DEFAULT '[]'` guarded by `PRAGMA table_info(session_outcomes)` check for idempotency.

```python
def record_routing_signal(
    session_id: str,
    member_id: str,
    source: Literal["manual_add", "missing_voice_flag"],
) -> None:
    """Append a routing-signal entry to the session's routing_misses column.

    Raises ValueError if session_id not found in ledger.
    """
    # Fetch current routing_misses JSON, parse, append new entry, serialize, UPDATE.
    # Entry shape: {"member_id": str, "source": str, "ts": iso8601_utc}
```

### Migration contract

- On `ledger.initialize()` (or the first call that opens the DB), check if `routing_misses` column exists via `PRAGMA table_info`. If missing, run `ALTER TABLE`. This must be idempotent (no-op on second+ calls).
- Existing rows get `'[]'` as default (no signal captured retroactively).

### Data shape

```json
[
  {"member_id": "critic", "source": "missing_voice_flag", "ts": "2026-04-21T14:32:17Z"},
  {"member_id": "architect", "source": "manual_add", "ts": "2026-04-21T14:30:02Z"}
]
```

Array allows multiple signals per session (user may flag multiple missing voices + add multiple manual members).

### Phase D consumer (future, not in scope)

Phase D's tuner (when designed and implemented) will read the `routing_misses` column to correlate member absence with query type and feedback rating. The exact aggregation API is out of scope for this spec; Phase A-lite's responsibility is only to capture the raw signal so that data exists when Phase D is designed.

### Test contracts

1. `record_routing_signal` appends to existing array without losing prior entries.
2. Raises `ValueError` when `session_id` not in ledger.
3. Schema migration is idempotent (second call is no-op).
4. Existing rows prior to migration get `'[]'` default.
5. Round-trip: write → read returns identical shape, including timestamps.

---

## Component 7: API Route

### File: `server/api/routes/board.py`

Add one route:

```
POST /sessions/{session_id}/routing-signal

Request body:
{
  "member_id": "critic",
  "source": "missing_voice_flag"   // or "manual_add"
}

Response 200:
{"status": "recorded", "session_id": "...", "member_id": "...", "source": "..."}

Response 404: {"detail": "session not found"}
Response 422: {"detail": "invalid source"} / {"detail": "unknown member_id"}
```

### Validation

- `member_id` must match a key in `MEMBER_ORDER` (loaded from the members roster).
- `source` must be `"manual_add"` or `"missing_voice_flag"`.
- `session_id` must exist in the ledger (proxy for "real session").
- Duplicate calls for the same `(session_id, member_id, source)` triple are appended (array grows). Deduplication is the consumer's job (Phase D).

### Test contracts

1. Valid POST returns 200 and appends to ledger.
2. Unknown `session_id` returns 404.
3. Invalid `source` returns 422.
4. Unknown `member_id` returns 422.
5. Multiple POSTs for same session + member + source all append.

---

## Component 8: Frontend API Client

### File: `ui/src/shared/api.ts`

Add one function:

```typescript
export async function recordRoutingSignal(
  sessionId: string,
  memberId: string,
  source: "manual_add" | "missing_voice_flag"
): Promise<void> {
  const res = await fetch(`/sessions/${sessionId}/routing-signal`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ member_id: memberId, source })
  });
  if (!res.ok) {
    throw new Error(`routing-signal failed: ${res.status}`);
  }
}
```

### Error handling

- Calls are best-effort (fire-and-forget from UI perspective). Failures logged to console but do not block UI state transitions — the chip still turns burgundy / the member still appears at the seat.
- If `sessionId` is null (user manually-adds before submitting), skip the call entirely.
- For manual-adds that occur before the session is ledger-persisted (after submit but before synthesis completes), buffer the calls in a local queue (`sessionId → [{memberId, source, ts}]`) and flush the queue on the `T6` completion event. On session failure, drop the queue.

---

## Density Rules Summary

| # | Rule | Enforced where |
|---|------|----------------|
| 1 | Drawers mutually exclusive unless pinned | `GovernancePage` drawer state machine |
| 2 | Max 5 visible seats; excess → `+N` pill | `RoundTable` seat selection logic |
| 3 | Done members shrink 64→48px, 70% opacity | `BoardAvatar` state-driven size/opacity |
| 4 | Live feed caps at 5 items, collapsible | `BriefingDrawer` feed component |
| 5 | Right drawer lazy sections (decision open, others collapsed) | `OutlookDrawer` accordion state |
| 6 | Holo card min 280×140; drawers overlay if canvas < 600px | `CenterArena` layout + drawer z-index logic |
| 7 | Done state: no halos, chair keeps subtle gold `ring-1 ring-primary/50` | `BoardAvatar` derived state from session.completed |

---

## Interaction Timeline (Reference)

| Phase | User state | Visual state |
|-------|------------|--------------|
| T0 — Idle | No question submitted | Cream canvas. Icon rail left. Round table empty (only CEO chair). Holo card "Awaiting". Composer centered below. No drawers. |
| T1 — Submit | Enter pressed | Composer shows "Classifier routing…". Routed members fade in at polar positions (120ms stagger, navy ring). Left drawer slides in. Holo card quotes query. Stage pip 1 gold. |
| T2 — Stage 1 | Members analyzing | Each speaking member: gold halo + full-size. Others: at-rest. Live feed appends events. Done members shrink + ✓. |
| T3 — Stage 2 | Peer review | Pip 2 gold. Reviewers re-glow (softer). Non-reviewers dim to 55%. |
| T4 — Stage 3 | Synthesis | Pip 3 gold. Chairperson sustained gold aura. Holo card "Drafting memo…". Right drawer slides in. Decision panel streams. |
| T5 — Stage 4 | Verification | Pip 4 fills (gold = pass, burgundy = fail). Holo card gets gold verified ring on pass. |
| T6 — Done | Session complete | All halos stop. Members at 48px/70%. Chair at 64px with subtle gold ring (`ring-1 ring-primary/50`). `MissingVoiceRow` renders below decision. |
| Override (any time after T1) | User clicks "+" | Popover opens. Select a member → fades in at empty seat with navy ring + transient "+" badge. POST fires. |

---

## Files Changed

### New / additive

| File | Type |
|------|------|
| `server/api/routes/board.py` | Add one route |
| `server/board/ledger.py` | Add `routing_misses` column + `record_routing_signal` |
| `tests/test_routing_signal_contract.py` | New test file |

### Modified (frontend)

| File | Scope of change |
|------|-----------------|
| `ui/src/index.css` | `@theme` rewrite; utility retune for cream |
| `ui/src/App.tsx` | Replace side nav → 72px icon rail; remove top bar |
| `ui/src/shared/components.tsx` | Retheme primitives (same class names) |
| `ui/src/shared/presentation.tsx` | Recalibrate `MEMBER_TONES` for cream bg; `taskStatusClass` retint |
| `ui/src/shared/api.ts` | Add `recordRoutingSignal` |
| `ui/src/domains/board/GovernancePage.tsx` | Strip 3-column layout; add `<CenterArena>`, `<BriefingDrawer>`, `<OutlookDrawer>`, `<MissingVoiceRow>`, `<OverflowSeat>`, `<IconRail>` (in App.tsx); remove top CEO avatar; add shrink-on-done + drawer mutual-exclusion |
| `ui/src/domains/board/PortfolioPage.tsx` | Retheme only |
| `ui/src/domains/harness/PerformancePage.tsx` | Recharts palette retheme |
| `ui/src/domains/execution/AgentExecutionPanel.tsx` | Retheme; lives in OutlookDrawer accordion |
| `ui/src/domains/memory/SotbCard.tsx` | Retheme |
| `ui/src/domains/memory/FeedbackWidget.tsx` | Retheme |

### Not changed

- `server/board/orchestrator.py`, `classifier.py`, `verification.py`, `compaction.py`
- Any member `.md` or protocol `.md`
- `server/board/harness_config.py`, `config.py`, `llm.py`, `metrics.py`
- `server/cli.py`
- No new dependencies (Framer Motion already present)

---

## Test Plan Summary

### Backend (pytest)

1. `record_routing_signal` appends correctly to existing JSON array.
2. `record_routing_signal` raises `ValueError` on unknown session_id.
3. Schema migration idempotent across repeated `initialize()` calls.
4. Existing pre-migration rows default to `'[]'`.
5. POST `/sessions/{id}/routing-signal` with valid body → 200 + ledger updated.
6. POST with unknown session_id → 404.
7. POST with invalid `source` → 422.
8. POST with unknown `member_id` → 422.
9. Multiple POSTs for same (session, member, source) all append.
10. All 72 existing ledger + harness tests still pass.

### Frontend (vitest / playwright — whichever project uses)

11. Icon rail renders 3 page icons + wordmark + settings + account.
12. Rail expand toggle persists in `localStorage`.
13. At idle (T0): zero seats + zero drawers + only bottom CEO chair + holo card "Awaiting".
14. After submit (T1): routed members fade in, left drawer slides in.
15. Stage pip fills correctly at T2, T3, T4.
16. Right drawer slides in at T4 (Stage 3 start).
17. Drawer mutual exclusion: opening right auto-collapses unpinned left to edge tab.
18. Pin toggles persist. Pinned drawers do not collapse each other.
19. Esc dismisses active drawer.
20. Overflow "+N" pill appears when ≥ 6 routed members; hover expands popover.
21. Done-member avatar shrinks 64→48, opacity 100→70.
22. Failed-member ring burgundy.
23. `MissingVoiceRow` renders after synthesis; clicking a chip fires POST + turns burgundy.
24. Manual-add "+" popover lists un-seated members; selection fires POST with `source=manual_add` + renders seat with navy ring + transient badge.
25. Top CEO avatar is removed; only bottom CEO chair icon present.
26. Contrast audit: all body text pairs ≥ 4.5:1; headlines + CTAs ≥ 3:1.

### Visual smoke

27. `cd ui && npm run build` passes, 0 TS errors.
28. Dev server boots, no runtime console errors.
29. Manual pass: submit a question, verify timeline T0→T6 renders as specified.

---

## Out of Scope (Explicit)

- Phase D tuner (`server/board/tuner.py`) that consumes `routing_misses` to adjust roster capabilities.
- Live roster capability weights in UI.
- Real-time classifier override (user overrides classifier mid-Stage-1).
- Mobile / tablet responsive layout below 1280px viewport.
- Keyboard shortcut sheet beyond Esc / Enter / Shift+Enter.
- A/B toggle between cream light and obsidian dark (theme switcher).
- Accessibility screen-reader pass (deferred to a dedicated a11y spec).
- Feedback rating UI redesign — existing thumbs-up/down stays, only receives cream retheme.

## Open Questions / Deferred

None at this time. All Q1–Q6 clarifications locked during brainstorming session.

## Dependencies

- Framer Motion — already in `ui/package.json`.
- Noto Serif + Manrope — already loaded in `ui/index.html`.
- No new npm or Python packages.

## Implementation Notes for the Plan Phase

- **Order of ops:** ledger migration first (backend-only, independently testable) → API route + test → frontend API client → palette swap → shell (icon rail, drop top bar) → round table + composer → drawers + edge tabs → MissingVoiceRow + manual-add popover → retheme aux pages.
- **Recommended split:** three sequential sub-agents (palette+shell, Governance hero, backend+aux) mirroring the prior overhaul's pattern. Reference: the prior dark-theme overhaul's sub-agent split worked; same model applies.
- **Feature flag:** if concerned about regression, wrap the shell swap in a `VITE_BOARDROOM_LIGHT=1` env flag so dark theme remains reachable via env toggle during rollout. (Optional — recommend not flagging; cream replaces dark fully.)
