"""Query classifier for adaptive routing.

Classifies incoming queries into board decision types and selects active members via
the roster capability registry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .llm import query_llm
from .roster import (
    decision_capabilities,
    get_stage_profile,
    load_roster,
    select_members_for_capabilities,
    select_members_for_decision_type,
)

logger = logging.getLogger(__name__)


@dataclass
class QueryClassification:
    query_type: str
    complexity: str
    relevant_member_ids: list[str]
    reasoning: str
    required_capabilities: list[str] | None = None
    unavailable_capabilities: list[str] | None = None
    stage_profile: str | None = None
    role_gap_memo: str | None = None


CLASSIFICATION_PROMPT = """Classify the following query for a board of directors deliberation.

Query: {query}

Respond with EXACTLY this format (no extra text):
decision_type: [{decision_types}]
complexity: [simple|moderate|complex]
capabilities: [comma-separated capabilities, or "default"]
reasoning: [one sentence explaining why]

Decision type rules:
- "strategic": market sizing, competitive landscape, positioning, go-to-market, market entry
- "product": MVP definition, feature prioritization, value proposition, product-market fit
- "customer": customer discovery, interviews, personas, pain points, user research
- "technical": prototyping, build-vs-buy, technical feasibility, stack selection
- "security": threat modeling, data privacy, compliance, auth, public APIs
- "operational": deployment, monitoring, uptime, incident response, release readiness
- "finance": pricing, runway, margin, budget, fundraising
- "legal": contracts, IP, liability, regulated data, legal compliance
- "full-board": spans multiple domains, major company-level impact

Known capabilities:
{capabilities}

If uncertain, choose "full-board"."""


async def classify_query(query: str) -> QueryClassification:
    """Classify a query and select relevant board members."""
    roster = load_roster()
    valid_decision_types = list(roster.get("decision_types", {}).keys())
    valid_capabilities = sorted({
        capability
        for member in roster.get("members", {}).values()
        for capability in member.get("capabilities", [])
    })

    try:
        resp = await query_llm(
            model="anthropic/claude-haiku-3.5",
            messages=[{
                "role": "user",
                "content": CLASSIFICATION_PROMPT.format(
                    query=query,
                    decision_types="|".join(valid_decision_types),
                    capabilities=", ".join(valid_capabilities),
                ),
            }],
            temperature=0.1,
            max_tokens=250,
            timeout=15.0,
        )

        query_type, complexity, required_capabilities, reasoning = parse_classification(
            resp.content,
            valid_decision_types=valid_decision_types,
        )
        if not required_capabilities:
            required_capabilities = decision_capabilities(query_type, roster=roster)
        else:
            required_capabilities = [
                capability
                for capability in required_capabilities
                if capability in valid_capabilities
            ] or decision_capabilities(query_type, roster=roster)

        selection = select_members_for_capabilities(
            required_capabilities,
            stage_profile=get_stage_profile(),
            roster=roster,
        )

        return QueryClassification(
            query_type=query_type,
            complexity=complexity,
            relevant_member_ids=selection.member_ids,
            reasoning=reasoning,
            required_capabilities=selection.required_capabilities,
            unavailable_capabilities=selection.unavailable_capabilities,
            stage_profile=selection.stage_profile,
            role_gap_memo=selection.role_gap_memo,
        )
    except Exception as e:
        logger.warning("Query classification failed: %s. Falling back to full-board.", e)
        selection = select_members_for_decision_type("full-board", stage_profile=get_stage_profile())
        return QueryClassification(
            query_type="full-board",
            complexity="complex",
            relevant_member_ids=selection.member_ids,
            reasoning=f"Classification failed ({e}); defaulting to full board.",
            required_capabilities=selection.required_capabilities,
            unavailable_capabilities=selection.unavailable_capabilities,
            stage_profile=selection.stage_profile,
            role_gap_memo=selection.role_gap_memo,
        )


def parse_classification(
    content: str,
    *,
    valid_decision_types: list[str],
) -> tuple[str, str, list[str], str]:
    """Parse the compact line-oriented classifier response."""
    query_type = "full-board"
    complexity = "complex"
    capabilities: list[str] = []
    reasoning = ""

    for line in content.strip().splitlines():
        line = line.strip()
        line_key = line.lower()
        if line_key.startswith("decision_type:") or line_key.startswith("type:"):
            parsed = line.split(":", 1)[1].strip().lower()
            if parsed == "market":
                parsed = "strategic"
            if parsed in valid_decision_types:
                query_type = parsed
        elif line_key.startswith("complexity:"):
            parsed = line.split(":", 1)[1].strip().lower()
            if parsed in ("simple", "moderate", "complex"):
                complexity = parsed
        elif line_key.startswith("capabilities:"):
            parsed = line.split(":", 1)[1].strip()
            if parsed.lower() != "default":
                capabilities = [
                    item.strip().lower()
                    for item in parsed.strip("[]").split(",")
                    if item.strip()
                ]
        elif line_key.startswith("reasoning:"):
            reasoning = line.split(":", 1)[1].strip()

    return query_type, complexity, capabilities, reasoning
