# Prompt2Play

Prompt2Play is an AI-powered platform that turns a natural-language description
into a complete, playable HTML5 browser game.

The intended experience is simple:

> describe a game → generate it → validate and repair it → play it immediately

## Project status

**Python foundation ready; product implementation not started.** The repository
has a typed Python package, reproducible development dependencies, automated
quality checks, and a multi-version CI workflow. The API, generation pipeline,
validator, and web interface are not implemented yet.

The target application stack is FastAPI and PostgreSQL, Celery with Redis,
React/Vite, Playwright, and content-addressed artifacts on a persistent
filesystem. Model-provider and deployment-vendor choices remain open behind
project-owned interfaces.

## MVP

The first demonstrable version should:

1. accept a game prompt;
2. turn it into a structured, validated specification;
3. generate a self-contained HTML/CSS/JavaScript bundle;
4. validate the bundle statically and in an isolated browser;
5. make a limited repair attempt when validation fails; and
6. expose a safe preview with an honest validation report.

A generated game is successful only if it renders, responds to input, and
supports an appropriate completion, failure, or restart flow.

## Design constraints

- Generated code is untrusted and must be isolated from secrets and application
  privileges.
- Games should work offline at runtime and avoid remote assets by default.
- Mobile WebViews and touch controls are first-class targets.
- Model providers and model identifiers must be configurable.
- Validation must measure playability, not only successful compilation.
- Repair attempts must be bounded and observable.

See [docs/architecture.md](docs/architecture.md) for the target system,
generation workflow, trust boundaries, artifact contract, and delivery plan.
The decisions are recorded in
[ADR 0001](docs/adr/0001-target-architecture.md) and
[ADR 0002](docs/adr/0002-generation-harness.md), with supporting evidence in
the [landscape review](docs/research/landscape.md).

## Repository contents

```text
.
├── .github/workflows/ci.yml  # Lint, types, tests, and package build
├── src/prompt2play/          # Installable Python package
├── tests/                    # Automated Python tests
├── AGENTS.md            # Repository-wide engineering and agent guidance
├── CLAUDE.md            # Claude Code-specific working instructions
├── CONTRIBUTING.md      # Contribution workflow and quality expectations
├── pyproject.toml        # Package metadata and tool configuration
├── SECURITY.md          # Security policy and generated-code threat model
├── uv.lock               # Reproducible dependency resolution
├── docs/
│   ├── adr/              # Accepted architectural decisions
│   ├── research/         # Product, implementation, and research analysis
│   └── architecture.md  # Target architecture and evolution plan
└── README.md
```

Application modules will be added with the first working vertical slice. The
likely boundaries are contracts, an API, generator, validator, artifact store,
templates, and a web interface. New directories should contain working code,
not placeholders.

## Getting started

Prerequisites:

- Python 3.11 or newer; Python 3.13 is the default local version;
- [uv](https://docs.astral.sh/uv/) for environments, dependencies, and builds.

Install the package and development tools from the lock file:

```bash
uv sync --locked --all-groups
```

Run the same checks used by CI:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
uv build
```

There is not yet a runnable API or web application. To contribute at this stage:

1. read [AGENTS.md](AGENTS.md) and [docs/architecture.md](docs/architecture.md);
2. choose work that advances the first end-to-end vertical slice;
3. document any new runtime or provider requirement; and
4. include tests and exact verification results with implementation changes.

GitHub Actions runs formatting, linting, strict type checking, package building,
and tests on Python 3.11, 3.12, 3.13, and 3.14.

## Contributing and security

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a change. Do not publish a
suspected vulnerability in a public issue; follow [SECURITY.md](SECURITY.md)
instead.

## License

No license has been selected. Until a license file is added, the repository is
not offered under an open-source license.
