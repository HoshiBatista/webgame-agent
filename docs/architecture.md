# Prompt2Play Target Architecture

## Status and scope

This document defines the target architecture for turning a natural-language
request into a validated, playable, revisioned HTML5 game. It is optimized for
four outcomes, in order:

1. high playable-delivery rate;
2. safe handling of generated code;
3. reproducible validation and repair; and
4. fast product iteration without an early microservice burden.

The target is not a promise to deploy every component on day one. The product
starts as a modular monolith and extracts only the execution boundary that must
be isolated for security. [ADR 0001](adr/0001-target-architecture.md) records the
system-level decisions, and
[ADR 0002](adr/0002-generation-harness.md) fixes the generation-harness
boundary. [The landscape review](research/landscape.md) explains the external
systems and research behind them. [The MVP capacity plan](capacity.md) derives
resource, quota, metric, and load-test requirements for 10 simultaneous active
generation runs. [ADR 0003](adr/0003-openai-luna-mvp.md) selects OpenAI GPT-6
Luna for the hackathon's first provider adapter.

## Architectural thesis

A good game generator is not primarily a code-completion system. It is a
revision system with an executable specification and a browser playtester.

Prompt2Play therefore follows these rules:

- **Explicit workflow, not an agent swarm.** Stages, inputs, budgets, retries,
  and terminal states are application-owned.
- **One harness invocation, one candidate.** The generation harness performs a
  single bounded attempt. The persisted workflow decides whether to validate,
  repair, regenerate, or stop.
- **Constrain before generating.** A versioned template supplies lifecycle,
  input, resize, audio, persistence, and test hooks. The model fills game-specific
  hooks rather than rebuilding infrastructure.
- **Test behavior, not source shape.** Every game exposes a deterministic test
  bridge and is also exercised through real pointer, touch, and keyboard input.
- **Immutable revisions.** Every generation and repair creates a new,
  content-addressed revision with provenance and evidence.
- **Generated code is hostile.** Generation, validation, and preview are separate
  trust zones with no ambient credentials.
- **Strong defaults, escape hatches later.** Canvas2D is the initial profile;
  locally bundled Phaser can be added for mechanics that justify it. Arbitrary
  frameworks and remote runtime dependencies are not accepted.

## System context

```text
                                      ┌─────────────────────────────┐
                                      │ Model and asset providers   │
                                      └──────────────▲──────────────┘
                                                     │ typed requests
                                                     │ and responses
┌──────────────┐  HTTPS/SSE   ┌──────────────────────┴──────────────┐
│ Creator web │◄─────────────►│ Control plane                       │
│ application │               │ API + DB-backed workflow state      │
└──────┬───────┘               └──────┬──────────┬──────────┬──────┘
       │ sandboxed iframe             │ metadata │ tasks    │ artifacts
       ▼                              ▼          ▼          ▼
┌──────────────┐              ┌────────────┐ ┌─────────┐ ┌──────────────┐
│ Preview      │              │ PostgreSQL │ │ Redis   │ │ Persistent   │
│ origin       │              │ + outbox   │ │ broker  │ │ filesystem   │
└──────────────┘              └────────────┘ └────┬────┘ └──────┬───────┘
                                                 │ Celery tasks │ read-only mount
                                                 └───────┬──────┘
                                                         ▼
                                                ┌──────────────────┐
                                                │ Execution plane  │
                                                │ Playwright in an │
                                                │ isolated sandbox │
                                                └──────────────────┘
```

The control plane may share a codebase and deployment at first. The execution
plane and preview origin must never share its privileges.

## Planes and trust boundaries

### Creator plane

The web application provides prompt entry, a stage timeline, source and file
inspection, validation findings, revision history, chat-based changes, and a
sandboxed preview. Use React, TypeScript, and Vite when this plane is
implemented; it needs a stateful editor experience but not a second server-side
application framework.

Server-to-client progress uses Server-Sent Events. Generation progress is
one-way, reconnectable, and ordered, so WebSockets add no value initially.
Commands such as cancel, repair, or revise remain ordinary authenticated HTTP
requests.

### Control plane

The Python control plane contains:

- a FastAPI HTTP boundary;
- application use cases and authorization;
- the explicit PostgreSQL-backed generation state machine;
- Celery task dispatch through Redis;
- Pydantic domain and transport contracts;
- a provider-independent model gateway;
- template and skill registries;
- revision, artifact, and validation metadata; and
- an event stream projected from persisted run state.

Use a project-owned `ModelGateway` port for structured outputs and usage data.
The first adapter uses the official OpenAI SDK and Responses API with
`gpt-6-luna`; application code does not import the provider SDK outside that
adapter. The workflow remains ours and no provider framework decides stage
order.

### Execution plane

The execution plane is the only component that opens generated HTML in a real
browser. It runs Playwright Chromium with:

- an ephemeral, non-persistent browser context per validation attempt;
- no cookies, credentials, extensions, downloads, granted permissions, or
  reused browser profile;
- service workers blocked;
- external requests aborted and recorded;
- desktop and mobile viewports;
- strict navigation, action, CPU, memory, output, and total-run limits; and
- a read-only artifact mount plus a separate evidence output directory.

Browser request interception is useful evidence, but it is not the security
boundary. The runner also needs network-namespace egress denial because browser
features such as WebRTC do not necessarily obey offline emulation. Production
runners use disposable OCI containers under gVisor or an equivalent
microVM-backed service, run as non-root, and receive no application secrets.

### Preview plane

Validated artifacts are served from a dedicated origin that has no control-plane
cookies. Private previews use short-lived, revision-scoped access; public games
are copied into a separate public-artifact namespace.

The editor embeds the preview with an iframe sandbox that grants scripts but
does not grant same-origin identity, top navigation, popups, forms, downloads,
or device permissions. The preview response sets a restrictive Content Security
Policy. Network access is denied by default.

Platform features such as saves, scores, or achievements use a versioned
`postMessage` capability bridge. The host validates the origin, revision,
message schema, rate, and capability grant. Generated code never receives a
platform token.

## Code organization

Keep the Python control plane as a modular monolith with dependency direction
toward the domain:

```text
src/prompt2play/
├── domain/                 # Pure entities, value objects, policies, findings
├── application/            # Use cases, workflow, ports, commands, queries
├── contracts/              # Versioned Pydantic API and artifact schemas
├── generation/             # Spec, planning, harness, templates, repair policy
├── validation/             # Static rules and validation-plan construction
├── adapters/
│   ├── models/             # Provider adapters (OpenAI first)
│   ├── persistence/        # PostgreSQL repositories
│   ├── artifacts/          # Content-addressed filesystem store
│   ├── tasks/              # Celery dispatch, routing, and task definitions
│   └── runners/            # Client for the isolated browser runner
├── api/                    # FastAPI routes, auth, SSE, transport mapping
└── workers/                # Celery worker and maintenance entry points

web/                        # React/TypeScript creator application
game_templates/             # Versioned trusted runtimes and skills
golden/                     # Prompts, rubrics, scenarios, expected thresholds
tests/                      # Unit, contract, integration, security, end-to-end
```

Domain and application modules do not import FastAPI, SQL clients, provider
SDKs, Playwright, or cloud SDKs. Ports make local-disk, fake-model, and in-process
test implementations possible without changing use cases.

Do not split the control plane into network services until independent scaling,
ownership, release cadence, or a trust boundary makes the cost worthwhile.

## Generation workflow

### State machine

```text
ACCEPTED
  └─► SPECIFYING
        └─► PLANNING
              └─► ASSET_PREPARING (optional)
                    └─► GENERATING
                    └─► COMMITTING
                          └─► STATIC_VALIDATION
                                └─► BROWSER_VALIDATION
                                      └─► VISUAL_REVIEW
                                            └─► PROMOTING ─► SUCCEEDED

Retryable validation failure
  └─► REPAIR_DECISION
        ├─► REPAIRING ─► COMMITTING ─► STATIC_VALIDATION
        ├─► REPLANNING ─► ASSET_PREPARING (optional) ─► GENERATING
        ├─► REGENERATING ─► COMMITTING
        └─► FAILED

Any active state ─► CANCELLED | FAILED | EXPIRED
```

State transitions are persisted and idempotent. Each stage has a deadline,
attempt policy, token and cost budget, structured input and output, and a stable
idempotency key. Infrastructure retries do not consume a semantic repair
attempt; a new model-produced patch does. A model turn or tool call is never a
Celery workflow stage. It belongs to one bounded `GenerationAttempt` and is
recorded as audit data only.

### Stage 1: intake

Validate identity, quota, prompt size, locale, requested capabilities, and
content policy. Create `Project`, `GenerationRun`, and an immutable initial
request. Return the run identifier immediately.

### Stage 2: specification

Transform the prompt into a `GameSpec` containing:

- player goal and core loop;
- game states and transitions;
- entities, mechanics, scoring, progression, and failure conditions;
- desktop and touch controls;
- visual and audio direction;
- viewport and performance constraints;
- requested platform capabilities;
- observable acceptance rubrics; and
- deterministic test scenarios.

The response is schema-constrained and validated. Missing product choices use
documented defaults rather than another free-form model turn.

### Stage 3: planning and template selection

Classify the game by mechanics before visual theme. Select a versioned template
profile and the smallest relevant set of skills. The initial profile is
`canvas2d-arcade-v1`; later profiles may include grid, cards, narrative, and
locally bundled Phaser.

Produce a `BuildPlan` that maps every acceptance rubric to a game hook and a
validation scenario. A requirement with no observable check is incomplete.

The plan also declares required assets before generation. The application
resolves curated assets or dispatches bounded asset jobs and commits their
immutable manifests in the optional `ASSET_PREPARING` substage. The generation
harness receives those assets read-only; it never waits synchronously for a
nested Celery task. If a previously unknown asset is essential, the attempt
returns a typed replan reason. Procedural or template-provided visuals remain
the default fallback.

### Stage 4: generation attempt

Instantiate the trusted template, then allow model tools only for:

- listing and reading the current workspace;
- reading an allowlisted skill or template reference;
- creating or patching normalized relative files;
- inspecting and selecting from the prepared asset manifest; and
- submitting metadata.

There is no general shell tool. Trusted packaging steps are selected by the
application, not written by the model. File count, individual size, total size,
path, MIME type, and extension are checked on every write.

The first attempt may create game-specific modules. Later attempts receive the
specification, a compact file manifest, relevant source fragments, and typed
findings; they return targeted patches rather than a complete replacement.

One invocation of `GenerationHarness` owns exactly one initial, repair, or
regeneration attempt and produces at most one `CandidateSubmission`. It neither
advances the global workflow nor creates a `Revision`. The harness is detailed
in [Generation harness](#generation-harness).

### Stage 5: candidate commit

An `ArtifactCommitter` closes the submitted staging workspace, canonicalizes
paths and file metadata, verifies template integrity and quotas, calculates the
bundle digest, and atomically promotes it to immutable storage. Because a POSIX
rename and a PostgreSQL transaction cannot be one atomic transaction, commit is
an explicit recoverable protocol: persist a fenced `PENDING` commit intent,
idempotently rename the digest directory, then finalize the `Artifact` and
immutable candidate `Revision` rows. A reconciler completes or rolls back stale
intents. An object written without a finalized database reference is harmless
and becomes eligible for grace-period garbage collection.

A harness crash before submission leaves only an expiring staging workspace; a
crash during commit is recoverable from the commit intent, revision metadata,
and digest.

Validation always consumes an immutable revision. Invalid revisions remain
auditable but are never previewable or publishable.

### Stage 6: release static validation

Reject the artifact before browser execution when any of these fail:

- manifest and schema validity;
- required entry point and template version;
- normalized paths and package limits;
- all local resource references resolve;
- no remote scripts, tracking, dynamic module import, or unapproved URLs;
- no obvious navigation, popup, download, permission, or storage violations;
- JavaScript parses and trusted template files retain their integrity; and
- the test bridge and required hooks are present.

Static analysis is a fast gate, not proof of safety or playability. The harness
may call the same rule library in `quick` mode for immediate model feedback.
Only the post-commit `release` mode writes authoritative findings or changes
revision status. Quick checks may omit expensive rules but may not use different
definitions for rules they share with release validation.

### Stage 7: browser validation

Run deterministic and black-box checks in this order:

1. boot without page errors, failed resources, or prohibited network attempts;
2. signal readiness within the deadline;
3. render non-empty, changing content at desktop and mobile viewports;
4. execute seeded bridge scenarios and verify state invariants;
5. repeat critical actions through actual keyboard, pointer, and touch input;
6. reach the required success or failure state and restart cleanly;
7. check resize, pause/resume, audio opt-in, and bounded frame timing; and
8. capture screenshots, console, network log, trace, and scenario results.

Bridge tests establish mechanics. Black-box tests catch broken wiring between
the bridge and the actual user surface. Both are required.

Do not expose the complete validation corpus to the model. Hidden black-box and
metamorphic scenarios vary legal action sequences and verify that observable
rendered state changes consistently with bridge state. This reduces the chance
of a generated game implementing a test-only bridge disconnected from its UI.

Every run records its scenario seeds and the immutable runner-image, Chromium,
Playwright, font-set, locale, timezone, device-scale, template, bridge, and
validator versions. Deterministic state assertions must reproduce exactly.
Screenshot and frame-timing checks use declared tolerances and are treated as
environment-sensitive evidence rather than bit-for-bit universal truth.

### Stage 8: visual and intent review

Deterministic heuristics check blank frames, overflow, clipped controls,
contrast, and layout at representative sizes. A vision-capable model may score
rubric evidence for visual usability and intent alignment, but its judgment is
advisory: it cannot waive a deterministic failure or security finding.

### Stage 9: repair decision

Normalize all failures to `Finding` values with code, severity, evidence,
location, rubric, repair hint, and retryability. The application-owned
`RepairPolicy` chooses the least expensive strategy that can plausibly address
the root cause:

- `LOCAL_PATCH` changes a small, bounded set of generated files;
- `STRUCTURAL_REPAIR` may reorganize several game-specific modules;
- `REPLAN` replaces an invalid build plan while retaining the specification;
- `REGENERATE` creates an independent candidate from the trusted template; or
- `STOP` records the failure as terminal.

The model may suggest a strategy but cannot select it or consume another
semantic attempt on its own. A minimum patch is preferred only for a genuinely
local finding; it is not a universal repair rule.

Default policy:

- at most two semantic repairs for an MVP run;
- no repair for policy violations that make the request ineligible;
- rerun static checks after every write;
- rerun affected scenarios first, then the full required suite; and
- stop when the same finding survives two targeted patches.

Each repair produces a child revision. Never mutate or hide the previous
artifact.

### Stage 10: promote; publish separately

After all mandatory gates pass, atomically point the project at the exact
validated revision and mark the generation run successful. Preview and
publication are separate actions outside the run and never rebuild or
recalculate the artifact. Publication copies only that digest through a
stage-verify-rename operation in the public-artifact namespace.

## Generation harness

### Boundary and ownership

`GenerationHarness` is a deterministic controller around a non-deterministic
model. It executes one bounded attempt and returns data to the application use
case. It does not import Celery, Redis, FastAPI, SQL, Playwright, provider SDKs,
or concrete filesystem paths. In particular, it does not retry workflow stages,
select the next repair strategy, create revisions, or publish artifacts.

```text
Celery task
  └─► generation use case       owns claim, lease, cancellation, persistence
        └─► GenerationHarness   owns one bounded model/tool loop
              └─► CandidateSubmission
        └─► ArtifactCommitter   owns canonicalization, digest, immutable revision
              └─► validators   own release findings and evidence
        └─► RepairPolicy        owns patch, replan, regenerate, or stop decision
```

The application passes ports into the harness for model calls, controlled draft
operations, quick static feedback, budget accounting, cancellation, and audit
events. An `EventSink` is diagnostic output, not workflow state; losing an
individual token or tool-progress event cannot change correctness.

### Attempt contract

A versioned `HarnessRequest` contains only explicit inputs:

- run, attempt, and current fenced-execution identifiers;
- mode: `INITIAL`, `LOCAL_REPAIR`, `STRUCTURAL_REPAIR`, or `REGENERATE`;
- immutable `GameSpec`, `BuildPlan`, and `TemplateSnapshot` references;
- parent revision and normalized findings when applicable;
- a versioned model and prompt policy;
- an attempt budget plus the remaining run-wide budget; and
- a newly allocated draft-workspace capability, not a host path.

The result status is `SUBMITTED`, `REJECTED`, `BUDGET_EXHAUSTED`, `CANCELLED`,
or `FAILED`. A submitted result contains a one-use `CandidateSubmission`
reference, normalized changed-file metadata, usage totals, audit references,
and a finish reason. It does not contain a final artifact digest or revision ID;
those exist only after `ArtifactCommitter` succeeds.

Every contract records `harness_protocol_version`, `tool_protocol_version`,
`prompt_profile_version`, and `model_policy_version`. Unsupported versions fail
closed rather than being interpreted approximately.

### Controlled loop

The harness is a small state machine, not a general autonomous agent:

```text
PREPARE_CONTEXT
  └─► MODEL_TURN
        ├─► VALIDATE_TOOL_CALL ─► EXECUTE_TOOL ─► ASSESS_PROGRESS ─┐
        │                                                         └─► MODEL_TURN
        ├─► QUICK_CHECK ─► MODEL_TURN
        ├─► SUBMIT ─► SUBMITTED
        └─► REJECTED | BUDGET_EXHAUSTED | CANCELLED | FAILED
```

Before every model call and tool operation, the controller checks cancellation,
the absolute attempt deadline, the execution fence, and all remaining budgets.
It detects repeated identical calls, no-op writes, repeated unchanged quick
findings, and turns without measurable progress. A model cannot extend a
budget, clear a finding, or declare the candidate validated.

Allowed model tools are intentionally narrow:

- `list_files` and bounded `read_file` for generated files;
- `read_skill` for an allowlisted, immutable skill snapshot;
- `create_game_file`, `patch_game_file`, and `delete_game_file` within the
  generated namespace;
- `inspect_manifest` without exposing host paths;
- `list_assets` and `read_asset_metadata` for immutable prepared assets;
- `run_quick_checks` using the shared static-rule library; and
- `submit_candidate` once.

There is no shell, process execution, arbitrary network access, package
installation, database access, direct browser control, absolute path access, or
write access to the trusted runtime. Tool results are bounded structured data.

### Context and trust

`ContextCompiler` preserves trust levels instead of concatenating everything
into an undifferentiated prompt:

| Input | Trust | Treatment |
| --- | --- | --- |
| System, safety, and tool policy | Trusted | Fixed instructions |
| Template and bridge contract | Trusted | Immutable versioned instructions |
| `GameSpec` and `BuildPlan` | Validated data | Structured data, never executable instructions |
| Findings and evidence summaries | Validated data | Schema checked and size bounded |
| User request | Untrusted | Delimited content |
| Generated source and asset metadata | Untrusted | Delimited content, lazily loaded |

The stable contract, acceptance rubrics, unresolved findings, and remaining
budget are present on every model turn. Source files and skills are loaded only
when relevant. Old tool output may be summarized, but required rubrics and
security rules are never silently truncated. Token estimation occurs before
dispatch; an input that cannot fit fails explicitly or uses a documented
compaction policy.

### Draft workspace

`DraftWorkspace` is a capability-scoped virtual view over one staging
directory. The model never receives its path. Operations normalize Unicode and
relative paths before access, reject traversal, symlinks, hard-link escapes,
devices, sockets, executable bits, disallowed extensions, and writes outside
the generated namespace. Trusted runtime files are mounted or copied read-only
and verified by digest at submission.

Limits apply per operation and cumulatively to bytes read and written, file
count, diff size, asset count, and output volume. File access uses APIs that do
not follow links and avoids check-then-open races. Submission closes the
workspace to further writes and creates a one-use capability for the committer.
Abandoned workspaces retain a lease and are deleted after a grace period.

### Budgets and model calls

Budgets are multi-dimensional: model turns, tool calls, input and output
tokens, estimated cost, wall time, files changed, bytes written, assets, and
quick-check executions. A versioned policy derives attempt limits from template
profile, specification complexity, repair mode, provider pricing, and the
remaining run-wide ceiling. Every dimension also has a hard platform maximum.

Each provider request reserves a `ModelInvocation` before network dispatch. It
has a stable request fingerprint, execution fence, absolute deadline, status,
provider request ID when available, usage, and response reference. A completed
identical invocation can be replayed after worker failure. An in-flight call
cannot always be deduplicated at the provider, so stale executions may still
incur cost, but fencing prevents their output from being submitted. Such cost is
measured separately as duplicate or abandoned spend.

Cancellation is cooperative but deadline-bound. It prevents every new model or
tool operation and attempts to cancel streaming provider calls. Provider
timeouts must be substantially shorter than the Celery hard limit; revoking the
Celery task is never the correctness mechanism.

## Game artifact contract

```text
revision/
├── index.html
├── manifest.json
├── src/                    # Generated game-specific modules
├── runtime/                # Trusted, versioned template runtime
└── assets/                 # Local, licensed or generated assets
```

The manifest includes schema version, entry point, template profile and digest,
game metadata, controls, viewport policy, capabilities, file digests, asset
license references, and the test-bridge version. Safe build provenance pins the
template, bridge, tool protocol, and packaging versions. Full provenance is a
private immutable sidecar that additionally records the harness, prompts, model
policy, skill snapshot, provider invocations, parent revision, and validator
suite. Validation summaries and evidence are also private sidecars because they
are created after the bundle digest is fixed.

Packaging may inline the bundle into one HTML file for export, but the editable
source revision remains structured. An export is a separate content-addressed
artifact linked to the source revision; publication never silently substitutes
an export digest for the digest that passed validation.

No artifact references a runtime CDN. Third-party runtime files are vendored,
versioned, license-recorded, and integrity-checked by the template registry.
The registry maintains an explicit compatibility matrix for template, bridge,
tool, manifest, and validator versions. Existing revisions are not migrated in
place. An upgrade that changes bytes creates a child revision and passes the
current release gates again.

## Executable game contract

The trusted runtime exposes `window.__prompt2play` version 1:

```typescript
interface Prompt2PlayBridgeV1 {
  schemaVersion: "1";
  ready(): Promise<void>;
  reset(seed: number): Promise<GameSnapshot>;
  dispatch(action: GameAction): Promise<GameSnapshot>;
  snapshot(): GameSnapshot;
  capabilities(): readonly string[];
}
```

`GameSnapshot` is JSON-serializable and contains only stable, player-observable
state: phase, score, lives or health, level or wave, key entity positions, and
declared objective progress. It must not expose DOM nodes, functions, clocks, or
random generator internals.

The template owns the bridge plumbing and seeded clock/random adapters. The
generated implementation supplies typed hooks. Public games may retain the
bridge because it grants no host capability; the platform bridge for saves and
scores is a separate protocol.

## Persistence model

PostgreSQL is the source of truth for metadata:

- `Project` — owner, title, visibility, current revision;
- `Revision` — immutable parent link, spec, plan, artifact digest, status;
- `GenerationRun` — request, budgets, current workflow state, terminal outcome;
- `StageRun` — attempt, idempotency key, timing, input/output references;
- `GenerationAttempt` — mode, parent, budget, execution fence, submission and
  terminal outcome;
- `ArtifactCommit` — fenced staging-to-digest intent and recovery status;
- `AssetJob` — planned asset request, invocation, license, digest, and outcome;
- `TaskExecution` — Celery task ID, queue, lease, delivery and retry metadata;
- `OutboxEvent` — transactionally committed task or domain-event publication;
- `ModelInvocation` — request fingerprint, execution fence, provider request,
  status, usage, cost, latency, and response reference;
- `ValidationRun` — environment, suite version, status, evidence prefix;
- `Finding` — stable code, severity, rubric, evidence, resolution revision;
- `Artifact` — digest, size, MIME manifest, storage location, retention; and
- `Publication` — public slug, revision, moderation and lifecycle state.

Large files, bundles, traces, screenshots, and logs live below a configured
persistent filesystem root. Paths are digest-based and immutable. Database rows
reference artifact IDs and normalized relative paths; they do not contain game
bundles or expose host paths.

The application accesses files only through an `ArtifactStore` port. Its first
and target implementation is a content-addressed POSIX filesystem store:

```text
<artifact-root>/
├── objects/sha256/ab/cd/<digest>/
│   ├── index.html
│   ├── manifest.json
│   ├── src/
│   ├── runtime/
│   └── assets/
├── private/<revision-id>/
│   ├── provenance.json
│   └── validation/<validation-id>/
├── public/sha256/ab/cd/<digest>/
├── staging/<write-id>/
└── quarantine/<artifact-id>/
```

Writers build a complete candidate under a lease-owned `staging` directory. A
one-use submission closes it to writes. The committer validates paths and
digests, flushes the manifest, records the commit intent, and atomically renames
the candidate into `objects` on the same filesystem. The rename and database
finalization are independently idempotent and reconciled after crashes.
Existing digest directories are never overwritten. Symlinks, hard-link escapes,
devices, sockets, executable bits, absolute paths, traversal, and normalized or
case-folded path collisions are rejected.

The API and packaging workers receive read/write access only where required.
Validation runners and the preview server mount completed objects read-only.
The preview and public servers cannot read `private`, `staging`, or
`quarantine`; publication copies the exact validated runtime object into the
dedicated `public` namespace without its private sidecars.
Filesystem quotas cover bytes, files, and inodes per project and globally. A
Celery retention task deletes an immutable object only when PostgreSQL has no
live reference and its grace period has elapsed. A separate sweep removes
expired, unsubmitted staging workspaces only after their lease and grace period
expire. The persistent volume has automated snapshots, off-host backups, and a
tested restore procedure.

The initial deployment keeps API and workers on one host with the artifact
volume attached. If workers later span hosts, use a shared POSIX filesystem and
retain the same `ArtifactStore` contract. Do not use Redis or PostgreSQL for
binary artifact payloads.

Celery is the task execution layer and Redis is its broker. PostgreSQL remains
the workflow source of truth: every stage claims an expected state, records its
result, and advances the run in one transaction. The transaction also writes an
`OutboxEvent`; a dispatcher publishes the next Celery task and marks the event
sent. Duplicate publication is safe because stage tasks are idempotent and use
the run ID, stage, attempt, and expected state as their execution key.

Every claim receives a monotonically increasing execution fence. Leases enable
recovery but do not grant correctness by themselves: artifact submission,
model-response acceptance, stage completion, and every other externally
visible side effect compare the current fence. A task whose lease expired may
finish local work, but it cannot commit stale output after a replacement has
claimed the stage.

Tasks carry identifiers and small commands only. Prompts, source bundles,
screenshots, traces, and model responses stay in PostgreSQL or the artifact
filesystem,
not Redis messages or Celery results.

Redis may provide a short-lived Celery result backend for operational status,
plus cache and rate-limit data, but no product state depends on those keys.
Cancellation is a durable flag in PostgreSQL that tasks check cooperatively;
Celery revoke is only a best-effort optimization. A single Celery Beat instance
drives outbox recovery, stale-stage reconciliation, retention, and health tasks.

Use separate queues and worker pools:

- `workflow` for lightweight state transitions and dispatch;
- `models` for provider calls;
- `assets` for image or audio jobs;
- `validation` for isolated browser runs; and
- `maintenance` for outbox, recovery, and retention work.

Canvas chains and groups are allowed for small, bounded fan-out, but a Celery
result graph is never the canonical workflow. Dynamic repair decisions always
return through the persisted state machine.

Baseline Celery policy:

| Setting or rule | Baseline |
| --- | --- |
| Task and result serialization | JSON only; never accept pickle |
| Long-task acknowledgement | `acks_late` with idempotent side effects |
| Worker loss | Reject and redeliver after the visibility lease |
| Long-task prefetch | One task per available worker process |
| Task duration | Per-queue soft and hard limits |
| Redis visibility timeout | Greater than the largest hard task limit |
| Result retention | Short TTL; results are operational, not canonical |
| Broker payload | IDs, stage, attempt, expected state, trace context |
| Concurrent redelivery | Lease plus monotonic execution fence on every commit |
| Scheduled recovery | One Celery Beat scheduler plus idempotent jobs |

## MVP capacity baseline

The initial capacity envelope is 10 active generation runs, including a burst
of 10 admissions in one second. This means active end-to-end workflows, not 10
idle browser sessions. At the 180-second mean-latency objective, a closed group
of 10 users can drive 3.33 completed runs per minute.

The derived baseline is:

- 20 run-admission write RPS and 50 mixed dynamic API RPS;
- 10 SSE connections carrying no more than 50 persisted progress events/s;
- 10 model-worker slots backed by provider quota of at least 45 RPM, 400k input
  TPM, 60k output TPM, and 12 simultaneous provider requests;
- five isolated browser-validation slots;
- an application-wide PostgreSQL budget of 40 connections and capacity for 50
  short write transactions/s; and
- 150 static preview RPS plus 20 MiB/s artifact delivery outside FastAPI.

These are calculated hypotheses, not proof of capacity. Admission closes before
model, browser, storage, or provider queues exceed their bounded thresholds.
Workers release database connections before external waits. The complete
assumptions, formulas, harness budgets, required metrics, alert thresholds, and
release-gate load tests are defined in [the MVP capacity plan](capacity.md).

## API surface

Initial versioned endpoints:

```text
POST   /v1/projects
GET    /v1/projects/{project_id}
POST   /v1/projects/{project_id}/runs
GET    /v1/runs/{run_id}
GET    /v1/runs/{run_id}/events       # SSE, resumable with event ID
POST   /v1/runs/{run_id}/cancel
POST   /v1/revisions/{revision_id}/revise
GET    /v1/revisions/{revision_id}
POST   /v1/revisions/{revision_id}/preview-token
POST   /v1/revisions/{revision_id}/publish
```

Mutating requests accept an idempotency key. External identifiers are opaque.
API responses expose artifact and evidence references, never internal paths,
provider secrets, raw workflow payloads, or sandbox coordinates.

## Reliability and backpressure

- API admission enforces per-user concurrency, token, storage, and cost quotas.
- Provider calls have timeouts, cancellation, retry classification, and circuit
  breakers. A fallback model is allowed only when its capabilities satisfy the
  stage contract and provenance records the change.
- Each model call is reserved before dispatch with a request fingerprint and
  execution fence. Reuse completed identical responses where policy permits;
  measure provider calls abandoned by a stale worker as duplicate spend.
- Celery tasks are idempotent; artifact writes use digest keys and conditional
  creation. Workers acknowledge long tasks after completion and may therefore
  execute a task more than once after failure.
- Work queues are separated by trust and resource profile: orchestration, model,
  assets, and browser validation.
- Long-running worker pools use a prefetch multiplier of one, explicit soft and
  hard time limits, and a Redis visibility timeout comfortably above the hard
  limit. Task and result serializers accept JSON only.
- Redis uses a dedicated database or instance, TLS and authentication in
  production, `noeviction`, AOF persistence, replication or managed failover,
  and broker-specific key prefixes. Large payloads never enter the broker.
- A recovery sweep republishes unsent outbox events and safely reclaims expired
  stage leases. Any replacement claim increments the execution fence. Celery
  Beat runs as a singleton to avoid duplicate schedules.
- Long stages renew their lease with the current fence. Loss of database
  connectivity stops new model calls and commits; it never causes a worker to
  assume that its old lease is still authoritative.
- Validation capacity controls generation admission so completed code does not
  accumulate indefinitely while waiting for scarce browsers.
- Every terminal failure returns structured findings and the last safe revision.

## Observability and evaluation

Instrument API, workflow, model, artifact, and validation operations with
OpenTelemetry. A trace follows one run across every plane. Record:

- stage and end-to-end latency;
- success and failure by stable finding code;
- first-pass and post-repair playable rate;
- repair yield and repeated-finding rate;
- token use and estimated cost by stage, model, and template;
- browser queue time and sandbox resource use; and
- quality score by golden prompt and rubric.

The capacity plan defines the required harness, provider-quota, queue,
duplicate-spend, fencing, sandbox-resource, database, and filesystem metrics.
Run, user, project, prompt, and file identifiers belong in traces or structured
logs, never metric labels.

Do not attach full prompts, generated source, screenshots, or model responses to
telemetry by default. Store sensitive evidence under the project's retention
and access policy.

The golden suite is a product asset, not just a test folder. Each case contains
a prompt, normalized specification, rubrics, bridge scenarios, black-box
actions, viewport matrix, and pass threshold. Start with:

- tap-to-jump runner;
- grid puzzle;
- space shooter;
- card or turn-based game; and
- touch-first drag-and-drop game.

Run the suite against every template, prompt, model, validator, and repair-policy
change. Compare distributions and cost, not a single showcase game.

## Security invariants

These are architectural requirements, not optional hardening:

1. Generated code never runs in the API or workflow process.
2. A sandbox receives no provider, database, or platform secret and only a
   read-only mount of the selected artifact.
3. Network denial is enforced outside the browser process.
4. Preview content has a separate origin and no application cookies.
5. Model tools cannot execute arbitrary shell commands or escape the workspace.
6. Artifact paths are normalized relative paths and symlink escapes are rejected.
7. Template runtime files are digest-verified before and after generation.
8. Every artifact and asset has provenance, size limits, and a retention policy.
9. Vision or language-model judgments never override deterministic security
   failures.
10. Publishing requires the exact validated artifact digest; it never rebuilds
    from mutable source.
11. Every state-changing worker operation presents the current execution fence;
    an expired worker cannot commit output.
12. Untrusted prompt, source, findings, and asset metadata remain delimited data
    and are never promoted into trusted model instructions.

## Evolution plan

### Phase 0 — deterministic vertical slice

- Domain contracts and fake model gateway.
- Versioned harness request/result, draft-workspace, and candidate-submission
  contracts with an in-process fake model.
- One trusted Canvas2D template and one fixture game.
- Local artifact store.
- Static checks and Playwright validation on the developer machine.
- Golden test for one runner game.

Exit criterion: the same fixture reproducibly passes specification-to-evidence
without network or model credentials.

### Phase 1 — usable single-node product

- FastAPI, PostgreSQL, Redis, Celery workers, and the React creator UI.
- Transactional outbox, fenced idempotent stage claims, and deadline-bound
  cooperative cancellation.
- Real provider through `ModelGateway`.
- Two-repair workflow, SSE progress, revision history.
- Separate local validation worker and dedicated preview origin.
- Five golden prompts across desktop and mobile.
- Production-like load tests for 10 active runs, provider quotas, five browser
  slots, cancellation, redelivery, and storage recovery.

Exit criterion: at least 80% of the fixed golden suite is playable after bounded
repair, every failure is explained by structured findings, and the capacity
release gates pass without exceeding budgets or SLOs.

### Phase 2 — production trust boundary

- Backed-up persistent artifact volume with enforced quotas and retention.
- Managed or replicated Redis with AOF, no eviction, and queue-specific worker
  pools and limits.
- Outbox recovery, stale-stage reconciliation, load-based admission, and
  independent scaling for model and validation workers.
- Recovery and fault-injection tests for pending artifact commits, expired draft
  workspaces, stale execution fences, and duplicate provider calls.
- gVisor or microVM-backed ephemeral validation runners with egress denial.
- Authentication, quotas, moderation, retention, and OpenTelemetry.
- Signed private previews and explicit publication flow.

Exit criterion: process restarts do not lose runs, no sandbox has platform
credentials, and load tests demonstrate backpressure rather than overload.

### Phase 3 — quality flywheel

- Versioned skill and debug-knowledge registry.
- Canvas, grid, cards, narrative, and Phaser template profiles.
- Vision review, human feedback, A/B model and prompt evaluation.
- Optional generated image and audio assets with license provenance.
- Curated remixing and capability-based saves, scores, and leaderboards.

Exit criterion: changes ship only when golden-suite playable rate, quality, cost,
and latency remain within declared budgets.

## Deliberately deferred

- 3D and world-model generation;
- multiplayer and arbitrary game networking;
- a general-purpose IDE or shell agent;
- user-supplied packages or runtime CDN dependencies;
- autonomous multi-agent swarms;
- Kubernetes before the execution-plane or scale requirement exists; and
- model fine-tuning before evaluation data demonstrates a repeatable gap.

These can become product directions later. None is required to prove the core
prompt-to-playable loop.
