# Sentinel

Sentinel discovers LAN devices, monitors ZTE H3601P client presence, records inventory and history, and sends alerts through Discord and Telegram. It runs as one Python process with modular discovery, storage, alerting, and command services.

Milestones 1 and 2 have completed implementation acceptance: durable inventory and address history, canonical source/transition events, ZTE collector health, explicit retention, and structured JSON logs/redaction. See the [inventory acceptance](docs/development/milestone-1-acceptance.md), [event-pipeline acceptance](docs/development/milestone-2-acceptance.md), and [deployment limits](docs/PROJECT_STATUS.md). No automatic cleanup is enabled; website work remains deferred.

## Setup

Use a Python version that supports the repository's modern type annotations (Python 3.10 or later). The package metadata still declares an older minimum and needs a separate compatibility review.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

On Linux, activate with `source .venv/bin/activate`. Create a local `.env` from `.env.example` only if it does not already exist. Configure the router and desired notification providers, then run:

```powershell
python -m scripts.sentinel start
```

The installed `sentinel start` command is equivalent. The runtime loads the repository-root `.env` without overriding variables already in the process environment. Keep local configuration and inventory databases out of Git.

## Configuration

| Variable | Use |
| --- | --- |
| `ZTE_ROUTER_URL` | Router base URL |
| `ZTE_USERNAME`, `ZTE_PASSWORD` | Required router credentials |
| `ZTE_RSA_PUBLIC_KEY` | Optional RSA public key; literal newline escapes are supported by the runtime loader |
| `SENTINEL_STORAGE_BACKEND` | `sqlite` or `postgresql`; defaults to `sqlite` |
| `SENTINEL_DATABASE_PATH` | SQLite path; defaults to `data/sentinel.db` relative to the working directory |
| `SENTINEL_DATABASE_URL` | Required PostgreSQL connection string when that backend is selected |
| `SENTINEL_NETWORK_SCOPE` | Logical network boundary; defaults to `default` |
| `DISCORD_WEBHOOK_URL` | Outbound Discord alerts |
| `DISCORD_BOT_TOKEN` | Inbound Discord slash commands |
| `DISCORD_ALLOWED_USER_IDS` | Comma-separated numeric command-user IDs |
| `DISCORD_GUILD_ID` | Optional guild for faster command synchronization |
| `TELEGRAM_BOT_TOKEN` | Telegram commands and notifications |
| `TELEGRAM_CHAT_ID` | Outbound notification destination |
| `TELEGRAM_ALLOWED_USER_IDS` | Comma-separated numeric command-user IDs |
| `SENTINEL_TEST_DATABASE_URL` | Dedicated PostgreSQL integration-test database |

PostgreSQL is the intended production backend; SQLite supports local development. Backend failures never trigger an automatic switch or inventory import. PostgreSQL behavior still needs broader integration verification. See [storage](docs/architecture/persistent-storage.md).

## Usage

- Use `/devices`, `/status`, `/alerts`, `/events`, `/alert-history`, and `/help` from an authorized Discord or Telegram account.
- `/devices` uses persistent assets when available and overlays current registry status. It never starts a scan.
- `python -m scripts.sentinel devices --refresh --json` polls the router once. The standalone CLI device command uses its own registry, not the persistent-inventory command handler.
- Run an explicit discovery scan with `python scripts/discover.py <CIDR> --method both --orchestrator`.
- Add `--resolve-hostnames` for enrichment and `--persist` for storage. These options apply to the orchestrator path. Unlike the integrated runtime, the discovery helper does not load `.env`; it uses process environment configuration.

See [commands](docs/commands.md) and [discovery](docs/monitoring/device-discovery.md) for options and limits.

## Development

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

Tests use mocks and temporary SQLite databases. The PostgreSQL test requires a dedicated test DSN and is skipped when it is absent. Read [contributing](CONTRIBUTING.md) before changing behavior.

## Documentation

- [Architecture](docs/architecture/overview.md), [components](docs/architecture/components.md), and [asset identity](docs/architecture/asset-identity.md)
- [Monitoring](docs/monitoring/monitoring.md), [alerts](docs/monitoring/alerts.md), and [troubleshooting](docs/troubleshooting/common-issues.md)
- [Project status](docs/PROJECT_STATUS.md) and [long-term plan](Sentinel_Project_Plan.md)
- [Deployment](docs/deployment/docker.md) and [release history](CHANGELOG.md)

REST API, dashboards, metrics export, and production container manifests remain planned work. License: [MIT](LICENSE).
