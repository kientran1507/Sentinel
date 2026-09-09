# Contributing

Thanks for contributing to Sentinel.

## Before You Open a Pull Request

- Keep changes aligned with the architecture and milestone scope.
- Avoid implementation work unless it is explicitly part of the current milestone.
- Update documentation when repository structure or release-facing text changes.

## Workflow

1. Create a focused branch for your change.
2. Make the smallest coherent update.
3. Verify links, images, and formatting.
4. Open a pull request with a clear summary.

## Local Setup and Tests

Use the project virtual environment and editable install:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Run the complete unittest suite with:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

The repository currently uses `unittest`; tests mock external Discord and Telegram APIs. Do not put `.env` or provider credentials in commits. Changes to discovery, monitoring, alerts, commands, or renderers should update the corresponding documentation.

## Documentation Expectations

- Prefer concise, technical Markdown.
- Keep terminology consistent with the Sentinel architecture documents.
- Use repository-relative links for markdown references.

## Review Notes

- Use the pull request template in [.github/PULL_REQUEST_TEMPLATE.md](.github/PULL_REQUEST_TEMPLATE.md).
- Keep public-facing language professional and milestone-appropriate.