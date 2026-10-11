# AGENTS.md — Prompt2Play Engineering Guide

This file applies to the entire repository. More specific `AGENTS.md` files may
be added to subdirectories later; when present, the closest file takes
precedence.

## Mission

Build **Prompt2Play**, an AI-powered service that turns a natural-language
request into a complete, playable, self-contained HTML5 game for modern
browsers and embedded WebViews.

A successful result is a tested game artifact, not a code sample: the user can
open it, understand the controls, play it, and restart it.

## Product contract

- **Input:** a natural-language game description, optionally including genre,
  mechanics, visual style, controls, and constraints.
- **Output:** a game bundle containing `index.html`, all required local assets,
  and generation and validation metadata.
- **Primary targets:** current desktop browsers and touch-first mobile
  WebViews.
- **Minimum playability:** the game starts, accepts input, changes state, and
  reaches a meaningful success, failure, or restart state.
- **Reliability rule:** report generation failures clearly and never describe
  untested output as validated.

## Delivery priorities

Work in this order:

1. Reproduce and measure the donor baseline, preserving failures as evidence.
2. Adopt a complete prompt-to-preview path with mandatory browser validation.
3. Extract optional trusted runtime capabilities across different mechanics.
4. Improve bounded editing and repair using controlled live comparisons.
5. Verify the chosen release in the target WebView and prepare the demonstration.

Follow the dependencies and exit gates in [docs/development-plan.md](docs/development-plan.md).
Do not infer that a documented target or donor feature is implemented here.

For a hackathon build, prefer one convincing end-to-end demo over several
unfinished features.

## Architecture principles

Use the smallest design that supports an explicit, testable pipeline:

1. **Specify:** convert the request into a validated game specification.
2. **Plan:** define mechanics, state transitions, assets, and acceptance checks.
3. **Generate:** create the complete HTML, CSS, JavaScript, and local assets.
4. **Validate:** perform static checks and run the game in an isolated browser.
5. **Repair:** apply targeted fixes for a bounded number of attempts while
   recording each defect and change.
6. **Package:** expose the artifact, preview location, metadata, and honest
   validation status.

Prefer a single orchestrator with explicit state and focused components. Add
agents, queues, databases, or large frameworks only when a demonstrated need
justifies their operational cost.

[ADR 0003](docs/adr/0003-hybrid-adoption.md) is the current architecture decision.
Adopt Django/DRF, PostgreSQL, React/Vite, and local Codex/API workers selectively.
Keep database-backed polling initially; do not introduce FastAPI, Celery/Redis,
or PydanticAI solely to follow superseded documents. Application code owns stage
transitions, validation, repair policy, and promotion. A generation harness
produces at most one candidate per invocation; LangGraph, if retained, stays
inside that attempt and must not own a second repair loop.

Preserve donor provenance, relevant regression tests, and lesson applicability.
Do not import donor secrets, environments, agent instructions, or complete
historical archives wholesale. Imported code must work without sibling folders.

Keep these boundaries clear:

- contracts and schemas;
- model-provider adapters;
- orchestration and repair policy;
- artifact storage and packaging;
- static and browser validation;
- API and user interface.

The repository layout described in [docs/architecture.md](docs/architecture.md)
is a target, not permission to create empty directories. Add a directory only
when it contains a working part of the product.

## Generated-game requirements

- Produce a complete game, not pseudocode, a tutorial, or a partial scaffold.
- Prefer vanilla HTML5 Canvas and JavaScript for small arcade-style games.
- Support DOM/SVG and hybrid presentation where appropriate. Use a small trusted
  runtime with optional capabilities; leave mechanics generated. Do not impose
  audio, persistence, or a real-time clock on games that do not need them.
- Avoid runtime CDN dependencies, remote fonts, analytics, and remote assets by
  default.
- Use relative paths and make `index.html` the bundle entry point.
- Render responsively and account for resize events and device pixel ratio.
- Support pointer or touch input, plus keyboard controls where appropriate.
- Show concise controls and provide visible start and restart actions.
- Avoid blocking dialogs, uncontrolled loops, uncaught exceptions, popups,
  downloads, and navigation outside the game.
- Use original or appropriately licensed assets; never imitate protected code or
  artwork.

## Security boundary

Treat prompts, retrieved content, and generated files as untrusted data.

- Never run generated code with API-server or developer-machine privileges.
- Preview and test games in a restricted browser context or container. Disable
  network access and limit resources where practical.
- Never expose secrets, environment variables, internal services, privileged
  browser APIs, or arbitrary filesystem paths to a generated game.
- Never interpolate prompts or model output into shell commands.
- Normalize and validate every artifact path. Reject absolute paths, traversal,
  symlinks that escape the artifact root, and writes outside the assigned
  directory.
- Validate all structured model output against a schema before using it.
- Do not present an iframe as a security boundary without an appropriate
  `sandbox` policy, Content Security Policy, and deployment isolation.
- Keep credentials out of source, fixtures, logs, artifacts, screenshots, and
  commits.

Report suspected vulnerabilities according to [SECURITY.md](SECURITY.md).

## Definition of done

A generated artifact is **validated** only when all applicable checks pass:

1. The expected files exist and `index.html` loads.
2. Startup produces no blocking JavaScript error or missing local resource.
3. The game displays meaningful content rather than a blank screen.
4. At least one relevant input causes an observable state change.
5. The completion, failure, and restart paths work where applicable.
6. Controls and layout are usable in a representative mobile viewport.

If automation cannot establish a criterion, mark it **unverified**. Preserve
browser logs, screenshots, validation reports, and repair history when
practical.

A required skipped check prevents successful delivery, normal preview, and
publication. Commit each submitted candidate immutably, validate the exact
delivered bytes, and preserve the last playable revision after a failed edit.
Recorded-provider replay is regression evidence, not live generation; a mobile
viewport is not evidence of compatibility with an actual WebView host.

## Engineering standards

- Use Python 3.11 or newer, the `src` package layout, and uv for environments,
  dependencies, locking, and builds.
- Keep `pyproject.toml` and `uv.lock` synchronized. Do not edit `uv.lock`
  manually or introduce another Python dependency manager.
- Before completing Python changes, run Ruff formatting and lint checks, strict
  Mypy, Pytest, and the package build using the commands documented in the
  README.
- Keep modules focused and public interfaces typed.
- Put provider-specific model integration behind a small adapter. Support
  timeouts, cancellation, bounded retries, and rate-limit failures.
- Make providers, model identifiers, artifact locations, and limits
  configurable. Never hardcode credentials or pricing assumptions.
- Record stage timings, attempts, token or cost estimates when available, and
  validation outcomes without logging sensitive values.
- Use deterministic fixtures in tests and retain representative games as
  regression cases.
- Test changes to generation, validation, repair, packaging, and security.
- Avoid unrelated refactors and speculative abstractions.

## Working protocol

Before editing:

1. Read the README, relevant manifests, source files, tests, and local
   instructions.
2. For nontrivial work, state a short plan and identify the affected files.
3. Define acceptance checks and note security implications.

While editing:

1. Make small, coherent changes and preserve public interfaces unless the task
   requires a change.
2. Reuse existing utilities and conventions before creating new ones.
3. Keep prompts and templates under version control when they affect behavior.
4. Run the narrowest relevant check first, followed by broader checks when
   practical.

After editing:

1. Summarize what changed and why.
2. Report the exact checks run and their pass/fail result.
3. Identify limitations and unverified behavior.
4. Do not claim browser, model, mobile, or WebView validation unless it was
   actually performed.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the repository workflow.
