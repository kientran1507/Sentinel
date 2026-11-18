# Alerts and Notifications

`PresenceTracker -> DeviceEvent -> EventBus -> AlertEngine -> AlertHistory + persistence + notifications`

The first successful monitor snapshot establishes a baseline. The default alert rules apply to subsequent transitions:

| Event | Alert | Severity |
| --- | --- | --- |
| `DEVICE_DISCOVERED` (serialized as `NEW_DEVICE`) | `UNKNOWN_DEVICE` | `WARNING` |
| `DEVICE_OFFLINE` | `DEVICE_OFFLINE` | `WARNING` |
| `DEVICE_RECOVERED` (serialized as `DEVICE_ONLINE`) | `DEVICE_RECOVERED` | `INFO` |

Offline transitions are debounced; a continuously missing device does not alert every poll. Other change events can be persisted without a default alert rule. Discovery alerts do not imply a persistent trust policy.

## Providers

| Delivery | Required settings |
| --- | --- |
| Discord webhook | `DISCORD_WEBHOOK_URL` |
| Telegram Bot API | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |

Providers receive device identity, event time, severity, and alert description. Provider failures are logged and isolated so another provider can continue. Zero providers is valid. Alert persistence is attempted before outbound delivery.

Milestone 4 development adds [scoped send-attempt history](../development/milestone-4-delivery-history.md)
to the integrated runtime. Each provider invocation has a separate start and
outcome record. Success means the provider call returned, not that a person read
the alert. A started row without an outcome means completion is unknown. Audit
failure preserves existing best-effort sending; no retry queue or automatic
resend is enabled. These changes are not deployed to the accepted running image.

```text
sentinel notification test --provider discord
sentinel notification test --provider telegram
sentinel notification test --provider all
```

These commands send real connectivity-test messages.

## Live and Durable History

`AlertHistory` keeps at most 100 live alerts by default; `/alerts` shows the latest 10. `/status` also uses the live buffer. `/alert-history` queries SQL, which survives restart independently of the buffer.

Discord commands use a bot token, separate from its outbound webhook. Telegram uses the same bot token for polling and outbound delivery, but command authorization uses user IDs rather than the notification chat ID. See [commands](../commands.md), [storage](../architecture/persistent-storage.md), and [monitoring](monitoring.md).
