# Commands

Sentinel exposes the same authorized command set through Telegram long polling and Discord native application commands:

- `/help` shows the command reference.
- `/devices` reads the current shared `DeviceRegistry` and displays hostname, IP, MAC, and state. It does not trigger discovery.
- `/status` reads the shared monitor, registry, and alert-history state.
- `/alerts` reads the shared bounded `AlertHistory`.

All commands require a numeric platform user ID in the relevant allowlist. Missing or malformed allowlists fail closed. Each user is limited to 10 commands per 30 seconds. Unknown commands, command arguments, shell commands, and arbitrary code are rejected.

## Discord

Discord uses a Gateway bot with native slash/application commands. Configure `DISCORD_BOT_TOKEN`, `DISCORD_ALLOWED_USER_IDS`, and optionally `DISCORD_GUILD_ID`. Guild synchronization is used when a guild ID is configured; otherwise commands synchronize globally. The bot needs the `bot` and `applications.commands` install scopes. Message Content privileged intent is not required.

Responses use embeds:

- `/devices` uses compact device fields with `ONLINE`, `OFFLINE`, or `UNKNOWN` indicators.
- `/status` uses an inline monitoring dashboard.
- `/alerts` uses severity indicators.
- `/help` groups monitoring and general commands.

## Telegram

Telegram uses `TELEGRAM_BOT_TOKEN` and Bot API `getUpdates` long polling. Configure `TELEGRAM_ALLOWED_USER_IDS` for authorization. Responses use escaped HTML and compact device entries rather than fixed-width tables. Only one polling consumer should use a bot token at a time; Telegram reports `Conflict: terminated by other getUpdates request` when another consumer is active.

## Runtime state

Use `python -m scripts.sentinel start` or the installed `sentinel start` for live state. That mode creates one `DeviceRegistry`, `PresenceTracker`, `EventBus`, `AlertEngine`, `AlertHistory`, and `CommandHandler` for monitoring and both adapters. A standalone command process cannot inspect another process's in-memory registry.

## CLI reference

The installed console script and module form expose the same commands:

```powershell
sentinel start
python -m scripts.sentinel start

sentinel bot start
python -m scripts.sentinel bot start

sentinel bot status
sentinel devices --json
sentinel devices --refresh
sentinel notification test --provider all
```

`sentinel start` is the preferred integrated runtime. `sentinel bot start` currently uses the same integrated runtime path for compatibility. `sentinel bot status` only reports whether bot credentials are configured and does not start monitoring. `sentinel devices --refresh` performs one ZTE poll for a CLI-local registry; remote `/devices` commands read the registry owned by the running integrated runtime.
