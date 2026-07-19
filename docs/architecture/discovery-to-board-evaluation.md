# Discovery-to-Board Evaluation

## Current implemented boundary (Slice A)

Discovery collection and semantic synthesis remain separate trust steps. The
coding-agent output is deterministically checked against prepared source
records, then imported as durable schema-v2 candidates. Import itself does not
invoke the board, create a venture, publish anything, or authorize execution.

Candidate lifecycle has four independent dimensions:

- discovery status: `new`, `ready_for_board`, `under_board_review`, `reviewed`;
- board label: `prioritize`, `investigate`, `defer`, `reject`, or null;
- founder disposition: `active`, `overridden`, `disposed`;
- validation state: `not_selected`, `queued`, `validating`, `validated`,
  `iterate`, `inconclusive`, or `rejected`.

Every change appends actor, previous/new values, reason, timestamp, and related
session/experiment IDs. Founder disposal is a reversible soft disposition.
Schema-v1 files migrate deterministically through a dry-run-by-default command;
apply mode creates backups before replacing files and stops on ambiguous legacy
records.

## Portfolio review

`review-portfolio` loads 5-10 active `ready_for_board` candidates and sends only
bounded summaries and exact evidence excerpts to one board session. The strict
result requires one decision per input candidate, no invented or missing IDs,
unique contiguous ranks, critical assumptions, cheapest credible tests,
success/stop signals, and minimum exposure.

The result is validated in full before candidate files change. A malformed
chair response receives one bounded repair attempt; failure records the review
attempt and leaves every candidate unchanged. Completed reviews are persisted
by deterministic idempotency key.

## Selected validation work

The board may select up to the available experiment capacity. The default is
three and the hard active maximum is five. A low-evidence portfolio may select
fewer. For each selected candidate the system idempotently creates:

1. a candidate-scoped venture;
2. an activated seven-day validation initiative whose objective is to falsify
   the critical assumption;
3. a typed validation experiment with day-7 review and day-14 expiry.

Experiment state and audit events live in domain-owned SQLite tables with a
unique candidate-plus-portfolio-review constraint. This flow does not enable
general `execution.always_on_enabled`.

## Publishing boundary

Slice A includes only a deterministic fake landing publisher used by tests. The
service rejects external publishers on this path. No network request, real site
deployment, account creation, social posting, paid action, or public API is part
of this slice.

The next slice must introduce a separately configured public landing/form trust
zone, one real free-plan adapter, explicit first-use confirmation, lead-data
retention/deletion behavior, and manual-first distribution packets.

## Concrete implementation map

| Responsibility | Implemented seam |
| --- | --- |
| Candidate schema and audit contract | `server/discovery/lifecycle/models.py` |
| Candidate file/index persistence | `server/discovery/lifecycle/store.py` |
| Backup-first v1 migration | `server/discovery/lifecycle/migrate.py` |
| Strict board portfolio contract | `server/board/portfolio.py` |
| Portfolio application/idempotency | `server/discovery/portfolio_review.py` |
| Experiment aggregate/transitions | `server/experiments/models.py` |
| Experiment SQLite/audit events | `server/experiments/store.py` |
| Venture/initiative/experiment creation | `server/experiments/service.py` |
| Fake-only publisher boundary | `server/experiments/landing/publisher.py` |
| Operator entrypoints | `server/discovery/cli.py` |

The detailed founder journey and error/retry behavior are shown in
`opportunity-validation-user-experience.md`.
