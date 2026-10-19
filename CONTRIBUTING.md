# Contributing

## Setup and Checks

Follow [README setup](README.md#setup), then run:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
python -m compileall -q services scripts tests
git diff --check
```

Use temporary SQLite databases for fast tests. PostgreSQL tests require a dedicated disposable database selected through `SENTINEL_TEST_DATABASE_URL`; they can create schema and retain records. Do not point them at production.

## Changes

1. Inspect the affected code and tests, then work on a focused branch.
2. Reuse existing models and modules; preserve monitoring, presence debouncing, commands, and notifications.
3. Add regression coverage proportional to the change. Mock routers and external providers.
4. Update the relevant guide to match the implementation.
5. Review the diff and open a pull request using the [template](.github/PULL_REQUEST_TEMPLATE.md).

Keep credentials, local databases, and `.env` out of commits. Use repository-relative documentation links and distinguish working features from planned milestones. See the [project plan](Sentinel_Project_Plan.md) for scope and [development guide](docs/development/contributing.md) for test areas.
