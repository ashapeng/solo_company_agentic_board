"""Context compaction for inter-stage response passing.

Pure string-parsing extraction — NO LLM calls. Reduces token volume
by pulling only the sections downstream stages actually need.

Stage 1 -> Stage 2:  TL;DR, Recommendation, top risk, confidence
Stage 2 -> Stage 3:  Updated Position, Peer Challenges, Ranking
"""

from __future__ import annotations

import re

from server.harness.config import HarnessConfig, resolve_stage1_compaction_policy

from .structured import parse_stage1, parse_stage2

_STAGE1_JSON_WARNING = "stage1_json_parse_failed"
_STAGE2_JSON_WARNING = "stage2_json_parse_failed"


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

def _compact_single_stage1(
    content: str,
    *,
    sections: list[str] | None = None,
    detail_sections: list[str] | None = None,
) -> str:
    parsed = parse_stage1(content)
    if parsed is not None:
        active_sections = sections or ["confidence", "tldr", "recommendation", "top_risk"]
        return _render_stage1_from_json(parsed, active_sections)
    return _compact_single_stage1_markdown(
        content, sections=sections, detail_sections=detail_sections,
    )


def _render_stage1_from_json(parsed, sections: list[str]) -> str:
    parts: list[str] = []
    if "confidence" in sections:
        parts.append(f"> Confidence: {parsed.confidence}")
    if "tldr" in sections and parsed.tldr:
        parts.append(f"## TL;DR\n{parsed.tldr}")
    if "analysis" in sections and parsed.analysis:
        parts.append(f"## Analysis\n{parsed.analysis}")
    if "recommendation" in sections and parsed.recommendation:
        parts.append(f"## Recommendation\n{parsed.recommendation}")
    if "top_risk" in sections and parsed.risks:
        severity_order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
        top = min(parsed.risks, key=lambda r: severity_order.get(r.severity, 99))
        parts.append(f"## Top Risk\n- **{top.severity}** {top.description}")
    if "open_questions" in sections and parsed.open_questions:
        parts.append(
            "## Open Questions\n" + "\n".join(f"- {q}" for q in parsed.open_questions)
        )
    return "\n\n".join(parts)


def _compact_single_stage1_markdown(
    content: str,
    *,
    sections: list[str] | None = None,
    detail_sections: list[str] | None = None,
) -> str:
    """Compact a single Stage 1 response to its key signals.

    Extracts:
    - Confidence level (from header)
    - TL;DR section (verbatim)
    - Recommendation section (verbatim)
    - Top risk (highest severity only)
    """
    active_sections = sections or ["confidence", "tldr", "recommendation", "top_risk"]
    detailed = set(detail_sections or [])

    parts: list[str] = []

    if "confidence" in active_sections:
        confidence = _extract_confidence(content)
        parts.append(f"> Confidence: {confidence}")

    content_parts_start = len(parts)  # track where content sections begin

    if "tldr" in active_sections:
        tldr = _extract_section(content, "TL;DR")
        if tldr:
            parts.append(f"## TL;DR\n{tldr}")

    if "analysis" in active_sections:
        analysis = _extract_section(content, "Analysis")
        if analysis:
            parts.append(f"## Analysis\n{analysis}")

    if "recommendation" in active_sections:
        recommendation = _extract_section(content, "Recommendation")
        if recommendation:
            parts.append(f"## Recommendation\n{recommendation}")

    if "top_risk" in active_sections:
        risks = _extract_section(content, "Risks")
        if "top_risk" in detailed and risks:
            parts.append(f"## Risks\n{risks}")
        else:
            top_risk = _extract_top_risk(risks)
            if top_risk:
                parts.append(f"## Top Risk\n{top_risk}")

    if "open_questions" in active_sections:
        open_questions = _extract_section(content, "Open Questions")
        if open_questions:
            parts.append(f"## Open Questions\n{open_questions}")

    # Rescue: if no content sections were found, try bold-header variants
    if not [p for p in parts[content_parts_start:] if p]:
        bold_tldr = re.search(r"\*\*TL;DR:?\*\*\s*(.+)", content, re.IGNORECASE)
        bold_rec = re.search(r"\*\*Recommendation:?\*\*\s*(.+)", content, re.IGNORECASE)
        if bold_tldr:
            parts.append(f"## TL;DR\n{bold_tldr.group(1).strip()}")
        if bold_rec:
            parts.append(f"## Recommendation\n{bold_rec.group(1).strip()}")

    return "\n\n".join(p for p in parts if p)


def _stage1_compaction_elements(content: str) -> dict[str, str]:
    """Return candidate Stage 1 compaction elements for usage analysis."""
    risks = _extract_section(content, "Risks")
    return {
        "tldr": _extract_section(content, "TL;DR"),
        "analysis": _extract_section(content, "Analysis"),
        "recommendation": _extract_section(content, "Recommendation"),
        "top_risk": _extract_top_risk(risks),
        "open_questions": _extract_section(content, "Open Questions"),
    }


def extract_stage1_compaction_elements(content: str) -> dict[str, str]:
    """Public wrapper used by harness evolution analysis."""
    return {
        section: text
        for section, text in _stage1_compaction_elements(content).items()
        if text
    }


def compact_stage1_with_warnings(
    responses,
    *,
    query_type=None,
    config=None,
):
    """Like compact_stage1_responses but also returns a list of parse warnings."""
    from .orchestrator import MemberResponse

    sections, detail_sections = resolve_stage1_compaction_policy(
        query_type=query_type, config=config,
    )
    warnings: list[str] = []
    compacted = []
    for resp in responses:
        if parse_stage1(resp.content) is None:
            warnings.append(f"{_STAGE1_JSON_WARNING}:{resp.member_id}")
        compacted.append(
            MemberResponse(
                member_id=resp.member_id,
                stage=resp.stage,
                content=_compact_single_stage1(
                    resp.content,
                    sections=sections,
                    detail_sections=detail_sections,
                ),
                model=resp.model,
                elapsed_seconds=resp.elapsed_seconds,
            )
        )
    return compacted, warnings


def compact_stage2_with_warnings(responses):
    from .orchestrator import MemberResponse

    warnings: list[str] = []
    compacted = []
    for resp in responses:
        if parse_stage2(resp.content) is None:
            warnings.append(f"{_STAGE2_JSON_WARNING}:{resp.member_id}")
        compacted.append(
            MemberResponse(
                member_id=resp.member_id,
                stage=resp.stage,
                content=_compact_single_stage2(resp.content),
                model=resp.model,
                elapsed_seconds=resp.elapsed_seconds,
            )
        )
    return compacted, warnings


def compact_stage1_responses(
    responses: list,
    *,
    query_type: str | None = None,
    config: HarnessConfig | None = None,
) -> list:
    """Return new MemberResponse objects with compacted Stage 1 content.

    The original responses are NOT modified. Compacted versions are used
    only for inter-stage passing; the session retains full raw responses.
    """
    compacted, _ = compact_stage1_with_warnings(
        responses, query_type=query_type, config=config,
    )
    return compacted


# ---------------------------------------------------------------------------
# Stage 2 compaction (for Stage 3 chairman synthesis)
# ---------------------------------------------------------------------------

def _compact_single_stage2(content: str) -> str:
    parsed = parse_stage2(content)
    if parsed is not None:
        return _render_stage2_from_json(parsed)
    return _compact_single_stage2_markdown(content)


def _render_stage2_from_json(parsed) -> str:
    parts = [f"> Confidence: {parsed.confidence}"]
    if parsed.updated_position:
        parts.append(f"### Updated Position\n{parsed.updated_position}")
    if parsed.peer_challenges:
        parts.append(
            "### Peer Challenges\n" + "\n".join(f"- {c}" for c in parsed.peer_challenges)
        )
    if parsed.ranking:
        parts.append("### Ranking\n" + "\n".join(f"- {r}" for r in parsed.ranking))
    return "\n\n".join(parts)


def _compact_single_stage2_markdown(content: str) -> str:
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
    compacted, _ = compact_stage2_with_warnings(responses)
    return compacted
