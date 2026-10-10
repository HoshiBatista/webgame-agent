# ADR 0001: Target Architecture for Prompt2Play

- **Status:** Accepted
- **Date:** 2026-10-10
- **Decision owners:** Prompt2Play maintainers

## Context

Prompt2Play must generate code, run it, decide whether it is playable, repair it,
and expose it to users. Generated browser code is untrusted, model calls are
slow and fallible, and visual output can appear correct while mechanics are
broken. The architecture must support an early demo without making production
security and durability a rewrite.

The landscape review found repeatable evidence for template constraints,
browser playtesting, executable game contracts, and bounded revision loops. It
did not find evidence that an unconstrained multi-agent swarm improves this
product enough to justify opaque state and operational complexity.

[ADR 0002](0002-generation-harness.md) refines this decision with the
single-attempt harness contract, candidate commit boundary, and execution
fencing rules.

## Decision

### 1. Use a modular monolith for the control plane

Domain, application, contracts, generation, validation, and adapters live in
one Python package with dependency direction toward the domain. FastAPI is the
eventual HTTP adapter. Separate services are introduced only for trust or
scaling boundaries.

### 2. Separate the execution and preview planes

Generated code never executes in the control-plane process. Playwright runs in
ephemeral gVisor or equivalent sandboxes with infrastructure-level egress
denial. User previews are served from a dedicated origin and embedded with a
restrictive iframe sandbox and CSP.

### 3. Use Celery and Redis behind a persisted state machine

The stage graph is specification, plan and template selection, generation,
candidate commit, static validation, browser validation, visual review, repair
decision, and promotion. Celery executes stage tasks and Redis is the broker.
PostgreSQL owns
the canonical run state, attempts, cancellation flag, stage leases, and a
transactional outbox. At-least-once task delivery is handled through idempotent
stage keys, atomic expected-state transitions, and monotonic execution fences.

Celery Canvas may express bounded fan-out, but its result graph is not workflow
truth. Redis results are short-lived operational data. Tests call task use cases
directly or use Celery eager mode without changing the state machine.

One harness invocation creates at most one candidate. Model turns and tool
calls remain inside that attempt and never become an independent workflow.

### 4. Generate through versioned template hooks

The default runtime is a trusted Canvas2D template. The model implements
game-specific hooks and cannot replace lifecycle, resize, input normalization,
seeded time and random support, or test-bridge plumbing. Additional template
profiles are admitted through golden-suite evaluation.

### 5. Make tests part of the specification

Every `GameSpec` contains rubrics and deterministic scenarios. Every game
implements the versioned `window.__prompt2play` bridge supplied by its template.
Validation combines static checks, bridge scenarios, black-box browser input,
and visual review.

### 6. Store immutable revisions on a persistent filesystem

PostgreSQL stores metadata and lineage. A dedicated persistent volume contains
source bundles and evidence in content-addressed directories. Writes complete
in a staging directory and become visible through an atomic rename. Repairs
create child revisions. Preview and publication refer to an exact validated
digest through a project-owned `ArtifactStore` interface.

### 7. Put model infrastructure behind a project port

Application code calls `ModelGateway` with typed requests and response models.
PydanticAI is the preferred adapter for provider portability and structured
outputs. Provider SDKs and model identifiers do not leak into domain code.

### 8. Keep validation deterministic where possible

Deterministic security, boot, state, interaction, and layout checks are release
gates. Vision-model scoring is advisory for visual usability and intent; it
cannot override deterministic failures.

## Decision matrix

| Concern | Selected | Rejected for the core |
| --- | --- | --- |
| Control plane | Modular monolith | Premature microservices |
| Orchestration | PostgreSQL state machine + Celery | Temporal, result graph as truth, autonomous swarm |
| Task broker | Dedicated Redis with AOF and no eviction | Database polling as the only queue |
| Model layer | Project port with PydanticAI adapter | Provider SDKs throughout the codebase |
| Game generation | Versioned template hooks | Unconstrained one-shot source generation |
| Default runtime | Canvas2D; local assets | Remote CDN framework dependencies |
| Complex 2D runtime | Evaluated, locally bundled Phaser profile | Mandatory framework for every game |
| Validation | Static + bridge + black-box + visual | Build success or screenshot alone |
| Metadata | PostgreSQL | Filesystem or Redis as source of truth |
| Bundles/evidence | Content-addressed persistent filesystem | Redis or database blobs |
| Progress transport | Reconnectable SSE | WebSocket before bidirectional need |
| Browser execution | Playwright in isolated runner | Browser in API process |
| Preview | Dedicated origin and capability bridge | Same-origin iframe with platform access |

## Consequences

### Positive

- API and worker processes share one typed application core while scaling
  independently by queue.
- Domain and application tests do not require providers, browsers, or cloud
  services.
- Generated-game reliability improves through structural constraints and
  observable behavior.
- Failed repairs and model changes remain auditable through revision lineage.
- PostgreSQL state and the transactional outbox make retries, cancellation, and
  recovery explicit and auditable.

### Costs

- Template and bridge design require upfront engineering.
- Celery workers, Redis, PostgreSQL, persistent-volume backups, and sandbox
  capacity add production operations.
- Supporting multiple templates requires compatibility and golden-suite gates.
- Strict isolation rules exclude some easy but unsafe external integrations.

### Risks and mitigations

- **Templates limit creativity:** add evaluated profiles and explicit escape
  hatches instead of removing the contract.
- **The bridge can pass while the UI is broken:** repeat critical scenarios
  through real browser input.
- **Vision judges are inconsistent:** keep them advisory and calibrate against
  human review.
- **At-least-once delivery creates duplicate work:** make each stage claim an
  expected state, idempotency key, and monotonic execution fence; compare the
  fence again before every externally visible commit.
- **Redis loss can drop queued messages:** enable AOF and failover, publish
  through a PostgreSQL outbox, and run a recovery sweep.
- **Long tasks can be redelivered early:** keep hard limits below the configured
  visibility timeout and use late acknowledgements with a prefetch of one.
- **A local volume is a host-level failure domain:** take off-host snapshots,
  test restoration, monitor bytes and inodes, and use a shared POSIX volume only
  when workers need to span hosts.
- **Sandboxing creates false confidence:** combine browser, container, kernel,
  network, origin, credential, and resource boundaries.

## Revisit triggers

Revisit this ADR when one of these becomes true:

- 3D games become a committed product requirement;
- arbitrary user dependencies or server-side generated code are allowed;
- multiplayer networking becomes part of the default contract;
- browser validation dominates cost enough to require a different execution
  strategy; or
- golden-suite evidence shows free-form generation outperforming hook-driven
  templates without reducing safety or reproducibility.
