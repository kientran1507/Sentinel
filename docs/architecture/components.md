# Architecture Components

This document describes the components that currently exist in the Python runtime.

## Discovery and Monitoring

- **`DiscoveryOrchestrator`** runs ARP/ICMP scanners and merges results by IP.
- **`HostnameResolver`** performs bounded PTR, NetBIOS, mDNS, and LLMNR enrichment.
- **`DeviceRegistry`** is the canonical in-memory store of `ZTEDevice` records.
- **`ZTECollector`** authenticates to the ZTE H3601P and merges DHCP/mesh clients.
- **`ZTEMonitor`** polls the collector and owns the monitoring loop.
- **`PresenceTracker`** detects discovery, offline, and recovery transitions.

## Event, Alert, and Command Components

- **`EventBus`** provides isolated event subscribers, optionally asynchronously.
- **`AlertEngine`** applies event rules and creates `Alert` objects.
- **`AlertHistory`** keeps a bounded in-memory recent-alert list.
- **`NotificationManager`** routes independently to Discord webhook and Telegram providers.
- **`CommandHandler`** provides shared authorization, parsing, rate limiting, and command semantics.
- **`CommandService`** hosts Telegram long polling and Discord Gateway slash commands.
- **Renderers** format structured responses as Discord embeds or Telegram escaped HTML.

## Boundaries

Discovery and monitoring do not know about Discord or Telegram. The event bus separates state transitions from alert processing. Notification failures are isolated from monitoring. Command adapters translate platform interactions into calls to the same `CommandHandler`.

There is currently no REST API, database, dashboard, or persistent queue. The registry and alert history exist only for the lifetime of the integrated runtime.
