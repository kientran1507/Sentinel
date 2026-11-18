# Milestone 4: explicit bounded notification dispatch

Implemented and unit/SQLite validated on 2026-11-18, following
[send-attempt history](milestone-4-delivery-history.md). This adds a durable outbox
repository and an explicitly invoked dispatcher. Nothing enqueues or dispatches
jobs automatically: no startup hook, timer, background worker, bot action or CLI
command is registered. The accepted running deployment is unchanged.

## Message and destination identity

`NotificationSnapshot.from_alert()` freezes the provider-facing fields of one
legacy device alert: its identity/type/severity/title/message/time, event identity/
type/time and the hostname/IP/MAC needed by existing providers. It copies no
arbitrary event metadata, device object, prior/current-state dictionaries or
transport configuration. Deserialization rejects unknown fields. Provider calls
reconstruct a fresh alert from this allowlisted snapshot.

The snapshot contains message/device data and needs database access protection
and a future retention policy. Unlike the metadata-only send-attempt ledger, it
stores the message body for dispatch. This is not an export of credentials or
destination configuration. Text is validated before admission, including UTF-8
validity and bounds: title 200, message 1,000, hostname 256, IP/MAC 64 and event ID
128 characters. Oversized data is rejected rather than silently truncated.

A job ID is derived from exact network scope, logical destination label and
alert ID. Re-enqueuing identical immutable content/policy returns the original
job, including terminal state. Different content, provider or retry policy with
the same identity conflicts. Different scopes or destinations create distinct
jobs. This prevents replay of the same alert to the same logical destination;
it does not group different alert IDs or suppress a stream of related alerts.

Destination labels are explicit non-secret names such as `telegram-ops-v1`,
containing 1–64 lowercase ASCII letters/digits/underscores/hyphens and starting
with a letter. The dispatcher receives an explicit mapping from those labels
to provider instances. A missing label or mismatched provider name sends nothing
and consumes no attempt. There is no environment-based fallback. The mapping is
copied on construction, but provider instances still own their transport settings.
Labels do not cryptographically pin remote destinations; integration must version
or reject a binding when its destination changes. No real binding is activated.

## Attempts and outcomes

The immutable default policy is three attempts total, with waits of 30 and 120
seconds after the first and second explicitly retryable failures. Smaller budgets
of one or two are supported with the matching delay count. Delays must be integer
seconds from 1–3,600; attempt budgets are 1–3. This is a development policy, not a
configured production service policy.

| Provider result | Outbox action |
| --- | --- |
| `send()` returns | Mark `sent`; provider-call success is not a human receipt |
| `RetryableSendError` | Adapter guarantees non-acceptance; schedule the next attempt if budget remains, otherwise mark `failed` |
| `RejectedSendError` | Adapter guarantees permanent rejection; mark `failed` |
| Any other ordinary exception | Mark `uncertain`; do not schedule another send |
| Process interruption or uncommitted outcome | Keep the claim; expiry marks `uncertain`, without reclaiming for another worker |

Existing Discord/Telegram providers have not been changed to issue either typed
non-acceptance guarantee. Their generic transport errors are uncertain when used
with this dispatcher. Tests use fixture adapters that deliberately implement the
typed contract. No HTTP status or timeout is assumed to prove non-acceptance.

## Atomic state and concurrency

Claims lock the scoped job and, in one transaction, consume one budget slot,
create a `started` row in the existing send-attempt ledger, link its attempt
number and record an exclusive attempt ID/lease. Only a due `queued` or
`retry_wait` job can be claimed. Independent workers coalesce on the same claim.
No database transaction spans the provider call.

Completion atomically updates the same send-attempt row, the attempt outcome and
job state/due time. Identical completion replay is read-only; contradictory
outcomes conflict. An old completed attempt cannot alter a later active claim.
Generic exceptions record a failed provider call in history while the outbox
remains uncertain about external acceptance. These states have different meanings.

Claims default to a 60-second lease, with explicit integer bounds of 1–3,600.
`expire_claims()` is an explicit bounded database operation. Expired work becomes
uncertain and retains its attempt ID; expiry never opens another send slot or
fabricates a provider outcome. An actual late completion for that retained claim
may record its real result. Unknown work is never automatically reclaimed.

Commit-acknowledgement failure after claiming prevents the sender from proceeding;
the database may retain an uncertain claim even though no request was sent. An
outcome-storage failure after sending similarly prevents automatic resend. If
the outcome committed before an acknowledgement error, its terminal state remains.
These choices prefer stopping for investigation over possible duplicate delivery.
Exactly-once external delivery and lossless automatic recovery are not promised.

`dispatch_one()` is an explicit single-job call. `dispatch_due()` performs one
bounded pass, default five and maximum ten candidates. There is no sleeping retry
loop or recursive resend. It does not expire claims implicitly. Storage errors
propagate to the explicit caller rather than trigger another send or a backend
fallback. No raw exception body is saved as an outcome.

## Persistence and rollout boundary

PostgreSQL migration **9** / SQLite schema **13** add `notification_outbox` and
`notification_outbox_attempts`, with scoped identity uniqueness, bounded attempt
numbers and due/expiry indexes. Attempt links reference the existing history
table. Existing history is not backfilled into jobs. Queue/history retention
must be coordinated; no retention or deletion API is enabled. Deleting a job
manually removes its link rows, not its underlying send-attempt history.

The delivery repository now shares internal transaction helpers with the outbox
so claims/outcomes and audit rows commit together. Its existing public history
API and ordinary runtime notification behavior remain unchanged. The outbox is
not instantiated as a runtime worker and does not replace `NotificationManager`.

Only disposable databases are used for validation. Initializing new development
code applies additive migrations; production requires a separately reviewed
backup, stopped-writer upgrade and compatibility procedure. Older application
versions reject newer schemas; changing images alone does not roll back a DB.

## Validation status

Five pure model tests pass. An actual-backend temporary SQLite smoke passed two
typed fixture failures, 30/120-second due-time enforcement, third-call success,
three history rows, terminal replay suppression, expired-claim uncertainty,
scoped access and full equality after reconnect. The backend-only check bypasses
the optional package facade and does not certify full runtime integration.

The owner-executed frozen-source regression passed **530 tests**, with **250
PostgreSQL skips**, zero failures/errors (780 entries). It used the accepted image,
network none, fixture providers and temporary SQLite. The unchanged guard blocked
Scapy's import-time AF_NETLINK interface bind before OS execution; this does not
validate live packet operations. Shared contracts include
independent writers, replay/conflicts, scoped claims, bounded batches, full audit
rollback, clock boundaries, interrupted calls, failures before/after commits,
late outcomes and migration rollback preserving existing history. New PostgreSQL
integration remains pending on a dedicated disposable database.

Private source, manifest and reports are retained under
`sentinel-acceptance/milestone-4-outbox-20261118.ef07vcrp`.
All 120 Python files in the tested copy match the working source; subsequent
changes were documentation-only. Report SHA-256:
`5270decaa1de550096f9fb5be1c0999db187bb1e558a9f8e9d99192df8c2b82b`.

## Remaining Milestone 4 work

Define live adapter rejection/retry classification and stable destination bindings
before any integration. Add operator inspection of queued/uncertain work, admission
capacity, cross-alert storm prevention and severity policy. Decide how the runtime
will switch from its existing immediate sender to an outbox path without sending
through both. Then validate disposable PostgreSQL contracts and review production
rollout. No live notification test, credentials, bot startup, scheduler activation
or production migration is authorized or performed by these offline tests.
