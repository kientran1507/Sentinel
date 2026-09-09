# Common Issues

## `/devices` is empty

Run `python -m scripts.sentinel start`, not a separately started command process, when you need live monitor state. The integrated runtime creates one shared `DeviceRegistry`; a separate Python process has an independent empty registry. Wait for the ZTE baseline poll to complete.

## Telegram HTTP 409

`Conflict: terminated by other getUpdates request` means another process or deployment is polling the same Telegram bot token. Stop the competing consumer and keep only one long-polling process active.

## Discord commands are missing

Confirm `DISCORD_BOT_TOKEN` is configured and the bot was installed with both `bot` and `applications.commands` scopes. Configure `DISCORD_GUILD_ID` for fast guild synchronization. Sentinel uses native slash commands and does not require the Message Content privileged intent.

## Commands are rejected

Set numeric IDs in `DISCORD_ALLOWED_USER_IDS` or `TELEGRAM_ALLOWED_USER_IDS`. Missing or malformed allowlists fail closed. Usernames and display names are not authorization identities.

## ARP fails

Install Scapy and grant the process raw-network privileges. Use ICMP as a fallback where ARP is unavailable or the target is routed.

## Notifications fail

Check `DISCORD_WEBHOOK_URL` for outbound Discord delivery and `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` for outbound Telegram delivery. A provider failure is logged and isolated; it should not stop monitoring or the other provider.

## Router polling fails

Check `ZTE_ROUTER_URL`, `ZTE_USERNAME`, `ZTE_PASSWORD`, and optional `ZTE_RSA_PUBLIC_KEY`. A failed collector poll is treated as unknown network state and does not mark all devices offline.
