# Milestone 4: finding acknowledgement

Status: first implementation slice implemented and unit/SQLite validated, started 2026-11-18 on
`codex/milestone-4-acknowledgement-20261118`, based on Milestone 3 checkpoint
`a0a1ac4`. This is development code, not a production deployment or completion
of all Milestone 4 incident-management work.

## Meaning and compatibility

Acknowledgement records that an authorized operator reviewed a finding. It stores
the first committed reviewer platform/ID, a required reason and an aware UTC time.
It does not resolve the finding, change its severity, alter its evidence or send
a notification. Existing open/resolved state and finding IDs remain unchanged.

Acknowledgement is optional and independent of resolution. An operator can review
an already resolved finding; that records a later review without reopening it.
Resolution does not fabricate an acknowledgement, and acknowledgement does not
fabricate a resolution. This slice is not assignment, an investigation timeline,
repeat-review history or a new `acknowledged` lifecycle/filter value.

## Persistence contract

`FindingAcknowledgement` is immutable. Operator platforms are `discord` or
`telegram`; actor IDs are 1–64 ASCII digits. A reason is one printable line of
1–500 characters after trimming. Time must be timezone-aware and is normalized
to UTC. Repository acknowledgement cannot predate retained finding evidence.

`DetectionRepository.acknowledge()` requires the exact network scope. Unknown and
out-of-scope IDs both return `None`. The insertion and returned first review share
one transaction. A unique finding-ID key with `ON CONFLICT DO NOTHING` preserves
the first committed complete record across retries and independent writers.
`get_acknowledgement()` joins through the scoped finding before returning data.

The original finding payload, evidence links and resolution audit remain intact
through acknowledgement, replay and reopen. An acknowledgement has a foreign key
to its finding, matching the existing resolution-audit deletion boundary. This
does not add any automatic finding deletion or evidence-retention policy.

## Commands and display

Telegram/shared command:

```text
/acknowledge-finding <finding-id> Investigating the reported evidence
/finding <finding-id>
```

Discord exposes `/acknowledge_finding` with required `finding_id` and `reason`
fields. The adapter quotes fields before shared parsing. Existing allowlists and
per-user/platform rate limits precede repository access. No caller supplies its
own actor identity or scope through command arguments.

`/finding` shows the recorded acknowledgement alongside the existing resolution
and evidence details. Review reasons displayed in detail are capped at 160
characters with a truncation marker; this applies to both acknowledgement and
resolution so their combined display remains bounded. The full 500-character
reason remains in the corresponding repository audit record. Command replies
use plain text on Telegram and a bounded Discord embed. Storage/read failures
return safe errors with no partial evidence or raw driver diagnostics.

## Schema and rollout boundary

PostgreSQL migration **6** and SQLite schema **10** add only
`detection_acknowledgements`. No existing status constraint, finding payload,
resolution audit or canonical event schema is rewritten. Legacy resolved findings
keep their resolution and have no acknowledgement until an explicit review.

These migrations are invoked by initialization of the new code. Do not point an
updated development CLI/runtime at production as an informal test: a deployment
requires its own reviewed backup, stopped-writer upgrade and compatibility plan.
The accepted running image and production schema have not been changed. Older
code rejects the newer schema; switching an upgraded database back to an older
application is not an automatic rollback procedure.

## Validation

- Four standalone model tests pass on host Python 3.11.
- Nine backend-focused smoke checks pass using the actual storage modules and
  disposable SQLite, including scoped access, first-review replay, unchanged
  evidence/lifecycle, transaction rollback, independent writers, resolution
  compatibility and failed/successful schema-9 upgrades. These checks load the
  backend modules separately from the optional discovery/vendor package facade;
  they do not establish full package integration.
- Shared repository and command contracts cover both backends, plus explicit
  SQLite/PostgreSQL migration cases. They include authorization, scope, bounded
  reasons/display, safe errors, replay/restart, and first-review concurrency.
- Owner accepted-image regression passed: 644 entries, **455 passed**, 189
  PostgreSQL cases deliberately skipped, zero errors/failures. Network was disabled,
  credentials absent and SQLite disposable. One Scapy import-time rtnetlink interface
  bind was attributed and blocked by the unchanged guard. This does not validate
  live Scapy packet operations or a new PostgreSQL integration run.
- The initial run passed 454 cases and found a redundant local import in the Discord
  test that shadowed `CommandParser`. The separate revision removed only that import;
  application code was unchanged and the first failed report remains preserved.
- Python 3.10 syntax parsing and whitespace checks pass. No new dependency was
  added. Tests contact no router, bot platform or production database.

Private local results are retained under
`sentinel-acceptance/milestone-4-acknowledgement-r2-20261118.c1c9gwjm`.
Report SHA-256: `b9dd5266aed760772c0942d149b4ed37c540bd24f5ce9df93ae01c755e853fde`.
All 101 Python files in the tested copy match the working source. Model and
backend-only smoke results are retained in the initial review directory.

## Remaining Milestone 4 work

1. Run the new shared contracts against a dedicated disposable PostgreSQL database.
2. Define incident identity, explicit finding links, scope isolation and timelines.
3. Implement incident/operator workflows without changing original evidence.
4. Add durable notification-delivery history, bounded retries and storm prevention.
5. Define severity and reopening policies, then perform a separately reviewed rollout.

No dashboard, packet capture, gateway deployment or additional live SSH acceptance
is part of this first slice.
