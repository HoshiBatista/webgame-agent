# Hybrid implementation and verification report

Branch: `codex/hybrid-architecture-plan`. Implementation began on 2026-10-11;
final verification continued on 2026-10-12 (Europe/Moscow).
This report records evidence scope; an implementation item is not automatically
a contest acceptance claim. The original donor directory was used read-only.

## What was adopted and rebuilt

| Responsibility | Adopted | Changed in the contest repository |
| --- | --- | --- |
| Studio | React/Vite projects, source, versions, findings and settings | Independent validation status, role-scoped runners, separate-origin preview, failed-edit preservation |
| Coordinator | Django/DRF auth, job polling and migrations | Persisted candidate stages, generation/validation separation, PostgreSQL fences, recovery and accounting-only receipts |
| Providers | Local Codex CLI and Responses API adapters | Typed restricted operations, schema compatibility, durable invocation identity, cancellation and uncertain-spend handling |
| Generation | Donor four-author strategy and semantic lessons | One candidate per harness call; application owns repair; single-author mode uses shared runtime and scoped editing |
| Validation | Static checks, isolated Playwright and artifact identity | Trusted external input recipes, causal input checks, immutable image/source identity and actual private evidence |
| Game infrastructure | Reviewed concepts from working games | Versioned optional runtime; mechanics remain generated; exact historical runtime bytes remain reproducible |
| Packaging | Donor deployment concepts | uv-based package/CLI, bundled studio/resources, consistent backup and verified empty-target restore |

The [adoption manifest](adoption-manifest.json) records source paths and hashes.
Raw provider history, secrets, environments, live databases and complete donor
archives were not imported into source. Historical fixture execution is separate
from fresh generation and from actual isolated browser execution.

## Fresh baseline

An untouched disposable donor copy with fresh locked dependencies passed **301
named tests and 24 separately counted authored regression cases**. The scope was
backend, worker/provider fixtures, HTTP integration, corpus, frontend and build;
it did not include live model calls or actual browser/WebView execution. See the
[immutable baseline summary](evidence/baseline-verification.json).

The original live planner was also tried using the locally authenticated Codex
provider and `gpt-6-astra`. It timed out after 240.05 seconds without a completed
response; 35,980 reserved tokens remain uncertain. This is an explicit G0 blocker,
not an original-donor success rate. An adapted four-author comparison addresses
provider/schema transport under the same frozen conditions as single-author mode.

## Evidence established during implementation

- Latest Python release suite: 191 passed; fifteen opt-in container tests are
  measured separately below. Core branch coverage was 90.05% against an 85% gate.
  The 169 adopted worker/provider regressions also passed. Ruff and strict Mypy
  passed (116 source/test files). PostgreSQL 18 checks include deterministic
  claim/cancel/deadline races and actual backup/restore. SQLite connections are
  explicitly closed; the final suite ran with resource warnings treated as errors.
  Scoped preview capabilities are redacted from access logs and actual Django
  exception emails; deployment proxy/access logs require their own query-free
  configuration.
- Studio logic: 56 tests and production build passed. The trusted creator-flow
  browser test covers generation, cancellation, revision, failed-edit preservation,
  result selection and role registration. Its provider/API data is an explicit test
  double; its harmless preview is not a freshly generated game.
  Restart and reopening refresh the ten-minute scoped preview URL; an expired
  URL is never used as a fallback after refresh failure.
- First diagnostic live native game: three coins, three actual Codex calls,
  44,130 reported tokens, 122.11 seconds. Its exact HTML passed isolated Chromium
  154 desktop and touch conformance. Raw artifacts and twelve evidence files are
  stored locally under `/private/tmp/prompt2play-first-live/`.
- First live coordinator job: `0ebc7f70-ab4e-4e05-918f-a31969763cc9`, immutable
  candidate `1ac1ec4c-ed7d-448c-8718-7c22ce0e0f6d`; three actual calls and 48,335
  reported tokens. HTML SHA-256:
  `78233c9d027deb77422b0012388fbd493cd38a04963f1ce91dde8f5e327dfc55`.
  This attempt was correctly rejected: a runtime upgrade during the call exposed
  inconsistent version/digest metadata, and generated source referenced protected
  toolbar IDs. A repair stopped after repeated checks; six total calls/98,296
  tokens remain recorded. Per-attempt runtime identity is now frozen before calls,
  packaging rejects version/digest mismatch, and author instructions state the
  toolbar boundary. The failed candidate was preserved, never rewritten.
- Fresh final coordinator run: three-coin game passed its first candidate with
  three calls/47,069 tokens. A meaningful three-to-four-coin revision also passed
  its first candidate with three calls/50,344 tokens. Actual authenticated HTTP
  downloads and separate-origin previews match the tested HTML exactly. See
  [base](evidence/live-coordinator-base.json),
  [revision](evidence/live-coordinator-revision.json) and
  [delivery identity](evidence/live-delivery-verification.json). The exact old
  base/revision HTML was additionally revalidated after the visibility and real
  touch-scroll fixes, with zero new model calls; both passed the final isolated gates.
  [Separate current-harness revalidation](evidence/live-demo-current-harness-revalidation-final.json)
  preserves the historical job, runtime and comparison results unchanged.
- Fifteen final real container regressions passed with Chromium 154.0.8037.92 and
  executed image `sha256:fef049f5c9f47265d14e09ef56809872e30fd71ea340b20e2d611d01e96c14c1`.
  Their 220 evidence files contain actual screenshots, console/network logs and
  traces. Eight game acceptance reports pass, six defective candidates are
  correctly rejected, and one platform qualification passes 42 checks. The suite
  includes invisible-toolbar rejection, causal rejection of broken keyboard input,
  detached/moved/foreign input lifecycle, real vertical swipes, offscreen control
  reachability and dense-button scrolling. A separate
  [dense-button gesture check](evidence/dense-button-touch-scroll-verification.json)
  confirms scrolling does not accidentally activate a button.
  [Browser metadata](evidence/isolated-browser-verification.json) distinguishes
  real audio graph scheduling from audible quality and synthetic lifecycle from
  actual operating-system backgrounding.
  The [original eight-fixture evidence](evidence/isolated-browser-verification-frozen-v2.json)
  retains the old executed image separately; the
  [twelve-test controls qualification](evidence/isolated-browser-verification-controls-v2.json)
  is preserved too. A [final real-touch recheck](evidence/historical-examples-final-touch-revalidation.json)
  passes the exact historical grid and shooter, and correctly rejects the old
  card game's unreachable offscreen control. Historical bytes remain unchanged;
  an earlier controls-only pass does not establish current mobile eligibility.
- A built wheel installed in an isolated virtual environment outside the repository
  passed setup against fresh application data, migrations, Django checks and HTTP studio/resource delivery.
  Preview origin does not expose the studio API; local configuration is private
  (`0600`). [Clean installation evidence](evidence/clean-install-verification.json).
  The first installation attempt caught a broad `artifacts/` ignore excluding a
  source package; the ignore is now root-scoped and CI checks wheel installation.
  The updated installed package bundles all 98 current Python source modules and
  serves the final studio assets. Studio and an actual backup both honor the
  custom SQLite path from literal local configuration; access-log redaction was
  exercised through the installed preview listener. No neighboring donor
  directory is required. Future module changes require a refreshed inventory.
  [Config-first production-mode setup](evidence/config-first-install-verification.json)
  also passed twice: an existing configuration and redirected database root retain
  one fresh signing key at the configuration discovery path, with mode0600.
  The installed package also passed actual two-service Gunicorn startup with
  debug disabled, healthy studio and denied preview API; access logs omitted
  query capabilities. [WSGI evidence](evidence/wsgi-install-verification.json)
  covers local HTTP, not TLS/reverse-proxy or public deployment.
- The live demonstration store was backed up and restored into a new PostgreSQL
  database: three jobs/candidates/reports, twelve recorded calls and two eligible
  revisions survived, with exact source/spec identity.
  [Actual demo restore evidence](evidence/live-backup-restore-verification.json).

The large official Playwright image download failed locally with a truncated
layer. All claimed local browser results used the explicitly labelled slim
Chromium alternative, with the actual executed image bound to every report.
Remote GitHub CI is configured but has not been run in this local task.

## Acceptance interpretation

The [first frozen comparison](evidence/frozen-comparison-v2.json) completed all
twenty fresh runs with `gpt-6-astra` through the authenticated Codex adapter.

| Measured result | Single author | Four authors |
| --- | --- | --- |
| Fresh bases passing isolated gates | 5/10 | 0/10 |
| Selected revisions passing | 2/3 | No successful base |
| Fresh provider-reported tokens, including cached input | 750,648 | 740,112 |
| Fresh calls with reported usage | 40 | 30 |
| Median fresh run duration | 186.262 seconds | 244.471 seconds |
| Unknown usage in these fresh runs | 0 | 0 |

The three single-author revisions used another 171,395 reported tokens and nine
calls. Summed durations in the evidence are per-run durations, not elapsed wall
time for concurrent groups. Passing a first submitted candidate can follow
several author responses and local quick-check corrections; it is not a claim
that the first model response was correct.

Four-author reservations exhausted concurrency headroom before a
candidate could be submitted. These results describe this implementation,
provider/model and budget; they do not establish that four authors cannot produce
a game. The original unmodified planner timeout above is a separate experiment.

Observed platform defects were fixed only after that comparison ended: overly
broad import/export text checks, binding input before appending a same-document
control, missing explicit semantic bounds in planner guidance, and simultaneous
four-author reservations. A separate negative test also exposed invisible native
toolbar controls passing browser checks. The updated validator checks rendered
Start/Restart/status at startup, outcome and restart. Historical results remain
immutable; the chosen implementation is evaluated in a separate fresh release run.
Qualification also caught a causal-input race: separate reset/freeze browser calls
allowed animation ticks between equal-seed timelines. Reset and clock freeze now
share one browser call; the broken-keyboard negative fails the input gate itself.
An additional real-touch review found that the old shared `touch-action:none`
blocked scrolling a long card game. Locator auto-scrolling had hidden the defect.
The [superseding mobile assessment](evidence/mobile-scroll-gap-review.json)
qualifies the historical card example. The attempted runtime0.4 release was
retired with its calls and interrupted state preserved: seven known calls,
126,319 reported tokens and zero unknown usage. The
[interrupted-run record](evidence/chosen-native-release-v3-interrupted.json)
and [exact source snapshot](evidence/interrupted-v3-source-snapshot.json)
remain separate from the final release denominator. Runtime1.0.5 allows ordinary
vertical scrolling while preserving Canvas and explicitly scoped dragging;
real swipes qualified offscreen controls before the final fresh release run.
The [post-comparison diagnostics](evidence/generation-defect-diagnostics.json)
include one bounded planner call proving eight `wait.ms` values violated the
unchanged 1,000-millisecond schema maximum. The full authoritative schema is now
included in planning guidance; provider wire-schema compatibility does not weaken
local validation. Diagnostics are not added to fresh-game success denominators.

The release suite is `modest-five-mechanics-v2-public-interface`, derived from
the preserved v1 suite. Visible control IDs and the common terminal phase were
frozen before comparison so both strategies receive the same interface and
validator-owned recipes. No genre mechanics are supplied as prewritten templates.
Two fresh runs of each of five cases are evaluated per strategy, with at most two
additional candidates, a shared 600-second deadline and a 180,000-token admission
budget. The first
successful base per case receives a meaningful revision. All failed attempts
remain in denominators; resumed responses are labelled and do not become new calls.

## Final chosen implementation

The [complete native v4 evaluation](evidence/chosen-native-release-v4.json)
used runtime1.0.5 and the final executed validator image above. All five case
groups used identical 39 source fingerprints. The
[preserved release snapshot](evidence/chosen-native-release-v4-source-snapshot.json)
binds the executed package, including all 223 production/resource/studio files,
to the launch protocol. No production source or prompt was changed during this
measurement, and no failed run was replaced.

| Case | Fresh games passing | First-success revision |
| --- | --- | --- |
| Runner | 2/2 | Visual contrast revision passed |
| Grid puzzle | 2/2 | Three-to-four-beacon mechanic change failed before candidate submission |
| Shooter | 1/2 | Visual revision passed |
| Card game | 2/2 | Visual/larger-hand revision passed |
| Held-out drag/drop | 0/2 | Unavailable: neither base passed |
| Total | **7/10** | **3/4 attempted; fifth case unavailable** |

All seven successful bases and three successful revisions passed their first
submitted candidate. Local author turns and quick-check corrections precede
some submissions. Fresh games used **835,127 provider-reported tokens and 43
calls**, with a median duration of **202.361 seconds**. Revisions used another
**230,514 tokens and 11 calls**, with a median of **162.214 seconds**. Total
known usage was **1,065,641 tokens / 54 calls**, including cached input; unknown
usage in this release was zero. Concurrent per-run durations do not sum to
elapsed wall time.

The unsuccessful shooter generated a minimum-width field clipped on the narrow
viewport, placing the third target's prescribed center outside the visible play
area. The target could be hit at its visible edge in a separate actual touch
challenge; this does not repair the failed mobile interface/layout requirement.
Further repair stopped when its next reservation no longer fit the run budget.
Both drag games declared storage but omitted the required game-level
`exportSave`/`importSave` functions, so the trusted save bridge correctly rejected
them at both widths. The second also failed mobile completion after an observed
canceled green drag; that gesture's cause remains unresolved. Repairs stopped
on repeated identical tool calls for the first and reservation headroom for the
second. The grid mechanic revision recorded `ProviderError` before submitting a
candidate; its more specific cause was not retained and is not inferred. Every
failed candidate, receipt and report remains preserved, and successful parents
remain usable.

The internal G4 target is **not met**: 7/10 is below 8/10, the held-out case has
no success, and the five-case revision target is incomplete. The successful
revisions establish observed visual editing; this release has no successful
shared-mechanic revision in the frozen matrix. Mandatory failures were rejected
and are not showcased as eligible games. Implementation of the planned product
path is complete; contest acceptance and reliable generation across these
mechanics require further work.

Token reservations control admission of new calls; actual terminal receipts
reconcile spend. Ten planning calls exceeded their estimates by 369–3,159 tokens,
including a measured 18,122-token receipt against a 17,197-token reservation.
No observed v4 run exceeded 180,000 total tokens. These observations do not make
the CLI's reservation estimate a guaranteed provider billing cap. Two rejected
reservations never started and are separately recorded as zero-cost operations.

The [single four-author feasibility supplement](evidence/adaptive-four-author-supplement-v4.json)
used the same frozen sources, model, grid-puzzle request and budgets. It failed
after one planner call: 25,809 known tokens and 141.098 seconds, with zero unknown
usage. Semantic validation rejected a transition from an undeclared state before
any author or browser ran. Thus the adaptive author batching fix remains covered
by deterministic tests, not demonstrated by this live supplement. This one-case
result is separate from both the original comparison and the native denominator.

An [unchanged-fixture storage supplement](evidence/storage-denial-runtime-supplement.json)
passed 42 checks across desktop/touch contexts with denied storage, quota failure,
and an actual opaque sandbox iframe. Load returned null and save returned false;
ordinary gameplay and restart remained usable without a false saved claim. This
qualifies runtime behavior for that authored fixture; it does not turn either
failed fresh storage game into a success.

Mechanical conformance establishes input effects, terminal state and restart in
the tested browser. It does not alone prove that a model implemented every game
rule correctly or produced an enjoyable game. Separate source/visual review
assesses requested rules, clarity, layout and presentation. The review performed
here was by an independent AI reviewer; actual participant assessment and audible
sound quality remain unmeasured, even when the container verifies the real audio
graph.

The contest WebView host is **unknown**, confirmed by the user. Chromium touch
emulation, synthetic visibility events and desktop screenshots do not close that
acceptance item. Once the host is named, test offline load, actual touch/drag,
viewport/focus, pause/resume, restart and applicable audio/storage there.
The studio preview uses an opaque origin and denies browser persistence; it shows
that restriction. A game must handle a denied write honestly and remain playable.
Downloaded HTML storage remains conditional on the actual host.

## User playtest and diagnostic follow-up

The user found the tiny evaluation examples too limited for the desired product.
The fixed suite measures minimum mechanics and infrastructure, not the quality
bar for a convincing contest game. The next quality assessment must use the
user's richer requests and actual play feedback; the existing modest-case results
remain unchanged.

For that playtest the local studio, separate preview, Codex generator and Docker
validator are running against a separate persistent PostgreSQL database. A
diagnostic gap was fixed after the frozen evaluation: worker failures previously
retained only their exception category. They now log redacted reasons, schema
coordinates, bounded stack frames, job/stage/fence identities and model receipts.
A real idle connection reset also exposed a worker exit; claim transport failures
now reconnect with backoff, while revocation stops and paid calls are not replayed.
These worker-only changes are outside the frozen v4 generation measurement.

The updated suite passed 191 tests with resource warnings treated as errors;
15 unchanged Docker tests retain their separately executed evidence above.
Core coverage remains 90.05%; Ruff and Mypy pass. The updated wheel and source
distribution were built and package bytes checked; the earlier clean-install
evidence explicitly binds the preserved evaluated wheel, not this later build.
The live user-test configuration and private operational logs are described in
the [runbook](runbook.md#diagnostic-records). Automated browser traces do not
record the user's subsequent manual play session.

## Reproduction and demonstration

The [runbook](runbook.md) covers installation, PostgreSQL, two worker roles,
independent acceptance configuration, recovery, backup/restore and separate-origin
deployment. The default authoring path is single-author; four-author is an explicit
comparison mode. Single-author has delivered eligible games in both the original
comparison and the chosen-release suite; the measured quality gaps above remain
open. The original same-version comparison, current native release, and separate
four-author feasibility supplement have different evidence scopes and must not
be combined into a new strategy success-rate comparison.

[Saved live examples](examples/README.md) preserve exact reviewed successful
outputs, source/spec/report bindings and evidence inventories. They remain
clearly labelled saved; copying or replaying them is never counted as a fresh
generation. Independent AI source/visual review is recorded in
[chosen-release review evidence](evidence/chosen-release-human-review.json), separately from participant
playtesting, which has not occurred.

For a demonstration, create a new project, run generation and validation workers,
play the eligible result, restart, download the exact HTML, then request a
meaningful revision. A failed revision remains inspectable while the previous
eligible version remains selected. Saved examples must be labelled as saved.
Do not execute newly generated game JavaScript on the host to bypass Docker.
