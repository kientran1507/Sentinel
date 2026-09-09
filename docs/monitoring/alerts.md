# Alerts

Sentinel uses an in-process pipeline:

`device state transition -> DeviceEvent -> AlertEngine rule -> Alert -> NotificationManager`

The ZTE monitor and presence tracker own discovery and state transitions. They do not call notification services. Event bus handlers are isolated from the monitoring loop, and provider failures are logged without stopping monitoring.

## Events and Rules

| Event | Alert | Severity |
| --- | --- | --- |
| `DEVICE_DISCOVERED` (`NEW_DEVICE` for compatibility) | `UNKNOWN_DEVICE` | `WARNING` |
| `DEVICE_OFFLINE` | `DEVICE_OFFLINE` | `WARNING` |
| `DEVICE_RECOVERED` (`DEVICE_ONLINE` for compatibility) | `DEVICE_RECOVERED` | `INFO` |

Offline events are debounced by the existing presence tracker. A device that remains missing generates one event after the configured threshold, not one event per poll.

## Notifications

Set these variables in `.env` (see `.env.example`):

```text
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
DISCORD_BOT_TOKEN=<discord-bot-token>
DISCORD_ALLOWED_USER_IDS=123456789012345678
DISCORD_GUILD_ID=<optional-guild-id>
TELEGRAM_BOT_TOKEN=123456:token
TELEGRAM_CHAT_ID=123456789
TELEGRAM_ALLOWED_USER_IDS=123456789
```

Discord messages use an embed. Telegram messages use the Bot API. Both include alert type, severity, hostname, IP, MAC, event time, and a readable description. Credentials are read from the environment and are never written to logs.

`NotificationManager` continues with the next provider when one provider times out, rejects a request, or has invalid configuration. Zero configured providers is valid. External API calls are covered by mocked tests and are not made by the automated suite.

Discord webhook delivery is outbound only. Discord bot commands use `DISCORD_BOT_TOKEN` and native slash commands. Telegram uses its bot token for both outbound messages and inbound long polling. Command allowlists are numeric user IDs; missing or malformed values reject commands.

## CLI

After installing Sentinel, use `sentinel devices` to display the devices in the active `DeviceRegistry`; `--online`, `--offline`, and `--json` are available for filtering and automation. The notification test command uses the configured providers directly:

```text
sentinel notification test --provider discord
sentinel notification test --provider telegram
sentinel notification test --provider all
```

Provider failures are reported individually and do not stop monitoring or another provider. A standalone `sentinel devices` process can only display devices supplied to its in-process registry; a future persistent service/API can expose a long-lived monitor registry across processes.

## Inbound Commands

Inbound commands are separate from outbound notifications. `DISCORD_WEBHOOK_URL` sends alerts; `DISCORD_BOT_TOKEN` authenticates the Discord Gateway command listener. Telegram uses `TELEGRAM_BOT_TOKEN` for both Bot API notifications and polling commands.

Configure stable numeric user IDs to authorize remote commands:

```text
DISCORD_BOT_TOKEN=
DISCORD_ALLOWED_USER_IDS=123456789012345678
DISCORD_GUILD_ID=
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_IDS=123456789
```

Start or inspect the listeners with `sentinel bot start` and `sentinel bot status`. Supported commands are `/help`, `/devices`, `/status`, and `/alerts`. Missing or malformed allowlists reject all remote commands. Unknown commands cannot execute shell commands, and each user is rate-limited to 10 commands per 30 seconds.

The command service is intended to run in the same process as the monitor so it can share the registry and bounded alert history. Running it as a separate process currently cannot observe another process's in-memory registry.

## Command Presentation

The command handler returns structured device, status, alert, and help data. Discord renders that data as embeds with accessible state/severity indicators; Telegram renders it as escaped HTML with compact device entries and summaries. Missing values are displayed as `unknown` rather than triggering a new lookup. Empty device and alert histories have explicit startup-safe messages. The renderers do not run discovery or change monitoring state.
