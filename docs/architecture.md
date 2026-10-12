# Prompt2Play Architecture

## Status and decision precedence

This is the accepted combined design as of 2026-10-11, recorded in
[ADR 0003](adr/0003-hybrid-adoption.md). It combines reusable Game Forge 1.3.0
components with Prompt2Play's bounded generation, immutable candidates, and
mandatory browser validation. The implementation sequence and transfer inventory
are in the [development plan](development-plan.md).

**The combined implementation is present in this branch.** Django coordination,
the React studio, bounded authoring, the shared runtime, immutable storage and
independent isolated validation work without the neighboring donor directory.
The [implementation report](implementation-report.md) separates fresh test and
live-call evidence from historical results. Contest WebView acceptance remains
pending because the host is unknown.

ADR 0003 supersedes the stack selection in ADR 0001 and amends the deployment
assumptions in ADR 0002. ADR 0002's single-attempt boundary remains applicable.
The landscape review is historical research, not the current implementation plan.

The **2026-10-12 implemented opt-in extension** is
[ADR 0004](adr/0004-adaptive-generation-control.md), delivered through the
[R0–R7 migration plan](pipeline-improvement-plan.md). Its supervisor, protected
acceptance contracts, image review and modular-source format are implemented for
selected jobs. The existing baseline remains operational while R7 is evaluated;
the [pipeline review](evidence/pipeline-review-2026-10-12.json) preserves the
original three defect reproductions. Regression tests now cover their fixes.

## Product scope

Input is a natural-language description of a game or a requested revision.
Output is a complete offline HTML5 game with controls, a meaningful playable
loop, an appropriate outcome, and restart behavior. A self-contained `index.html`
is the delivery format. `runtime-v1` preserves `game.js` and optional `style.css`.
`runtime-modules-v2` accepts planned local JS/CSS/JSON/SVG/base64 PNG modules and
assets, then uses pinned esbuild in an unprivileged, networkless container to
create one offline HTML. Source modules are retained for later edits.

Support different mechanics through Canvas, DOM/SVG, or hybrid presentation.
Do not reduce generation to selecting a prewritten game by genre. At the same
time, do not promise arbitrary complexity: genre coverage is established by
fresh measured generations. The initial supported envelope is offline browser
2D and DOM games; 3D, multiplayer, arbitrary packages, and remote runtime
services remain deferred. WebView compatibility is a separate acceptance target
that requires testing in an identified host and device.

## Selected stack and boundaries

| Concern | Decision | Reason |
| --- | --- | --- |
| Creator application | Adopt React/TypeScript/Vite studio | Reuse projects, revisions, source inspection, findings, and preview UI |
| HTTP and persistence adapters | Adopt Django/DRF with PostgreSQL | Reuse API, auth, migrations, leases, and concurrency handling |
| Workflow | Application-owned persisted state machine; HTTP polling workers | Extend the existing durable queue without introducing a second scheduler |
| Generation | Project-owned `GenerationHarness` and `ModelGateway` | Separate one candidate attempt from workflow and provider details |
| Model access | Adapt local Codex CLI and Responses API providers | Retain the team's worker topology and provider portability |
| LangGraph | Optional bounded attempt implementation | Reuse author fan-out only if it helps; never own the repair loop twice |
| Game infrastructure | Small versioned trusted runtime with optional capabilities | Reuse lifecycle/input primitives while leaving mechanics generated |
| Validation | Static rules plus mandatory isolated Playwright | Establish observable behavior before declaring success |
| Artifacts | Content-addressed persistent filesystem | Keep candidates, lineage, and evidence reproducible |
| Preview | Dedicated origin, sandboxed iframe, restrictive CSP | Keep generated code outside studio identity and privileges |
| Progress | Persisted events with cursor-based polling initially | Reuse the existing UI; SSE is optional later |

FastAPI, Celery/Redis, PydanticAI, and a new agent framework are not prerequisites.
A provider adapter may adopt PydanticAI after a concrete capability or maintenance
benefit is demonstrated. Adding a broker later requires a transactional outbox,
idempotent delivery, and an ADR; the broker must not become workflow truth.

The first installation serves one trusted authoring team, as the donor does.
Generated code remains untrusted. Public multi-tenant authoring requires project
ownership enforcement, quotas, abuse controls, and stronger deployment isolation
before it is enabled; team-wide access must not be advertised as tenant isolation.

```text
React studio ── authenticated HTTP + event polling ── Django/DRF
    │                                                │
    │ sandboxed iframe                               ├─ PostgreSQL: workflow/metadata
    ▼                                                └─ ArtifactStore: files/evidence
Separate preview origin                                       ▲
(validated artifacts only)                                     │ HTTP submission
                                                   Local generation workers
                                                   Codex CLI / API adapter
                                                              │
                                          Application dispatches validation
                                                              ▼
                                           Isolated Playwright execution
                                           read-only input, no network/secrets
```

## Code ownership

The implemented layout uses Python `src` and uv. Runtime and evaluation resources
are inside the package so installed distributions remain self-contained:

```text
src/prompt2play/
├── application/            # Eligibility, bounded repair and workflow policy
├── contracts/              # Versioned game, attempt, API, artifact schemas
├── generation/             # Planning, context selection, bounded harness
├── validation/             # Container client, real input, evidence verification
├── adapters/
│   ├── django/             # Models, DRF routes, auth, repositories, queue claims
│   ├── artifacts/          # Filesystem store and candidate commit
├── legacy/                 # Namespaced adopted providers, baseline and validator
├── resources/
│   ├── runtime/            # Trusted core and immutable prior runtime versions
│   ├── knowledge/          # Applicable lessons with regression references
│   ├── evaluation/         # Versioned prompts and independent input recipes
│   └── legacy/             # Selected prompts and historical regression corpus
├── workers/                # Generator and validator roles; durable HTTP journal
├── evaluation.py           # Bounded live comparison and immutable evidence
├── operations.py           # Consistent backup and verified empty-target restore
└── cli.py                  # Setup, studio/preview, workers and operations
web/                        # Adopted React studio
```

Domain and application code depend on ports, not Django ORM, provider SDKs,
LangGraph, Playwright, or physical storage paths. Donor modules may temporarily
retain their internal layout during a tested import; extract boundaries as each
slice is made operational. Do not create a simultaneous framework migration.

## Contracts and reusable game infrastructure

### GameSpec and BuildPlan

Adapt the donor's semantic contract, scenario language, and dependency mapping.
Separate two versioned contracts:

- `GameSpec`: player goal, mechanics, states, legal actions, outcomes, observable
  requirements, input expectations, visual/audio direction, and acceptance rubric.
- `BuildPlan`: runtime capabilities, presentation, generated modules, ownership
  and dependency graph, implementation schemas, prepared assets, and scenarios
  covering the specification.

The planner may initially return both in one schema-constrained response. Their
identities remain separate: replanning changes implementation choices while
preserving user requirements. Changing requirements requires an explicit revised
specification. Validate schema structure, references, ownership, and scenario
coverage before authoring.

Retain lessons about authoritative state, transaction idempotency, legal optional
actions, hidden information, event delivery, persistence, and asynchronous work.
Make them conditional: a puzzle without saves does not need storage migration,
and a turn-based game must not invent real-time ticks or a mandatory wait action.

### Trusted runtime and generated hooks

The runtime supplies stable infrastructure, not prewritten genre mechanics:

| Trusted responsibility | Generated responsibility |
| --- | --- |
| Mount/dispose, resource ownership helpers, pause/resume | Game rules, transitions, objectives, progression |
| Keyboard/pointer/touch normalization and resize | Mapping inputs to actions and composing the game UI |
| Seeded randomness and optional fixed-step clock | Simulation and action semantics |
| Audio activation, preferences, resource cleanup | Music, sound design, and event-to-sound mapping |
| Optional storage transport and error reporting | Save schema, validation, migration, and conflict semantics |
| Test-bridge plumbing to the active game session | Observable snapshots and declared legal actions |

Capabilities are selected by mechanics: real-time Canvas, turn-based DOM, and
hybrid games can share the core without sharing a simulation loop. Persistence,
audio, and fixed-step timing are optional. A game with no requested sound must
not fail merely because it creates no audio sources.

Pin runtime and capability versions/digests in the plan. Generated writes cannot
change trusted files. Runtime upgrades create new child revisions and require
validation; existing games are never silently rewritten. Curated libraries or
future asset adapters must be local, versioned, licensed, and integrity-checked.
Procedural visuals and Web Audio remain the initial defaults.

### Test bridge

The trusted runtime exposes versioned `window.__prompt2play` operations for
readiness, seeded reset, action dispatch, observable snapshot, and capability
inspection. Optional clock and persistence operations exist only when declared.
Bridge actions operate on the actual UI-owned session through the normal action
path. There is no test-only second engine or arbitrary state injection.

Snapshots are bounded JSON of stable observable state, not DOM nodes, functions,
wall clocks, or privileged opponent information. Hidden-information tests may
use separately controlled evidence without exposing private data to bots or UI.

An adapter can support donor `__GAME_TEST__` fixtures during migration. Record its
version and limitations; interface compatibility is not evidence that UI wiring
or browser behavior passed. Retain old fixtures without rewriting their history.

## Workflow: one owner, one candidate per attempt

PostgreSQL is the canonical owner of run state, attempts, budgets, cancellation,
and promotion. Workers claim bounded operations via HTTP. The application state
machine, rather than a worker's local graph, decides the next stage:

```text
ACCEPTED → SPECIFYING → PLANNING → GENERATING → COMMITTING
    → STATIC_VALIDATION → BROWSER_VALIDATION → PROMOTING → SUCCEEDED

Generation rejection or retryable validation failure → REPAIR_DECISION
    → LOCAL_REPAIR | STRUCTURAL_REPAIR | REPLAN | REGENERATE | STOP

Any active state → CANCELLED | FAILED | EXPIRED
```

Optional model source/vision review provides findings between validation and the
repair decision. It cannot turn a failed or unverified check into a pass.
Unavailable validation infrastructure is an operational retry or explicit failure,
not a reason to spend a semantic repair attempt modifying the game.

### Attempt boundary

`GenerationHarness.run(request)` owns one initial, repair, or regeneration
attempt. It returns at most one `CandidateSubmission` or a typed rejection,
failure, cancellation, or budget-exhaustion result. It cannot create revisions,
publish, run the release browser, or start another repair attempt.

The request contains explicit spec/plan/runtime references, parent revision,
findings, protocol versions, model policy, attempt/run budgets, execution fence,
and an opaque draft-workspace capability. The result includes changed-file
metadata, usage, audit references, and finish reason.

Adapt the existing four-author path as a measured baseline. Its internal repair
loop must be removed from the integrated harness before the application owns
repair. Parallel authors, if retained, are bounded components inside one attempt;
they are not independent workflow owners. Compare this mode with a single author
using the same evaluation prompts, budgets, and acceptance checks before choosing
a default. Exactly four output files is a migration format, not a permanent rule.

### Controlled model operations

Allow bounded file listing/reading, relevant knowledge reads, normalized file
creation/patch/deletion, manifest inspection, quick static checks, and one submit.
No shell, package installation, arbitrary network, database access, release-browser
control, or trusted-runtime edits are available to generated instructions.

The existing Codex adapter is structured-output generation, not yet a file-tool
harness. Preserve it for baseline calls. A future adapter may return typed file
operations which the application validates and applies; do not enable unrestricted
CLI tools to simulate the target interface. Adapters advertise capabilities and
reject unsupported modes explicitly.

Check cancellation, fence, the selected run budget policy, file count and bytes
before operations. Studio has no default operation, productive-turn or quick-check
count ceiling. The current planner pauses on repeated identical rejection;
the adaptive author/reviewer loops record shared observations and request a
constrained supervisor diagnosis on stagnation, conflicts and readiness. Repeated
invalid advice or ineffective decisions preserve the draft and pause. Provider
output limits are only enforced where supported; a Codex reservation estimate is
not a guaranteed provider cap. Preserve reported usage and conservative unknown
reservations after interrupted calls.

### Model context and prefix reuse

The native harness sends stable instructions, approved design and relevant lessons
before source and transient feedback. Canonical artifact hashing remains unchanged;
prompt ordering has its own serializer. `context-v1` preserves one conversation per
attempt/model/schema/instruction set and role. The author and source reviewer never
share a conversation. Native planning also reuses its own scoped conversation;
historical four-author calls remain independent.

The first call contains a full authoritative snapshot. Subsequent user messages
append only actual state changes and tool results: file additions/deletions, unique
exact-text replacements or full replacement where an unambiguous patch is not smaller.
A create/replace already present in the previous assistant reply is referenced only
after byte equality with the application's current source. Proposed operations are
never assumed successful. `read` still returns complete authoritative file content.
Approved plans, lessons and current source are not truncated to achieve a cache target.

Codex uses explicit `exec resume <session-id>`, a stable private working directory,
read-only sandbox, disabled shell/search, ignored user configuration and rules.
These scoped CLI sessions use Codex's normal local session storage; its retention
policy applies to those transcripts. The application does not put raw transcripts
in worker diagnostics or adopt them as canonical game state. Responses uses explicit
user/assistant message history with `store:false`, keeping data out of instructions.

When retained visible history plus the next delta exceeds the larger of 64 KB and
twice the current snapshot, start a fresh conversation with the full latest snapshot,
last author summary and feedback. This refreshes context without ending generation
or imposing a turn count. Errors discard the affected conversation. Worker restarts,
budget continuation and approval boundaries reconstruct from the immutable draft;
they never depend on a stale external conversation or execute a proposed patch twice.

Admission reserves the entire retained conversation, including an observed prior
input/output floor for provider-added context, without assuming a cache hit. Codex
resume receipts are cumulative: subtract the previous successfully observed thread
totals before charging the invocation. Responses receipts remain per-call. Unknown
or regressing totals retain uncertain reservations. Receipt replay is distinct from
provider prefix caching. Structured diagnostics record snapshot/message hashes,
context sizes, refresh reasons and reported cache usage, with no raw source text.

Prefix reuse follows the [official prompt-caching contract](https://developers.openai.com/api/docs/guides/prompt-caching).
Preserving the message prefix enables reuse; it does not guarantee a particular hit
rate across models, expiration, cold starts or changed design. Evaluate actual cost
and quality as well as the cached-token percentage.

### Human review in Lite and Pro

`creation_mode` is persisted at launch: Lite is automatic; Pro requires decisions.
`Job.review` stores proposal CAS keys, the approved key, user feedback and manual
revision count. A plan hook persists the exact GameSpec/BuildPlan and releases the
worker lease into `waiting/review_plan`. Non-planning paid calls and candidate
submission are rejected unless the coordinator has a matching approved plan.
Approval requeues the same job; completed model receipts are reused, not rebilled.
Feedback invalidates approval and replans with the previous proposal and notes.

After mandatory validation, a Pro proposal becomes an immutable playable Version,
but does not update `Project.latest_version` yet. `waiting/review_build` permits
preview, acceptance or feedback. Acceptance verifies the candidate bytes and
validation before updating the primary version. Feedback routes another attempt
through planning/approval and validation using the same budget. User-requested
revisions are counted separately from the bounded automatic validation repairs.
Waiting is active for the one-job-per-project invariant and remains cancellable;
no worker claims a waiting job. Every human decision requires the observed stage
fence, so concurrent/stale approval cannot release twice or revive cancellation.
Only native single-author workers advertising `interactive_plan_v1` claim Pro.

The insights endpoint reads plans and bounded step summaries independently of
committed candidates. Uncommitted source critiques are explicitly marked as draft
responses. They cannot establish browser validation or a finished build. Lite
users can inspect the same information without adding approval pauses.

### Repair policy

Native harness v1.2 requires structured `visual_design` and
`implementation_design` in new plans. The former defines art direction, palette,
desktop/mobile composition, asset silhouettes and detail layers, UI states,
motion, rendering cost and visual criteria. The latter records rule ownership,
read-only rendering, input/UI boundaries, data-driven content and extension
points for subsequent edits. A short `visual_direction` remains readable in
historical plans but is no longer sufficient for new generation. New work must
match requested scope and quality, without an implicit small-game/demo target.

Before native draft submission, a separate `visual_review` call critiques source
against these plans in seven areas. Each result cites an exact source excerpt;
the harness validates coverage and citations and binds the result to source and
plan hashes. `needs_revision` returns findings to the author; acceptance requires
a fresh critique of changed source. Critiques share the attempt's accounting,
cancellation and lease without a default review-count limit. Invalid review
evidence returns corrective feedback; remaining findings block submission.
This is a draft tool round trip, not a
second application repair or promotion loop. Provenance explicitly records
`rendered_visual_review: not_performed`; no source review becomes browser or
artistic-quality evidence. The retained four-author comparison baseline is
unchanged. New artistic quality still needs evaluation on actual rendered runs.

Application code chooses `LOCAL_PATCH`, `STRUCTURAL_REPAIR`, `REPLAN`,
`REGENERATE`, or `STOP` from structured findings. Local fixes preserve unrelated
files; shared contract changes expand to declared dependencies. A bad plan can
be replaced rather than repeatedly patching incompatible modules.

The current job policy defaults to two additional semantic candidate attempts,
shared across repair, replan and regeneration. Replanning consumes the original
budget and cannot reset the attempt counter or accounting. Repeated failures compare concrete case/action/assertion identities. They preserve
useful source and request diagnosis instead of discarding it. The adaptive version
distinguishes productive repairs from stalls without a fixed candidate ceiling. Old jobs retain their recorded policy.
Infrastructure retries must not consume semantic attempts or change game code.
Every selected strategy needs recorded evidence and a reason.

Each submitted attempt becomes a child candidate, including failed candidates.
Promotion updates the project's current playable revision only after required
checks pass. A failed revision request leaves the previous playable game intact.

## Persistence, claims, and recovery

Adapt the donor's `Project`, `Job`, `Version`, `Runner`, and `Event` concepts.
Evolve them incrementally toward:

| Record | Responsibility |
| --- | --- |
| Project | Team/owner, title, current playable revision |
| GenerationRun | Request, state, cancellation, budgets, terminal reason |
| StageRun | Expected state, operation identity, renewable lease, execution fence |
| GenerationAttempt | Parent, mode, submission, usage, outcome |
| Revision | Immutable spec/plan/source references and lineage |
| ArtifactCommit | Pending storage promotion and recovery intent |
| ModelInvocation | Request fingerprint, reservation, status, response/usage |
| ValidationRun / Finding | Exact artifact, suite/environment, checks, evidence |
| Runner / Event | Worker capability and authorization; ordered progress |

Revision source and provenance are immutable; append validation records and derive
eligibility from them. Job checkpoints and events are recovery/audit information,
not replacements for committed candidate identity.

Retain conditional claim writes, renewable leases, stale-result rejection,
cancellation, monotonic usage accounting, and one active run per project.
Introduce monotonically increasing execution fences for stage ownership. Every
model-result acceptance, submission, commit, and stage completion checks the
current fence; a lease alone does not authorize late writes. Losing contact with
the coordinator stops new calls and commits. In-flight provider work may still
incur cost, which is recorded without making its stale output current.

Studio generation does not enforce a wall-clock deadline, at either run or model
call level. The user may cancel a long request. Heartbeats still establish worker
liveness; isolated validation keeps its resource limits. Optional explicit limits
remain for bounded experiments and historical jobs. Their saved evidence is immutable.

A durable `codex_wall_timeout` receipt is written only after the local Codex
process cleanup; it does not establish zero remote cost. The gateway allows one
retry using the original request hash plus `:retry:1`, with a new reservation.
Completed plan/author/review receipts are reused across restarts. Generic ambiguous
requests, cancellation, lost fences and depleted budgets cannot trigger this retry.
A guarded operator recovery of an eligible legacy failed timeout clears its wall
limit and increments `resume_count`; it preserves all money/token receipts,
uncertain reserves, attempts, inputs and model settings. Recovery is logged, and
the UI accepts a failed-to-live transition only with a newer recovery count/fence.

A provider invocation is reserved before dispatch. Reuse completed matching
responses where policy permits; never blindly replay an ambiguous paid request.
The claim operation can reclaim an expired stage under a new execution fence.
The idempotent `manage recover` command finalizes pending artifact commits without
replaying model calls. Automatic draft cleanup and destructive retention are not
implemented; operators retain immutable evidence and apply reviewed storage
maintenance separately. Polling the database-backed API means there is no broker
delivery/outbox requirement in this first topology.

PostgreSQL is the shared deployment baseline. SQLite may serve isolated tests or
single-worker development, but PostgreSQL integration tests must establish claim,
cancellation, and completion concurrency before team deployment.

## Artifact storage and candidate commit

The initial remote-worker topology does not require a shared filesystem. Workers
send bounded source submissions to the coordinator over authenticated HTTP. They
receive scoped draft/upload capabilities, never server filesystem paths. The
trusted committer resolves runtime references, assembles the deliverable, and
checks template integrity and quotas; a worker-supplied success flag is not enough.

```text
<artifact-root>/
├── staging/<submission-id>/
├── objects/sha256/<digest>/     # Immutable delivered bytes and source manifest
├── private/<revision-id>/      # Provenance and validation evidence
├── public/sha256/<digest>/      # Exact validated export only
└── quarantine/                 # Failed or policy-rejected content
```

Keep editable modules and a manifest recording spec, plan, runtime, bridge,
packager, source digests, controls, capabilities, and entry point. Initially the
committer also creates the standalone `index.html`, and the validator tests those
exact delivered bytes. Never validate one bundle and silently substitute a newly
built export. Additional export formats later receive their own digest and gate.

The commit protocol closes the draft, normalizes paths, checks limits, calculates
the content digest, persists a fenced pending intent, atomically renames on the
same filesystem, and finalizes the reference in PostgreSQL. The database and
filesystem do not share a transaction: each step is idempotent and recovery must
handle a crash between them. Evidence remains a private sidecar so new reports do
not mutate an already committed artifact.

Reject traversal, absolute paths, Unicode/case collisions, escaping symlinks or
hard links, special files, executable bits, disallowed types, and excessive sizes.
Existing digest objects are never overwritten. Enforce byte/file/inode quotas and
grace-period garbage collection only for unreferenced objects. Back up metadata
and artifact storage together and verify restoration before depending on them.

Donor HTML/JSON database fields may be used in the isolated baseline. New contest
candidates use the store. If legacy versions are imported, verify hashes, preserve
their historical status, and never retroactively mark them browser-validated.

## Validation and release eligibility

Keep static, scenario, and evidence-binding code from Game Forge, then extend it.
Quick checks inside an attempt and release checks share rule definitions; only
post-commit release checks can establish eligibility.

A validation result is `passed`, `failed`, or `unverified` (including required
skips). **A required skipped check prevents `SUCCEEDED`, normal preview, and
publication.** Donor `partial` reports map to `unverified`. Runner absence/image
failure is visible, not a successful fallback to static-only generation. A request
may finish operationally while the game is not eligible for delivery.

Mandatory checks cover:

1. Manifest, paths, sizes, local references, syntax, runtime integrity, and
   prohibited dependencies or capabilities.
2. Browser boot, readiness, non-empty meaningful rendering, page errors,
   missing resources, and attempted external requests.
3. Seeded bridge scenarios, legal state transitions, and applicable invariants.
4. Actual keyboard, pointer, and touch actions correlated with visible output
   and bridge state; not just a Start click followed by bridge-only actions.
5. The declared playable loop, applicable success/failure outcomes, and restart.
6. Desktop/mobile layout, resize, relevant lifecycle behavior, and optional audio
   activation or persistence according to selected capabilities.

Independent team-authored and held-out scenarios complement planner scenarios.
Do not send the entire release suite to the model. Vary legal action sequences and
check consistency between UI and bridge to detect a disconnected test path.
Human review judges intent, usability, pacing, and audio/visual quality; advisory
model judgments cannot waive deterministic failures.

Persist screenshots, console/network logs, traces where practical, seeds,
scenario outcomes, and limitations. Record runner-image digest, browser and
Playwright versions, viewport/input emulation, device scale, locale, timezone,
fonts, runtime, bridge, and validator versions. A screenshot hash alone does not
let a reviewer inspect the image. Synthetic lifecycle tests remain labeled as
such. Mobile viewport checks do not constitute Android/iOS WebView verification.

## Execution and preview trust zones

Generated JavaScript runs only in the isolated validator or restricted preview.
Never execute it in a host Node VM, coordinator, or generation process. Fixed,
reviewed repository fixtures are a separately identified test path, not a bypass
for fresh model output.

For the trusted-team contest installation, adapt the existing disposable Docker
runner: non-root, network disabled outside the browser, read-only input/root,
separate bounded evidence output, dropped capabilities, no application/provider
credentials, and CPU/memory/process/output/deadline limits. Playwright uses fresh
contexts with service workers, downloads, permissions, external requests, and
unexpected navigation disabled. Review inherited Chromium launch flags; do not
mistake an ordinary container or request interception for a complete public
service boundary. Public hostile workloads require gVisor or equivalent microVM
isolation and dedicated capacity before admission.

Generation-worker credentials stay on the worker. They are never mounted into
validation. Authoring workers cannot approve their own release by submitting an
arbitrary `passed` report: validation dispatch and report acceptance use a separate
trusted runner role, bind to the immutable artifact and suite, and enforce the
current execution fence.

Preview is served from a dedicated origin with no studio cookies, scoped
short-lived access for private games, restrictive response CSP, and
`sandbox="allow-scripts"` without same-origin, top-navigation, popup, form,
download, or device privileges. Only eligible revisions are served. Raw failed
candidate files and private logs are available only as authorized diagnostic data,
never automatically executed in the studio. Future saves/scores use a separately
versioned, capability-limited host message protocol; no platform tokens enter games.
The current opaque preview denies browser persistence. The studio/runtime expose
that restriction and generated save logic must handle it honestly; storage in a
downloaded artifact is conditional on its actual host permissions.

## Context, knowledge, and evaluation

Preserve donor logs as historical evidence, not instructions or automatic model
training. Convert useful lessons into versioned entries with applicability,
concise guidance, source provenance, and a regression case. Select entries by
mechanics and findings. Never load every game's history into every request.

Trusted runtime/tool policy precedes delimited untrusted requests, source, and
model-generated data. Keep the specification, outstanding findings, and budgets
available; load neighboring source by explicit dependency rather than arbitrary
prefix truncation. Record prompt/knowledge/model versions and provider-reported
usage, including cached input when supplied. Do not infer cache hits or pricing.

Maintain two distinct suites:

- **Regression fixtures:** known games replayed through adapters to verify code,
  contracts, packaging, and validation. Their pass rate is not live generation.
- **Live evaluation:** fixed fresh prompts, bounded attempts, revisions, held-out
  mechanics, independent acceptance, and human assessment. Include every failure.

Measure first-pass and post-repair playable rate, requirement satisfaction,
revision regressions, repeated defects, elapsed time, actual tokens, estimated
cost when available, and validation resource use. The
[development plan](development-plan.md) defines the first evaluation and exit gates.

## Deferred work and revisit triggers

- Add Celery/Redis only when measured queue/backpressure or worker-routing needs
  justify it; preserve the same persisted workflow and fences.
- Add SSE if polling measurably impairs the creator experience.
- Replace Django only for a demonstrated boundary or maintenance need, not stack
  conformity with the superseded ADR.
- Add generated image/audio providers, Phaser, or new runtime capabilities after
  an evaluation case exposes a concrete quality or mechanics gap.
- Expand beyond offline 2D/DOM, multi-tenant authoring, or public untrusted loads
  only with explicit scope, acceptance, and deployment-boundary changes.
- Compare single-author and bounded parallel-author generation experimentally;
  neither is presumed superior from architecture alone.

### USD API-equivalent budget (implemented 2026-10-12)

Studio creates runs with `budget_usd`; the coordinator resolves and freezes the
model and versioned Standard tariff before queueing. `pricing.py` performs
Decimal arithmetic and returns integer nanodollar cost bounds. Each invocation
reserves estimated input/output cost, then replaces the reservation with its
usage receipt. Cached input is a subset of total input. Context thresholds apply
per invocation, with a lower/upper bound for aggregated Codex turns. Cache-write
counts are unavailable, so the upper bound treats fresh input as cache writes.
The budget uses that upper estimate plus all unresolved reservations.

The coordinator serializes reservations and accounting through the job write
fence, including late receipts after cancellation. Worker-side admission uses
the same frozen policy. Restarted workers receive both known cost and unresolved
reservations. Receipt identity makes reconciliation idempotent. USD runs never
apply the legacy total-token ceiling; old token jobs and evaluation replays keep
their original semantics. A running provider call may exceed its estimated
reservation; the overrun is visible and prevents additional calls.

The UI displays the rate date, model, three token rates, current USD range, held
reservations and remaining budget. Rates can be updated through the server's
`PROMPT2PLAY_PRICING_FILE`; old snapshots remain immutable. New or unrecognized
models require an operator-reviewed tariff. Standard-equivalent cost does not
claim to reproduce subscription usage limits or an actual API invoice.


## Continuable native authoring (2026-10-12)

Harness v1.4 removes the default operation-batch, operation-total, author-turn,
quick-check and source-review count ceilings. Each operation still checks the
current lease and cancellation; each paid request reserves against the same job
budget. Path/source byte constraints and isolated validation remain. An optional
explicit `WorkspaceLimits` bound is for controlled experiments, not Studio's default.
Repeated reads and no-op/failed writes are tool feedback. Rejected structured
responses and invalid review evidence feed a new request; the model cannot waive
schema/path/runtime validation. Unknown transport outcomes are not blindly retried.
A durable rejected-response marker prevents paying for that same failed response
again after a process crash, while retaining its reported spend or unknown reserve.

The native loop alternates author and source-review phases until source readiness.
It writes an immutable CAS draft at each boundary, including before paid review.
The coordinator stores only its key and scope (attempt/stage/feedback round) in
`Job.checkpoint.authoring_draft`; `/worker/jobs/:id/draft/` is role- and lease-fenced.
Plan approval is required in Pro, and snapshot plan bytes must match the current
proposal. Claims return only a matching scoped snapshot. The harness checks its
request identity and ready snapshots require a matching successful source review.
Drafts are not candidates and cannot create previews or versions. Old workers
without `continuable_authoring_v1` cannot reclaim a job with a saved draft.

`resume_authoring` is a guarded operator action for failures caused by obsolete
count limits. It preserves all accounting and failure evidence; where no snapshot
exists, it reconstructs an unambiguous initial attempt using completed receipts
without a provider call. It never authorizes replay of an unknown in-flight call.
The next request contains explicit recovery feedback and has its own identity.
User-configured post-browser repair attempts remain an application policy, distinct
from authoring iterations. Historical bounded-run evidence is not rewritten.


## Mechanics acceptance and explicit failure continuation (2026-10-12)

Native harness v1.8 requires a `BuildPlan.mechanics` matrix. Cases map every
non-lifecycle GameSpec action to desktop/touch inputs and snapshot assertions.
Revisions retain old action names, case IDs and keyboard coverage alongside new
actions; all cases run again, including affected mechanics and regressions.
Continuous keyboard cases must include hold/release/re-press and simulated time.
Comparisons reference an earlier observed step or finite JSON; ordering comparisons
require numbers, while equality also supports arrays and objects. No model
JavaScript test or privileged game-state setup is executed. A plan rejected for
missing coverage returns explicit correction feedback within the same budget.

The container runs each case from a fresh deterministic state through real UI
input. It records expected/actual values, visible effects and failures in the
immutable mechanics evidence. The coordinator rejects passing native reports
that omit required case coverage. Scenario edits can correct selectors and preparation steps. Protected fields,
operators, literal/observed baselines, tolerances and assertion multiplicity cannot
be weakened or deleted. Action/control coverage is also preserved. These checks verify the declared contract; they do not prove every
possible behavior or replace human
assessment of intent, difficulty, balance or complete playthrough.

`POST /api/jobs/<id>/resume/` accepts an authenticated, CSRF-protected explicit
user continuation with the current stage fence. Project/job serialization blocks
concurrent successors and stale double clicks. The same job, draft, model, budget,
known usage, immutable candidates and completed invocation responses are kept.
Only unsuccessful logical invocations receive a new user-resume identity;
unknown spend stays reserved. This is not silent transport retry or a budget
reset. Budget extensions use the same conservative continuation rule. Failed
validation after a recorded report starts repair with a new candidate, while a
transport failure during validation can retry delivery of the same candidate.
Commit recovery finalizes the existing immutable artifact before validation.

Codex failures retain bounded sanitized terminal errors, error classification,
provider code, process exit status and diagnostic hashes before temporary logs
are deleted. Unknown errors are labeled unknown instead of implying login is
broken. Worker logs correlate failures with invocation keys; job error events
retain safe exception frames and provider details. Successful output, request
payloads, credentials and raw transcripts are excluded. No additional generation
wall-clock or operation-count limits are introduced.

## Adaptive generation implementation

This section describes the R1–R6 implementation, enabled by default for new jobs
at the user's request. R7 comparisons and human artistic assessment remain separate
release criteria. PostgreSQL remains the only workflow owner. A supervisor is another
structured model role behind `ModelGateway`; it has no independent scheduler,
host tools, publication permission or authority over budget and trusted checks.

Separate immutable `Requirements` and `AcceptanceContract` revisions from
`GameSpec`/`BuildPlan` design and `ExecutionPlan` work items. An execution item binds
its dependencies, file scope and completion evidence to the relevant requirements.
Changing a selector or preparation step is distinct from changing expected game
behavior. The author cannot approve weaker expectations for its own implementation.

At each meaningful boundary, persist a `StepObservation` containing actual changes,
typed defects, evidence identity and cost. A deterministic policy continues clear
productive work or identifies a decision requiring supervision. Invoke the model
for contradictions, lack of progress, scope changes and readiness milestones;
do not pay for supervision after every file read or patch.

Browser diagnostic access is part of the author contract. `read_diagnostic` reads
only text/JSON entries in the current job's immutable browser report, authenticated
by the generator's active lease and stage fence. It cannot read arbitrary storage
objects or modify evidence. Empty path lists the evidence; a JSON Pointer selects
a state or step, and explicit character pagination bounds each response to 16,000
characters. Stale report keys return an operation result, never another job's data
or a spurious lease failure. Saved reports remain readable after pause/restart.

Both author and supervisor receive the artifact identity, inventory and bounded
failure previews; the author can request precise details without rerunning the
browser. `inputs-<viewport>.json` records scenario and mechanics steps, before/after
state projections, touch geometry and actual hit target, and operation errors.
Replay operations are excluded. Snapshot truncation and dropped old records are
explicit; assertions always use full states, never these diagnostic projections.
Each viewport log is capped at 2 MB. On interruption, request-bound input records
are copied into immutable evidence alongside the partial findings. Historical
reports can lack these newer observations; one new check captures them. Screenshots
and trace archives remain stored; this text operation does not claim image review.
Read-only inspection is neutral evidence acquisition, not a failed author repair
or verified gameplay improvement.

The supervisor proposes a typed decision with evidence and an expected improvement.
The coordinator validates the current plan/draft/fence, allowed scope, acceptance
preservation, budget and approvals. Applying an accepted decision creates an
immutable child DesignPlan and decision record, then advances their active
references atomically with the draft and approval transition. Checkpointed
authoring can then resume within the same candidate attempt. Late responses remain
accounted but cannot modify a draft under an incompatible plan.

```text
Execution item → Author/tool step → Saved observation
    → Deterministic progress policy → Continue the plan
                                   → Supervisor proposal
                                       → Coordinator checks
                                           → Revised plan / targeted repair
                                           → Validation retry / user decision / pause
All requirements verified → Readiness decision → Immutable candidate
    → Independent final validation → Pro acceptance when applicable → Publication
```

One ledger accounts for planning, authoring, supervision and visual review. Stable
requirements and the active plan lead each role's context; relevant observations
and confirmed deltas follow. Receipt reuse and prefix caching remain different
mechanisms. Unknown paid outcomes never become automatic retries through a
supervisor suggestion. Productive work has no default wall-clock or step ceiling;
stalled or internally contradictory supervision must yield an explained pause.

Lite applies technical corrections within the user's intent automatically. Pro
shows substantial plan changes and waits for approval before dependent work.
Both expose evidence, the reason for the next action and pause/continuation.
Neither permits silent scope reduction, budget increases or cancellation reversal.

R5 captures rendered-state evidence and image-capable art/UI review, with explicit
human review when unavailable. R6 supports modular source and local resources
with deterministic isolated assembly into a single HTML. Both preserve exact-byte
validation, historical runtimes and immutable published versions. Pin workflow
versions, use compatible checkpoint migration and worker capability checks, and
roll back by pausing incompatible work rather than resetting or deleting it.

The job pins `pipeline_version` and `project_format`. A worker must declare
`adaptive_generation_v1` to author adaptive jobs. `/resume/` can explicitly
upgrade a paused native legacy draft; the original CAS object and its identity
remain intact, and the migrated draft must pass new coverage/art checks. Optional
continuation feedback is delivered without changing the prior request identity,
financial receipt or requirements. Unknown WebView hosts still require separate
device acceptance.
