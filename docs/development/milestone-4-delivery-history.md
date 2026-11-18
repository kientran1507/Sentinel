# Milestone 4: notification send-attempt history

Implemented and unit/SQLite validated on 2026-11-18, following explicit investigation cases. The runtime
can record each actual notification-provider invocation and expose bounded,
read-only history. No source change has been deployed or applied to production.
This is a recording layer; it does not introduce a retry queue or scheduler.

## Meaning of the three states

| State | Meaning |
| --- | --- |
| `started` | An attempt record committed before calling the provider; completion is unknown until an outcome commits |
| `succeeded` | The provider's `send()` call returned without an exception |
| `failed` | The provider's `send()` call raised an ordinary exception |

Success is not a human receipt or an independent end-device delivery guarantee.
A failed call also does not prove that the remote provider accepted nothing: a
transport error can occur after acceptance.
A crash, interruption, clock rollback or database failure can leave a started
record after a provider actually accepted the request. Started records must not
be interpreted as definitely unsent and must not be automatically retried.

The existing runtime sends legacy device alerts. Detection findings and incident
actions still do not send new notifications. Explicit connectivity tests and
providers called outside an audited manager are outside this alert ledger.

## Send and audit boundaries

The existing alert-persistence wrapper still attempts to save the alert before
delivery. `NotificationManager` accepts an optional audit collaborator; integrated
runtime construction supplies `RuntimePersistence.delivery_audit` and the exact
configured network scope. Standalone managers preserve their prior behavior
unless that collaborator is supplied.

For each provider, the manager records a fresh random attempt ID, commits the
start, invokes `send()` outside the database transaction, then commits its result.
A failed provider does not block later providers. Audit errors are logged by
operation and exception class without database diagnostics, and do not change
the provider result or block existing best-effort sending. A failed start may
therefore leave no row; a failed finish leaves completion unknown. The journal
is deliberately not a guarantee that every external request has a durable audit.

Repeated calls to `notify()` remain actual new sends with separate attempt IDs.
Replaying a record in the repository is different: the same ID and work context
preserve the first start/outcome. Contradictory work or terminal outcomes conflict.
Identical outcome retries return the original finish time. Writers serialize
per attempt on both backends. Start and finish are separate transactions; no SQL
lock spans an HTTP call. Restart performs no automatic sends or state rewriting.

## Stored data and reads

Each attempt stores only its random ID, network scope, alert ID, short logical
provider name, UTC start/finish times, state and the fixed `provider-error`
category for failures. No token, webhook URL, chat ID, destination credentials,
message body, exception text, response body or device snapshot is copied into
the journal. Provider names contain 1–32 lowercase ASCII letters/digits/hyphens/
underscores, starting with a letter. Alert IDs are printable nonblank text up to
128 characters. Identity is independent of any secret value.

The alert ID is a soft reference. Historical attempt records survive independent
alert deletion, and no automatic retention is enabled. No unscoped legacy alert
lookup is performed by the remote history commands. Multiple configured instances
of the same logical provider produce separate attempt IDs; this slice does not
identify or freeze their destinations for future dispatch.

```text
/deliveries
/deliveries --status failed --provider telegram --limit 2
/deliveries --alert <alert-id>
/delivery <attempt-id>
```

Both platforms use the same names. Discord provides separate optional filter
fields. Existing allowlists and per-user/platform rate limits precede reads.
Scope comes from the runtime; it cannot be overridden by a command argument.
Missing and out-of-scope attempt IDs share the same response.

Lists default to five attempts, newest start time then identity. `--limit` accepts
1–5; `--status` accepts `started`, `succeeded`, `failed` or `all`. Optional provider,
alert and bounded `--before` cursor filters are preserved in the returned next-page
command. Detail shows one attempt. Reads initiate no sends, retries or status
changes. Telegram uses plain text and Discord uses a bounded embed. Read failures
discard partial results and never echo driver messages.

## Schema and rollout

PostgreSQL migration **8** / SQLite schema **12** add `notification_deliveries`
and scoped time, alert and status indexes. Existing alerts, findings, incident
records and their audit histories are preserved; no historical attempts are
invented. No destination or transport secret is used as a database key.

Initialization of the new code applies additive migrations. Do not point a
development CLI/runtime at production to test it. Production upgrade requires a
separate backup, stopped-writer and compatibility review. Old code rejects newer
schemas, so returning to an older image alone is not a database rollback.

## Validation status

Four standalone model tests and an actual-backend SQLite smoke pass, including
concurrent completion, scoped reads and complete record equality after reconnect.
The backend-only smoke bypasses the optional package facade and does not establish
full application integration. Python 3.10 syntax and whitespace checks pass.

The owner-executed frozen accepted-image suite passed **505 tests**, with **230
PostgreSQL skips**, zero errors/failures (735 entries). It used network none,
credential-free source, fixture providers and temporary SQLite. The unchanged
guard blocked Scapy's import-time AF_NETLINK interface bind before OS execution;
this does not validate live packet operations. Shared
contracts cover start/outcome replay, conflicting identities/outcomes, independent
writers, rollback, interrupted sends, audit failure isolation, commit visibility
before sending, pagination, authorization, scope and Unicode response bounds.
Upgrade/rollback tests preserve existing alert and incident records. New
PostgreSQL cases require a dedicated disposable test database and remain pending.

Private source, manifest and reports are retained under
`sentinel-acceptance/milestone-4-delivery-history-20261118.hx6ui5xd`.
All 115 tested Python files match the working source; subsequent changes were
documentation-only. Report SHA-256:
`0e2af12bc9e453557578901c5c7cda4a6e750f2b5e3e77fa690e68d8e2cfd5ed`.

## Next delivery work

Before any automatic retry implementation, define a separate durable dispatch
record with an immutable message snapshot and an explicit logical destination
identity, attempt budget, due time and concurrency ownership. Decide treatment
of provider rejection, transient failure and uncertain completion, including the
duplicate-delivery tradeoff. Do not turn historical `started` rows into a queue.
Then add bounded retries, storm prevention and severity policy, with offline
failure/restart tests before a separately reviewed rollout. Milestone 4 remains
in progress; the running deployment stays unchanged.
