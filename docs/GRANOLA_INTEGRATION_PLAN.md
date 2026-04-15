# Granola Integration Plan — Agentic Board

## Overview

Connect Granola meeting notes to the agentic board so that meetings automatically trigger focused deliberations with dynamically assembled board members, generate CEO-ready summaries with actionable questions, and support manual queries enriched with meeting context.

---

## Architecture Design

### System Flow

```
                    Granola Cloud
                         |
                         | (Public API - Bearer token)
                         v
              +---------------------+
              | integrations/granola |  <-- Data access layer
              |   client.py         |      Fetches notes, polls for new ones
              |   models.py         |      Pydantic models for Granola data
              |   extractor.py      |      Extracts key transcript excerpts
              +---------------------+
                         |
                         v
              +---------------------+
              | board/classifier.py |  <-- AI meeting classifier
              |                     |      Reads summary, selects 3-5 members
              +---------------------+
                         |
                         v
              +---------------------+
              | board/orchestrator   |  <-- Extended orchestrator
              |  .deliberate()      |      Accepts subset of members +
              |                     |      meeting context injection
              +---------------------+
                         |
                    +---------+
                    |         |
                    v         v
           +----------+  +-----------+
           | data/     |  | notify/   |
           | awaiting_ |  | email.py  |
           | ceo/      |  |           |
           +----------+  +-----------+
```

### New Directory Structure

```
solo_company_agentic_board/
├── board/
│   ├── config.py              # MODIFY: Add tags/expertise lookup helpers
│   ├── orchestrator.py        # MODIFY: Accept member subset + meeting context
│   ├── prompts.py             # MODIFY: Add MEETING_STAGE1, MEETING_STAGE3 templates
│   ├── classifier.py          # NEW: AI classifier for dynamic board assembly
│   └── llm.py                 # No changes
├── integrations/
│   ├── __init__.py            # NEW
│   ├── granola/
│   │   ├── __init__.py        # NEW
│   │   ├── client.py          # NEW: Granola Public API client
│   │   ├── models.py          # NEW: Pydantic models (GranolaNotes, etc.)
│   │   ├── extractor.py       # NEW: Key transcript excerpt extraction
│   │   └── poller.py          # NEW: Background polling service
│   └── email/
│       ├── __init__.py        # NEW
│       └── notifier.py        # NEW: Email push notifications
├── api/
│   └── main.py                # MODIFY: Add meeting endpoints
├── data/
│   ├── conversations/         # Existing (no change)
│   └── awaiting_ceo/          # NEW: CEO decision queue folder
├── pyproject.toml             # MODIFY: Add new dependencies
└── .env.example               # MODIFY: Add Granola + email env vars
```

### Files Changed vs Created

| File | Action | Lines (est.) | Purpose |
|------|--------|-------------|---------|
| `integrations/granola/client.py` | CREATE | ~120 | Granola API client (list, get, poll) |
| `integrations/granola/models.py` | CREATE | ~80 | Pydantic data models |
| `integrations/granola/extractor.py` | CREATE | ~100 | LLM-based transcript excerpt extraction |
| `integrations/granola/poller.py` | CREATE | ~130 | Background polling + folder filtering |
| `integrations/email/notifier.py` | CREATE | ~80 | Email notifications via SMTP/Resend |
| `board/classifier.py` | CREATE | ~120 | AI meeting classifier → member selection |
| `board/prompts.py` | MODIFY | +80 | Meeting-specific prompt templates |
| `board/orchestrator.py` | MODIFY | +30 | Accept member_ids + external_context |
| `api/main.py` | MODIFY | +100 | Meeting endpoints + webhook receiver |
| `pyproject.toml` | MODIFY | +3 | New dependencies |
| `.env.example` | MODIFY | +8 | New env vars |

---

## Design Principles

### 1. Separation of Concerns — Granola Knows Nothing About the Board

The `integrations/granola/` module is a pure data access layer. It fetches and transforms Granola data into structured Python objects. It has zero knowledge of board members, prompts, or deliberation stages. The board receives a `MeetingContext` dataclass — it doesn't know the data came from Granola.

**Why**: This means you can swap Granola for any other meeting tool (Otter, Fireflies, Fathom) by writing a new client that produces the same `MeetingContext` shape.

### 2. Prompt Injection, Not Code Injection

Meeting data enters the deliberation as structured text in the prompt, not as new agent code or tools. The 3-stage protocol is unchanged. New `MEETING_STAGE1_WRAPPER` and `MEETING_STAGE3_SYNTHESIS` templates wrap the meeting context alongside the user query.

**Why**: The board's strength is its deliberation protocol. Changing the protocol for one data source would fragment the architecture. Context injection is simpler, testable, and composable.

### 3. Dynamic Assembly via AI Classifier

A lightweight LLM call (using the cheapest fast model) reads the meeting summary and returns a JSON list of 3-5 member IDs plus a meeting category. The orchestrator then creates a `BoardOrchestrator` with only those members.

**Why**: Running all 9 council members on every meeting is expensive (~9 LLM calls x 2 stages = 18 calls). A sales meeting doesn't need the Security Guardian or QA Lead. The classifier costs 1 cheap call and saves 8-12 expensive ones.

### 4. Token Budget Awareness

Full transcripts can be 50K+ tokens. The `extractor.py` module uses an LLM to distill the transcript into key excerpts: decisions made, disagreements, action items, and open questions. Target: <3000 tokens of excerpt per meeting.

**Why**: Injecting raw transcripts into 9 member prompts x 2 stages = 18 copies of the transcript in context. At 50K tokens each, that's 900K tokens per deliberation. Excerpt extraction costs 1 LLM call and saves ~850K tokens.

### 5. Interface-Agnostic Data Layer

`GranolaClient` exposes `list_notes()` and `get_note()`. Today it uses the Public API (Bearer token). Tomorrow it could use MCP (OAuth 2.0) by swapping the implementation without changing any board code.

**Why**: Granola's MCP requires OAuth 2.0 browser-based auth, which is complex for a backend service. The Public API gives identical data with simple Bearer token auth. But the interface is designed so MCP migration is a drop-in replacement.

### 6. CEO-Centric Output

The Stage 3 synthesis for meetings uses a modified template that produces:
- Executive meeting summary (what happened)
- Decisions requiring CEO input (with options and board recommendation)
- Action items with owners and deadlines
- Risk flags (anything the board flagged as concerning)

This is saved to `data/awaiting_ceo/` and pushed via email.

---

## Phase Breakdown

### Phase 1: Data Access Layer (integrations/granola/)

**Goal**: Fetch meeting data from Granola and transform it into board-ready context.

#### 1A. Pydantic Models (`integrations/granola/models.py`)

```python
"""Pydantic models for Granola API data."""

from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel


class GranolaAttendee(BaseModel):
    name: str | None = None
    email: str


class GranolaCalendarEvent(BaseModel):
    event_title: str | None = None
    organiser: str | None = None
    scheduled_start_time: datetime | None = None
    scheduled_end_time: datetime | None = None
    invitees: list[dict[str, str]] = []


class GranolaFolder(BaseModel):
    id: str
    name: str


class GranolaTranscriptSegment(BaseModel):
    speaker: dict[str, str]  # {"source": "microphone" | "speaker"}
    text: str
    start_time: datetime | None = None
    end_time: datetime | None = None


class GranolaNoteSummary(BaseModel):
    """Returned from GET /v1/notes (list endpoint)."""
    id: str
    title: str | None = None
    owner: GranolaAttendee | None = None
    created_at: datetime
    updated_at: datetime


class GranolaNote(BaseModel):
    """Returned from GET /v1/notes/{id} (detail endpoint)."""
    id: str
    title: str | None = None
    owner: GranolaAttendee | None = None
    created_at: datetime
    updated_at: datetime
    summary_text: str | None = None
    summary_markdown: str | None = None
    attendees: list[GranolaAttendee] = []
    folder_membership: list[GranolaFolder] = []
    calendar_event: GranolaCalendarEvent | None = None
    transcript: list[GranolaTranscriptSegment] = []


class MeetingContext(BaseModel):
    """Board-ready meeting context (Granola-agnostic)."""
    meeting_id: str
    title: str
    summary: str                          # markdown summary
    key_excerpts: str                     # extracted transcript highlights
    attendees: list[str]                  # display names or emails
    scheduled_time: datetime | None = None
    duration_minutes: int | None = None
    folder: str | None = None             # source folder name
    source: str = "granola"               # origin system
```

#### 1B. API Client (`integrations/granola/client.py`)

```python
"""Granola Public API client."""

from __future__ import annotations

import os
import logging
from datetime import datetime

import httpx

from .models import GranolaNote, GranolaNoteSummary

logger = logging.getLogger(__name__)

GRANOLA_BASE_URL = "https://public-api.granola.ai/v1"


class GranolaClient:
    """Thin async wrapper around Granola's Public API (v1)."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("GRANOLA_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "GRANOLA_API_KEY not set. "
                "Create one at Granola desktop app > Settings > API."
            )
        self.base_url = GRANOLA_BASE_URL

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def list_notes(
        self,
        *,
        created_after: datetime | None = None,
        updated_after: datetime | None = None,
        page_size: int = 10,
        cursor: str | None = None,
    ) -> tuple[list[GranolaNoteSummary], str | None]:
        """List notes with optional date filters. Returns (notes, next_cursor)."""
        params: dict = {"page_size": page_size}
        if created_after:
            params["created_after"] = created_after.isoformat()
        if updated_after:
            params["updated_after"] = updated_after.isoformat()
        if cursor:
            params["cursor"] = cursor

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.base_url}/notes",
                headers=self._headers(),
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

        notes = [GranolaNoteSummary(**n) for n in data.get("notes", [])]
        next_cursor = data.get("cursor")
        return notes, next_cursor

    async def get_note(
        self,
        note_id: str,
        *,
        include_transcript: bool = True,
    ) -> GranolaNote:
        """Fetch a single note by ID, optionally with transcript."""
        params = {}
        if include_transcript:
            params["include"] = "transcript"

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.base_url}/notes/{note_id}",
                headers=self._headers(),
                params=params,
            )
            resp.raise_for_status()

        return GranolaNote(**resp.json())

    async def list_all_notes_since(
        self, since: datetime, page_size: int = 30
    ) -> list[GranolaNoteSummary]:
        """Paginate through all notes created after a given datetime."""
        all_notes: list[GranolaNoteSummary] = []
        cursor = None

        while True:
            notes, cursor = await self.list_notes(
                created_after=since, page_size=page_size, cursor=cursor,
            )
            all_notes.extend(notes)
            if not cursor:
                break

        return all_notes
```

#### 1C. Transcript Excerpt Extractor (`integrations/granola/extractor.py`)

```python
"""Extract key transcript excerpts using a lightweight LLM call."""

from __future__ import annotations

import json
import logging

from board.llm import query_llm

logger = logging.getLogger(__name__)

EXTRACT_PROMPT = """\
You are a meeting analyst. Given a raw meeting transcript, extract the most
important excerpts organized into these categories:

1. **Decisions Made** — concrete decisions with who decided
2. **Disagreements** — points of contention, unresolved debates
3. **Action Items** — tasks assigned with owners (if mentioned)
4. **Open Questions** — questions raised but not answered
5. **Key Insights** — surprising information, data points, or strategic signals

RULES:
- Keep total output under 2000 words
- Quote directly from transcript when possible (use "..." for brevity)
- Include speaker attribution when identifiable
- Skip pleasantries, logistics, and filler
- If a category has no content, omit it entirely

Return as structured markdown.

TRANSCRIPT:
{transcript}
"""

# Use the cheapest fast model for extraction
EXTRACT_MODEL = "openai/gpt-4.1-mini"


async def extract_key_excerpts(
    transcript_segments: list[dict],
    model: str = EXTRACT_MODEL,
) -> str:
    """Distill a raw transcript into key excerpts (~2000 words max).

    Args:
        transcript_segments: List of transcript segment dicts with
            'speaker', 'text', 'start_time', 'end_time' keys.
        model: LLM model to use for extraction.

    Returns:
        Structured markdown string of key excerpts.
    """
    if not transcript_segments:
        return "(No transcript available)"

    # Format raw transcript
    lines = []
    for seg in transcript_segments:
        source = seg.get("speaker", {}).get("source", "unknown")
        speaker_label = "You" if source == "microphone" else "Other"
        lines.append(f"[{speaker_label}]: {seg['text']}")

    raw_transcript = "\n".join(lines)

    # If transcript is short enough (<1500 words), return directly
    word_count = len(raw_transcript.split())
    if word_count < 1500:
        logger.info(f"Transcript short enough ({word_count} words), skipping extraction")
        return raw_transcript

    prompt = EXTRACT_PROMPT.format(transcript=raw_transcript)
    messages = [{"role": "user", "content": prompt}]

    logger.info(f"Extracting key excerpts from {word_count}-word transcript")
    content = await query_llm(model, messages, max_tokens=2048, temperature=0.3)
    return content
```

---

### Phase 2: AI Meeting Classifier (`board/classifier.py`)

**Goal**: Read a meeting summary and select the 3-5 most relevant board members.

```python
"""AI meeting classifier — selects relevant board members per meeting."""

from __future__ import annotations

import json
import logging

from .config import BOARD_MEMBERS, BoardMember
from .llm import query_llm

logger = logging.getLogger(__name__)

# Cheapest fast model for classification
CLASSIFIER_MODEL = "openai/gpt-4.1-mini"

CLASSIFY_PROMPT = """\
You are a meeting router for a company advisory board. Given a meeting summary,
select 3-5 board members whose expertise is most relevant.

AVAILABLE BOARD MEMBERS:
{members_description}

MEETING SUMMARY:
{meeting_summary}

MEETING ATTENDEES:
{attendees}

INSTRUCTIONS:
1. Identify the meeting's primary domain (sales, engineering, security, strategy, etc.)
2. Select 3-5 members whose expertise directly applies
3. Always include "chairperson" — the CEO must see every meeting
4. Assign a meeting_category label

Return ONLY valid JSON (no markdown fences):
{{
  "meeting_category": "sales|engineering|security|strategy|product|hiring|finance|operations|general",
  "selected_members": ["chairperson", "strategist", "builder"],
  "reasoning": "Brief explanation of why these members were selected"
}}
"""


def _describe_members() -> str:
    """Build a compact description of all board members for the classifier."""
    lines = []
    for m in BOARD_MEMBERS:
        lines.append(
            f"- **{m.id}** ({m.title}, {m.role}): "
            f"Expertise in {', '.join(m.expertise)}"
        )
    return "\n".join(lines)


async def classify_meeting(
    meeting_summary: str,
    attendees: list[str],
    model: str = CLASSIFIER_MODEL,
) -> tuple[list[BoardMember], str]:
    """Classify a meeting and return selected board members + category.

    Returns:
        (selected_members, meeting_category)
    """
    prompt = CLASSIFY_PROMPT.format(
        members_description=_describe_members(),
        meeting_summary=meeting_summary,
        attendees=", ".join(attendees) if attendees else "Not specified",
    )
    messages = [{"role": "user", "content": prompt}]

    content = await query_llm(model, messages, max_tokens=512, temperature=0.2)

    # Parse JSON response
    try:
        # Strip markdown fences if present
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
        result = json.loads(cleaned)
    except (json.JSONDecodeError, IndexError):
        logger.warning(f"Classifier returned invalid JSON, falling back to full board: {content[:200]}")
        return [m for m in BOARD_MEMBERS], "general"

    selected_ids = result.get("selected_members", [])
    category = result.get("meeting_category", "general")

    # Always ensure chairperson is included
    if "chairperson" not in selected_ids:
        selected_ids.insert(0, "chairperson")

    # Map IDs to BoardMember objects
    members_by_id = {m.id: m for m in BOARD_MEMBERS}
    selected = [members_by_id[mid] for mid in selected_ids if mid in members_by_id]

    if len(selected) < 2:
        logger.warning("Classifier selected too few members, falling back to full board")
        return [m for m in BOARD_MEMBERS], "general"

    logger.info(
        f"Meeting classified as '{category}', "
        f"selected {len(selected)} members: {[m.id for m in selected]}"
    )
    return selected, category
```

---

### Phase 3: Orchestrator Extension

**Goal**: Allow `BoardOrchestrator` to accept a subset of members and inject meeting context into prompts.

#### 3A. Modify `board/orchestrator.py`

**Changes** (minimal — 3 modifications):

1. `deliberate()` accepts optional `external_context: str` parameter
2. `stage1()` and `stage2()` pass context through to prompts
3. `BoardSession` stores `meeting_id` and `meeting_category` metadata

```python
# In BoardSession dataclass, add:
    meeting_id: str | None = None
    meeting_category: str | None = None

# In to_dict(), add:
    "meeting_id": self.meeting_id,
    "meeting_category": self.meeting_category,

# In deliberate(), change signature:
    async def deliberate(
        self,
        user_query: str,
        session_id: str | None = None,
        external_context: str = "",         # NEW
        meeting_id: str | None = None,      # NEW
        meeting_category: str | None = None, # NEW
    ) -> BoardSession:

# In stage1(), pass context:
    async def stage1(self, user_query: str, external_context: str = "") -> list[MemberResponse]:
        ...
        for member in self.council:
            prompt = STAGE1_WRAPPER.format(
                system_prompt=member.system_prompt,
                role=member.role,
                user_query=user_query,
                external_context=external_context,  # NEW
            )
```

#### 3B. Add Meeting-Specific Prompts to `board/prompts.py`

```python
# ---------------------------------------------------------------------------
# Meeting-Specific Stage 1 — Independent Analysis with Meeting Context
# ---------------------------------------------------------------------------

MEETING_STAGE1_WRAPPER = """\
{system_prompt}

───────────────────────────────────────
BOARD SESSION — STAGE 1: MEETING ANALYSIS
───────────────────────────────────────

You are in Stage 1 of a board deliberation triggered by a meeting.
Analyze the meeting content through the lens of your role as {role}.

MEETING CONTEXT:
Title: {meeting_title}
Attendees: {attendees}
Category: {meeting_category}
Time: {meeting_time}

MEETING SUMMARY:
{meeting_summary}

KEY TRANSCRIPT EXCERPTS:
{key_excerpts}

Structure your response as:
1. **Meeting Assessment**: What happened in this meeting and what's the strategic significance?
2. **Domain Analysis**: What matters from your specific expertise area?
3. **Risks & Red Flags**: Anything concerning from your perspective?
4. **Recommendations**: Concrete actions the company should take.
5. **CEO Questions**: 1-3 specific questions the CEO should weigh in on.

Be direct. Be specific. Focus on actionable intelligence, not summary.
"""


# ---------------------------------------------------------------------------
# Meeting-Specific Stage 3 — CEO-Oriented Synthesis
# ---------------------------------------------------------------------------

MEETING_STAGE3_CEO_SYNTHESIS = """\
{chairman_system_prompt}

───────────────────────────────────────
BOARD SESSION — STAGE 3: CEO MEETING BRIEFING
───────────────────────────────────────

Your board has analyzed a meeting. Synthesize all input into a CEO briefing
that enables fast, informed decision-making.

SYNTHESIS PROTOCOL:
1. Lead with decisions that need CEO attention — do not bury them.
2. Weigh evidence over opinion. Where members disagree, present both sides.
3. Be brutally concise — the CEO reads this in 2 minutes.

STRUCTURE YOUR CEO BRIEFING AS:

## Meeting Briefing: {meeting_title}

### TL;DR
(2-3 sentences: what happened and why it matters)

### Decisions Requiring CEO Input
(Numbered list. Each: the decision, options, board's recommendation, and WHY)

### Action Items
(Who | What | Deadline | Priority)

### Risk Flags
(Anything the board flagged as concerning — ranked by urgency)

### Strategic Implications
(How this meeting connects to company strategy and priorities)

### Board Consensus vs Dissent
(Where the board agreed, where they disagreed, and unresolved debates)

MEETING TITLE: {meeting_title}
MEETING CATEGORY: {meeting_category}

───────────────────────────────────────
STAGE 1 — INDEPENDENT ANALYSES:
───────────────────────────────────────
{stage1_responses}

───────────────────────────────────────
STAGE 2 — PEER REVIEWS:
───────────────────────────────────────
{stage2_responses}

───────────────────────────────────────
YOUR CEO BRIEFING:
"""
```

---

### Phase 4: Background Polling Service

**Goal**: Poll Granola for new notes in watched folders, trigger deliberations automatically.

```python
"""Background polling service for Granola notes."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from .client import GranolaClient
from .models import MeetingContext, GranolaNote
from .extractor import extract_key_excerpts

logger = logging.getLogger(__name__)

STATE_FILE = Path("data/granola_poll_state.json")


class GranolaPoller:
    """Polls Granola for new meeting notes and triggers board deliberation."""

    def __init__(
        self,
        client: GranolaClient,
        watched_folders: list[str],         # folder names to watch
        poll_interval_seconds: int = 300,   # 5 minutes default
        on_new_meeting: callable = None,    # callback(MeetingContext)
    ):
        self.client = client
        self.watched_folders = [f.lower() for f in watched_folders]
        self.poll_interval = poll_interval_seconds
        self.on_new_meeting = on_new_meeting
        self._last_check = self._load_state()
        self._running = False

    def _load_state(self) -> datetime:
        """Load last poll timestamp from disk."""
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text())
            return datetime.fromisoformat(data["last_check"])
        return datetime.now(timezone.utc)

    def _save_state(self):
        """Persist last poll timestamp."""
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({
            "last_check": self._last_check.isoformat(),
        }))

    def _in_watched_folder(self, note: GranolaNote) -> bool:
        """Check if note belongs to any watched folder."""
        if not self.watched_folders:
            return True  # no filter = watch all
        for folder in note.folder_membership:
            if folder.name.lower() in self.watched_folders:
                return True
        return False

    async def _build_meeting_context(self, note: GranolaNote) -> MeetingContext:
        """Transform a GranolaNote into a board-ready MeetingContext."""
        # Extract key transcript excerpts
        transcript_dicts = [seg.model_dump() for seg in note.transcript]
        key_excerpts = await extract_key_excerpts(transcript_dicts)

        # Calculate duration
        duration = None
        if note.calendar_event and note.calendar_event.scheduled_start_time and note.calendar_event.scheduled_end_time:
            delta = note.calendar_event.scheduled_end_time - note.calendar_event.scheduled_start_time
            duration = int(delta.total_seconds() / 60)

        return MeetingContext(
            meeting_id=note.id,
            title=note.title or "Untitled Meeting",
            summary=note.summary_markdown or note.summary_text or "",
            key_excerpts=key_excerpts,
            attendees=[a.name or a.email for a in note.attendees],
            scheduled_time=note.calendar_event.scheduled_start_time if note.calendar_event else None,
            duration_minutes=duration,
            folder=note.folder_membership[0].name if note.folder_membership else None,
        )

    async def poll_once(self) -> list[MeetingContext]:
        """Run a single poll cycle. Returns new meetings found."""
        logger.info(f"Polling Granola for notes since {self._last_check.isoformat()}")

        notes, _ = await self.client.list_notes(
            created_after=self._last_check,
            page_size=30,
        )

        new_meetings = []
        for note_summary in notes:
            # Fetch full note with transcript
            full_note = await self.client.get_note(
                note_summary.id, include_transcript=True,
            )

            # Check folder filter
            if not self._in_watched_folder(full_note):
                logger.debug(f"Skipping note {full_note.id} — not in watched folders")
                continue

            meeting = await self._build_meeting_context(full_note)
            new_meetings.append(meeting)
            logger.info(f"New meeting found: {meeting.title} ({meeting.meeting_id})")

        # Update checkpoint
        self._last_check = datetime.now(timezone.utc)
        self._save_state()

        # Fire callback for each new meeting
        if self.on_new_meeting:
            for meeting in new_meetings:
                await self.on_new_meeting(meeting)

        return new_meetings

    async def start(self):
        """Start the background polling loop."""
        self._running = True
        logger.info(
            f"Granola poller started. Watching folders: {self.watched_folders}. "
            f"Interval: {self.poll_interval}s"
        )
        while self._running:
            try:
                await self.poll_once()
            except Exception as e:
                logger.error(f"Poll cycle failed: {e}", exc_info=True)
            await asyncio.sleep(self.poll_interval)

    def stop(self):
        """Signal the polling loop to stop."""
        self._running = False
```

---

### Phase 5: Meeting Deliberation Pipeline

**Goal**: Wire everything together — from meeting context to CEO briefing.

This is the core orchestration function that lives in a new file:

```python
# integrations/granola/pipeline.py
"""End-to-end meeting deliberation pipeline."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from board.classifier import classify_meeting
from board.orchestrator import BoardOrchestrator
from board.prompts import MEETING_STAGE1_WRAPPER, MEETING_STAGE3_CEO_SYNTHESIS

from .models import MeetingContext

logger = logging.getLogger(__name__)

CEO_QUEUE_DIR = Path("data/awaiting_ceo")


async def deliberate_meeting(
    meeting: MeetingContext,
    *,
    on_stage_start: callable = None,
    on_member_done: callable = None,
    on_stage_done: callable = None,
) -> dict:
    """Run full board deliberation on a meeting.

    1. Classify meeting → select relevant board members
    2. Create orchestrator with selected members
    3. Run 3-stage deliberation with meeting-specific prompts
    4. Save result to awaiting_ceo/ folder
    5. Return the session dict

    Returns:
        Complete board session dict with meeting metadata.
    """
    logger.info(f"Starting deliberation for meeting: {meeting.title} ({meeting.meeting_id})")
    t0 = time.monotonic()

    # Step 1: Classify and select members
    selected_members, category = await classify_meeting(
        meeting_summary=meeting.summary,
        attendees=meeting.attendees,
    )
    logger.info(f"Classified as '{category}', selected: {[m.id for m in selected_members]}")

    # Step 2: Build meeting context string for prompt injection
    meeting_context = _format_meeting_context(meeting, category)

    # Step 3: Create orchestrator with selected members only
    orchestrator = BoardOrchestrator(
        members=selected_members,
        on_stage_start=on_stage_start,
        on_member_done=on_member_done,
        on_stage_done=on_stage_done,
    )

    # Step 4: Run deliberation
    session = await orchestrator.deliberate(
        user_query=f"Analyze this meeting and produce a CEO briefing:\n\n{meeting_context}",
        session_id=f"meeting_{meeting.meeting_id}_{int(time.time())}",
        external_context=meeting_context,
        meeting_id=meeting.meeting_id,
        meeting_category=category,
    )

    # Step 5: Save to CEO queue
    _save_to_ceo_queue(session, meeting, category)

    elapsed = round(time.monotonic() - t0, 2)
    logger.info(f"Meeting deliberation complete in {elapsed}s: {meeting.title}")

    return session.to_dict()


def _format_meeting_context(meeting: MeetingContext, category: str) -> str:
    """Format meeting data as structured text for prompt injection."""
    return f"""MEETING: {meeting.title}
CATEGORY: {category}
TIME: {meeting.scheduled_time or 'Unknown'}
DURATION: {meeting.duration_minutes or 'Unknown'} minutes
ATTENDEES: {', '.join(meeting.attendees) if meeting.attendees else 'Unknown'}
FOLDER: {meeting.folder or 'Uncategorized'}

--- MEETING SUMMARY ---
{meeting.summary}

--- KEY TRANSCRIPT EXCERPTS ---
{meeting.key_excerpts}
"""


def _save_to_ceo_queue(session, meeting: MeetingContext, category: str):
    """Save the deliberation result to the CEO decision queue."""
    CEO_QUEUE_DIR.mkdir(parents=True, exist_ok=True)

    output = {
        **session.to_dict(),
        "meeting_metadata": {
            "meeting_id": meeting.meeting_id,
            "title": meeting.title,
            "category": category,
            "attendees": meeting.attendees,
            "scheduled_time": meeting.scheduled_time.isoformat() if meeting.scheduled_time else None,
            "folder": meeting.folder,
        },
    }

    filepath = CEO_QUEUE_DIR / f"{session.session_id}.json"
    filepath.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    logger.info(f"Saved to CEO queue: {filepath}")
```

---

### Phase 6: Email Notifications

```python
# integrations/email/notifier.py
"""Email notification for CEO meeting briefings."""

from __future__ import annotations

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)


async def notify_ceo(
    meeting_title: str,
    meeting_category: str,
    ceo_briefing_content: str,
    session_id: str,
):
    """Send email notification to CEO with meeting briefing summary.

    Uses SMTP. Configure via environment variables:
    - SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD
    - CEO_EMAIL (recipient)
    - BOARD_EMAIL_FROM (sender display)
    """
    smtp_host = os.getenv("SMTP_HOST")
    ceo_email = os.getenv("CEO_EMAIL")

    if not smtp_host or not ceo_email:
        logger.warning("Email not configured (SMTP_HOST or CEO_EMAIL missing), skipping notification")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[Board] {meeting_category.upper()}: {meeting_title}"
    msg["From"] = os.getenv("BOARD_EMAIL_FROM", "board@agentic-board.local")
    msg["To"] = ceo_email

    # Extract first ~500 chars of Stage 3 synthesis as preview
    preview = ceo_briefing_content[:500] + "..." if len(ceo_briefing_content) > 500 else ceo_briefing_content

    text_body = f"""
Meeting Briefing: {meeting_title}
Category: {meeting_category}
Session: {session_id}

{preview}

---
Full briefing saved to: data/awaiting_ceo/{session_id}.json
"""

    html_body = f"""
<html><body>
<h2>Meeting Briefing: {meeting_title}</h2>
<p><strong>Category:</strong> {meeting_category}</p>
<p><strong>Session:</strong> {session_id}</p>
<hr>
<pre>{preview}</pre>
<hr>
<p><small>Full briefing saved to: data/awaiting_ceo/{session_id}.json</small></p>
</body></html>
"""

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(smtp_host, int(os.getenv("SMTP_PORT", "587"))) as server:
            server.starttls()
            server.login(
                os.getenv("SMTP_USER", ""),
                os.getenv("SMTP_PASSWORD", ""),
            )
            server.send_message(msg)
        logger.info(f"CEO notification sent: {meeting_title}")
    except Exception as e:
        logger.error(f"Failed to send CEO notification: {e}", exc_info=True)
```

---

### Phase 7: API Endpoints

**Goal**: Expose meeting deliberation via REST API.

Add to `api/main.py`:

```python
# New models
class MeetingDeliberateRequest(BaseModel):
    note_id: str                            # Granola note ID
    include_transcript: bool = True

class ManualMeetingRequest(BaseModel):
    title: str
    summary: str
    attendees: list[str] = []
    transcript_excerpts: str = ""

class PollerConfig(BaseModel):
    watched_folders: list[str]
    poll_interval_seconds: int = 300


# New endpoints

@app.post("/meetings/deliberate")
async def deliberate_meeting_endpoint(req: MeetingDeliberateRequest):
    """Manually trigger board deliberation on a specific Granola note."""
    from integrations.granola.client import GranolaClient
    from integrations.granola.extractor import extract_key_excerpts
    from integrations.granola.models import MeetingContext
    from integrations.granola.pipeline import deliberate_meeting

    client = GranolaClient()
    note = await client.get_note(req.note_id, include_transcript=req.include_transcript)

    # Build context
    transcript_dicts = [seg.model_dump() for seg in note.transcript]
    excerpts = await extract_key_excerpts(transcript_dicts) if req.include_transcript else ""

    duration = None
    if note.calendar_event and note.calendar_event.scheduled_start_time and note.calendar_event.scheduled_end_time:
        delta = note.calendar_event.scheduled_end_time - note.calendar_event.scheduled_start_time
        duration = int(delta.total_seconds() / 60)

    meeting = MeetingContext(
        meeting_id=note.id,
        title=note.title or "Untitled Meeting",
        summary=note.summary_markdown or note.summary_text or "",
        key_excerpts=excerpts,
        attendees=[a.name or a.email for a in note.attendees],
        scheduled_time=note.calendar_event.scheduled_start_time if note.calendar_event else None,
        duration_minutes=duration,
        folder=note.folder_membership[0].name if note.folder_membership else None,
    )

    result = await deliberate_meeting(meeting)
    return result


@app.get("/meetings/ceo-queue")
async def list_ceo_queue():
    """List all meetings awaiting CEO decision."""
    path = Path("data/awaiting_ceo")
    if not path.exists():
        return []
    items = []
    for f in sorted(path.glob("*.json"), reverse=True):
        data = json.loads(f.read_text())
        meta = data.get("meeting_metadata", {})
        items.append({
            "session_id": data.get("session_id"),
            "meeting_title": meta.get("title"),
            "category": meta.get("category"),
            "attendees": meta.get("attendees"),
            "scheduled_time": meta.get("scheduled_time"),
        })
    return items


@app.get("/meetings/ceo-queue/{session_id}")
async def get_ceo_briefing(session_id: str):
    """Get a specific CEO meeting briefing."""
    filepath = Path(f"data/awaiting_ceo/{session_id}.json")
    if not filepath.exists():
        raise HTTPException(404, "Briefing not found")
    return json.loads(filepath.read_text())


@app.post("/meetings/poller/start")
async def start_poller(config: PollerConfig):
    """Start background polling for new Granola notes."""
    from integrations.granola.client import GranolaClient
    from integrations.granola.poller import GranolaPoller
    from integrations.granola.pipeline import deliberate_meeting

    client = GranolaClient()
    poller = GranolaPoller(
        client=client,
        watched_folders=config.watched_folders,
        poll_interval_seconds=config.poll_interval_seconds,
        on_new_meeting=deliberate_meeting,
    )

    # Run in background task
    asyncio.create_task(poller.start())
    return {"status": "started", "watched_folders": config.watched_folders}


@app.get("/meetings/notes")
async def list_granola_notes(
    created_after: str | None = None,
    page_size: int = 10,
):
    """List recent Granola notes (proxy to Granola API)."""
    from integrations.granola.client import GranolaClient
    from datetime import datetime

    client = GranolaClient()
    since = datetime.fromisoformat(created_after) if created_after else None
    notes, cursor = await client.list_notes(created_after=since, page_size=page_size)
    return {
        "notes": [n.model_dump(mode="json") for n in notes],
        "cursor": cursor,
    }
```

---

### Phase 8: Configuration & Dependencies

#### `pyproject.toml` additions

```toml
dependencies = [
    "httpx>=0.27",
    "fastapi>=0.115",
    "uvicorn>=0.34",
    "python-dotenv>=1.0",
    "rich>=13.9",
    "pydantic>=2.10",
]
```

No new dependencies required! The project already uses `httpx` (for HTTP), `pydantic` (for models), and `fastapi` (for API). Email uses Python stdlib `smtplib`.

#### `.env.example` additions

```bash
# Granola Integration
GRANOLA_API_KEY=                          # Granola Personal or Enterprise API key
GRANOLA_WATCHED_FOLDERS=Board Review,Strategy  # Comma-separated folder names
GRANOLA_POLL_INTERVAL=300                 # Seconds between polls (default 5 min)

# Email Notifications (optional)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
CEO_EMAIL=                                # Where to send meeting briefings
BOARD_EMAIL_FROM=board@agentic-board.local
```

---

## Implementation Order

| Step | Phase | Est. Effort | Dependencies |
|------|-------|------------|--------------|
| 1 | Phase 1A: Pydantic models | 30 min | None |
| 2 | Phase 1B: Granola API client | 45 min | Phase 1A |
| 3 | Phase 1C: Transcript extractor | 30 min | Phase 1A, board/llm.py |
| 4 | Phase 2: AI classifier | 45 min | board/config.py |
| 5 | Phase 3A: Orchestrator extension | 30 min | board/orchestrator.py |
| 6 | Phase 3B: Meeting prompts | 30 min | board/prompts.py |
| 7 | Phase 5: Meeting pipeline | 45 min | Phases 1-3 |
| 8 | Phase 4: Background poller | 30 min | Phases 1, 7 |
| 9 | Phase 6: Email notifier | 20 min | None |
| 10 | Phase 7: API endpoints | 45 min | All above |
| 11 | Phase 8: Config + env setup | 10 min | None |
| 12 | Testing + integration | 60 min | All above |

**Total estimated**: ~7 hours of implementation

---

## Data Flow Diagram (Complete)

```
┌─────────────────────────────────────────────────────────────────┐
│                        TRIGGER SOURCES                          │
│                                                                 │
│  ┌─────────────┐    ┌──────────────┐    ┌────────────────────┐  │
│  │ Background   │    │ Manual API   │    │ Manual CLI         │  │
│  │ Poller       │    │ POST /meet/  │    │ (future)           │  │
│  │ (every 5min) │    │ deliberate   │    │                    │  │
│  └──────┬──────┘    └──────┬───────┘    └────────┬───────────┘  │
└─────────┼──────────────────┼───────────────────  ┼──────────────┘
          │                  │                     │
          v                  v                     v
┌─────────────────────────────────────────────────────────────────┐
│                    GRANOLA DATA LAYER                            │
│                                                                 │
│  GranolaClient.get_note()  ──→  GranolaNote (Pydantic)         │
│         │                                                       │
│         v                                                       │
│  extract_key_excerpts()    ──→  Condensed transcript (~2K words)│
│         │                                                       │
│         v                                                       │
│  MeetingContext             ──→  Board-ready dataclass           │
└─────────┬───────────────────────────────────────────────────────┘
          │
          v
┌─────────────────────────────────────────────────────────────────┐
│                    AI CLASSIFIER                                 │
│                                                                 │
│  classify_meeting(summary, attendees)                           │
│         │                                                       │
│         ├──→  meeting_category: "sales"                         │
│         └──→  selected_members: [chairperson, strategist, ...]  │
└─────────┬───────────────────────────────────────────────────────┘
          │
          v
┌─────────────────────────────────────────────────────────────────┐
│                    BOARD DELIBERATION                            │
│                                                                 │
│  BoardOrchestrator(members=selected_members)                    │
│         │                                                       │
│         ├──→  Stage 1: Selected members analyze (parallel)      │
│         │         Uses MEETING_STAGE1_WRAPPER + meeting context  │
│         │                                                       │
│         ├──→  Stage 2: Peer review (parallel)                   │
│         │         Uses standard STAGE2_WRAPPER (unchanged)       │
│         │                                                       │
│         └──→  Stage 3: Chairman CEO briefing (serial)           │
│                   Uses MEETING_STAGE3_CEO_SYNTHESIS              │
└─────────┬───────────────────────────────────────────────────────┘
          │
          v
┌─────────────────────────────────────────────────────────────────┐
│                    OUTPUT                                        │
│                                                                 │
│  ┌──────────────────┐    ┌──────────────────┐                   │
│  │ data/awaiting_ceo │    │ Email to CEO     │                   │
│  │ /{session_id}.json│    │ (SMTP push)      │                   │
│  └──────────────────┘    └──────────────────┘                   │
│                                                                 │
│  ┌──────────────────┐                                           │
│  │ GET /meetings/    │                                           │
│  │ ceo-queue         │  <── API access to queue                  │
│  └──────────────────┘                                           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Key Decisions & Tradeoffs

| Decision | Chosen | Alternative | Why |
|----------|--------|-------------|-----|
| Data source | Public API (Bearer token) | MCP (OAuth 2.0) | MCP requires browser OAuth dance — unsuitable for automated server. Public API gives same data. Interface designed for easy swap. |
| Assembly | AI classifier | Folder-to-member mapping | More flexible, handles cross-domain meetings. Costs 1 cheap LLM call, saves 8-12 expensive ones. |
| Transcript handling | LLM excerpt extraction | Full transcript | 50K-token transcripts x 18 prompt injections = 900K tokens. Extraction costs 1 call, saves ~850K tokens. |
| Protocol | Same 3-stage, new prompts | 2-stage shortcut | Preserves the board's core strength (peer review). Meeting-specific prompts give domain-appropriate output without protocol fragmentation. |
| Storage | JSON files (existing pattern) | Database | Consistent with current architecture. Database migration can come later when scale demands it. |
| Notification | SMTP email | Slack/webhook | No new dependencies (stdlib smtplib). Can add Slack later as another notifier. |
| Polling | Background asyncio task | Cron job / Zapier | Self-contained within the app. No external dependencies. Zapier adds cost + latency. |
