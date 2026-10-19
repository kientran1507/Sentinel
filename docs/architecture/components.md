# Components

| Component | Responsibility |
| --- | --- |
| `ARPScanner` / `ICMPScanner` | Local-link ARP and system-ping discovery |
| `DiscoveryOrchestrator` | Isolated scanner execution, IP merge, optional resolver/sink |
| `HostnameResolver` | PTR, Windows NetBIOS, mDNS; LLMNR reverse lookup unavailable |
| `ZTEH3601PClient` / `ZTECollector` | Router authentication and DHCP/mesh snapshots |
| `ZTEMonitor` | Continuous collection and event publication |
| `PresenceTracker` / `DeviceRegistry` | Baseline, live presence, missed polls, transitions |
| `EventBus` | In-process delivery with isolated subscribers |
| `AlertEngine` / `AlertHistory` | Rules and bounded live alert buffer |
| `NotificationManager` | Independent Discord webhook/Telegram delivery |
| `RuntimePersistence` and adapters | Best-effort repository writes at runtime boundaries |
| Storage/repositories | SQL lifecycle, devices/assets/observations/events/alerts |
| `HistoryService` | Bounded persisted event/alert queries |
| `CommandHandler` | Shared authorization, parsing, rate limits, query semantics |
| `CommandService` and renderers | Telegram polling, Discord Gateway, HTML/embeds |

The scanners and presence logic do not own SQL or outbound notification APIs. The integrated runtime shares live state with command adapters; another process cannot inspect that memory.

See [data flow](overview.md), [storage](persistent-storage.md), and [commands](../commands.md).
