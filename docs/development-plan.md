# Prompt2Play Development and Adoption Plan

## Status and scope

Accepted planning baseline: **2026-10-11**. This plan implements
[ADR 0003](adr/0003-hybrid-adoption.md) and the
[combined architecture](architecture.md). The implementation below is now present
in branch `codex/hybrid-architecture-plan`; fresh evidence and remaining release
gaps are maintained in the [implementation report](implementation-report.md).
The detailed tasks remain the acceptance specification, not a substitute for
their evidence. The user confirmed that the contest WebView host is unknown.
Final chosen-release measurement is **7/10 fresh games and 3/4 attempted
revisions**; no held-out base passed, so the fifth revision was unavailable.
The internal quality target remains unmet. Human participant assessment and
actual host/device acceptance remain open; these are not claimed complete by
the implementation status below.

| Phase | Implementation status | Evidence boundary |
| --- | --- | --- |
| G0 | Donor reproduced; original planner blocker recorded | 301 fresh named tests plus 24 authored cases; original live planner timed out, so no original live success rate |
| G1 | Integrated studio, durable coordinator, two worker roles, gated preview/download | PostgreSQL concurrency, API workflow, creator browser flow and fresh live end-to-end check |
| G2 | Optional runtime, exact historical packaging, Canvas/DOM/hybrid conformance | Container fixtures and fresh games; mobile emulation does not establish actual WebView support |
| G3 | Typed editing, dependency-aware repair, durable provider accounting, comparison tooling | Both strategies measured with the same frozen prompts, budgets and external recipes |
| G4 | Packaging, installation, backup/restore, demo and evidence reporting | Quality threshold and human assessment reported explicitly; contest host acceptance remains open |

Work in dependency order. Each phase must leave a runnable or reviewable result
and explicit evidence. No calendar deadline is inferred from the historical
team discussion. Adjust scope to the contest date when the team confirms it.

## Starting point and evidence

| Source | Current state | What it establishes |
| --- | --- | --- |
| This repository at planning baseline | Typed Python foundation, uv lock, CI, documentation; package-version test only | Original starting point, superseded by the integrated implementation |
| Game Forge 1.3.0 handoff | Django/React application, workers, generation graph, contracts, validator, games, logs | Reusable implementation and historical regression evidence |
| Historical Forge run `20261011T113440.380419Z` | Reported 301 named tests plus 24 separately counted cases | Recorded regression results; not a new local run |
| Handoff integrity check during initial assessment | 774 recorded files matched; 7 nested ZIPs checked; only two extra `.DS_Store` files | Transfer bytes were intact; no behavioral inference |
| Frontend check during initial assessment | 52 tests passed in the local environment | Frontend logic tests, not a browser/UI acceptance pass |
| Live provider / isolated Chromium / target WebView | Not established by the handoff report or initial assessment | Required new evidence |

The donor is currently available in the neighboring
`../game_forge_old/game_forge/` directory; original game projects and handoff
context are under `../game_forge_old/`. These are discovery locations only.
Use paths relative to the donor root in adoption manifests. The contest product
and its tests must work without that sibling directory after each import.

Never confuse the original game with its corpus adapter, or recorded provider
replay with a fresh generated game. Preserve artifact hashes and evidence scope.

## Transfer inventory

Paths in the source column are relative to the donor generator root unless
explicitly marked otherwise. The concrete imported paths and both source and
adapted-byte hashes are recorded in `adoption-manifest.json`.

| Source | Treatment | Destination / change | Acceptance before relying on it |
| --- | --- | --- | --- |
| `frontend/src/`, package manifest and lock | Adopt, adapt API/status mapping | `web/`; retain projects, versions, source, findings, settings and job monitor | Existing logic tests and build pass; browser test covers submit, cancel, revise, and result selection |
| `backend/forge/` models, auth, views, serializers, services, migrations and tests | Adopt incrementally | Django adapter; extract application use cases; preserve team access semantics | API and PostgreSQL claim/cancel/reclaim races; old worker cannot commit |
| `worker/transport.py` and worker entry point | Adopt and extend | Scoped HTTP operations, leases, cancellation, stage fences | Disconnect, expiry, revocation and restart tests; credentials never enter artifacts |
| `worker/providers.py` and provider tests | Adopt behind `ModelGateway` | Codex/API structured output, usage, timeout and cancellation | Fake transport tests plus bounded real calls with configured provider; no blind replay after ambiguous failure |
| `worker/core.py`, `worker/semantics.py`, semantic tests | Adapt | `GameSpec`, `BuildPlan`, ownership/dependencies, optional capabilities | Schema compatibility and real-time/turn-based contract cases; irrelevant requirements stay absent |
| `worker/pipeline.py` | Preserve as baseline; refactor ownership | Four-author mode inside one attempt; application owns commit, validation and repair | One invocation cannot start global repair or promote output; restart/budget tests |
| `prompts/*.txt` | Curate, version, simplify after runtime extraction | Stable instructions plus applicable knowledge entries | Every behavior-changing prompt revision evaluated on the fixed suite |
| `validator/checks.py`, scenarios, evidence binding and tests | Adopt and extend | Shared quick/release rules; independent acceptance scenarios | Tampered HTML/spec/report rejected; required skips cannot promote |
| `validator/docker.py`, runtime/probes, Dockerfile | Adopt as implementation starting point; audit and run | Mandatory isolated runner, actual input, stored screenshots/traces | Real container run, egress/resource controls, desktop and touch interaction; image absence fails eligibility |
| `frontend/src/lib/preview.ts`, preview component | Retain policy/UI, replace document delivery | Separate preview origin serving exact eligible artifact | Cookie/secret separation, CSP/sandbox tests, failed/unknown revision denied |
| `backend/forge/artifacts.py` and `validator/evidence.py` | Reuse identity checks; replace storage | Content-addressed store, pending commit protocol, immutable candidates | Crash recovery, hash binding, duplicate submission and exact-download checks |
| `reference/corpus/`, relevant original games and tests | Selectively import with provenance | Regression fixtures and legacy bridge adapter | Original versus adapted bytes identified; replay never counted as live generation |
| `reference/evaluation_prompts.json` | Seed and rebalance the suite | Fixed modest-scope prompts, revisions, held-out mechanics | Independent rubric and bounded attempts defined before calls |
| Lesson documents and relevant JSONL entries | Preserve selected evidence; distill rules | `knowledge/`: applicability, concise rule, source hash, regression | Entries selected by actual mechanic/finding; no raw history dump in model context |
| Setup/release scripts and deployment files | Reuse concepts, adapt commands and topology | uv-based Python setup, frontend lock, validator image, separate preview | Clean installation and reproducible package; no historical pass reused for changed bytes |
| Environments, secrets, working databases, complete archives, donor `AGENTS.md` | Do not import wholesale | New local configuration; retain this repository's instructions | Source inventory excludes credentials and generated caches |

For each imported slice, record source release/path/hash, local destination,
modifications, relevant test results, and known limitations in an adoption
manifest. Check dependency availability, licenses and compatibility before pinning
versions. Migrate Python requirements through uv; change `pyproject.toml` and
`uv.lock` together. The frontend retains its own package lock.

## Phase 0 — reproduce and measure the donor

**Purpose:** discover whether the existing generation path works before choosing
which part to redesign first. This is an isolated baseline, not the contest app.

Tasks:

1. Preserve the original handoff and historic reports. Use a disposable working
   copy for setup and tests that refresh generated reports.
2. Reproduce backend, worker/provider/validator, corpus, frontend, and build checks
   with fresh local dependencies. Distinguish fixture execution from browser runs.
3. Audit/build the isolated validator image and execute known Canvas and DOM games.
   Verify egress denial, resource bounds, and actual input. Do not run fresh model
   JavaScript in a host VM as a workaround.
4. Run the fixed initial live suite with explicit provider/model configuration,
   bounded budgets, and isolated browser validation. Retain every failed attempt.
5. Try one meaningful revision for each successful game. Record model/schema
   incompatibilities, integration failures, validation weaknesses, and context cost.

**Deliverable:** baseline report, immutable artifacts/evidence, dependency notes,
and a ranked list of observed defects. Do not claim that generated examples match
the quality of the manually developed originals without measuring it.

**Exit G0:** baseline results and limitations are reproducible. A failing provider
or runtime can be an explicit result: move to the smallest implementation task
that addresses its recorded blocker, then repeat the affected baseline. No
success metric may be filled in using recorded source as a substitute.

## Phase 1 — import one complete, gated product path

**Depends on:** G0 evidence or a specifically documented G0 blocker being resolved.

**Purpose:** move from an external donor to a self-contained contest repository
that accepts a prompt and delivers only a browser-checked game.

Tasks, in dependency order:

1. Import the minimal Django/DRF coordinator, React studio, provider adapters,
   contracts, tests, and worker transport. Keep existing routes initially where
   possible; avoid an API rename while also changing behavior. Preserve cancellation,
   runner revocation, one active job per project, and usage accounting.
2. Define run/stage/attempt contracts and extract repair routing from the donor
   graph into application use cases. Initially reuse whole-module authoring inside
   one attempt. Add stage fences, persisted invocation reservations, and an
   idempotent recovery command. No new paid calls or commits after lease loss.
3. Introduce the filesystem store and candidate committer before accepting new
   integrated outputs. Commit each submitted attempt, including failed candidates,
   with parent/spec/plan/source identity and a recoverable pending commit intent.
4. Import static and isolated browser validation. Bind reports to the exact
   committed HTML and suite; use a separately authorized validation runner role.
   Required skipped checks map to `unverified`. Add actual input scenarios and
   store inspectable screenshots/logs rather than their hashes alone.
5. Promote only eligible candidates. Keep the previous playable revision on a
   failed edit. Serve previews on a separate origin and download the exact
   validated standalone HTML. Adapt the UI to show generation and validation
   status separately, with clear unavailable-runtime errors.

**Transition format:** `legacy-four-module-v1` may use the donor assembler and
`__GAME_TEST__` adapter. Record assembler/adapter versions. All four game modules
remain untrusted generated code; this format does not claim to have a trusted
shared lifecycle runtime. Baseline `partial` results remain diagnostic only.

**Deliverable:** a runnable prompt → candidate → browser → playable-preview flow,
plus revision, cancellation, source inspection, findings, and download.

**Exit G1:**

- A fresh prompt completes through the real configured provider and isolated
  browser; the delivered HTML digest matches the tested digest.
- A missing validator, malformed report, failed input check, or required skip
  cannot produce a ready game or preview token.
- Failed edits preserve the last playable version; all submitted candidates remain
  inspectable as data with their real validation state.
- Stale workers, duplicate completion, worker restart, cancellation, and a crash
  between filesystem commit and DB finalization have reproducible tests.
- API/concurrency checks pass against PostgreSQL; frontend logic/build and a real
  browser creator-flow test pass. The sibling donor directory is unnecessary.

## Phase 2 — extract the shared runtime without narrowing mechanics

**Depends on:** G1.

**Purpose:** remove repeated infrastructure generation while preserving genre
freedom and a working reference path for comparison.

Tasks:

1. Split the semantic plan into `GameSpec` and `BuildPlan`, preserving legacy
   conversion tests. Give schemas and knowledge selection explicit versions.
2. Extract mount/dispose, input/resize, seeded primitives, optional fixed-step
   timing, audio activation/cleanup, optional storage transport, and test-bridge
   plumbing from reviewed code. Add only capabilities backed by a working case.
3. Integrate both a real-time Canvas game and a turn-based DOM game; keep hybrid
   compatibility. Let generated code own mechanics, presentation choices, sound
   content, and game-specific save semantics.
4. Add runtime digest verification and prohibit model writes to trusted files.
   An upgrade creates a child revision. Keep old fixtures and the bridge adapter
   available until replacement evidence covers them.
5. Reduce prompts by removing instructions now enforced in trusted code. Select
   additional lessons by mechanics and findings rather than sending all history.

**Deliverable:** a small runtime with optional capabilities, versioned contracts,
converted examples, and fresh generations using it.

**Exit G2:** real-time and turn-based games both pass real input, deterministic
rules, pause/restart, and applicable audio/storage cases. A no-audio/no-save game
has no invented audio/storage obligations. Runtime changes cannot alter old
revisions. Compare live results against G0 with the same suite and budgets;
record any regressions before making the new path the default.

## Interactive creation delivery — Lite / Pro

Implemented after the combined baseline: Lite preserves automatic creation;
Pro adds durable plan approval and acceptance of a validated build. Existing
plans and saved model-step summaries are inspectable while generation runs.
User feedback replans in the same budget, completed receipts are reused, waiting
jobs are cancellable, and stale/double confirmations are fenced. The primary
playable version changes only on acceptance. These controls do not establish
artistic quality and do not change mandatory browser/WebView acceptance gates.

## Phase 3 — improve editing and choose the generation strategy

**Depends on:** G2; can prepare measurement tooling while G1/G2 are implemented.

**Purpose:** make revisions reliable and stop spending whole attempts on local
errors or incompatible plans.

Tasks:

1. Add a capability-scoped draft workspace and typed read/create/patch/delete/
   quick-check/submit operations. Enforce path, file, byte and turn limits,
   runtime immutability, cancellation and current fences on every step. Studio
   generation has no wall-clock timeout; bounded experiments may opt into one.
2. Adapt providers explicitly to the allowed operations. A structured-output
   adapter can return operations for the application to validate and apply;
   enabling unrestricted shell/file access is not an acceptable shortcut.
3. Implement application repair strategies: local patch, structural repair,
   replan, regenerate, stop. Add dependency expansion for shared contract changes,
   repeated-finding detection, and one run-wide budget/semantic-attempt counter.
4. Compare single-author and bounded four-author generation at equivalent budgets.
   Record first-pass quality, integration defects, repair yield, latency, usage,
   and success of revisions, with every failed attempt included.
5. Exercise cancellation during a model/tool call, ambiguous provider failure,
   resumed checkpoints, no-op loops, unsupported adapter capability, and immutable
   candidate submission. Reusing a completed response must preserve provenance.

**Deliverable:** bounded editing harness, repair policy, and a documented default
generation mode backed by the comparison. Keep the losing mode only if it serves
a measured use case; do not maintain two global orchestrators.

**Exit G3:** a visual-only edit preserves unrelated source and gameplay; a shared
schema change updates its dependencies; a structurally bad plan can be replaced;
repeated failures stop within the original budget. Targeted tests and the full
release suite pass on the exact final candidate.

## Delivered follow-up — revision diagnostics and basic mechanics (2026-10-12)

**Status: implemented; dedicated browser regressions distinguish broken and working controls.** Investigating a failed
revision exposed two separate gaps. The first planning call failed before any
new draft was saved; the provider adapter retained only a generic error and
deleted its temporary process diagnostics. Separately, inspection of an accepted
space-game HTML showed that its movement handler expects `keyup` through
`ctx.input.key`, whereas the embedded runtime forwards only `keydown`. Released
keys therefore remain in the game's pressed-key set, and opposite directions
cancel each other. Its desktop acceptance scenario presses only `ArrowLeft`
once, so it cannot detect this defect. These are source/report findings, not a
new browser reproduction or proof of the provider failure's underlying cause.

Implemented scope and acceptance:

1. Preserve bounded, secret-safe provider failure evidence: process exit status,
   terminal event type, available structured error code, and a useful sanitized
   diagnosis tied to the invocation. Keep an explicit unknown category instead
   of implying an authentication failure. Test retention and redaction before
   retrying a failed request; preserve ambiguous accounting and previous versions.
2. Make keyboard press/release semantics explicit in the runtime contract,
   generation instructions, examples, and checks. Provide a compatible route for
   held controls and reset pressed state on blur, pause, and restart. Do not
   silently send new release events to existing press-only handlers. Repair
   affected games through new immutable revisions, preserving their original
   runtime and artifact evidence.
3. Require a per-game matrix of basic mechanics even with manual playthrough:
   each declared direction/action, held input across multiple frames, release,
   repeated press, opposite directions in sequence, applicable simultaneous
   keys, focus loss/recovery, and pointer/touch equivalents. Check the expected
   gameplay effect and visible result for each case; opening a menu or a single
   changed frame cannot establish that movement works. Tests must follow the
   game's declared interaction model, without imposing continuous movement on
   turn-based games.
4. For combat games, cover the declared primary attack, target selection,
   cooldown/repeat behavior, and auto-attack with no target, nearest target in
   range, and targets outside range. Derive expectations from the approved spec
   and revision request, and retain unaffected-mechanic checks after an edit.
5. Run these short scenarios on the exact final artifact in the isolated browser,
   recording inputs, expected/observed outcomes, screenshots, and errors. Require
   the known keyboard mismatch to fail a regression scenario before the fix and
   pass afterward. Report missing required evidence as unverified. Full victory,
   difficulty, balance, and complete playthrough remain human review by default;
   automatic full playthrough stays optional.

**Exit:** a validated game cannot pass on one incidental input response while a
declared basic control is broken; failed revisions retain actionable diagnostics
and the previous playable version. Explicit continuation is available in the studio. No user-game revision or paid
model generation was run as part of this implementation.

## Phase 4 — contest acceptance and reproducible demonstration

**Depends on:** G1 for a minimum viable submission; G2/G3 when included in the
release. Never release an unfinished new path merely to satisfy phase breadth.

Tasks:

1. Rerun the fixed suite on the chosen implementation, prompt/runtime versions,
   provider, and budgets. Include a mechanic not used during runtime development.
2. Assess intent, clarity, controls, layout, game outcomes, animation, and optional
   sound by human review. Record gaps separately from mechanical test results.
3. Identify and test the intended WebView host/device. Check touch, viewport,
   focus, pause/resume, restart, audio activation when present, and offline loading.
   If the contest host is unknown, record the tested host and outstanding gap;
   desktop mobile emulation cannot close this requirement.
4. Verify preview access control, private evidence separation, retention/storage
   limits, cancellation/recovery, and a clean deployment from documented setup.
   Back up and restore the candidate store together with metadata.
5. Prepare a live generation and revision demonstration plus clearly labeled saved
   examples for reference. Record model/configuration, time, actual usage, attempts,
   final digest, checks, and limitations. Never present a replay as a fresh run.

**Deliverable:** reproducible release, evaluated examples, evidence report,
installation/runbook, and demonstration sequence.

**Exit G4:** mandatory game gates pass for each showcased artifact; WebView
acceptance names its actual environment; fixed-suite results meet the declared
internal threshold below or are explicitly reported as a remaining release gap.
No claim of arbitrary-genre reliability is inferred from a small demonstration.

## Initial live evaluation protocol

Define the suite and rubrics before running or comparing implementations:

| Case | Mechanic / presentation | Required observations |
| --- | --- | --- |
| Runner | Real-time Canvas, keyboard and tap | Start, jump/input effect, collision/failure, restart, resize |
| Grid puzzle | Turn-based DOM or Canvas | Legal/illegal action, visible progress, solved state, restart |
| Shooter or small tower defense | Real-time state/economy | Input, resource or damage accounting, outcome, restart |
| Card game | Turn-based DOM, human and bot | Decision ownership, legal alternatives, no hidden-data leak, completion |
| Held-out interaction game | Drag/drop or a previously unused mechanic | Real pointer/touch interaction, objective, outcome, restart |

Scope prompts to small complete games. Preserve the donor's larger camp/card
requests as later stress cases, not mandatory complexity for every baseline.
Where sound or persistence is requested, add applicable checks explicitly.

- Start with two fresh generations per case: ten runs. Fix the per-run token
  admission budget, time deadline and at most two additional semantic candidate
  attempts before calls. Reconcile actual provider usage; an estimated Codex
  reservation is not a guaranteed billing cap for the invocation already running.
- Request one meaningful revision on the first successful run of each case;
  report cases with no successful base separately. Use visual/local changes and
  at least one shared-mechanic change across the suite.
- Record first-pass and post-repair success with denominators, per-case failures,
  revision regressions, actual reported usage, unknown spend, duration, and human
  rubric scores. Runtime outages remain failed delivery attempts and receive a
  separate infrastructure classification.
- As an internal contest target, aim for at least 8/10 playable runs after bounded
  repair, at least one success in every case, and no required-gate regression in
  the five selected revisions. This is a small-sample release target, not a
  statistical guarantee or a requirement asserted by the contest organizer.
- A hard security or mandatory playability failure cannot be averaged away by a
  high aggregate score. Keep held-out release scenarios separate from model-visible
  examples. Changes to prompts or thresholds require a new version and rerun.

## Suggested work ownership

These are team workstreams, not assignments to named people or authorization to
start parallel agent tasks:

| Workstream | Primary work | Coordination boundary |
| --- | --- | --- |
| Backend / integration | Import, workflow, claims, store, commit/recovery, deployment | Run/attempt/revision API and trusted runner protocol |
| Frontend / browser | Studio adoption, preview, actual input, mobile and WebView evidence | Eligibility states, event contract, exact artifact delivery |
| ML / generation | Baseline, spec/plan, context, runtime collaboration, harness comparison | ModelGateway, GameSpec/BuildPlan, independent rubric and budgets |

Agree contract versions and acceptance examples before changing both ends of a
boundary. The runtime/bridge requires joint game and browser review. Every
workstream contributes a tested part of the same end-to-end path.

## Scope cuts and subsequent work

If time is short, keep the working G1 flow and improve its measured defects.
Reduce game complexity, supported optional capabilities, and UI polish before
weakening isolation, browser gates, budget limits, or result honesty. A partial
G2/G3 experiment stays behind an explicit mode and out of the contest default.

Defer FastAPI migration, Celery/Redis, SSE, broad runtime/genre registries,
generated external assets, public multi-tenant authoring, multiplayer, and 3D
until there is a measured need or new agreed scope. Public hostile execution
requires the stronger sandbox boundary before exposure, not after an incident.

## Implementation completion checklist

For each phase or imported slice, report:

- source provenance and changed contracts;
- runnable user-visible path and exact setup;
- fresh relevant checks, including backend, frontend, browser and provider scope;
- artifacts and evidence bound to exact versions/digests;
- known failures and unverified behavior;
- the next dependency that is now unblocked.

Keep immutable historical reports. New source, prompt, runtime, provider-policy,
or validation changes require fresh evidence; an old successful report is never
proof of a changed release.


### Authoring continuation follow-up (2026-10-12)

- Remove default fixed authoring batch/operation/turn/check/source-review ceilings.
- Return invalid operations and review evidence as actionable model feedback.
- Save immutable source checkpoints between steps, with fenced restoration and
  unchanged budget/accounting across restarts; keep Pro plan approval mandatory.
- Recover the existing operations-limit failure from its completed responses,
  preserving both original failed receipts and their spending.
- Acceptance: exceed each old count threshold, survive a crash around a rejected
  response without double billing, resume a draft without reauthoring, reject
  stale/cancelled writes and incompatible old workers, and retain mandatory final
  browser validation. Fixture checks and fresh live results remain separate evidence.
