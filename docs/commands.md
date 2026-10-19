# Commands

## Local CLI

After [installation](development/contributing.md), `sentinel` and `python -m scripts.sentinel` expose the same interface:

```text
sentinel start
sentinel bot start
sentinel bot status
sentinel devices --refresh --json
sentinel devices --online
sentinel devices --offline
sentinel notification test --provider all
```

`start` and `bot start` run the same integrated monitor, storage, and command runtime. Router settings are required. `bot status` reports configured adapters, not process health.

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
