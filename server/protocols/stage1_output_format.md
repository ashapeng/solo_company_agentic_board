# Stage 1 Output Format

Every Stage 1 response must follow this structure exactly. Do not add sections.

> Member: [Your Title] | Stage: 1 | Confidence: [High|Medium|Low]

## TL;DR
- Max 2 bullets, 40 words total. Lead with your highest-value domain finding.

## Analysis
- Max 5 bullets. Each: [finding] - [<url> or [UNVERIFIED]].
- For numeric, named-entity, or comparative findings, the citation MUST be a
  real http(s) URL — usually one returned by your web_search tool. Copy the URL
  exactly. The literal string [UNVERIFIED] is only valid for findings asserted
  from prior knowledge or inference. Abstract tags like [DOMAIN_KNOWLEDGE] /
  [INFERENCE] / [BloombergNEF report] are NOT valid citations.

## Risks
- Max 3 risks.
- Format: **[Critical|High|Medium|Low]**: [concrete scenario] - Probability: [H|M|L], Impact: [H|M|L].

## Recommendation
- **Do this:** [specific action, owner, timing]
- **Because:** [1-sentence evidence-based rationale]
- **Risk if not:** [1-sentence consequence]

## Open Questions
- Max 2 questions. Include only questions whose answer would change the recommendation.
