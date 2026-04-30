"""Stage-specific prompt templates for the 3-stage deliberation protocol.

Primary path: loads templates from protocols/*.md files.
Fallback: hardcoded strings (kept for resilience during transition).
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Protocol loader
# ---------------------------------------------------------------------------

_PROTOCOLS_DIR = Path(__file__).resolve().parents[2] / "protocols"


def load_protocol(name: str) -> str:
    """Load a protocol template from protocols/ directory.

    Returns the raw markdown content.  Raises FileNotFoundError if missing.
    """
    path = _PROTOCOLS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")


def _load_or_fallback(name: str, fallback: str) -> str:
    """Try loading a protocol file; return fallback on failure."""
    try:
        return load_protocol(name)
    except Exception as e:
        logger.warning("Failed to load protocol '%s': %s; using fallback", name, e)
        return fallback


# ---------------------------------------------------------------------------
# JSON response suffix constants
# ---------------------------------------------------------------------------

_BACKTICK = "```"  # three backticks

STAGE1_JSON_SUFFIX = (
    "\n\n---\n"
    "Return your response as a single fenced JSON object matching this schema,\n"
    "followed by any prose you want to include:\n\n"
    f"{_BACKTICK}json\n"
    "{\n"
    '  "confidence": "High | Medium | Low",\n'
    '  "tldr": "...",\n'
    '  "analysis": "...",\n'
    '  "recommendation": "...",\n'
    '  "risks": [{"severity": "Critical|High|Medium|Low", "description": "..."}],\n'
    '  "open_questions": ["..."]\n'
    "}\n"
    f"{_BACKTICK}\n\n"
    "If you cannot produce JSON, respond in the previous markdown format and keep\n"
    "`##` section headers exactly as before.\n"
)

STAGE2_JSON_SUFFIX = (
    "\n\n---\n"
    "Return a single fenced JSON object:\n\n"
    f"{_BACKTICK}json\n"
    "{\n"
    '  "confidence": "High | Medium | Low",\n'
    '  "updated_position": "...",\n'
    '  "peer_challenges": ["..."],\n'
    '  "ranking": ["..."]\n'
    "}\n"
    f"{_BACKTICK}\n\n"
    "Markdown fallback uses the same `###` section names as before.\n"
)


# ---------------------------------------------------------------------------
# Output formats
# ---------------------------------------------------------------------------

def get_output_format() -> str:
    """Backward-compatible alias for the Stage 1 output format."""
    return get_stage1_output_format()


def get_stage1_output_format() -> str:
    """Load the Stage 1 board member output format."""
    return _load_or_fallback("stage1_output_format", _FALLBACK_STAGE1_OUTPUT_FORMAT)


def get_stage2_output_format() -> str:
    """Load the Stage 2 delta-only board member output format."""
    return _load_or_fallback("stage2_delta_format", _FALLBACK_STAGE2_OUTPUT_FORMAT)


# ---------------------------------------------------------------------------
# Stage 1 — Independent Analysis
# ---------------------------------------------------------------------------

def format_stage1(*, role: str, user_query: str) -> str:
    """Build the Stage 1 user prompt for a council member.

    The member's system_prompt is sent separately via the system parameter,
    so we pass an empty string for {{system_prompt}}.
    """
    template = _load_or_fallback("stage1_independent", _FALLBACK_STAGE1)
    output_format = get_stage1_output_format()
    return (
        template
        .replace("{{system_prompt}}", "")
        .replace("{{output_format}}", output_format)
        .replace("{{user_query}}", user_query)
        + STAGE1_JSON_SUFFIX
    )


def format_stage2(
    *,
    role: str,
    user_query: str,
    anonymized_responses: str,
    stage2_behavior: str,
) -> str:
    """Build the Stage 2 user prompt for a council member."""
    template = _load_or_fallback("stage2_peer_review", _FALLBACK_STAGE2)
    output_format = get_stage2_output_format()
    return (
        template
        .replace("{{system_prompt}}", "")
        .replace("{{output_format}}", output_format)
        .replace("{{stage2_behavior}}", stage2_behavior)
        .replace("{{user_query}}", user_query)
        .replace("{{anonymized_responses}}", anonymized_responses)
        + STAGE2_JSON_SUFFIX
    )


def format_stage3(
    *,
    user_query: str,
    stage1_responses: str,
    stage2_responses: str,
    sotb: str = "(No prior State of the Board.)",
) -> str:
    """Build the Stage 3 user prompt for the chairperson."""
    template = _load_or_fallback("stage3_synthesis", _FALLBACK_STAGE3)
    return (
        template
        .replace("{{chairman_system_prompt}}", "")
        .replace("{{user_query}}", user_query)
        .replace("{{stage1_responses}}", stage1_responses)
        .replace("{{stage2_responses}}", stage2_responses)
        .replace("{{sotb}}", sotb)
    )


def format_stage4(
    *,
    user_query: str,
    stage1_responses: str,
    stage2_responses: str,
    stage3_synthesis: str,
) -> str:
    """Build the Stage 4 (Secretary Brief) user prompt for the secretary."""
    template = _load_or_fallback("stage4_secretary_brief", _FALLBACK_STAGE4)
    return (
        template
        .replace("{{secretary_system_prompt}}", "")
        .replace("{{user_query}}", user_query)
        .replace("{{stage1_responses}}", stage1_responses)
        .replace("{{stage2_responses}}", stage2_responses)
        .replace("{{stage3_synthesis}}", stage3_synthesis)
    )


# ---------------------------------------------------------------------------
# Legacy aliases — kept for backward compatibility with existing orchestrator
# ---------------------------------------------------------------------------

# These use Python .format() style placeholders to match the old interface.
# The orchestrator can use either these or the new format_stage*() functions.

STAGE1_WRAPPER = """\
{system_prompt}

───────────────────────────────────────
BOARD SESSION — STAGE 1: INDEPENDENT ANALYSIS
───────────────────────────────────────

You are in Stage 1 of a board deliberation. You will analyze the following
request INDEPENDENTLY. Do not reference other board members — you have not
seen their responses yet.

Provide your expert perspective given your role as {role}.

Output format:
{output_format}

Be direct. Be specific. No filler.

USER REQUEST:
{user_query}
"""


STAGE2_WRAPPER = """\
{system_prompt}

───────────────────────────────────────
BOARD SESSION — STAGE 2: PEER REVIEW & CHALLENGE
───────────────────────────────────────

You are in Stage 2. Review compacted Stage 1 responses from other members.
Output only deltas that help the Chairperson resolve the decision.

No praise-only comments. No restating your Stage 1 analysis.

Output format:
{output_format}

Role-specific peer-review lens:
{stage2_addendum}

ORIGINAL REQUEST:
{user_query}

───────────────────────────────────────
ANONYMIZED BOARD RESPONSES (Stage 1):
───────────────────────────────────────
{anonymized_responses}

───────────────────────────────────────
YOUR UPDATED ANALYSIS:
"""


STAGE3_SYNTHESIS = """\
{chairman_system_prompt}

───────────────────────────────────────
BOARD SESSION — STAGE 3: FINAL SYNTHESIS
───────────────────────────────────────

You are the Chairperson. The board has completed independent analysis (Stage 1)
and peer review (Stage 2). Your job is to synthesize ALL input into a single,
authoritative board decision.

SYNTHESIS PROTOCOL:
1. Weigh evidence over opinion. Where board members disagree, side with the
   one who provided stronger evidence.
2. Identify unanimous concerns — these are highest priority.
3. Resolve conflicts explicitly: state the disagreement and your ruling.
4. Produce actionable output, not a summary of what people said.

STRUCTURE YOUR FINAL DECISION AS:

## Board Decision

### Executive Summary
(2-3 sentences: what we're doing and why)

### Critical Findings
(Unanimous or near-unanimous concerns across the board)

### Strategic Direction
(The chosen path with explicit rationale)

### Architecture & Design
(Key technical decisions locked in)

### Security Posture
(Threat assessment and required mitigations)

### Implementation Plan
(Phased plan with milestones and owners)

### Risk Register
(Top risks ranked by probability x impact, with mitigations)

### Verification & Ship Criteria
(What "done" looks like; testing and release requirements)

### Dissenting Views
(Any strong objections that were overruled, and why)

### Immediate Next Steps
(The first 3 concrete actions to take NOW)

ORIGINAL REQUEST:
{user_query}

───────────────────────────────────────
STAGE 1 — INDEPENDENT ANALYSES:
───────────────────────────────────────
{stage1_responses}

───────────────────────────────────────
STAGE 2 — PEER REVIEWS:
───────────────────────────────────────
{stage2_responses}

───────────────────────────────────────
YOUR FINAL BOARD DECISION:
"""


# ---------------------------------------------------------------------------
# Fallback content (used only if protocol files are missing)
# ---------------------------------------------------------------------------

_FALLBACK_STAGE1_OUTPUT_FORMAT = """\
> Member: [Your Title] | Stage: 1 | Confidence: [High|Medium|Low]

## TL;DR
Max 2 bullets, 40 words total.

## Analysis
Max 5 bullets. Each includes evidence or [UNVERIFIED].

## Risks
Max 3 risks. Each rated by severity, probability, and impact.

## Recommendation
Concrete, actionable. Who does what, by when, and why.

## Open Questions
Max 2 questions that would change the recommendation.
"""

_FALLBACK_STAGE2_OUTPUT_FORMAT = """\
> Member: [Your Title] | Stage: 2 | Confidence: [High|Medium|Low]

### Peer Challenges
Max 3 material challenges or agreements. No praise-only comments.

### Updated Position
Changed because ... or No change because ...

### Ranking
Rank up to 3 peer responses by value to the final decision.
"""

_FALLBACK_STAGE1 = STAGE1_WRAPPER.replace("{system_prompt}", "{{system_prompt}}").replace("{role}", "{{role}}").replace("{output_format}", "{{output_format}}").replace("{user_query}", "{{user_query}}")
_FALLBACK_STAGE2 = STAGE2_WRAPPER.replace("{system_prompt}", "{{system_prompt}}").replace("{role}", "{{role}}").replace("{output_format}", "{{output_format}}").replace("{user_query}", "{{user_query}}").replace("{anonymized_responses}", "{{anonymized_responses}}").replace("{stage2_addendum}", "{{stage2_behavior}}")
_FALLBACK_STAGE3 = STAGE3_SYNTHESIS.replace("{chairman_system_prompt}", "{{chairman_system_prompt}}").replace("{user_query}", "{{user_query}}").replace("{stage1_responses}", "{{stage1_responses}}").replace("{stage2_responses}", "{{stage2_responses}}")


STAGE4_SECRETARY_BRIEF = """\
{secretary_system_prompt}

───────────────────────────────────────
BOARD SESSION — STAGE 4: SECRETARY EXECUTIVE BRIEF
───────────────────────────────────────

You are the Board Secretary. Produce a precise, attributed executive brief.

## Required Format

# Secretary Executive Brief

## One-Liner
(Single sentence, max 30 words.)

## Key Findings
(3-7 bullets. Each MUST attribute: " — [Role]".)

### Conflicts Flagged (if any)
**CONFLICT [HARD/SOFT]: [Topic]**
- Side A - [Role]: position
- Side B - [Role]: position

## Decision Summary
Table: Aspect | Decision | Source

## Risk Snapshot
Table: Risk | Prob*Impact | Mitigation | Raised By

## Action Items
Table: # | Action | Owner | Deadline | Criteria

## Detail Index
Table: Topic | Member | Stage | Reference

ORIGINAL REQUEST:
{user_query}

STAGE 1 RESPONSES:
{stage1_responses}

STAGE 2 RESPONSES:
{stage2_responses}

STAGE 3 SYNTHESIS:
{stage3_synthesis}

YOUR SECRETARY BRIEF:
"""

_FALLBACK_STAGE4 = STAGE4_SECRETARY_BRIEF.replace("{secretary_system_prompt}", "{{secretary_system_prompt}}").replace("{user_query}", "{{user_query}}").replace("{stage1_responses}}", "{{stage1_responses}}").replace("{stage2_responses}}", "{{stage2_responses}}").replace("{stage3_synthesis}}", "{{stage3_synthesis}}")


# ---------------------------------------------------------------------------
# Standalone Secretary Brief  (used when there is NO prior deliberation data)
# ---------------------------------------------------------------------------

STANDALONE_SECRETARY_BRIEF = """\
{secretary_system_prompt}

───────────────────────────────────────
STANDALONE SECRETARY EXECUTIVE BRIEF
───────────────────────────────────────

You are the Board Secretary. The CEO has asked you to provide a direct
executive brief **without** a prior board deliberation cycle.

Analyze the request below and produce a structured brief based on your
own expertise. If you lack specific data, clearly mark findings as
``[REQUIRES INPUT]``.

## Required Format

# Secretary Executive Brief

## One-Liner
(Single sentence, max 30 words.)

## Key Findings
(3-7 bullets. Attribute each with your role: " — [Board Secretary]".)

### Conflicts Flagged (if any)
**CONFLICT [HARD/SOFT]: [Topic]**
- Position A: …
- Position B: …

## Decision Summary Table
| # | Decision | Rationale | Risk |
|---|----------|-----------|------|

## Risk Snapshot
| Risk | Impact | Likelihood | Mitigation |
|------|--------|-----------|------------|

## Action Items
| # | Action | Owner | Deadline |
|----|--------|-------|----------|

## Detail Index
| Topic | Source | Reference |
|-------|--------|-----------|

---
CEO REQUEST:
{user_query}

YOUR SECRETARY BRIEF:
"""

_FALLBACK_STANDALONE_SECRETARY = STANDALONE_SECRETARY_BRIEF.replace(
    "{secretary_system_prompt}", "{{secretary_system_prompt}}"
).replace("{user_query}", "{{user_query}}")


def format_standalone_secretary_brief(*, user_query: str) -> str:
    """Build a standalone secretary prompt (no stage 1–3 context)."""
    template = _load_or_fallback("standalone_secretary_brief", _FALLBACK_STANDALONE_SECRETARY)
    return (
        template
        .replace("{{secretary_system_prompt}}", "")
        .replace("{{user_query}}", user_query)
    )


# ---------------------------------------------------------------------------
# Live Discussion Secretary Brief  (summarises a live conversation transcript)
# ---------------------------------------------------------------------------

LIVE_SECRETARY_BRIEF = """\
{secretary_system_prompt}

───────────────────────────────────────
LIVE BOARD DISCUSSION — SECRETARY {brief_mode} EXECUTIVE BRIEF
───────────────────────────────────────

You are the Board Secretary. A live boardroom discussion is in progress.
{final_context}

## Your Job
Produce a **precise, attributed executive brief** from the raw conversation
transcript below so the CEO grasps the strategic picture in under 60 seconds
while retaining drill-down ability.
{interim_instruction}

## Required Format

# 📋 Secretary Executive Brief ({brief_mode})

## One-Liner
*(Single sentence: what was discussed and the board's collective direction. Max 30 words.)*

## Key Findings
*(3-7 bullets. Each bullet MUST attribute source(s). Use format: " — [Role]".)*

### Conflicts Flagged (if any)
**CONFLICT [HARD/SOFT]: [Topic]**
- Side A — [Role]: their exact position
- Side B — [Role]: their exact position

## Decision Summary
| Aspect | Board Position | Source |
|--------|----------------|--------|

## Risk Snapshot
| Risk | Prob×Impact | Mitigation | Raised By |
|------|-------------|------------|-----------|

## Action Items
| # | Action | Owner | Deadline |
|---|--------|-------|----------|

## Detail Index
| Topic | Member | Key Quote / Reference |
|-------|--------|----------------------|

## Operating Rules
1. Attribute EVERY claim: always say who said what.
2. Flag conflicts fairly: present both sides equally.
3. Be precise: use numbers ("3 of 5 members") not vague words ("most").
4. Stay neutral: you are organising information, not advocating.
5. Do NOT introduce new analysis not present in the transcript.
6. Preserve dissent: overruled objections MUST appear.

───────────────────────────────────────
CEO'S ORIGINAL TOPIC:
───────────────────────────────────────

{user_query}

───────────────────────────────────────
CONVERSATION TRANSCRIPT SO FAR:
───────────────────────────────────────

{transcript}

───────────────────────────────────────
YOUR SECRETARY BRIEF:
"""

_FALLBACK_LIVE_SECRETARY = (
    LIVE_SECRETARY_BRIEF
    .replace("{secretary_system_prompt}", "{{secretary_system_prompt}}")
    .replace("{user_query}", "{{user_query}}")
    .replace("{transcript}", "{{transcript}}")
    .replace("{brief_mode}", "{{brief_mode}}")
    .replace("{final_context}", "{{final_context}}")
    .replace("{interim_instruction}", "{{interim_instruction}}")
)


def format_live_secretary_brief(*, user_query: str, transcript: str, brief_mode: str = "FINAL", is_final: bool = True) -> str:
    """Build a secretary prompt for a live discussion transcript."""
    template = _load_or_fallback("live_secretary_brief", _FALLBACK_LIVE_SECRETARY)

    if is_final:
        final_context = (
            "Every council member has spoken. The CEO (chairperson) now needs your "
            "comprehensive executive brief to make an informed decision."
        )
        interim_instruction = ""
    else:
        final_context = (
            f"The discussion is still ongoing — this is an **{brief_mode.lower()}** update. "
            "More members may still speak after this brief."
        )
        interim_instruction = (
            "\n## Interim Brief Rules\n"
            "- Focus on what has been said so far; note that discussion continues.\n"
            "- Highlight the latest speaker's key contributions.\n"
            "- Keep it concise — this is a progress snapshot, not the final word."
        )

    return (
        template
        .replace("{{secretary_system_prompt}}", "")
        .replace("{{user_query}}", user_query)
        .replace("{{transcript}}", transcript)
        .replace("{{brief_mode}}", brief_mode)
        .replace("{{final_context}}", final_context)
        .replace("{{interim_instruction}}", interim_instruction)
    )
