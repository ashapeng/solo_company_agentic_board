# Stage 1 — Independent Analysis

{{system_prompt}}

───────────────────────────────────────
BOARD SESSION — STAGE 1: INDEPENDENT ANALYSIS
───────────────────────────────────────

You are in Stage 1 of a board deliberation. You will analyze the following
request INDEPENDENTLY. Do not reference other board members — you have not
seen their responses yet.

Provide your expert perspective given your role and expertise.

## Output Format

You MUST follow the output format below exactly. Do not skip sections.
Do not add extra sections. Stay within the stated limits.

{{output_format}}

## Instructions

1. Start with the header line: your title, stage number (1), and your confidence level.
2. Lead your TL;DR with the single most important finding from your domain.
3. Every bullet in Analysis must end with either an http(s) URL (drawn from
   your web_search tool results — copy the URL exactly) or the literal string
   `[UNVERIFIED]`. Do NOT use abstract tags like `[DOMAIN_KNOWLEDGE]`,
   `[INFERENCE]`, or shorthand source names like `[BloombergNEF report]` —
   the downstream verifier rejects them. Use a real URL or `[UNVERIFIED]`
   and nothing else.
4. Risks must have concrete scenarios — no vague speculation.
5. Your Recommendation must be actionable: who does what, by when, and why.
6. Be direct. Be specific. No filler.

───────────────────────────────────────
USER REQUEST:
───────────────────────────────────────

{{user_query}}
