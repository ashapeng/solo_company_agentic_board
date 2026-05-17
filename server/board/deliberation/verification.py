"""Stage 4: Verification layer — quality gate on chairman synthesis."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from dataclasses import asdict

from server.harness.config import get_config, resolve_verification_threshold

from ..config import get_verification_model
from ..llm import query_llm

logger = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    score: int              # 1-10
    passed: bool            # score >= 7
    deficiencies: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    status: str = "completed"
    verifier_model: str | None = None
    verifier_provider: str | None = None
    chairman_provider: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


VERIFICATION_PROMPT = """You are a quality evaluator for a board of directors deliberation system.

Evaluate the chairman's synthesis against this checklist:

1. Does it address the original query directly? (not tangential)
2. Are recommendations concrete and actionable? (who, what, when — not vague)
3. Is evidence cited for key claims? (not just assertions)
4. Are dissenting views from the board represented? (check the peer reviews)
5. Does it follow the Board Decision format? (Executive Summary, Critical Findings, etc.)
6. Is it a decision, not just a summary of what people said?

ORIGINAL QUERY:
{user_query}

STAGE 2 PEER REVIEWS (compacted):
{stage2_compacted}

CHAIRMAN'S SYNTHESIS:
{synthesis}

Respond with EXACTLY this JSON format (no other text):
{{
    "score": <1-10>,
    "deficiencies": ["issue 1", "issue 2"],
    "suggestions": ["fix 1", "fix 2"]
}}

Score guide:
- 9-10: Excellent — actionable, evidence-backed, addresses all challenges
- 7-8: Good — minor gaps but usable
- 5-6: Mediocre — missing key elements, needs revision
- 1-4: Poor — fails to synthesize or address the query"""


async def verify_synthesis(
    synthesis: str,
    stage2_compacted: str,
    user_query: str,
    *,
    query_type: str | None = None,
) -> VerificationResult:
    """Evaluate chairman synthesis quality.

    Uses a configured evaluator model separate from the chairman.
    Returns VerificationResult with score and deficiencies.
    """
    from server.board.config import get_chairman_model, get_verification_model
    from server.harness.config_provider import provider_of

    verifier_model = get_verification_model()
    verifier_provider = provider_of(verifier_model)
    chairman_provider = provider_of(get_chairman_model())

    prompt = VERIFICATION_PROMPT.format(
        user_query=user_query,
        stage2_compacted=stage2_compacted,
        synthesis=synthesis,
    )

    try:
        resp = await query_llm(
            model=get_verification_model(),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,  # near-deterministic for evaluation
            # Honor harness_config.stage4_max_tokens (default 3000). Hardcoded 500
            # was being consumed by reasoning tokens on thinking models, causing
            # empty content -> JSON parse fail -> indeterminate verdict.
            max_tokens=get_config().stage4_max_tokens,
            timeout=120.0,  # was 30s; v4-pro / glm-5.1 reasoning can take 60-90s
            fallback=True,
        )

        # Parse JSON response
        # Try to extract JSON from the response (model might wrap it in markdown)
        content = resp.content.strip()
        # Strip markdown code blocks if present
        if content.startswith("```"):
            content = content.split("\n", 1)[1]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

        data = json.loads(content)
        score = int(data.get("score", 5))
        deficiencies = data.get("deficiencies", [])
        suggestions = data.get("suggestions", [])

        return VerificationResult(
            score=score,
            passed=score >= resolve_verification_threshold(
                query_type=query_type,
                config=get_config(),
            ),
            deficiencies=deficiencies,
            suggestions=suggestions,
            verifier_model=verifier_model,
            verifier_provider=verifier_provider,
            chairman_provider=chairman_provider,
        )
    except Exception as e:
        logger.warning("Verification failed: %s. Defaulting to indeterminate.", e)
        return VerificationResult(
            score=0,
            passed=False,
            deficiencies=[f"Verification error: {e}"],
            suggestions=["Review the synthesis manually; verifier output was not parseable."],
            status="indeterminate",
            verifier_model=verifier_model,
            verifier_provider=verifier_provider,
            chairman_provider=chairman_provider,
        )
