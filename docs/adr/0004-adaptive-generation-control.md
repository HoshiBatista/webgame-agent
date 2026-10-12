# ADR 0004 Adaptive generation control and protected acceptance

- **Status:** Implemented; adaptive default enabled by explicit user request on 2026-10-12
- **Date:** 2026-10-12
- **Extends:** [ADR 0003](0003-hybrid-adoption.md)
- **Amends:** [ADR 0002](0002-generation-harness.md), specifically its iteration
  limits and the scope of resumable work inside one candidate attempt
- **Delivery plan:** [Pipeline improvement plan](../pipeline-improvement-plan.md)

## Context

The integrated studio persists drafts, model receipts, budgets and immutable
candidates. Planning can correct rejected proposals and pause on repeated errors.
Authoring receives tool and browser feedback, but no shared progress policy
distinguishes a defective game, an invalid test, a contradictory plan and an
unavailable environment throughout the attempt.

The [2026-10-12 review](../evidence/pipeline-review-2026-10-12.json) reproduced
three gaps: caching unavailable browser results across continuation, treating
different failed mechanics as the same failure and triggering regeneration,
and accepting weakened assertions while preserving test/action labels.
Source art review also has no rendered-image input. These gaps must be addressed
before model-directed planning decisions become authoritative application actions.

## Decision

1. Keep the application as the sole workflow owner. Add a supervisor model role
   behind the existing gateway, with no separate service, scheduler or nested
   repair orchestrator. Its structured proposals require coordinator validation.
2. Separate user requirements, acceptance meaning, design and execution plans.
   Give their immutable revisions explicit identities and dependencies. The
   execution plan may adapt; silently weakening user requirements or acceptance
   to achieve a passing test is forbidden.
3. Record observations after meaningful work boundaries. Evaluate progress using
   resolved defects and verified requirements, not source changes or elapsed time
   alone. Invoke model supervision for an unresolved decision or milestone, not
   for every file read or patch. Include a final readiness decision before release.
4. Permit continue, code repair, scenario repair, plan revision, validation retry,
   user input, pause and justified regeneration proposals. Infrastructure recovery
   cannot consume semantic repair attempts or rewrite game mechanics. Compare
   specific defects and evidence before escalating the repair scope.
5. Extend a candidate attempt with checkpointed decision boundaries. An author
   may request a plan change; it saves its draft and yields before dependent work.
   The coordinator commits a versioned decision under the current fence. The
   harness still emits at most one candidate and cannot schedule global repair,
   publish output or change trusted application/runtime code.
6. Keep all model roles in the same job ledger and user-authorized budget.
   Continuation preserves receipts, uncertain spend, attempts and work. There is
   no default generation wall-clock, operation or productive-turn count ceiling.
   Lack of progress triggers diagnosis and ultimately a resumable pause; model
   supervision must also detect repetition in its own rejected proposals.
7. Preserve Lite automation and Pro approval. Technical corrections within scope
   may proceed automatically. User intent/budget changes require a user decision;
   substantial Pro design/plan changes require explicit approval of their diff.
   Cancellation cannot be silently reversed by a supervisor.
8. Add image-based art/UI review with evidence bound to source, plan and captured
   states. Keep semantic acceptance and rendered quality separate from source
   critique. No model opinion can waive a mandatory deterministic failure. A
   provider without image support must expose an explicit human-review path.
9. Introduce a new modular-source format with isolated deterministic packaging
   into one offline HTML. Keep historical formats/runtime bytes readable; migrate
   by child revision and validate the exact packaged artifact before delivery.

## Failure handling boundary

Deterministic checks identify known schema/transport/environment facts. Models
may investigate ambiguous game/test/plan failures using scoped observations.
They cannot alter validators, remove security rules, modify credentials, raise
budgets, claim unobserved success or blindly replay a paid request whose outcome
is unknown. A validator defect may have a valid equivalent scenario workaround;
otherwise the system preserves work and reports a platform incompatibility.
Trusted application fixes follow the repository's tested deployment process.

## Compatibility and deployment

Use additive metadata and explicit worker capabilities. Pin workflow and
contract versions per job. Migrate saved work only at a durable pause/continuation
boundary, preserving the original snapshot and ledger. Accepting a newer plan
invalidates stale pending actions, not their recorded cost. Every applied decision
is fenced and idempotent.

Deploy verified R0 corrections first. Observe supervisor recommendations before
enabling automatic decisions for selected new jobs, then measure quality and cost
before default adoption. Rollback stops new adoption and pauses incompatible
active jobs; it never deletes financial history or rewrites old artifacts.

## Consequences and acceptance

The design adds plan/evidence lineage, policy checks, review UI and model cost.
It can reduce unproductive regeneration and improve diagnosis; neither lower
cost nor universally autonomous repair is assumed without measurement.
Uncertain art judgments and novel mechanics may still need human review.

R0–R7 define executable regression cases, migration races, browser acceptance,
human visual assessment and controlled live comparisons. Old games, working
preview/download and explicit continuation remain available during migration.
Acceptance of this plan does not mark these capabilities implemented.

## Implementation mapping

`contracts/adaptive.py` keeps immutable requirement, acceptance, design and
execution versions. A plan revision is a new DesignPlan with its parent identity,
paired with the supervisor decision in the same fenced draft/approval transition.
`application/progress.py` stores observations and distinguishes changes from
verified progress. `generation/supervisor.py` constrains advice; the coordinator
checks receipts, requirement preservation and Pro approval. Source coverage is
reviewed separately from mechanics and actual PNG review. Missing or failed image
transport opens a human gate without erasing uncertain spend.

`runtime-modules-v2` supports local JS/CSS/JSON/SVG/base64 PNG, 32 files,
2 MB/file and 4 MB source. Pinned esbuild 0.25.12 runs read-only, without network
or generated config/plugins/dependency installation. Output is one HTML up to
8 MB. Adaptive provenance is bounded to 16 MiB and drafts to 32 MiB; legacy
envelopes remain unchanged. Compiler resource limits are isolation safeguards,
not model-generation timeouts.

The user explicitly requested enabling the planner after a live legacy run repeatedly
repaired mobile controls without shared progress supervision. New Studio and API jobs
now default to adaptive generation; the previous process remains selectable for
comparison. Existing jobs retain their pinned protocol until explicitly upgraded at a
durable pause. Migration preserves source bytes, the plan, original snapshot and ledger,
then invokes supervision before authoring. Only a matching saved browser result seeds
verified work; other evidence remains unverified. Browser preference schema v3 replaces
the former default without resetting the selected model or budget.

Enabling the default does not assert superior comparative quality, human visual
acceptance or completion of WebView-host verification. Those checks remain separate.
