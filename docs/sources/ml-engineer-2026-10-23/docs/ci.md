# Continuous integration and evaluation

Prompt2Play separates deterministic pull-request checks from paid model
evaluation. This keeps every code change reproducible while still detecting
quality regressions in the configured model on a controlled schedule.

## Required pull-request gate

Protect `main` and `develop` and require `CI / required gate` plus both CodeQL
matrix jobs. The aggregate CI gate succeeds only when every lane succeeds:

| Lane            | Evidence                                                                                                                                                           |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Backend quality | locked dependency graph, Ruff format/lint, strict Mypy including eval scripts, offline Alembic SQL, sdist/wheel checks, isolated wheel import                      |
| Backend unit    | deterministic tests on Python 3.11, 3.12, 3.13 and 3.14                                                                                                            |
| Frontend        | Prettier, type-aware ESLint, Vitest coverage thresholds, npm audit and production Vite build                                                                       |
| Integration     | real PostgreSQL 17 and Redis 8, migration up/down/up, API-to-artifact vertical slice, 65% combined backend coverage                                                |
| Browser         | real Playwright Chromium at the mobile validation viewport, including input, state change and reset                                                                |
| AI contracts    | schema, adversarial prompt and golden-rubric scoring without credentials or network calls                                                                          |
| Security        | Bandit, `pip-audit`, npm audit, Trivy vulnerability/misconfiguration/secret scan, credential-pattern guard, zizmor workflow audit and CodeQL for Python/TypeScript |
| Delivery        | role-specific Docker targets, full Compose stack, secret/egress/read-only boundaries, migrations, API readiness through nginx, rate limiting, OpenAPI and teardown |

Coverage reports and the frontend bundle are retained as workflow artifacts for
14 days. Dependency updates are grouped weekly for uv/Python, npm, Docker base
images and GitHub Actions. Action references are pinned to immutable commit
hashes; Dependabot keeps those pins current.

## Local deterministic checks

```bash
uv sync --locked --all-groups
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run pytest -m "not integration and not browser"
uv build

npm --prefix web ci
npm --prefix web run format:check
npm --prefix web run lint
npm --prefix web run test:coverage
npm --prefix web run build
```

The unit threshold is 52% branch-aware backend coverage. The real-database CI
lane raises the combined threshold to 65%. Frontend thresholds are 70% lines,
70% statements, 70% functions and 60% branches.

## Service and browser checks

Integration tests never fall back to SQLite. Start PostgreSQL and Redis, point
`P2P_DATABASE_URL` and `P2P_REDIS_URL` at them, then run:

```bash
P2P_INTEGRATION_TESTS=1 uv run pytest -m integration --no-cov
uv run playwright install --with-deps chromium
P2P_BROWSER_TESTS=1 uv run pytest -m browser --no-cov
```

The full delivery smoke test is equivalent to:

```bash
cp .env.example .env
sed -i 's/^P2P_ADMIN_PASSWORD=$/P2P_ADMIN_PASSWORD=ci-admin-password-123/' .env
sed -i 's/^P2P_VLLM_API_KEY=$/P2P_VLLM_API_KEY=ci-placeholder/' .env
docker compose config --quiet
docker compose build
docker compose up --detach
curl --fail http://localhost:5173/readyz
curl --fail http://localhost:5173/
docker compose down --volumes --remove-orphans
```

Use only a non-production placeholder connector key for this smoke test. The model
worker starts so its health and secret boundary can be checked, but no generation
task is submitted and no model request is made. CI also proves that port 8000
is not published, only `worker-models` receives the key and egress network, API
and validation mounts are read-only, validation has no public network path, and
nginx returns 429 under a generation burst.

## Live model evaluation

Create a protected GitHub environment named `ai-evals`, add either the
`OPENAI_API_KEY` secret or the `VLLM_BASE_URL` and `VLLM_API_KEY` secrets, and
require an approver where model use must be authorized. The live workflow:

1. caps the evaluated case count (three by default);
2. uses the versioned dataset in `golden/evals/cases.json`;
3. validates Structured Outputs through the production adapter;
4. scores task-specific observable criteria and static security findings;
5. opens every candidate in isolated Chromium and exercises input/reset; and
6. uploads only aggregate scores, finding codes, timings and token counts.

It intentionally does not store prompts, raw provider responses or generated
HTML in Actions artifacts. Run the same evaluator only in a trusted shell:

```bash
P2P_MODEL_PROVIDER=vllm P2P_VLLM_BASE_URL=... P2P_VLLM_API_KEY=... \
  P2P_VLLM_MODEL=prompt2play-code uv run python scripts/run_live_evals.py \
  --limit 3 --minimum-pass-rate 0.80 --browser
```

The live lane is weekly and manually dispatchable. It is separate from the
pull-request gate because provider availability, quota, latency and cost are not
deterministic properties of a code revision.
