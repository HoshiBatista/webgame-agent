# Prompt2Play

Prompt2Play is an AI-powered platform that turns a natural-language description
into a complete, playable HTML5 browser game.

The intended experience is simple:

> describe a game → generate it → validate and repair it → play it immediately

## Project status

**The hackathon vertical slice is implemented.** The repository now contains a
React creator UI, FastAPI control plane, PostgreSQL workflow state, Redis/Celery
workers, generation through a replaceable LLM connector, immutable content-addressed game
artifacts, bounded repair, static rules, and Playwright mobile validation.

The implementation deliberately does not use SQLite. Docker Compose starts the
production-like MVP stack: PostgreSQL 17, Redis with AOF/no-eviction, separate
model and validation workers, Celery Beat outbox recovery, API, and web UI.
Provider code remains behind the project-owned `ModelGateway`. The default
adapter uses a remote vLLM OpenAI-compatible Responses endpoint with Structured
Outputs; a hosted OpenAI adapter remains an optional fallback. Provider, URL,
credential and served-model ID are configuration rather than workflow code.

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
                                                               ├─ model worker → vLLM connector
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
generation rules, iterative revisions, a public community feed, likes,
revision-frozen publishing and one-click remix into a separately owned project.
Cross-genre specifications, procedural graphics/WebAudio, aggregate gameplay
analytics, and creator ratings with recurring quality priorities are also fed
into future specifications. Each generation stores the exact bounded feedback
context it used, so the behavior is auditable and cannot silently change while
a run is in flight. This is prompt-level preference learning, not automatic
fine-tuning of model weights. See
[docs/hackathon-requirements.md](docs/hackathon-requirements.md).

The creator studio uses a Beeline-inspired black/yellow visual theme with a
collapsible chat sidebar, persisted requests in the conversation, and a phone
preview beside the editor. On mobile, the game opens in an in-app full-screen
player with a visible exit action. The community has newest/popular sorting,
an author-only filter, editable titles and explicit publication removal.

Each project exposes its revision history. A creator can preview an older
validated version, make it current, or download its exact HTML / ZIP bundle
(`index.html` plus specification and validation metadata). Existing ratings
load when switching versions. Restoring a private revision does not update the
published game until the creator explicitly publishes again.

Deleting a chat archives the project and cancels unfinished runs. It removes
private access to the chat while preserving its public game, likes and remix
lineage. Removing a publication is separate: its share link becomes unavailable,
but the private chat and existing remixes remain. Archived records are retained
in storage; chat deletion is not a personal-data erasure operation.

Studio endpoints:

- `POST /v1/revisions/{id}/restore` selects a validated private revision;
- `GET /v1/revisions/{id}/export?format=html|zip` downloads it;
- `GET /v1/projects/{id}/feedback` returns the creator's saved revision ratings;
- `DELETE /v1/projects/{id}` archives a chat;
- `GET /v1/public-games?sort=newest|popular&mine=true|false` filters the feed;
- `DELETE /v1/public-games/{id}` removes an owned publication.

Apply migrations through `20261017_0008` with `uv run alembic upgrade head`
before running this version against an existing database.

Migration `0001` contains a frozen historical schema, independent of the current
ORM models. Both directions can be rendered without a database using
`uv run alembic upgrade head --sql` and
`uv run alembic downgrade head:base --sql`. Offline SQL also includes the legacy
publication backfill. CI checks a live PostgreSQL upgrade → downgrade → upgrade;
never run the destructive downgrade check against a database containing real data.

Workflow stages now hold a persisted exclusive lease. Duplicate deliveries are
ignored while the lease is held; completion releases it in the same transaction
that queues the next stage. Unhandled storage/validation errors fail the run.
The periodic dispatcher fences expired executions and reports their timeout
without silently spending another model call. `P2P_STAGE_LEASE_SECONDS` defaults
to 600 seconds and must exceed the worker's hard task limit. Timeout recovery
requires the workflow worker and Celery Beat to be running.

Database failures before stage ownership receive five bounded worker retries.
Old, unclaimed commands with no pending outbox record are redelivered after the
lease grace interval, so an early failure cannot leave a run silently orphaned.
Artifact-store initialization happens inside the stage guard. Restores and new
revision requests advance a project selection counter: a late candidate remains
in history but cannot replace a newer creator choice.

Artifact reads, browser paths and reuse verify SHA-256, containment and size;
corrupted stored content is never served under its previous validation status.
A missing Chromium runtime is reported as unverified and does not consume model
repair calls. The creator UI retains the logical request key across ambiguous
failures, separates publication success from clipboard/analytics availability,
and locks feedback fields while their submitted value is being saved.

Targeted revision validation compares deterministic state-transition traces of
the parent and candidate in both viewports, as well as their specifications.
This checks sampled behavior; it does not prove equivalence of every possible
playthrough. Generated controls expose `data-p2p-action="start|restart"`; older
games use a matching accessible button name instead of the first visible button.

## Repository contents

```text
.
├── .github/workflows/        # CI, CodeQL and bounded live model evaluations
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
- access to an OpenAI-compatible vLLM endpoint and its API key, or configured
  OpenAI fallback credentials;
- for host-only development: Python 3.11+, uv, Node.js 24 and npm.

Start the complete stack:

```bash
cp .env.example .env
# Set vLLM connection values and P2P_ADMIN_PASSWORD in .env, then:
docker compose up --build
```

The repository does not start or download a model. Point the model worker at a
separately operated vLLM server that exposes the Responses API and structured
JSON output. The served name may be an alias independent of the weights:

```env
P2P_MODEL_PROVIDER=vllm
P2P_VLLM_BASE_URL=https://models.internal.example/v1
P2P_VLLM_MODEL=prompt2play-code
P2P_VLLM_API_KEY=replace-with-internal-token
P2P_MODEL_MAX_OUTPUT_TOKENS=64000
```

For a temporary hosted fallback, set `P2P_MODEL_PROVIDER=openai`,
`P2P_OPENAI_MODEL` and `OPENAI_API_KEY`. Only the selected adapter validates and
uses its credential.

Open `http://localhost:5173`. nginx is the only published service: the API and
OpenAPI UI are available through the same origin at
`http://localhost:5173/v1/...` and `http://localhost:5173/docs`. Port 8000 is
internal and is not published. The first validation-worker image build installs
Playwright Chromium and can take several minutes; the API and model images do
not contain a browser.

The creator studio has no public registration. On startup, the one-shot
`bootstrap-admin` job creates or refreshes `P2P_ADMIN_USERNAME`, stores only a
salted password hash, and assigns legacy ownerless projects to that account.
Usernames are unique case-insensitively. Login uses an opaque HttpOnly session;
project history, runs, revisions, previews, publishing and analytics are scoped
to the authenticated owner. Published `/play/{slug}` links remain public.

The services are intentionally separate:

- `api` accepts prompts and streams persisted progress;
- `bootstrap-admin` provisions the closed creator account after migrations;
- `worker-models` is the only service with model credentials and provider egress;
- `worker-workflow` dispatches durable outbox commands without provider secrets;
- `worker-validation` opens untrusted games in Chromium on an internal-only
  network with read-only artifacts;
- `beat` recovers unsent PostgreSQL outbox commands;
- `postgres` owns product state; Redis is delivery infrastructure only;
- `web` serves React and reverse-proxies API, SSE, previews and public games.

Runtime containers are non-root, capability-free, read-only and resource
bounded. In production, terminate TLS at the platform ingress/load balancer and
forward `X-Forwarded-Proto: https`; nginx then emits HSTS. Use a dedicated
provider credential scoped to inference and inject it only into `worker-models`.

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

Live model calls are deliberately absent from pull requests. A protected live
evaluation workflow runs a bounded golden dataset manually or on a weekly
schedule using credentials from the `ai-evals` GitHub environment. It records
pass rate, token counts, latency, static
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
