# Prompt2Play

Prompt2Play is an AI-powered platform that turns a natural-language description
into a complete, playable HTML5 browser game.

The intended experience is simple:

> describe a game → generate it → validate and repair it → play it immediately

## Project status

**Integrated studio implemented; contest acceptance in progress.** This branch
contains Django/DRF coordination, React studio, local Codex/API adapters, budget-controlled
generation and configurable repair, immutable artifact storage, and a separate isolated
browser validation role. Only candidates that pass required checks can be played
or downloaded. A failed edit preserves the previous playable version.

The accepted plan selectively adopts the existing Game Forge 1.3.0 application:
Django/DRF and PostgreSQL, React/Vite, and local Codex/API workers. The target
adds an application-owned workflow, resumable generation attempts, a small trusted
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
supports a working restart flow. Full victory/failure playthrough and balance are reviewed by a person by default; automatic end-to-end playthrough is an optional launch setting.
New native plans include mandatory named mechanics checks with real inputs and expected gameplay-state assertions on desktop and touch. Revisions retain previous action/control coverage and test new actions; a single input reaction is insufficient. Failed jobs offer **Continue after error**, preserving drafts, completed responses and uncertain cost reserves. Increasing the budget also preserves unknown spend.
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

Studio settings default to **manual playthrough**: automatic launch, input, rendering, restart, mobile layout and error checks remain required. The report explicitly says that victory, defeat and balance need human review. Select automatic playthrough for a reliable game-specific scenario; its failure then blocks delivery. Existing jobs retain their old choice unless explicitly changed when extending the budget.

New Studio runs use a **USD API-equivalent budget** (default $10, editable
from $0.01 to $1,000), including Codex subscription runs. Fresh input, cached
input, and output use different Standard rates. The server fixes the explicit
model and dated tariff at job creation; the UI shows those rates before launch.
Cached input is subtracted from total input, and reasoning is already included
in output. Actual receipts are priced per invocation, never from the run's
aggregate context size. There is no additional total-token ceiling for USD runs.

The bundled rate card covers seven models, checked against official OpenAI model
pages on **2026-10-12** (`src/prompt2play/resources/pricing.json`). To update it,
configure `PROMPT2PLAY_PRICING_FILE` on the server with a reviewed file of the same
schema. Existing jobs keep their snapshot. Unknown model IDs are rejected rather
than assigned an invented price; blank models require a unique, explicit default
among online generators. The catalog is not fetched/scraped during generation.

Reports show a cost range because current receipts omit cache-write counts;
Codex also aggregates potentially multiple internal requests into one turn.
The upper estimate accounts for cache writes and possible long context and is
used for the budget. Standard API equivalent excludes Fast/Batch/Flex, regional
premiums, discounts, tax and subscription billing. This is a comparison and
stopping policy, not an invoice. Before dispatch, reserve estimated input and
output cost without assuming a cache hit. An in-flight response can exceed the
reservation (Codex exposes no portable hard output cap); record the overrun and
stop subsequent calls. Unreported usage retains its reservation even after
cancellation or restart. Repeated receipts never charge twice.

Authoring and source review now retain separate conversations within each attempt.
The next turn sends confirmed file changes and feedback instead of rebuilding the
entire game context. Codex resumes an explicit local CLI session; Responses retains
message history with `store:false`. Oversized history is refreshed from the complete
current draft, plan and last author summary, without stopping generation. Restarted
workers also recover from that draft. No plan/source truncation or new turn limit is
used to increase cache hits. CLI transcripts follow the local Codex retention policy.
Worker logs include context sizes, refresh reasons and actual cached-input ratios;
resume accounting subtracts prior cumulative Codex receipts. See
[context reuse and its measured scope](docs/evidence/context-reuse-verification.json).

After a budget stop, the job monitor offers **Increase limit and continue**.
Enter the new **total** USD limit (or token total for legacy runs). The same job
continues from its saved draft with its original model, tariff, paid receipts,
uncertain reservations and repair history. The change is recorded and fenced
against double clicks, cancellation and a concurrently started successor.
Increasing a budget never silently launches a new game or resets its usage.
Already-paid author responses are saved even when their final receipt exceeds
the admission estimate; only subsequent paid requests are stopped.

`budget_usd` is a decimal API field; send it without `budget_tokens`. Legacy API
clients omitting `budget_usd`, existing jobs, and the offline evaluation CLI
retain the old token policy for reproducibility. No token limit is silently
converted to dollars. Browser preferences migrate model/provider/repair settings;
the new dollar limit starts at $10. Migration 0006 is additive.

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

Studio generation has **no wall-clock timeout**: a slow model request continues
until it returns or the user cancels. New jobs store no execution deadline, and
the native worker applies no run or model-call timer by default. Money admission,
manual cancellation, worker heartbeat/fencing and isolated validation limits remain.
Explicit time limits are retained for bounded CLI experiments and older jobs;
measured historical evidence is not rewritten.

A recorded local Codex timeout may dispatch one additional request with a distinct
invocation identity, retaining unknown spend and reusing completed answers.
Cancellation, exhausted budget, lost leases and ambiguous network failures do not
allow blind replay. `prompt2play manage resume_timeout JOB_ID` is a separate,
guarded operator action for an eligible old failed timeout: it removes that run's
time limit, preserves its money budget/receipts and records the recovery event.
It refuses cancelled/completed jobs, an active successor or an exhausted retry.
The ordinary `manage recover` command still only finalizes artifact commits.

The job monitor polls every 1.5 seconds while a run is active. It shows worker
contact, the current model operation and elapsed time, and saved call history.
These come from durable invocation receipts and worker leases; elapsed time is
not presented as a completion percentage. Usage appears when a request returns.

Creation mode is chosen before launch. **Lite** runs automatically. **Pro** pauses
before coding to approve the game plan, and after mandatory browser validation
to accept the proposed version. Both modes use the same quality requirements.
The Plan and stages tab exposes mechanics, controls, art/UI design, acceptance,
saved author steps, source critique and validation; it also reads old planner
receipts while a Lite run is still active.

In Pro, describe corrections in ordinary language. The revised proposal requires
another confirmation. Pauses have no wall-clock limit and dispatch no new model
requests; feedback and subsequent revisions retain the original money budget.
A waiting job remains the project's active job and can be cancelled. The previous
primary playable version remains selected until acceptance; a passed proposal
can already be previewed. Checks never become optional. Only a runner advertising
`interactive_plan_v1` can claim Pro generation. Approval is fenced against stale
or double submissions and survives coordinator/worker restarts.

New native runs require a detailed art/UI design and a maintainable implementation
plan before coding: palette, scene composition, actor/object detail, interface
states, motion, responsive layout and concrete visual criteria. The generator
preserves the requested scope and supports later revisions; it is not instructed
to create a small demo. State/rules, rendering, interface and content definitions
have explicit ownership even when packaged in one JavaScript file.

Before submission a separate `visual_review` model call critiques the exact source
against that plan. Material findings return to the author for changes; unchanged
rejected source cannot be submitted. Authoring, quick checks and source critiques
have no default count limit. Invalid review citations return to the reviewer;
material findings return to the author until the source is ready or the original
budget is exhausted. A review failure never silently accepts a placeholder. Plans and review rounds are visible on the Checks tab. This is a
source critique, not a screenshot review or proof of artistic quality. Browser
validation still runs separately on the committed bytes. Older versions remain
unchanged; a revision of an old plan adds design through a new planning call.

Native authoring has **no fixed limit of 16 operations per response, 64 operations,
8 turns, 8 quick checks or 3 source reviews**. Operations are applied sequentially
with cancellation/fence checks. Repeated reads and unsuccessful patches return
feedback instead of failing the entire job. Malformed structured author/review
responses are durably recorded, charged once and corrected in a fresh budgeted
request; network failures with uncertain results still require reconciliation.
Explicit operation/check/turn bounds remain available only to offline experiments.

The author has separate `check()` (source/syntax only) and `browser_check()`
(isolated desktop/touch execution) operations. Browser diagnostics preserve
exact source bytes, screenshots, trace and per-step state observations. They are
visible under Plan and stages, but never grant preview/publication eligibility;
the validator role still checks the committed candidate independently.
Unchanged diagnostics are reused, and submission requires a passing diagnostic
when the studio browser callback is available.

`set_test_scenario(content)` corrects declarative gameplay actions separately from
the approved mechanics/design. Optional automatic native playthroughs must explicitly reach `/phase`
`won` or `lost` through normal controls. In that automatic mode, a test of an intermediate command, such
as ordering a worker, is reported as an unsuitable scenario instead of silently
relabelled as a whole-game completion test. Clock games support up to ten simulated
minutes per wait, thirty per scenario, advanced in batches that respect the trusted
runtime's 600-tick call bound. These sandbox work quotas do not limit generation
time or author operations. No instant-win test commands are allowed.

The worker saves immutable draft snapshots between author/review steps. A restart
uses the saved files, plan, current step and feedback without rewriting completed
work or resetting the ledger. Snapshots cannot be played or published; immutable
candidate submission and independent browser validation are still mandatory.
Only workers advertising `continuable_authoring_v1` may reclaim saved drafts.
`prompt2play manage resume_authoring JOB_ID` recovers a failed obsolete authoring
limit from a snapshot or, for an unambiguous first attempt, recorded responses.
It refuses cancelled/completed jobs, an active successor or an unreconciled last
call. Recovery preserves the budget, usage, reservations and previous failure event.
User-configured automatic repair limits after independent browser validation are
separate from the now-unlimited authoring steps inside each candidate attempt.

The generator uses the controlled single-author runtime by default. The
`--mode four_author` option preserves the adopted donor strategy for measured
comparisons and does not use the new native art-review gate. Fresh evaluation
results, failures, costs and remaining quality
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
