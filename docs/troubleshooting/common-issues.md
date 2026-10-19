# Troubleshooting

## Empty or Unexpected Devices

Remote `/devices` uses durable inventory when nonempty, with live MAC matches overlaid. Unmatched assets show `UNKNOWN` after restart. Live-only devices are not unioned into a nonempty persisted list. Wait for a successful ZTE baseline and check persistence errors.

Local `sentinel devices` uses a new process-local registry; `--refresh` polls ZTE once. It does not read another process or the database. See [commands](../commands.md).

## Storage Startup or Write Errors

Check backend selection, permissions/path for SQLite, or DSN/reachability and psycopg installation for PostgreSQL. An unset backend selects SQLite; PostgreSQL never falls back to it. Relative SQLite paths depend on the current working directory.

Initialization failure stops startup; later write failures are logged and isolated. Asset/address/observation updates roll back together, but preceding legacy device writes and subsequent event/alert writes are independent. Preserve database files and avoid treating a restart as a repair. PostgreSQL migration and rollback tests pass; network-outage recovery still needs verification. See [storage](../architecture/persistent-storage.md).

## Discovery Flags Have No Effect

Use `--orchestrator` with `--persist` or `--resolve-hostnames`. The discovery helper does not load repository `.env`; provide storage settings in its process environment. ARP needs Scapy, packet access, and local-link reachability; ICMP may be filtered.

## Telegram HTTP 409

`Conflict: terminated by other getUpdates request` indicates competing pollers using one token. Keep one active consumer.

## Missing or Rejected Commands

Discord needs its bot token, `bot` and `applications.commands` installation scopes, and successful command synchronization. Optional numeric `DISCORD_GUILD_ID` selects guild synchronization. Message Content intent is not required.

Use comma-separated numeric platform user IDs in the command allowlists. Missing/malformed values fail closed; usernames and Telegram notification chat IDs do not substitute for user IDs. Rate limiting can also reject commands.

For historical queries, use one filter at a time; filters do not combine. Discord spells alert history `/alert_history`.

## Notifications or Router Polls Fail

Outbound Discord uses `DISCORD_WEBHOOK_URL`; Telegram uses `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. A command bot being connected does not verify outbound notification configuration.

Router polling needs `ZTE_ROUTER_URL`, `ZTE_USERNAME`, `ZTE_PASSWORD`, and optionally `ZTE_RSA_PUBLIC_KEY`. A failed collection does not mark all devices offline. The integrated client disables TLS verification; no runtime environment switch changes that behavior.

Inspect logs without publishing credentials or collected network data. See [setup](../development/contributing.md) and [monitoring](../monitoring/monitoring.md).
