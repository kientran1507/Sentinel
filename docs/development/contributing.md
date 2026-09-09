# Contributing

Sentinel is a Python project. Keep changes modular and preserve the shared runtime boundaries: discovery/monitoring own state transitions, `AlertEngine` owns alert rules, notification providers own outbound APIs, and `CommandHandler` owns shared command semantics.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Copy `.env.example` to `.env` for local router/provider testing. Never commit `.env`, tokens, passwords, webhook URLs, or user IDs that identify a real deployment.

## Testing

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
python -m unittest tests.test_commands tests.test_command_renderers -v
python -m py_compile services/commands/*.py scripts/sentinel.py
```

Tests must not make real Discord, Telegram, or router requests. Use mocks and preserve the existing failure-isolation tests. Update documentation when command output, configuration, runtime wiring, or deployment behavior changes.

## Pull Requests

Use focused branches and explain architectural impact, tests, configuration changes, and any limitations. Keep future architecture clearly separate from implemented behavior.
