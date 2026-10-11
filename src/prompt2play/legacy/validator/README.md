# Isolated optional runtime validation

The default worker performs source checks and `node --check` only. It does not
execute generated JavaScript on the host. These checks cannot establish that a
game works: a version remains `partial` when the isolated runtime gate is skipped.

On a runner with Docker, explicitly build the image from the project directory:

```sh
docker build -t game-forge-validator:local validator
python -m worker --server http://127.0.0.1:8000 --provider codex --validator docker
```

Activate the worker virtual environment first and configure the runner token as
described in `worker/README.md`. For the Responses API, replace `--provider codex`
with `--provider openai` and configure the API key/model locally. Use
`--validator-image IMAGE` if you have built a differently named trusted image.
The worker never pulls or builds an image automatically. If Docker, its daemon,
or the named image is unavailable, the report explicitly records a skipped gate
and `partial` validation. A runtime check that actually runs and fails is a failure.
`docker run --pull=never` enforces this even if the inspected image disappears.
Container output is spooled outside its input mount, size-checked while running,
and never accumulated without a bound in worker memory. Cleanup is attempted
even when the Docker client has already exited; client exit does not prove the
container has stopped. Empty, malformed or incomplete success reports fail.

`Dockerfile` pairs the Playwright 1.58.2 package with its matching official browser
image. At job time the container has no network, a read-only root filesystem,
read-only input mount, no added capabilities, no privilege escalation, a non-root
UID, bounded temporary storage, one CPU, 768 MiB RAM, and a 128-process limit.
No Docker socket, provider credentials, or coordinator token is mounted. Chromium
uses `--no-sandbox` inside this container; the container is the isolation boundary.
Docker is not equivalent to a VM boundary against hostile browser/kernel exploits;
run this optional validator on a dedicated disposable machine when appropriate.

The runtime checks desktop and mobile browser viewports, startup, the test bridge,
observable progress scenarios, deterministic reset, game-surface samples, audio-source
activity after a user gesture, JavaScript errors, and attempted external requests.
Audio activity requires an actual successful source `start()` whose scheduled
time has arrived in a running AudioContext. Allocating unused nodes does not
pass. The probe uses bounded private records and handles the prefixed constructor
alias without double instrumentation. It does not inspect samples or establish
audibility, connected gain paths, or musical quality.
Surface changes and audio-source activity are smoke signals, not proof of visual
quality, audible music, full game completion, or actual Android/iOS WebView behavior.
An inner browser timeout and outer process wall limit bound each validation run.

The original donor development notes recorded only static and host-side tests
with provider doubles. The contest release runner below has separate, executed
Docker/Chromium regressions; their exact image, browser and evidence hashes are
recorded in `docs/evidence/isolated-browser-verification.json`.

## Genre-neutral acceptance scenarios

The planner now declares `qa_scenarios`, each with `id`, `purpose`, `category`,
`seed`, `affected_files`, `limitations` and `steps`. Steps are JSON strings in
provider output; `validator.scenarios.validate_scenarios()` returns a decoded
copy. Source strings, JavaScript expressions, fixture injection and arbitrary
methods are not part of the language. A reviewer must still check that the
scenario observes a real rule and that the bridge uses the actual game path.

The common bridge adds `setManualMode(boolean)` and `reset({seed})`. In manual
mode, the RAF simulation clock stops; `advance(frames)` dispatches the same
fixed-step game action used by live play. It must not modify state directly or
implement a second simulation. Turn-based games use meaningful real actions and
need no `wait` action, player entity or continuously moving idle scene. Seeded
reset restores the declared deterministic initial state after the initial start
gesture, including a menu/preparation phase where specified. Scenarios dispatch
the actual start action when needed. Reset does not inject a fabricated snapshot
or bypass resource costs.

Supported steps:

| Step | Meaning |
| --- | --- |
| `{"op":"act","action":{"type":"..."},"repeat":1}` | Dispatch a real game action; repeat is optional |
| `{"op":"advance","frames":60}` | Advance a fixed-step game through its real update path |
| `{"op":"capture","key":"before"}` | Keep a copied snapshot for a later comparison |
| `{"op":"assert","left":{"path":"/gold"},"cmp":"lt","right":{"saved":"before","path":"/gold"}}` | Compare observed values |
| `{"op":"reset","seed":"seed-a"}` | Restart through the real UI path; seed is optional |
| `{"op":"click","selector":"#buy"}` | Click an actual DOM control in Chromium |
| `{"op":"focus","selector":"#target"}` | Focus a real DOM control |
| `{"op":"key","key":"ArrowLeft"}` | Send a browser keyboard event |
| `{"op":"serialize","key":"run-save"}` | Capture text from the actual `exportSave()` serializer |
| `{"op":"restore","saved":"run-save","expect":"accepted"}` | Import previously captured text through the actual `importSave(text)` path |
| `{"op":"restore","text":"","expect":"rejected"}` | Check explicit rejection of literal input, including a genuinely empty file |
| `{"op":"storage_fault","mode":"quota"}` | Make local storage method writes fail until a subsequent mode change or scenario cleanup |
| `{"op":"lifecycle","event":"hide"}` | Deliver synthetic visibilitychange/pagehide events with document.hidden=true |
| `{"op":"lifecycle","event":"show"}` | Deliver synthetic pageshow/visibilitychange events with document.hidden=false |
| `{"op":"lifecycle","event":"remount"}` | Await the real dispose/init path exposed as remount(), preserving the chosen save semantics |
| `{"op":"reload"}` | Reload the same intercepted HTML at the same isolated origin; no reset, seed change or start click |

Operands are JSON pointers, saved snapshot pointers, literal JSON values,
`{"sum":[operand,...]}`, `{"count":operand}` and read-only DOM observations
`{"element":"#target","property":"focused"}`. DOM properties are limited to
`focused`, `text`, `value`, `disabled`, `hidden`, `count`. Comparisons are
`eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `exists`. Missing properties cannot silently
pass `ne`, and ordering/sums require finite numbers. Paths cannot address
prototype properties. Every scenario needs both an operation and an assertion
that actually observes state or DOM. Literal-only assertions and comparisons of
an operand with itself do not count as game evidence; self-comparisons are rejected.
Keys named `path` or `element` inside a literal JSON value are still literal data.

This can express entity conservation (`spawned = killed + escaped + active`),
resource deductions, repeated input, pause invariance, seeded reset, import
rejection and focus preservation without fixing a genre. Delayed Promise races,
interleaving writes from multiple windows, real mobile multitouch and subjective
balance still require suitable specialized tests/review; no automatic claim of
that coverage is made.

Bounds: at most eight scenarios, 64 steps per scenario, twelve captures per
scenario, 3,600 frames per advance, 120,000 frames and 1,200 repeated actions per
suite. Persistence operations have an additional suite limit of 64. A scenario
may retain at most eight serialized saves, each at most 512,000 UTF-8 bytes, with
a 2,048,000-byte cumulative budget, and switch storage fault mode at most eight
times. JSON values/selectors/captures/output are bounded independently. Both
viewports execute the declared suite; the outer 90-second limit still applies.
Long scenarios can time out and report failure; there is no unlimited retry.
Lifecycle operations are limited to eight per scenario and 24 per suite; reloads
to two per scenario and eight per suite. Each lifecycle or reload operation needs
a subsequent observable assertion before the next lifecycle/reload/reset and
before scenario completion. Real actions and input can precede that assertion,
for example hide → attempt a move → assert unchanged → show → move → assert progress.
At least one operand in that assertion must read a live snapshot path without
`saved`, or a DOM property. Comparing only earlier captures and literals does
not observe the transition; a captured snapshot remains useful as the baseline
on the other side of a comparison with current state.

### Page lifetimes and actual document reload

The new optional bridge method is `remount() -> {ok:true}`. It must release the
current input listeners, timers, renderer and audio, then invoke the actual mount
path and re-read applicable persistence. It is not an alias for seeded `reset()`.
The bridge can retain its object identity, but must expose `ready:true` once the
new controller is ready. The interpreter then reapplies manual clock mode.
An absent method, false/empty completion result or unready controller fails.
The completion acknowledgement proves that a call returned; subsequent gameplay
and DOM assertions and source review are still needed to assess cleanup itself.

For `hide`/`show`, a trusted probe temporarily controls the document's observable
visibility and dispatches actual DOM events. It records each delivery and checks
the requested state. Scenario cleanup returns the probe to the native mode and
restores the live clock; failed cleanup fails the scenario. This is synthetic
delivery inside an isolated browser, not actual OS suspension, throttling,
process death, mobile backgrounding or BFCache behavior. Game code uses its usual
event handlers, not a separate test-only mutation of game state.

`reload` uses the browser's real document reload and repeats the harness-owned
response of the exact input HTML. It preserves origin storage and installs new
probes, then waits for `__GAME_TEST__.ready` without clicking start or calling
reset. The bridge therefore needs to become ready after initialization/restoring
even when the UI still shows a start menu. A scenario can subsequently choose a
real resume/start action if that is part of the planned flow. Unlike `restore`,
this operation really replaces the document. It does not simulate a browser crash
or prove storage durability on a physical device. To avoid silently losing probe
state, reload is rejected while synthetic hidden mode or an injected storage
fault is active: first use show/normal and observe the required transition.

The language deliberately does not add arbitrary JavaScript, arbitrary URLs,
snapshot injection, multi-window writers or delayed AudioContext promises.
Those last two remain specialized reference regressions and explicit review
limitations. Existing click/focus/key plus read-only focused/selected state
observations already express keyboard-selection and modal-return sequences.

### DOM, Canvas and hybrid presentation

`spec.presentation_mode` is `canvas`, `dom` or `hybrid`; a historical missing
value means `canvas`. New games identify the actual playing surface with
`data-testid="game-surface"`. Canvas mode requires that surface to be a real
visible canvas with nonzero backing dimensions; the legacy first-canvas fallback
remains available. DOM mode requires a visible non-canvas element containing game
markup. Hybrid mode requires an element containing a visible canvas and other
markup. A hidden dummy canvas is not a substitute for a DOM playing surface.
The surface and counted canvases must also have positive computed opacity through
their ancestor chain: Playwright's geometric visibility alone permits opacity:0.
The `opacity_chain_visible` observation is required by the receiving report gate.

`surface_size:<width>` records the declared presentation mode and measured
geometry; `surface_frames:<width>` records two screenshots of that surface,
their hashes, byte counts, interval and whether they differ. Both render modes
retain progress, real input, audio and scenario checks. An unchanged idle scene
can pass the capture check with a warning; neither changed samples nor nonzero
geometry are labelled animation quality, good layout or card legibility.

### Persistence paths and honest fault evidence

The optional bridge methods are `exportSave() -> string` and
`importSave(text) -> {ok:boolean}`. They are required when a scenario uses
serialization or import. They must invoke the game's real serializer, semantic
validator and controller replacement path. An exception escaping the importer is
a failed scenario, not a successful expected rejection. Empty input is passed
unchanged; the bridge must not substitute a previous save with `text || stored`.

Serialized text and captured observations have separate namespaces. A restore
expecting acceptance must reference a saved key previously captured by
`serialize`; literal text is allowed only with `expect: "rejected"`. This prevents
an invented healthy or wealthy state from substituting for the real gameplay
path. The interpreter enforces the same rule before calling the game importer.
A restore only establishes the observed acceptance outcome. Follow it with a comparison
against a snapshot captured before serialization to establish preservation of
the declared state domains. After rejection, compare the relevant game domains;
the UI can legitimately update an error message. Transient animation events may
be omitted from a stable gameplay observation when the contract explicitly says
they are discarded on load. Importing into the current document is not proof of
a page reload, browser crash recovery, or cross-process durability.

`storage_fault` accepts `normal`, `quota`, and `denied`. The trusted probe is
installed before the game in the isolated document. Quota mode blocks
`localStorage.setItem`, preserving reads and deletion. Denied mode rejects new
access to `window.localStorage` and calls through an already cached local Storage
object. Session storage is unaffected. The probe instruments `getItem`, `setItem`,
`removeItem`, `clear`, `key`, and `length`; named-property writes such as
`localStorage.save = text` are not instrumented and cannot satisfy this fault
coverage gate.

Each non-normal interval must actually reach an injected failure: quota needs a
blocked write, denied needs a blocked access/read/write/removal. Merely toggling
a fault and asserting an unrelated field fails. Evidence records interval-specific
blocked operation counts in `storage_faults`; it does not expose saved text.
The scenario must separately assert that the live game remains usable and that
its UI does not claim durable success. Cleanup returns storage to normal and
restores the live simulation clock. A cleanup failure also fails the scenario.

The browser receives the exact game HTML as an intercepted response at
`https://game-forge.invalid/index.html`. This gives it a normal isolated origin
for local storage. The harness fulfills its initial navigation and explicitly
requested, bounded reloads locally; all other requests are aborted and remain
evidence of prohibited networking.
Docker still has no network. No web server is started or external site contacted.
The route and browser integration are authored but have not been executed in the
development environment; host tests exercise the trusted probe with explicit
Storage doubles.

For v3 specifications, `semantic_coverage` binds the first useful play loop and
declared transaction/progression/persistence obligations to their scenario IDs.
This is a **static declaration check**, labelled `status: declared` in its
evidence. Its passing status does not promote skipped runtime scenarios to
passed. Historical v2 reports are not silently upgraded to v3 coverage.

## Evidence binding and truthful results

Every v2 report includes an `artifact` manifest: exact UTF-8 HTML bytes/hash,
per-module hashes and a hash of the final specification (including frozen
execution settings). Every check has `check_kind`, `artifact_sha256`, explicit
limitations and bounded observations. The extracted final inline script is
compared to the actual assembler output before it is parsed. A changed HTML,
source or specification invalidates the old report.

A static run reports declared scenarios as **skipped**. It never promotes valid
scenario JSON or a model's review to successful execution. The browser runner
returns the exact input manifest plus the hash of its request file. The worker
rejects stale requests, duplicate check names, wrong check kinds and absent
scenario results. Each name is also bound to its kind, scenario ID and supported
viewport, including in reports that already contain another failure. A browser
check slot cannot be relabelled as a passing scenario. Reports are separate from
model review provenance.

The current container protocol additionally requires `runtime_contract_version=2`
in its request and response. Rebuild the explicitly configured image after
upgrading the validator; an old image cannot certify a new lifecycle/surface
request. This protocol version is separate from the artifact report schema2 and
semantic contract version3.

Every passing scenario must report positive completed steps and assertions. In
production these and all action/frame, capture, input, reset, serialization,
restore, fault, lifecycle and reload counts must exactly match the decoded
requested sequence. Seed/category, actual visibility observations, completion
acknowledgements and successful cleanup must also match. A non-normal storage
interval needs the corresponding positive blocked-operation observation.
An empty or shortened success report fails even when another check already
reports an error. Failed scenarios can legitimately contain partial counters.
These bindings validate the execution record; they do not turn a weak assertion
into a comprehensive game test or prove that model-written bridge code is faithful.

The production Playwright transport lives in `bridge_adapter.mjs`. Game
`snapshot()` remains synchronous and returns a JSON object: a Promise cannot be
serialized into an empty apparent state. The transport checks the object shape
before and after serialization, keeps null-prototype JSON objects valid and
returns detached bounded data. Original members are checked even after `toJSON`
conversion: nested Promise/Map/Set/Date and class instances cannot silently
disappear into `{}` or change into strings. Ordinary cross-realm JSON objects
remain supported by the authored reference harness. `importSave()` must return an object with a boolean
`ok`; arrays and functions carrying an `ok` property are not normalized into
successful outcomes. Empty import text still reaches the real importer unchanged.
Array observations use JSON indices or the DSL `count` operand. JavaScript
`Array.length` is metadata and is not exposed as a JSON Pointer member.

The browser records two sampled game-surface hashes and whether they differ.
A static idle turn-based scene is not rejected for lacking continuous movement;
unchanged samples produce a warning. This measurement alone is not a successful
animation-quality test. The separate seeded reset check compares real snapshots,
and state progress depends on declared observable assertions when scenarios are
available.

Before smoke actions, the browser observes the visible master control identified
by `data-testid="sound"`. A button must expose `aria-pressed="true"/"false"`;
a native checkbox/radio exposes `checked`. The harness clicks only a control
observed to be off and waits for its enabled state. It never blindly toggles an
already-enabled control or fabricates game events to create audio. The subsequent
real smoke actions should include an actual sound-producing gameplay action.
Missing/unknown control state is a contract failure for v2, and a skipped check
for legacy sources. The activation decision, gesture and subsequent audio-source
observation are reported separately. Trusted helper tests exercise those decisions
with doubles; they are not evidence of real browser audio.

Development verification used the trusted interpreter against handwritten fake
adapters (terminal accounting, focus loss, pause, save roundtrip, invalid import,
duplicate claims, storage failure and recovery), the method-level storage probe
against a Storage double, the same production bridge transport against an explicit
page double, canonicalization checks and container process doubles.
Save loss, blank-input fallback, mutation on rejected import, false durable
status, unexercised fault declarations, non-finite snapshots, oversized UTF-8
saves and failed cleanup are negative cases. These are original donor regression
notes. The contest isolated browser results are recorded separately below and
in `docs/evidence/isolated-browser-verification.json`. The production interpreter
is copied into the isolated image and never runs untrusted model code on the
coordinator or worker host.

## Contest validation boundary

The adopted legacy harness above remains available for baseline regressions.
The contest application calls `prompt2play.validation.IsolatedValidator`; it
always executes `release_runtime.mjs` in the explicitly built isolated image.
There is no host evaluation fallback. An unavailable daemon, absent image,
missing acceptance mapping, or required skipped check produces `unverified`.

Build the pinned official image from this directory, or the documented Debian
Chromium development alternative when the official registry is unavailable:

```sh
docker build -t prompt2play-validator:local src/prompt2play/legacy/validator
docker build -f src/prompt2play/legacy/validator/Dockerfile.slim -t prompt2play-validator:local src/prompt2play/legacy/validator
```

The image is inspected and run by its immutable SHA-256 ID. Every harness/probe
source digest is compared inside the container before executing a game; stale
images fail. The runner disables network, drops capabilities, uses a read-only
root filesystem, sets memory/CPU/PID/deadline limits, and mounts only immutable
input plus a separate private evidence directory. Actual screenshots, console
and denied network records, and a Playwright trace are preserved and verified
against their exact byte hashes before the validator-role API uploads them.

For native `runtime-v1`, model input descriptors guide real key/pointer/touch
operations. Independent platform checks use known start/restart controls, a
fixed `snapshot.phase` terminal oracle (`won` or `lost`), visible trusted terminal
status, game-surface changes and a frozen clock around each input observation.
Real-time actions receive fixed ticks and are compared with an equal-seed replay
that omits the current input while advancing the same ticks. This accepts delayed
physics changes while preventing idle animation from standing in for input.
Pixel comparisons ignore at most 8 levels of channel quantization noise and
require at least 16 materially changed pixels for visible input progress; the
no-input snapshots and state comparisons remain mandatory. PNG hashes still
bind the original recorded evidence bytes. Responsive drag endpoints can use `from_selector` and `to_selector`.
Native sources cannot directly write the test bridge, native toolbar or raw
timers. New runtime hooks have an immutable version/digest identity, but game
and bridge share a browser realm: these observations are not proof against
deliberately falsified state, and human mechanics review remains required. A frozen
external acceptance configuration can supply the release scenarios instead.
Legacy candidate-authored conditions alone remain diagnostic and unverified.

Audio and persistence are checked only when requested. Storage checks round-trip
a genuine played save and reject malformed input without state mutation.
Synthetic visibility events are explicitly labeled; desktop Chromium and touch
emulation never count as a real Android/iOS WebView or OS backgrounding test.

Opt-in isolated regressions (use a fresh evidence directory for every run):

```sh
P2P_RUN_ISOLATED_BROWSER=1 P2P_BROWSER_EVIDENCE=/tmp/p2p-browser-run-unique .venv/bin/python -m pytest tests/test_validation_browser.py -o addopts=''
```

The development Chromium image uses an ALSA null output sink to run the real
Web Audio graph without physical speakers, so only source scheduling is claimed.
The runner allows up to 256 processes/threads: Chromium audio initialization
exceeded 128 in an observed regression; CPU, memory and wall-time remain bounded.
