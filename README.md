# Prompt2Play

Prompt2Play is an AI-powered platform that turns a natural-language description
into a complete, playable HTML5 browser game.

The intended experience is simple:

> describe a game → generate it → validate and repair it → play it immediately

## Project status

**Integrated studio implemented; contest acceptance in progress.** This branch
contains Django/DRF coordination, React studio, local Codex/API adapters, bounded
generation and repair, immutable artifact storage, and a separate isolated
browser validation role. Only candidates that pass required checks can be played
or downloaded. A failed edit preserves the previous playable version.

The accepted plan selectively adopts the existing Game Forge 1.3.0 application:
Django/DRF and PostgreSQL, React/Vite, and local Codex/API workers. The target
adds an application-owned workflow, bounded generation attempts, a small trusted
game runtime, mandatory isolated Playwright validation, and content-addressed
artifact storage. Database-backed worker polling is the initial dispatch model;
FastAPI, Celery/Redis, and a new model framework are not required.

Selected donor code is imported with [source provenance](docs/adoption-manifest.json).
The donor was freshly reproduced: 301 named tests and 24 separately counted
authored regression cases passed. Fresh live generation, browser acceptance and
strategy comparison are tracked separately in the [implementation report](docs/implementation-report.md).
The contest WebView host is currently unknown; a mobile viewport does not establish
device compatibility. See the [phased plan](docs/development-plan.md).

## Implemented workflow

The studio supports this complete workflow:

1. accept a game prompt;
2. turn it into a structured, validated specification;
3. generate a self-contained HTML/CSS/JavaScript bundle;
4. validate the bundle statically and in an isolated browser;
5. apply a bounded repair policy and preserve each submitted candidate; and
6. expose a preview and download of the exact artifact that passed mandatory checks.

A generated game is successful only if it renders, responds to input, and
supports an appropriate completion, failure, or restart flow.
Required skipped checks, including unavailable browser validation, mean
**unverified**, not successful delivery. A failed edit preserves the last
playable revision.

## Design constraints

- Generated code is untrusted and must be isolated from secrets and application
  privileges.
- Games should work offline at runtime and avoid remote assets by default.
- Mobile WebViews and touch controls are first-class targets.
- Model providers and model identifiers must be configurable.
- Validation must measure playability, not only successful compilation.
- Repair attempts must be bounded and observable.
- Canvas, DOM/SVG, and hybrid games share optional infrastructure capabilities;
  generated mechanics are not restricted to a catalog of prewritten games.

See [docs/architecture.md](docs/architecture.md) for the target system,
generation workflow, trust boundaries, and artifact contract. The
[development plan](docs/development-plan.md) defines what to transfer, redesign,
and verify in dependency order. [ADR 0003](docs/adr/0003-hybrid-adoption.md)
records the combined decision, supersedes the stack selection in
[ADR 0001](docs/adr/0001-target-architecture.md), and amends
[ADR 0002](docs/adr/0002-generation-harness.md). The
[landscape review](docs/research/landscape.md) remains historical research.

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
│   ├── adr/              # Current and superseded architectural decisions
│   ├── research/         # Product, implementation, and research analysis
│   ├── architecture.md  # Combined target architecture
│   └── development-plan.md # Transfer inventory, phases, and acceptance gates
└── README.md
```

Application modules are implemented under `src/prompt2play/`: `contracts`,
`generation`, `application`, `adapters/artifacts`, `adapters/django`, `workers`,
and `validation`. Reviewed runtime, prompts, regression fixtures and evaluation
requests live in package `resources`; the React studio lives in `web`.
The main boundaries are
contracts, Django adapters, application workflow, generation, validation, artifact
storage, trusted runtime, and the creator UI. New directories should contain
working code, not placeholders. Imported components must not depend on the donor
directory being present on the developer's machine.

## Getting started

Prerequisites:

- Python 3.11 or newer, [uv](https://docs.astral.sh/uv/), Node.js 22.12+ and npm;
- Docker for mandatory browser validation;
- PostgreSQL for shared or concurrent execution; SQLite is available for a local
  single-runner installation;
- a locally authenticated Codex CLI, or an API key and an available API model.

Install the package and development tools from the lock file:

```bash
uv sync --locked --all-groups
cd web
npm ci --ignore-scripts
npm run build
cd ..
uv run prompt2play setup
uv run prompt2play build-validator
uv run prompt2play serve
```

Open `http://127.0.0.1:8000`. The preview listener runs separately on port 8001.
Setup asks for the administrator password and creates a private local
`.prompt2play/.env` with a fresh signing secret. For unattended setup use
`PROMPT2PLAY_ADMIN_PASSWORD` and `setup --noinput`; no password is passed in argv.
The `--slim` validator build uses a system Chromium image when the larger official
Playwright image is impractical; reports record the actual image and browser.

In settings create a generation runner and a validation runner. Each token is
shown once. Start them in separate terminals with the respective token supplied
through `PROMPT2PLAY_RUNNER_TOKEN`:

```bash
uv run prompt2play worker --role generator --provider codex
uv run prompt2play worker --role validator
```

The studio's launch settings list models reported by the connected Codex runner
through `model/list`. The catalog refreshes between stages every five minutes;
failed discovery retries after one minute and leaves the configured default and
manual entry available. Add `--model YOUR_AVAILABLE_MODEL` to set an explicit
runner default, or select a model for each game in the studio. API model names
remain a separate setting. Catalog discovery never starts an inference turn.

The generator uses the controlled single-author runtime by default. The
`--mode four_author` option preserves the adopted donor strategy for measured
comparisons. Fresh evaluation results, failures, costs and remaining quality
gaps are recorded in the [implementation report](docs/implementation-report.md).
Legacy games require independent real-input acceptance configuration;
native games also have a fixed platform conformance profile. Neither profile
establishes all genre-specific rules or subjective quality. See the [runbook](docs/runbook.md)
for PostgreSQL, API models, worker configuration, recovery and deployment.

Run the same checks used by CI:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest
uv build
```

The 85% branch-coverage gate applies to contracts, generation, repair policy and
the artifact store. Django, transport/CLI and container boundaries have separate
functional tests. Run the container acceptance suite explicitly:

```bash
P2P_RUN_ISOLATED_BROWSER=1 uv run pytest tests/test_validation_browser.py --no-cov
```

CI includes PostgreSQL claim/cancel races, frontend logic/build, isolated reviewed
games and a real-browser creator flow. Live model calls are explicit evaluation
runs, not routine CI. Portable distributions include the built studio, runtime,
prompts and validator sources and require no neighboring donor directory.

To contribute:

1. read [AGENTS.md](AGENTS.md), [docs/architecture.md](docs/architecture.md), and
   [docs/development-plan.md](docs/development-plan.md);
2. choose the next phase task or a documented baseline blocker;
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
