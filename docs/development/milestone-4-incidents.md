# Milestone 4: explicit investigation cases

Implemented and unit/SQLite validated on 2026-11-18, following the
[acknowledgement slice](milestone-4-acknowledgement.md). An incident is an
operator-created case grouping finding references and investigation notes.
The running accepted image and production database remain unchanged.

## Operator workflow

Shared/Telegram commands:

```text
/create-incident ssh-review Investigate repeated SSH failures
/link-finding <incident-id> <finding-id> Same target and account
/incident-note <incident-id> owner-check Owner confirms test activity
/incident <incident-id>
/resolve-incident <incident-id> Investigation complete; no further action
/incidents --status resolved --limit 2
```

Substitute IDs returned by previous commands. Discord exposes underscore names
for the four multiword actions, with separate required fields. Adapters quote
free-text fields before shared parsing. Existing allowlists and rate limits run
first; scope and actor identity come from the runtime and authenticated user.
These commands need a future reviewed deployment before production use.

`/incidents` defaults to five open cases. `--limit` accepts 1–5 and `--status`
accepts `open`, `resolved` or `all`. A returned `--before` cursor pages older
cases, ordered by creation time then identity. Notes do not reorder cases.

`/incident` shows three newest audit events and up to three finding references.
Its separate `--before` cursor pages older timeline events, including all finding
link actions. Use `/finding` for retained finding details. Missing findings are
labelled unavailable; their case references remain. Displayed reasons are capped
at 160 characters with a truncation marker; full reasons remain stored. Responses
are bounded for Telegram plain text and Discord embeds. No raw finding/event
payload is included. Read/storage failures discard partial responses.

## Identity, retries and lifecycle

Incident identity derives from the exact network scope and a stable case key.
Case/note keys accept 1–64 ASCII letters/digits/dots/underscores/hyphens, starting
with a letter or digit. Titles are immutable printable lines of 1–120 characters.
Reusing a case key and identical normalized title returns the original case and
creation audit; a different title conflicts.

Each immutable audit event records action, incident, authenticated platform/user,
reason and aware UTC timestamp. Links also carry the finding ID; notes carry a
stable note key. Reasons use the same 1–500 printable-character validation as
finding reviews. Actor IDs are 1–64 ASCII digits; platforms are Discord/Telegram.
Commands supply the current server time. Repository actions cannot predate case
creation; links also cannot predate retained finding evidence. Out-of-order
note/link timestamps after creation are accepted; `updated_at` retains the latest
action time. Resolution cannot predate that time.

Actions commit atomically and serialize writers for the same case. Creation,
link and resolution retries retain the first committed audit. A repeated note
key with identical normalized text returns its original audit; different text
conflicts. Reuse the original stable key when retrying. Existing audits cannot
be replaced by a later actor/time/reason. New actions on resolved cases fail;
replays of committed actions return the original result without reopening.
There is no edit, unlink, delete, reassignment or reopen command.

A finding may belong to several cases, once per case. Both records must have the
same scope when linked. Missing and out-of-scope records have the same response.
Closing a case leaves every finding's payload, evidence, acknowledgement and
open/resolved state unchanged. Findings retain their own review/resolve commands.
No notification is sent by incident actions.

## Persistence and rollout

PostgreSQL migration **7** / SQLite schema **11** add `incidents`,
`incident_events` and `incident_findings`. They provide scoped case-key uniqueness,
creation/timeline indexes and foreign keys between the case tables. Finding IDs
are soft references: independent finding deletion does not erase the timeline.
Reads join finding details through the case's exact scope, so stale references
cannot expose another scope's payload. No automatic incident retention is added.
Manual SQL mutation is outside the immutable repository contract.

The existing runtime supplies shared storage and scope to the incident commands.
No collector starts as a result of an incident action. Bounded list/detail queries
are separate reads and may see concurrent commits rather than one frozen snapshot.

New initialization applies additive migrations. Development validation uses only
disposable databases. Production rollout requires a separate backup, stopped-writer
upgrade and compatibility review. Older code rejects newer schemas; changing an
image alone is not a database rollback.

## Validation

- Five pure model tests pass on host Python 3.11.
- A backend-only smoke test using actual modules and temporary SQLite passed
  creation/linking, concurrent identical notes, pagination, case closure without
  finding changes and full audit equality after reconnect. It bypasses the
  optional package facade and does not claim full application integration.
- Owner execution of the frozen source in the accepted image passed **482 tests**:
  693 entries, **211 PostgreSQL skips**, zero failures/errors. Network was disabled,
  credentials absent and SQLite temporary. The unchanged guard blocked Scapy's
  import-time AF_NETLINK interface-enumeration bind before OS execution. This
  does not establish live Scapy packet-operation coverage.
- Shared repository/command contracts cover replay, scope, authorization,
  validation, overlapping creators/linkers, note/resolution races, rollback,
  restart, full timeline paging, missing references, safe errors and Unicode
  response bounds. SQLite upgrade/rollback preserves finding and review records.
- Equivalent PostgreSQL contracts and migration tests are included but have not
  run against a new disposable PostgreSQL database. Historical PostgreSQL results
  do not certify these new changes.
- Python 3.10 syntax parsing and whitespace checks pass; no dependency was added.

Private frozen source, manifest and reports are retained under
`sentinel-acceptance/milestone-4-incidents-20261118.jak5vqcu`.
Report SHA-256:
`02a8af7be7ba77b5d9e5af789d07608f68c91e46820edcb5a87e7d5b6e7827b0`.
All 109 Python files in that frozen copy match the working source. Subsequent
changes were documentation-only; 112 local links in changed guides were checked.

## Remaining milestone work

Explicit links provide operator-selected correlation. Automatic related-alert/
finding grouping remains a separate policy decision. Durable notification-delivery
history, bounded retries, storm prevention, severity policy, PostgreSQL acceptance
and reviewed rollout remain unfinished. This slice does not complete Milestone 4.
