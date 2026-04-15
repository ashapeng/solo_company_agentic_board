"""Context compaction for inter-stage response passing.

Pure string-parsing extraction — NO LLM calls. Reduces token volume
by pulling only the sections downstream stages actually need.

Stage 1 -> Stage 2:  TL;DR, Recommendation, top risk, confidence
Stage 2 -> Stage 3:  Updated Position, Peer Challenges, Ranking
"""

from __future__ import annotations

import re


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_section(content: str, section_name: str) -> str:
    """Extract a named ## section from structured output.

    Searches for a line starting with ``## <section_name>`` (case-insensitive)
    and returns everything up to the next ``## `` header or end-of-string.
    Returns an empty string if the section is not found.
    """
    # Build a pattern: ## Section Name (possibly with leading whitespace)
    pattern = re.compile(
        rf"^##\s+{re.escape(section_name)}\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(content)
    if not match:
        return ""

    start = match.end()
    # Find next ## header (same level or higher)
    next_header = re.search(r"^##\s+", content[start:], re.MULTILINE)
    if next_header:
        end = start + next_header.start()
    else:
        end = len(content)

    return content[start:end].strip()


def _extract_subsection(content: str, section_name: str) -> str:
    """Extract a named ### subsection from structured output.

    Same logic as _extract_section but for ### level headers.
    Returns empty string if not found.
    """
    pattern = re.compile(
        rf"^###\s+{re.escape(section_name)}\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(content)
    if not match:
        return ""

    start = match.end()
    # Find next ### or ## header
    next_header = re.search(r"^##(?:#)?\s+", content[start:], re.MULTILINE)
    if next_header:
        end = start + next_header.start()
    else:
        end = len(content)

    return content[start:end].strip()


def _extract_confidence(content: str) -> str:
    """Extract the confidence level from the header line.

    Expected format: ``> Member: ... | Confidence: [High|Medium|Low]``
    Returns the confidence value or "Unknown".
    """
    match = re.search(r"Confidence:\s*(High|Medium|Low)", content, re.IGNORECASE)
    return match.group(1) if match else "Unknown"


def _extract_top_risk(risks_text: str) -> str:
    """Return the first (highest-severity) risk bullet from the Risks section.

    Risks are ordered Critical > High > Medium > Low in the output format.
    We return the first bullet line found, which should be the most severe.
    """
    if not risks_text:
        return ""

    severity_order = ["Critical", "High", "Medium", "Low"]
    lines = risks_text.strip().splitlines()
    risk_lines = [ln.strip() for ln in lines if ln.strip().startswith("- ")]

    # Try to find the highest severity first
    for severity in severity_order:
        for line in risk_lines:
            if f"**{severity}**" in line:
                return line
    # Fallback: return the first risk bullet if severity labels don't match
    return risk_lines[0] if risk_lines else ""


# ---------------------------------------------------------------------------
# Stage 1 compaction (for Stage 2 peer review)
# ---------------------------------------------------------------------------

def _compact_single_stage1(content: str) -> str:
    """Compact a single Stage 1 response to its key signals.

    Extracts:
    - Confidence level (from header)
    - TL;DR section (verbatim)
    - Recommendation section (verbatim)
    - Top risk (highest severity only)
    """
    confidence = _extract_confidence(content)
    tldr = _extract_section(content, "TL;DR")
    recommendation = _extract_section(content, "Recommendation")
    top_risk = _extract_top_risk(_extract_section(content, "Risks"))

    parts = [f"> Confidence: {confidence}"]

    if tldr:
        parts.append(f"## TL;DR\n{tldr}")
    if recommendation:
        parts.append(f"## Recommendation\n{recommendation}")
    if top_risk:
        parts.append(f"## Top Risk\n{top_risk}")

    return "\n\n".join(parts)


def compact_stage1_responses(responses: list) -> list:
    """Return new MemberResponse objects with compacted Stage 1 content.

    The original responses are NOT modified. Compacted versions are used
    only for inter-stage passing; the session retains full raw responses.
    """
    from .orchestrator import MemberResponse

    compacted = []
    for resp in responses:
        compact_content = _compact_single_stage1(resp.content)
        compacted.append(
            MemberResponse(
                member_id=resp.member_id,
                stage=resp.stage,
                content=compact_content,
                model=resp.model,
                elapsed_seconds=resp.elapsed_seconds,
            )
        )
    return compacted


# ---------------------------------------------------------------------------
# Stage 2 compaction (for Stage 3 chairman synthesis)
# ---------------------------------------------------------------------------

def _compact_single_stage2(content: str) -> str:
    """Compact a single Stage 2 response for chairman synthesis.

    Extracts:
    - Confidence level (from header)
    - Updated Position (what changed after peer review)
    - Peer Challenges (disagreements needing resolution)
    - Ranking (how this member ranked peers)
    """
    confidence = _extract_confidence(content)
    updated_position = _extract_subsection(content, "Updated Position")
    peer_challenges = _extract_subsection(content, "Peer Challenges")
    ranking = _extract_subsection(content, "Ranking")

    # Fallback: try ## level headers if ### didn't match
    if not updated_position:
        updated_position = _extract_section(content, "Updated Position")
    if not peer_challenges:
        peer_challenges = _extract_section(content, "Peer Challenges")
    if not ranking:
        ranking = _extract_section(content, "Ranking")

    parts = [f"> Confidence: {confidence}"]

    if updated_position:
        parts.append(f"### Updated Position\n{updated_position}")
    if peer_challenges:
        parts.append(f"### Peer Challenges\n{peer_challenges}")
    if ranking:
        parts.append(f"### Ranking\n{ranking}")

    return "\n\n".join(parts)


def compact_stage2_responses(responses: list) -> list:
    """Return new MemberResponse objects with compacted Stage 2 content.

    Preserves structure for _format_identified_responses() in Stage 3.
    """
    from .orchestrator import MemberResponse

    compacted = []
    for resp in responses:
        compact_content = _compact_single_stage2(resp.content)
        compacted.append(
            MemberResponse(
                member_id=resp.member_id,
                stage=resp.stage,
                content=compact_content,
                model=resp.model,
                elapsed_seconds=resp.elapsed_seconds,
            )
        )
    return compacted
