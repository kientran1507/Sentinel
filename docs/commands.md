# Commands

## Local CLI

The [Docker deployment](deployment/docker.md) runs the same commands from an
installed package. Mounted journals use `--journal-directory /host/journal` on
`host-snapshot` or `host-watch`. The integrated runtime and watcher both close
owned services/storage on SIGTERM.

After [installation](development/contributing.md), `sentinel` and `python -m scripts.sentinel` expose the same interface:

```text
sentinel start
sentinel start --collector-failure-threshold 5 --collector-failure-window 60
sentinel bot start
sentinel bot status
sentinel devices --refresh --json
sentinel devices --online
sentinel devices --offline
sentinel notification test --provider all
sentinel ingest lab-events.jsonl --scope lab
sentinel host-snapshot all --scope lab --collector-id pi5 --host-ip 198.51.100.5
sentinel host-watch ssh --scope lab --collector-id pi5 --host-ip 198.51.100.5 --polls 1
sentinel prune-host-history ssh --scope lab --collector-id pi5
```

`start` and `bot start` run the same integrated monitor, storage, and command runtime. Router settings are required. `bot status` reports configured adapters, not process health.

`ingest` validates a bounded canonical JSONL file against an explicit scope. Add `--apply` to persist the prevalidated records and evaluate all default rules using the configured backend. Preview finishes before configuration loading or storage initialization. Apply commits records independently and reports partial progress if a later database operation fails. [Input contract, example, and replay](architecture/activity-evidence.md)

`host-snapshot` reads SSH journald or cumulative interface/firewall counters and reports each source's availability. `--events` emits sanitized canonical JSONL with statuses on stderr. `--input` reads an approved source export, with `--observed-at` required for counter captures. `prune-host-history` previews a source/collector/scope-limited 30-day retention batch and requires `--apply` for deletion. Example addresses use documentation ranges. [Host commands, permissions, and limits](monitoring/host-telemetry.md)

`host-watch` provides explicit periodic collection. Preview reports health without opening storage. `--apply` enables ingestion with a bounded process-local retry buffer. Defaults are a 60-second wait after each poll and 5,000 pending events. `--polls` bounds an acceptance run, and shutdown reports unsaved events. Optional sources retain their unconfigured status. [Watch lifecycle and loss limits](monitoring/host-telemetry.md#periodic-watching)

Both startup commands accept `--collector-failure-threshold` from 1 through 500 and `--collector-failure-window` from 1 through 86400 seconds. Defaults are 3 failures in a fixed 300-second UTC window. These options configure OPS-001 findings for that process. A changed policy has a distinct deduplication identity and can create another finding for retained failures. Invalid values fail before configuration loading or runtime startup. [Rule policy](monitoring/detection-rules.md)

`start`, `bot start`, `ingest`, and `host-watch` also accept repeated `--activity-rule RULE=COUNT/SECONDS` options for NET-001, NET-002, NET-003, AUTH-001, and AUTH-002. Counts accept 1 through 500 and windows accept 1 through 86400 seconds. Each rule ID can appear once. For example, `--activity-rule AUTH-001=3/60 --activity-rule AUTH-002=2/300` tunes both authentication policies. Other rules retain their defaults. Invalid or repeated IDs fail before configuration loading, input reading, storage creation, or source collection. Preview still performs validation without persistence.

Policies apply to the current process or import. Use the same settings across writers intended to share a policy. Thresholds and windows qualify finding identity, so changed settings can create additional findings when evidence is explicitly replayed. Existing findings and resolution audits retain their original policy and state.

Local `devices` reads a new process-local registry, normally empty. `--refresh` performs one ZTE poll; it does not query durable inventory or another running process. `--online`, `--offline`, and `--json` control output. Notification tests send real messages; providers are `discord`, `telegram`, or `all`.

## Remote Commands

| Command | Data source |
| --- | --- |
| `/help` | Command reference |
| `/devices` | Durable assets when nonempty, overlaid by live MAC matches; otherwise registry |
| `/status` | Live monitor, registry counts, latest live alert |
| `/alerts` | Recent in-memory alerts |
| `/events` | Persisted device events |
| `/alert-history` | Persisted alerts; Discord spelling is `/alert_history` |
| `/findings` | Persisted detection findings and current lifecycle state in the runtime's configured scope |
| `/finding` | One scoped finding with source, lifecycle, policy settings, and evidence references |
| `/resolve-finding` | Scoped resolution with a required reason and durable operator audit; Discord spelling is `/resolve_finding` |

Assets without a live match show `UNKNOWN`. A nonempty durable inventory does not union in live-only devices. No remote command triggers scanning or hostname/vendor lookup.

If the inventory list or any address query fails, `/devices` logs the failure, discards partial inventory rows, and returns the live registry instead. After restart that registry can be empty. Failed vendor enrichment displays `Unknown`. Later reads try again; PostgreSQL can reconnect on a later operation after a broken connection is discarded. Interrupted operations are not automatically replayed.

All commands require numeric user IDs in comma-separated `DISCORD_ALLOWED_USER_IDS` or `TELEGRAM_ALLOWED_USER_IDS`. Missing/malformed allowlists fail closed. Rate limiting defaults to 10 commands per user/platform in 30 seconds. Unknown commands and unsupported arguments are rejected; commands cannot execute arbitrary code or a shell.

## Platform Configuration

Discord requires `DISCORD_BOT_TOKEN`, its allowlist, and installation scopes `bot` and `applications.commands`. Optional numeric `DISCORD_GUILD_ID` selects guild synchronization; otherwise synchronization is global. Message Content privileged intent is not needed. Responses use embeds.

Telegram requires `TELEGRAM_BOT_TOKEN` and its allowlist. It uses `getUpdates` long polling and escaped HTML responses. Keep one poller per token. Outbound notification settings are described in [alerts](monitoring/alerts.md).

## Historical Queries

Telegram/shared-handler examples:

```text
/events 20
/events --device 192.0.2.10
/events --type DEVICE_OFFLINE
/alert-history --severity WARNING
/alert-history --type DEVICE_OFFLINE
```

Limits default to 50 and accept 1 through 500. Device filters accept IP, MAC, or legacy `ip:`/`mac:` identities, not opaque asset IDs. Discord exposes named limit/device/type options and severity for alert history.

Filters currently select one query path rather than intersecting: events prefer type over device; alerts prefer severity, then type, then device. Use one filter at a time. Empty history and query errors return bounded operator messages.

Event type filters use serialized values: `NEW_DEVICE`, `DEVICE_ONLINE`, `DEVICE_OFFLINE`, `IP_CHANGED`, `HOSTNAME_CHANGED`, or `CONNECTION_CHANGED`. The code names `DEVICE_DISCOVERED` and `DEVICE_RECOVERED` serialize as `NEW_DEVICE` and `DEVICE_ONLINE` respectively.

See [storage](architecture/persistent-storage.md) for restart behavior and [troubleshooting](troubleshooting/common-issues.md).

## Detection Findings

For offline review of a labelled dataset, run `python -m scripts.evaluate_activity observations.jsonl labels.json --scope lab`. It compares exact expected activity-finding counts using a separate in-memory database for each scenario. It loads no environment configuration and never connects to deployed storage. Optional `--activity-rule RULE=COUNT/SECONDS` overrides use the existing bounds. [Labels, reports, and limitations](development/labelled-activity-evaluation.md)

For a controlled acceptance run after deploying the script, use `python -m scripts.validate_detection --scope lab`. Add `--apply` to persist its 57 labelled synthetic records and check all five default activity rules, negative controls, evidence, and connection-restart replay. Each run retains its test evidence and findings under a unique collector label. Preview opens no storage. [Acceptance boundaries and expected results](development/milestone-3-acceptance.md#repeatable-controlled-activity-check)

For controlled recovery checks, use `python -m scripts.validate_host_recovery --scope lab`. Add `--apply` to exercise six process-local fault scenarios against configured storage. Expected results are 27 retained synthetic records, three deliberate buffer drops, and five findings. Run it as a separate process. [Recovery cases and limits](development/milestone-3-acceptance.md#controlled-recovery-check)

The integrated runtime exposes `/findings` through the shared allowlisted command handler and native Discord registration. It queries the runtime's configured network scope and defaults to five open findings. Limits accept 1 through 5 to keep both platform responses bounded. Status accepts `open`, `resolved`, or `all`.

```text
/findings
/findings --limit 2
/findings --status resolved
/findings --limit 5 --status all
/findings --limit 2 --before <cursor-from-previous-response>
/finding <finding-id>
```

Discord exposes named `limit`, `status`, and `before` options. Results include the finding ID, rule, severity, lifecycle state, initial evidence time, summary, and evidence count. When more results exist, the response supplies the next-page command and cursor. Continue with the same limit/status filters. Summaries and rule labels are bounded for display. Telegram uses plain text for these responses, and Discord uses an embed.

Copy a finding ID from `/findings` into `/finding <finding-id>` to inspect its rule version, source/collector, asset reference, evidence time range, resolution time, threshold/window settings, and up to three evidence IDs. Available event summaries show type, UTC timestamp, and observed IP. Expired or out-of-scope event rows display an unavailable marker. Displayed event summaries describe the current retained canonical rows. The finding retains its original evidence references and time range.

Discord exposes a named `finding_id` option. Finding IDs must use the complete `detection:v1:` identifier. The query requires the configured scope, and an unknown ID or an ID from another scope produces the same missing-finding response. Display values are bounded, and oversized evidence references are omitted from the message. The repository exposes the full finding payload and complete reference list.

Scope is supplied by runtime wiring. Missing storage or scope returns an unavailable response. Invalid/repeated options are rejected, query errors discard partial results, and the existing allowlist/rate-limit checks run before storage access. [Finding lifecycle](architecture/detection-engine.md#lifecycle)

Use `/resolve-finding <finding-id> <reason>` in Telegram, or Discord `/resolve_finding` with its required reason field. Reasons must contain 1 through 500 printable characters on one line. Existing allowlisted operators can resolve findings in the runtime scope. The state change and operator platform/ID, reason, and UTC timestamp commit together. Retries preserve the first resolution. `/finding` displays its recorded operator and reason. Older internal resolutions retain their original state and have no attributed operator audit.
