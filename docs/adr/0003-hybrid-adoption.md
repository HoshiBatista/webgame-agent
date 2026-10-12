# ADR 0003: Adopt Game Forge Components with a Bounded Generation Workflow

- **Status:** Accepted
- **Date:** 2026-10-11
- **Decision owners:** Prompt2Play maintainers
- **Supersedes:** [ADR 0001](0001-target-architecture.md)
- **Amends:** [ADR 0002](0002-generation-harness.md)

[ADR 0004](0004-adaptive-generation-control.md) is the implemented opt-in extension for
adaptive decisions, protected acceptance and rendered quality. It retains this
stack and the single persisted workflow owner; its implementation is tracked
separately in the [R0–R7 migration plan](../pipeline-improvement-plan.md).

## Context

Prompt2Play has an architectural plan and a Python foundation, but no product
implementation. A separate Game Forge 1.3.0 handoff already contains a
Django/DRF coordinator, React studio, local Codex/API workers, a LangGraph
pipeline, semantic contracts, revision handling, validation code, and regression
games derived from prior game-development work.

These assets justify selective adoption. They do not establish live generation
quality: recorded corpus providers replay existing source, and the historical
release verification explicitly excludes live model generation, Docker/Chromium,
and real WebView assessment. The old pipeline can complete with static-only
`partial` validation, generates common infrastructure repeatedly, and owns its
repair loop inside the worker.

The combined design must reuse concrete engineering work while establishing the
contest requirement: a fresh prompt produces a demonstrably playable HTML5 game.

## Decision

1. **Adopt the existing product surface.** Keep React/TypeScript/Vite,
   Django/DRF, PostgreSQL, local worker providers, and cursor-based event polling.
   Preserve stale-worker rejection, cancellation, and usage accounting. Do not
   require a FastAPI migration, Celery/Redis, or PydanticAI for the contest build.
2. **Keep one persisted workflow owner.** Application use cases own planning,
   candidate commit, authoritative validation, repair strategy, and promotion.
   Database-backed HTTP polling remains the initial dispatch mechanism. LangGraph
   can implement a bounded attempt, but cannot retain a second global repair loop.
3. **Retain ADR 0002's attempt and trust boundaries.** One harness invocation
   produces at most one candidate. Narrow tools, budget checks, execution fences,
   immutable commits, and independent release tests remain required. References
   to Celery in that decision are deployment-independent worker operations;
   PydanticAI is an optional adapter implementation rather than a dependency.
4. **Combine semantic contracts with small runtime capabilities.** Adapt donor
   ownership, action, persistence, timing, dependency, and scenario contracts into
   separate `GameSpec` and `BuildPlan` identities. Extract tested lifecycle/input/
   audio/bridge primitives. Preserve Canvas, DOM, hybrid, real-time, and turn-based
   options; do not create a catalog of prewritten games or impose every subsystem
   on every request. Generated mechanics remain editable.
5. **Make actual browser validation mandatory for delivery.** Static-only,
   skipped, or unavailable checks are `unverified`, never successful generation.
   Use isolated Playwright, real input, independent scenarios, stored evidence,
   and an identified WebView acceptance pass. Model review is supplementary.
6. **Store every submitted candidate immutably.** Move game bytes from database
   blobs to a project-owned filesystem `ArtifactStore`. Keep metadata in
   PostgreSQL, failed candidates private, and previous playable revisions intact.
   Validate exactly the delivered HTML; do not rebuild during publication.
7. **Measure before selecting generation strategy.** Keep four-author generation
   as a baseline and compare it with a single author under the same budgets and
   suite. Targeted patching and explicit replan/regenerate decisions replace
   unconditional whole-module repair as capabilities are implemented.
8. **Adopt selectively and preserve provenance.** Import source, relevant tests,
   fixtures, and applicable lessons in working slices. Do not copy secrets,
   environments, complete archive history, or donor agent instructions wholesale.
   The contest repository must not depend on a neighboring local folder at runtime.

## What changes from the earlier decisions

| Earlier selection | Current decision |
| --- | --- |
| FastAPI control-plane adapter | Adopt Django/DRF; retain framework-independent application ports |
| Celery/Redis required for the first product | Existing database-backed polling with leases and fences |
| PydanticAI preferred initial adapter | Adapt existing Codex/API implementations; library choice remains optional |
| Canvas2D arcade profile first, other presentation deferred | Preserve Canvas/DOM/hybrid; prove real-time and turn-based coverage |
| SSE initially | Keep polling initially; add SSE only for a demonstrated need |
| Build all product pieces in the new layout | Import functioning slices and extract boundaries incrementally |

Immutable candidates, mandatory isolated execution, separate preview origin,
versioned contracts, bounded repair, content-addressed storage, and independent
release checks are retained. The absence of a broker removes the immediate outbox
requirement, not durable workflow, cancellation, or recovery requirements.

## Consequences

### Benefits

- Existing UI, API, provider integration, contracts, and regression knowledge
  reduce duplicated implementation work.
- Fresh generation quality and actual playability become measurable gates.
- Infrastructure can evolve behind stable ports without replacing the product.
- Conditional runtime capabilities support different mechanics without asking
  the model to recreate all infrastructure on every attempt.

### Costs and risks

- Existing whole-job orchestration must be split without weakening lease,
  cancellation, checkpoint compatibility, or token accounting.
- Runtime extraction and a new test bridge can break existing examples; retain
  adapters and run both real-time and turn-based regressions at each change.
- Moving storage introduces a database/filesystem commit boundary and requires
  recovery and import verification, not only a directory rename.
- Ordinary Docker isolation is a bounded team-deployment step; public hostile
  workloads require the stronger sandbox boundary before admission.
- Reuse does not guarantee donor dependencies work in this environment or that
  the model accepts its schemas. Reproduce both before trusting the baseline.

## Alternatives not selected

- A complete rewrite: discards useful UI, concurrency, provider, and regression
  work before establishing the actual generation bottleneck.
- Shipping the donor unchanged: permits partial validation to become a completed
  result and leaves generation quality unmeasured.
- Keeping two repair orchestrators: makes budgets, retries, and final state
  ambiguous after interruptions.
- A universal fixed genre template: would narrow the requested generation goal.
- Implementing every production component before the first live evaluation:
  delays discovery of model, contract, and playability failures.

## Implementation and review

The [architecture](../architecture.md) defines the target contracts and trust
boundaries. The [development plan](../development-plan.md) owns the transfer
matrix, sequencing, dependencies, and exit criteria. This ADR changes documents
only; no component is marked imported or validated by accepting it.

Revisit after measured queue pressure, a provider capability gap, demonstrated
runtime restrictions, a committed public deployment, or controlled comparisons
showing a better generation strategy. Record evidence, not framework preference.
