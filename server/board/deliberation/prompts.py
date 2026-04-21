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
