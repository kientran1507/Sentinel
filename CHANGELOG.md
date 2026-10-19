# Changelog

## Unreleased

- Added SQLite device, event, and alert repositories with historical queries and commands.
- Added asset inventory, address summaries, observation records, vendor enrichment, and PostgreSQL initialization.
- Added persistent inventory with a live-state overlay to the bot `/devices` command.
- Added optional hostname enrichment to discovery persistence.
- Added backend and network-scope configuration, an identity contract, and a storage ADR.

These changes are implemented on the development branch. PostgreSQL verification and several identity, migration, and recovery requirements remain open; see [project status](docs/PROJECT_STATUS.md).

## v0.1.0

- Established the repository, architecture documentation, diagrams, and development scaffolding.
- Developed ICMP/ARP discovery, hostname enrichment, and authenticated ZTE collection.
- Added presence tracking, typed events, alert rules, notifications, and authorized Discord/Telegram commands.
- Added a shared monitor/command runtime and platform-specific rendering.

See [release notes](docs/releases/v0.1.0.md) for the historical scope.
