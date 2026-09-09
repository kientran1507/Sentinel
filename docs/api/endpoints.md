# API Endpoints

Sentinel does not currently expose a REST API. The implemented operator interface is the shared command handler exposed through Telegram Bot API polling and Discord native slash commands.

## Future API Surface

When a REST API is introduced, it should expose read-only equivalents of device status, alert history, and runtime health without bypassing `DeviceRegistry`, `AlertHistory`, or command authorization policy. No endpoint names or authentication contract are committed yet.
