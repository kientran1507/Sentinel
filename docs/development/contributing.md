# Development

## Setup

Use a current Python environment compatible with the code and dependencies. Although package metadata says Python >=3.8, the source uses modern annotations and has not established support for every version in that range.

From the repository root on Windows:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

On Linux, activate with `source .venv/bin/activate`. The editable install provides `sentinel` and installs cryptography, mac-vendor-lookup, psycopg, Scapy, zeroconf, and discord.py.

For a new local setup, use [.env.example](../../.env.example) as the configuration template; preserve an existing `.env`. Never commit credentials, tokens, real user IDs, or collected network/database data.

## Configuration and Startup

The integrated CLI loads repository-root `.env` and preserves variables already set in the process. It handles simple key/value lines, matching outer quotes, and literal `\n` escapes; it is not a full shell parser.

| Purpose | Variables |
| --- | --- |
| Required integrated ZTE runtime | `ZTE_ROUTER_URL`, `ZTE_USERNAME`, `ZTE_PASSWORD` |
| Optional router key | `ZTE_RSA_PUBLIC_KEY` |
| Outbound Discord | `DISCORD_WEBHOOK_URL` |
| Discord commands | `DISCORD_BOT_TOKEN`, `DISCORD_ALLOWED_USER_IDS`, optional `DISCORD_GUILD_ID` |
| Outbound Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| Telegram commands | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_IDS` |

See [storage settings](../architecture/persistent-storage.md) for backend, database, scope, and test DSN details. An unset backend selects SQLite. The current runtime is configured for PostgreSQL; integration coverage and remaining gaps are recorded in [project status](../PROJECT_STATUS.md).

```text
python -m scripts.sentinel start
```

No notification providers are required. Configured outbound providers make real requests. The discovery helper is separate and does not load `.env`; see [discovery](../monitoring/device-discovery.md).

## Checks and Changes

```text
python -m unittest discover -s tests -p "test_*.py" -v
python -m unittest discover -s tests -p "test_commands.py" -v
python -m unittest discover -s tests -p "test_postgres_storage.py" -v
```

PostgreSQL integration tests run only when `SENTINEL_TEST_DATABASE_URL` is set. Use a disposable database and a role allowed to create schemas and terminate its own sessions: each test creates a unique `sentinel_test_` schema, sets that connection's search path to it, and drops it during cleanup. Disconnect tests terminate only their own storage connection by its backend PID. Tests never derive a test DSN from runtime configuration. Keep the DSN private and do not point it at production. Schema/migration failure and commit-failure tests deliberately provoke SQL errors. Other service requests should be mocked in tests. See the [Milestone 1 acceptance matrix](milestone-1-acceptance.md).

Keep discovery/presence, alert rules, notifications, command semantics, and persistence boundaries separate. Scale verification to the behavior changed, preserve failure-isolation coverage, and document limitations alongside features. Do not use SQLite results as PostgreSQL acceptance evidence.
