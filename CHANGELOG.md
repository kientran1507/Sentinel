# Changelog

## Unreleased

- Started Milestone 4 with scoped first-review acknowledgement, authorized Telegram/Discord commands, bounded audit display and additive development-only SQLite/PostgreSQL migrations; production is unchanged.
- Fixed regular-package discovery so built distributions include the service modules, and aligned the Python minimum with the source (3.10).
- Removed unused command-state flags and unreachable ARP fallback code; isolated ARP packet construction in unit tests.
- Classified Telegram transport/HTTP failures without echoing token-bearing diagnostics and rejected malformed response objects consistently.
- Completed bounded Milestone 3 Pi acceptance for SSH, local TCP and owner-approved equivalent gateway policy evidence, with replay and isolated fault checks; broader firewall/IDS and deployment coverage remain separate.
- Removed unused internal imports and redundant placeholders from populated directories.
- Added SQLite device, event, and alert repositories with historical queries and commands.
- Added asset inventory, address summaries, observation records, vendor enrichment, and PostgreSQL initialization.
- Added persistent inventory with a live-state overlay to the bot `/devices` command.
- Added optional hostname enrichment to discovery persistence.
- Added backend and network-scope configuration, an identity contract, and a storage ADR.

These changes are implemented on the development branch. Historical disposable PostgreSQL/identity/migration acceptance and remaining production recovery/deployment limits are distinguished in [project status](docs/PROJECT_STATUS.md). No production rollout is implied.

## v0.1.0

- Established the repository, architecture documentation, diagrams, and development scaffolding.
- Developed ICMP/ARP discovery, hostname enrichment, and authenticated ZTE collection.
- Added presence tracking, typed events, alert rules, notifications, and authorized Discord/Telegram commands.
- Added a shared monitor/command runtime and platform-specific rendering.

See [release notes](docs/releases/v0.1.0.md) for the historical scope.
