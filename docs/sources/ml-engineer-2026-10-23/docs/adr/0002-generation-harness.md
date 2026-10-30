# ADR 0002: Bound the Generation Harness to One Candidate Attempt

- **Status:** Accepted
- **Date:** 2026-10-10
- **Decision owners:** Prompt2Play maintainers

## Context

ADR 0001 selects a PostgreSQL-backed workflow, Celery execution, versioned game
templates, immutable revisions, and layered validation. A generation harness is
still needed to manage model turns and controlled file tools inside the
generation and repair stages.

If that harness also owns retries, workflow transitions, artifact publication,
or browser validation, Prompt2Play would have two competing orchestrators. A
Celery redelivery could then run two model loops, stale workers could publish
output after their leases expire, and quick model feedback could be mistaken
for release validation. The boundary must make those outcomes impossible even
when a worker or provider fails at an inconvenient point.

## Decision

### 1. One invocation produces at most one candidate

`GenerationHarness.run(request)` executes one bounded `INITIAL`, `LOCAL_REPAIR`,
`STRUCTURAL_REPAIR`, or `REGENERATE` attempt. It returns one submitted candidate
or a typed terminal outcome. It never decides to start another attempt.

The PostgreSQL state machine remains the only owner of stage order, workflow
retries, semantic repair count, replan and regeneration policy, cancellation,
and terminal run status. Model turns and tool calls are audit events within a
`GenerationAttempt`; they are not Celery stages.

### 2. Keep infrastructure outside the harness

The harness depends on application ports for model calls, a controlled draft
workspace, quick static feedback, budget accounting, cancellation, and audit
events. It has no knowledge of Celery, Redis, FastAPI, SQL, Playwright, provider
SDKs, or host paths.

PydanticAI may implement typed model and tool adapters behind `ModelGateway`,
but it does not own the application workflow or repair policy.

### 3. Separate draft submission from immutable revision commit

The model writes only through `DraftWorkspace`, a capability-scoped view of one
staging directory. `submit_candidate` closes that workspace and returns a
one-use `CandidateSubmission`; it does not calculate the canonical artifact
digest.

An application-owned `ArtifactCommitter` independently canonicalizes paths and
metadata, rechecks template integrity and quotas, calculates the digest,
atomically promotes the directory, and records the immutable candidate
`Revision`. A database commit intent and reconciler bridge the unavoidable
atomicity gap between PostgreSQL and a POSIX rename. Validators consume only
immutable revisions. Failed revisions stay auditable but cannot be previewed or
published.

### 4. Use one static-rule library with two authorities

The harness may run shared rules in `quick` mode to help the model correct
syntax, manifest, reference, and template-integrity errors. After commit, the
workflow runs `release` mode. Only release validation creates authoritative
findings or changes revision status.

Quick mode may contain a strict subset of release rules. It may not redefine a
shared rule or waive a failure.

### 5. Fence every attempt and provider result

Claiming a generation stage allocates a monotonically increasing execution
fence. Model-response acceptance, candidate submission, artifact commit, and
stage completion all compare that fence with the current PostgreSQL value. A
stale worker cannot publish output even if it continues after its lease expires.

Before dispatch, every provider call reserves a `ModelInvocation` with a stable
request fingerprint, execution fence, deadline, and status. A completed
identical response may be replayed when policy permits. Third-party calls cannot
always be cancelled or deduplicated, so stale work may still cost money; it is
recorded as duplicate or abandoned spend rather than accepted as current output.

### 6. Treat all content inputs according to trust

System policy, tool policy, and template contracts are trusted instructions.
Specifications, plans, findings, user text, generated source, and asset metadata
are delimited data with distinct validation levels. Content read from an old
revision is never promoted into system instructions.

The stable contract, unresolved rubrics, safety policy, and remaining budget
remain present on every turn. Files and skills are loaded lazily, and context
compaction cannot silently remove mandatory constraints.

### 7. Expose narrow tools, not a filesystem or shell

The model can list and read bounded generated files, read allowlisted skill
snapshots, create or patch game files, delete generated files, inspect a
manifest, inspect immutable prepared assets, run quick checks, and submit once.
It cannot run a shell, install packages, access arbitrary paths or networks,
edit the trusted runtime, connect to a database, dispatch or wait for nested
Celery jobs, or drive the release browser.

Asset requirements are planned and materialized by the application before the
harness starts. If an essential unplanned asset is discovered, the harness
returns a typed rejection and lets the workflow decide whether to replan; it
does not suspend while an asset worker runs.

Workspace operations reject path traversal, Unicode path ambiguity, symlinks,
hard-link escapes, special files, executable bits, disallowed extensions, and
quota violations. The model receives opaque capabilities rather than host
paths.

### 8. Enforce run-wide and attempt-level budgets

Budget dimensions include turns, tool calls, tokens, estimated cost, wall time,
files and bytes changed, assets, output volume, and quick-check executions. A
versioned policy derives attempt limits from specification complexity, template
profile, mode, provider pricing, and the remaining run-wide ceiling. Every
dimension also has a platform hard maximum.

The controller checks budget, cancellation, deadline, and execution fence
before every model call and tool operation. Repeated identical calls, no-op
patches, unchanged findings, and turns without progress terminate early.

### 9. Keep repair strategy in the application

`RepairPolicy` classifies failures as `LOCAL_PATCH`, `STRUCTURAL_REPAIR`,
`REPLAN`, `REGENERATE`, or `STOP`. Minimal patches are preferred for local
defects, but structural failures are not forced through repeated small edits.
The model may provide a suggestion; it cannot select or schedule the strategy.

### 10. Keep release tests independent

The model may know public bridge examples and acceptance rubrics, but it does
not receive the complete release corpus. Browser validation includes hidden
black-box and metamorphic scenarios that correlate actual pointer, keyboard,
and touch effects with bridge and rendered state. This detects test-only bridge
implementations and overfitting.

## Consequences

### Positive

- There is one durable workflow owner and one small per-attempt controller.
- Worker redelivery cannot make stale output current.
- Provider and framework changes stay behind stable project contracts.
- Invalid candidates remain reproducible without becoming publishable.
- Quick model feedback and release evidence cannot be confused.
- Repair cost and failure modes are measurable by strategy.

### Costs

- Candidate submission and commit require an explicit two-step protocol.
- Fencing must be checked at every state-changing boundary, not only at task
  start.
- Provider calls can still incur duplicate cost after ambiguous network or
  worker failures.
- Versioned prompt, tool, template, and validator contracts require compatibility
  tests and retention discipline.
- Hidden validation scenarios add test-authoring and maintenance work.

## Rejected alternatives

- **Let the harness own the whole workflow:** duplicates PostgreSQL/Celery
  orchestration and makes recovery opaque.
- **Make every model turn a Celery task:** increases latency and persistence
  complexity without creating a useful business boundary.
- **Let the model run shell and browser tools:** expands the attack surface and
  makes resource use difficult to bound.
- **Treat staging output as a revision:** allows mutable or partially written
  content to enter validation and preview.
- **Use harness quick checks as release validation:** lets model-visible checks
  become the only quality gate.
- **Always request the smallest patch:** wastes repair budget on systemic plan or
  architecture failures.
- **Rely on a lease without fencing:** permits a slow, expired worker to overwrite
  the result of its replacement.

## Revisit triggers

Revisit this decision if model providers offer durable, application-scoped
idempotent execution; if evaluation proves that multiple independent candidates
outperform repair within the same cost and latency budget; or if generation
must support server-side builds that require a separately isolated build plane.
