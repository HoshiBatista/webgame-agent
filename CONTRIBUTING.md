# Contributing to Prompt2Play

Thank you for helping build Prompt2Play. The project is currently at the
bootstrap stage, so changes should favor a small working product over broad
scaffolding.

## Before you start

1. Read [AGENTS.md](AGENTS.md), [README.md](README.md), and the relevant design
   documentation.
2. Search existing issues and changes before starting overlapping work.
3. For a large feature or architectural decision, agree on its scope before
   implementing it.
4. Never include API keys, private prompts, customer data, or generated files
   containing sensitive information.

## Change guidelines

- Keep each change focused on one behavior or decision.
- Prefer an end-to-end vertical slice over disconnected layers or empty
  directories.
- Add or update tests for behavioral changes.
- Document new configuration values without committing real credentials.
- Keep model providers replaceable and generated-code execution isolated.
- Update the README when setup, commands, dependencies, or user-visible behavior
  changes.
- Record important, difficult-to-reverse technical decisions in `docs/`.

## Local verification

The project uses Python 3.11 or newer and uv. Create or update the local
environment from the committed lock file:

```bash
uv sync --locked --all-groups
```

Format code while working:

```bash
uv run ruff format .
uv run ruff check --fix .
```

Before review, run the complete local check set:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
uv build
```

Add runtime dependencies with `uv add <package>` and development dependencies
with `uv add --dev <package>`. Commit `pyproject.toml` and `uv.lock` together;
do not edit the lock file manually.

Run all checks relevant to your change. In the change description, list the
exact commands and their outcomes. Clearly label checks that were skipped or
could not be run. Once browser validation exists, include it for changes that
affect generated games or previews.

## Commit and review expectations

- Use clear, imperative commit messages.
- Explain the user-visible result and the reason for the change.
- Keep generated artifacts out of version control unless they are intentional
  examples or regression fixtures.
- Include screenshots or browser-validation evidence for visible behavior when
  practical.
- Call out security implications, migrations, new dependencies, and known
  limitations.

## Definition of ready for review

A change is ready when it is scoped, documented, tested in proportion to its
risk, free of committed secrets, and consistent with the product contract in
`AGENTS.md`.
