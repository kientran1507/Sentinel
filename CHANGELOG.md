## Current Implementation

- Added ICMP/ARP discovery orchestration and hostname enrichment.
- Added authenticated ZTE H3601P collection, continuous presence tracking, offline debouncing, and recovery events.
- Added typed events, an in-process event bus, rule-based alerts, bounded alert history, and Discord/Telegram notification providers.
- Added shared authorized commands `/help`, `/devices`, `/status`, and `/alerts` for Telegram and native Discord slash commands.
- Added an integrated runtime so monitoring, alerting, and both command adapters share one `DeviceRegistry` and `AlertHistory`.
- Added Discord embeds and Telegram HTML command renderers.

The current runtime remains in memory. REST API, database persistence, dashboards, metrics export, and packaged Docker/K3s deployment are future work.

# Changelog

## v0.1.0

### Added

- Repository structure
- GitHub project
- Architecture documentation
- Draw.io diagrams
- Docker/Kubernetes scaffolding
- Development documentation
