# Discovery Agent and Browser Policy

## Execution boundary

Discovery is an IDE-agent-operated workflow. The project may fetch approved
sources, normalize records, prepare an agent input bundle, validate candidate
topic files, and persist accepted output. It must not call project-configured
LLM providers for collection, topic generation, clustering, or summarization.

The intended flow is:

```text
IDE coding agent
  -> run discovery doctor/fetch/prepare
  -> read the prepared bundle
  -> write candidate topics JSON with source keys and URLs
  -> run deterministic import validation
```

Board-model calls begin only after the founder explicitly promotes an accepted
topic into a board session.

## Collection order

Use the first available option in this order:

1. Official API with a dedicated application credential and read-only scopes.
2. Public RSS, Atom, CSV, or documented open-data endpoint.
3. Search-provider result metadata with links back to the original source.
4. Attended browser review of public pages when platform terms permit it.
5. Automated browser extraction only after a platform-specific review records
   the allowed paths, rate, retention, and authentication requirements.

Browser automation is not a workaround for an unavailable API, robots rules,
rate limits, CAPTCHA, access controls, or platform terms.

## Authentication rules

- Never automate with the founder's primary social-media account.
- Prefer application OAuth/API tokens over browser cookies.
- Request read-only, least-privilege scopes and use a dedicated research app or
  account where the platform permits one.
- Do not store usernames, passwords, MFA seeds, recovery codes, or session
  cookies in the repository, logs, manifests, prompts, or agent bundles.
- If browser authentication is explicitly approved, use an isolated browser
  context/profile stored outside the repository. Treat saved storage state as
  a secret capable of impersonating the account.
- Require a human to complete login, consent, MFA, and CAPTCHA. Automation must
  stop rather than bypass or repeatedly retry these gates.
- Never automate posting, liking, following, messaging, purchasing, or other
  write actions as part of discovery.

## Crawler behavior

- Identify the client honestly with a stable user agent and contact reference.
- Check and honor `robots.txt` for automated website crawling. Robots rules are
  an additional constraint, not proof that collection is legally permitted.
- Enforce per-host concurrency of one by default, exponential backoff with
  jitter, `Retry-After`, provider quotas, and a daily request ceiling.
- Cache responses within platform retention rules and support deletion or
  refresh where required.
- Do not rotate accounts, IP addresses, proxies, or credentials to evade a
  denial, suspension, rate limit, or geo/access restriction.
- Stop on 401, 403, 429, CAPTCHA, consent walls, or account-challenge pages and
  record a non-sensitive health error for human review.

## Data minimization

- Store source ID, channel, title, short excerpt, canonical URL, public
  engagement counts, and retrieval time only when needed for validation.
- Avoid private groups, private profiles, direct messages, email addresses,
  phone numbers, precise locations, deleted content, and special-category data.
- Do not use collected material for model training. Topic synthesis is
  transient analysis of a bounded research bundle.
- Publish summaries and short attributed excerpts, not full copied posts or
  audiovisual content.

## Current adapter review

| Adapter | Default posture | Required action |
|---|---|---|
| RSS and government open data | Allow | Honor source terms, attribution, and refresh requirements. |
| Hacker News Algolia | Allow with limits | Keep bounded weekly queries and source links. |
| GitHub through `gh` | Allow with limits | Use authenticated API access and respect API rate limits. |
| Reddit unauthenticated JSON | Hold for production | Replace with approved OAuth/Data API access and confirm commercial-use terms. |
| YouTube through `yt-dlp` | Hold for production | Replace discovery scraping with the YouTube Data API; do not scrape pages or download audiovisual content. |
| Product Hunt API | Allow when configured | Use its token and API terms; retain only required metadata. |
| Generic authenticated browser | Deny by default | Require a platform-specific approval record and isolated research identity. |

This policy is an engineering control, not legal advice. Platform rules and
privacy obligations change, so review the official terms before enabling a
new adapter or materially changing collection volume or purpose.
