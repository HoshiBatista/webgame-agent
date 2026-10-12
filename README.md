# Prompt2Play

Prompt2Play is an AI-powered platform that turns a natural-language description
into a complete, playable HTML5 browser game.

The intended experience is simple:

> describe a game → generate it → validate and repair it → play it immediately

## Project status

**The hackathon vertical slice is implemented.** The repository now contains a
React creator UI, FastAPI control plane, PostgreSQL workflow state, Redis/Celery
workers, OpenAI generation through GPT-6 Luna, immutable content-addressed game
artifacts, bounded repair, static rules, and Playwright mobile validation.

The implementation deliberately does not use SQLite. Docker Compose starts the
production-like MVP stack: PostgreSQL 17, Redis with AOF/no-eviction, separate
model and validation workers, Celery Beat outbox recovery, API, and web UI.
Provider code remains behind the project-owned `ModelGateway`; the first adapter
uses the OpenAI Responses API with Structured Outputs and configurable model ID
`gpt-6-luna`. See the [official model page](https://developers.openai.com/api/docs/models/gpt-6-luna).

The MVP capacity target is 10 simultaneous active generation runs. This is a
documented, testable envelope; it is not considered proven until the prescribed
load tests pass.

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
[ADR 0002](docs/adr/0002-generation-harness.md). The implemented container
trust boundaries are recorded in
[ADR 0004](docs/adr/0004-container-trust-boundaries.md), with supporting evidence in
the [landscape review](docs/research/landscape.md). Resource and provider-quota
requirements are calculated in the
[MVP capacity plan](docs/capacity.md).

## Implemented product flow

```text
Browser → nginx :5173 ┬→ React static UI
                      └→ internal FastAPI → PostgreSQL outbox → Redis/Celery
                                                               ├─ model worker → GPT-6 Luna
                                                               ├─ workflow worker
                                                               └─ validation worker → Chromium
                                                                          ↓
                                                        immutable SHA-256 artifact
                                                                          ↓
                                                       sandboxed iframe + CSP/share
```

Games are schema-planned before code generation. A candidate is not exposed as
playable until static security checks and a mobile Chromium interaction test
pass. Failed candidates receive at most two model repairs; every candidate is
an immutable revision with validation evidence.

Implemented bonus features include audience adaptation, touch/responsive
generation rules, iterative revisions, gallery and share URLs, cross-genre
specifications, procedural graphics/WebAudio, and aggregate gameplay analytics
fed into future specifications. See
[docs/hackathon-requirements.md](docs/hackathon-requirements.md).

## Repository contents

```text
.
├── .github/workflows/        # CI, CodeQL and bounded live Luna evaluations
├── src/prompt2play/          # API, workflow, adapters, validation, Celery
├── web/                      # React/TypeScript/Vite creator application
├── alembic/                  # PostgreSQL schema migration
├── tests/                    # Unit and contract tests
├── compose.yaml              # Full local MVP stack
├── Dockerfile                # Separate API/model/workflow/validation build targets
├── AGENTS.md                 # Repository-wide engineering guide
├── CONTRIBUTING.md           # Contribution workflow
├── pyproject.toml            # Python metadata and tools
├── SECURITY.md               # Generated-code threat model
├── uv.lock                   # Reproducible Python dependency resolution
├── docs/
│   ├── adr/              # Accepted architectural decisions
│   ├── research/         # Product, implementation, and research analysis
│   ├── architecture.md  # Target architecture and evolution plan
│   ├── capacity.md           # MVP throughput and load-test targets
│   └── hackathon-requirements.md # PDF requirement matrix
└── README.md
```

## Getting started

Prerequisites:

- Docker with Compose for the complete stack;
- an OpenAI API key with access to `gpt-6-luna`;
- for host-only development: Python 3.11+, uv, Node.js 24 and npm.

Start the complete stack:

```bash
cp .env.example .env
# Set OPENAI_API_KEY in .env, then:
docker compose up --build
```

Open `http://localhost:5173`. nginx is the only published service: the API and
OpenAPI UI are available through the same origin at
`http://localhost:5173/v1/...` and `http://localhost:5173/docs`. Port 8000 is
internal and is not published. The first validation-worker image build installs
Playwright Chromium and can take several minutes; the API and model images do
not contain a browser.

The services are intentionally separate:

- `api` accepts prompts and streams persisted progress;
- `worker-models` is the only service with OpenAI credentials and public egress;
- `worker-workflow` dispatches durable outbox commands without provider secrets;
- `worker-validation` opens untrusted games in Chromium on an internal-only
  network with read-only artifacts;
- `beat` recovers unsent PostgreSQL outbox commands;
- `postgres` owns product state; Redis is delivery infrastructure only;
- `web` serves React and reverse-proxies API, SSE, previews and public games.

Runtime containers are non-root, capability-free, read-only and resource
bounded. In production, terminate TLS at the platform ingress/load balancer and
forward `X-Forwarded-Proto: https`; nginx then emits HSTS. Use a dedicated
OpenAI project service account with the narrow `api.responses.write` permission,
and inject its key only into `worker-models`.

Host-only quality checks do not require credentials or infrastructure:

Install the package and development tools from the lock file:

```bash
uv sync --locked --all-groups
```

Run the same checks used by CI:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest -m "not integration and not browser"
uv build
npm --prefix web run format:check
npm --prefix web run lint
npm --prefix web run test:coverage
npm --prefix web run build
```

To run services directly on a configured host, apply `uv run alembic upgrade
head`, then start Uvicorn, Celery workers, and Celery Beat with the commands in
`compose.yaml`.

GitHub Actions runs independent gates for backend quality and packaging, Python
3.11–3.14 unit tests, PostgreSQL/Redis integration, real mobile Chromium game
validation, deterministic AI contracts, frontend formatting/lint/coverage/build,
dependency and source security scanning, reversible migrations, and a full
Docker Compose smoke test. CodeQL scans Python and TypeScript separately.

Paid model calls are deliberately absent from pull requests. A protected
`Live Luna evaluation` workflow runs a bounded golden dataset manually or on a
weekly schedule using the `ai-evals` GitHub environment and its
`OPENAI_API_KEY` secret. It records pass rate, token counts, latency, static
findings and browser evidence without retaining prompts or generated HTML. See
[the CI guide](docs/ci.md) for local commands, required branch rules, service
tests and live-evaluation setup.

## Contributing and security

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a change. Do not publish a
suspected vulnerability in a public issue; follow [SECURITY.md](SECURITY.md)
instead.

## License

No license has been selected. Until a license file is added, the repository is
not offered under an open-source license.
