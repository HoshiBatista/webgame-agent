# Prompt-to-Game Landscape Review

## Purpose

This review identifies patterns worth adopting for Prompt2Play. Public product
pages establish visible capabilities, not private implementation details; any
architectural conclusion drawn from product behavior is labeled as an
inference. Research papers and open-source repositories provide stronger
implementation evidence.

Reviewed on 2026-10-10.

## Product systems

### Rosebud AI

[Rosebud](https://rosebud.ai/ai-game-creator) turns a plain-language idea into
browser-playable code, art, and sound. Its product loop is describe, generate,
play, revise by chat, remix, and publish. It exposes editable JavaScript,
supports 2D and Three.js games, and generates multiple asset types.

What to adopt:

- generation must remain editable after the first result;
- code, assets, preview, iteration, and publishing belong to one revision model;
- remix is naturally represented by immutable parent revisions; and
- asset provenance must be first-class if generated art and audio are added.

Inference: the smooth product loop matters more to users than the identity of a
single underlying model. Prompt2Play should preserve project state and revision
lineage rather than expose generation as a stateless endpoint.

### Astrocade

[Astrocade 2.0](https://www.astrocade.com/blog/astrocade-2-worlds-first-agentic-ai-game-creation-platform)
adds guided brainstorming, a game-specific generated edit mode, remixing, and
creator profiles.

What to adopt:

- separate idea refinement from code generation;
- derive editor controls from the structured game specification; and
- keep game metadata sufficiently structured to support remix and discovery.

Inference: a generated editor is feasible only when the platform understands
declared game parameters. Free-form source alone is not enough.

### Replit Agent

[Replit Agent](https://replit.com/products/agent) periodically tests its work in
a browser, produces a report, and applies fixes in a reflection loop.

What to adopt:

- browser validation is part of generation, not a post-processing utility;
- validation findings need to be shown to both the repair model and the user;
  and
- progress should stream as durable stage events.

The product does not publish enough implementation detail to justify copying
its internal architecture.

### Google DeepMind Genie 3

[Genie 3](https://deepmind.google/blog/genie-3-a-new-frontier-for-world-models/)
generates navigable worlds directly rather than exportable HTML game code. Its
documented limits include constrained action space, complex multi-agent
interaction, text rendering, and sessions lasting minutes rather than hours.

Conclusion: world models are a different product class. They may later help
with ideation, visual prototypes, or training data, but they are not the core
runtime for portable, inspectable, persistent browser games.

## Open implementations

### GameSmith

[GameSmith](https://github.com/AbdulHannan031/gamesmith-ai-game-generator)
uses Canvas2D and ES modules, a tool loop for files, skills, sprites,
playtesting, and visual inspection, and Server-Sent Events for its editor. Its
skill library is loaded on demand from concise summaries, and its agent limits
context through manifests and compacted tool results.

What to adopt:

- narrow model tools instead of a general shell;
- on-demand, versioned game-development skills;
- a small file manifest in model context;
- SSE for one-way generation progress;
- code-drawn graphics and WebAudio as the reliable offline default; and
- separate functional playtesting from screenshot-based visual review.

What not to copy directly:

- a single-process SQLite design is excellent for a local studio but is not the
  target for durable multi-tenant generation; and
- free-form file editing alone does not create a stable behavioral contract.

### BeyondPlay Game Prompt Engine

[Game Prompt Engine](https://github.com/BeyondPlay-AI/game-prompt-engine)
offers provider choice and produces self-contained, responsive HTML games with
touch controls and restart behavior.

What to adopt:

- provider-independent generation;
- self-contained export as a supported packaging target; and
- keyboard and touch behavior as baseline requirements.

What to improve:

- a one-shot single-file result needs independent validation evidence,
  revisions, and targeted repair before it can be called reliable.

### OpenGame

[OpenGame](https://github.com/0xinnovator/opengame) combines reusable Template
and Debug skills, a game-specialized coding workflow, Phaser, browser execution,
and multimodal evaluation.

The associated [paper](https://arxiv.org/abs/2604.18394) reports that removing
hook-driven template implementation reduced Build Health by 10.1 points and
Intent Alignment by 11.6 points in its ablation. Its evaluator separates Build
Health, Visual Usability, and Intent Alignment.

What to adopt:

- trusted templates with explicit extension hooks;
- mechanics-first template routing;
- a living but reviewed library of verified debugging knowledge; and
- distinct functional, visual, and intent metrics.

What not to copy directly:

- a specialized 27B model is unnecessary before Prompt2Play owns representative
  evaluation data; and
- model-specific CLI scaffolding should not become the product boundary.

## Evaluation research

### PlaytestArena and Play2Code

[GUI Agents for Continual Game Generation](https://arxiv.org/abs/2605.28258)
evaluates games through the same browser surface a player sees. Play2Code pairs
a coding agent with a GUI playtester and reports a 66.8% rubric pass rate,
improving over single-pass and agentic-coding baselines by 37.1 and 14.6 points.

Architectural consequence: repair feedback should come from interaction and
rubric evidence, not only source inspection. Prompt2Play should preserve shared
revision memory while keeping the number of repair rounds bounded.

### GameASG-Bench

[GameASG-Bench](https://github.com/areal-project/GameASG-Bench) separates a
player-visible game specification from a testing specification, then combines
source-level checks with headless Chromium behavior tests. Its public
`window.__gameTest` interface supports reset, scenario setup, input, and stable
state snapshots.

Architectural consequence: Prompt2Play should define its test bridge before
generation. The bridge is supplied by a trusted template, while generated game
hooks expose stable observable state.

### WebGameBench

[WebGameBench](https://arxiv.org/abs/2605.17637) judges complete delivered games
in a browser. Its reported best configuration achieved a 76.9% usable rate but
only a 20.2% excellent rate.

Architectural consequence: "loads and responds" and "is a good game" are
different quality levels. Prompt2Play needs separate release gates and metrics
for playable delivery, rubric satisfaction, and polish.

## Infrastructure patterns

### Typed model boundary

[PydanticAI](https://pydantic.dev/docs/ai/overview/) supplies typed structured
outputs, model adapters, tool schemas, usage information, OpenTelemetry
instrumentation, and durable-execution integrations. It is a good adapter
implementation, but Prompt2Play retains a project-owned `ModelGateway` so model
framework details do not leak into the domain.

### Task execution and workflow state

[Celery](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/)
supports Redis as a stable broker and provides routing, retries, monitoring,
worker pools, and Canvas primitives. It has a mature Python ecosystem and keeps
the initial operating model smaller than a dedicated workflow platform.

Celery delivery is intentionally treated as at least once. Its
[task documentation](https://docs.celeryq.dev/en/stable/userguide/tasks.html)
notes that late-acknowledged tasks can run more than once after worker failure
and therefore must be idempotent. The workflow state belongs in PostgreSQL, with
expected-state transitions and a transactional outbox; a Celery result graph is
not durable product state.

[Celery's Redis guide](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/redis.html)
documents visibility-timeout redelivery, dedicated broker databases, AOF
persistence, key prefixes, and the need to prevent eviction. Prompt2Play sends
only small identifiers through Redis and keeps large artifacts on its
content-addressed persistent filesystem. Long-running queues use late
acknowledgement, a prefetch multiplier of one, and task limits below the
visibility timeout.

### Browser validation

[Playwright browser contexts](https://playwright.dev/python/docs/api/class-browsercontext)
provide isolated non-persistent sessions, viewport and mobile emulation, error
events, screenshots, traces, and input automation. Its
[network routing](https://playwright.dev/python/docs/network) can abort and log
requests, and its documentation notes that service workers should be blocked
for reliable interception.

Request interception is not a complete sandbox. In particular, offline browser
emulation does not necessarily stop WebRTC traffic. Network egress must also be
denied outside Chromium.

### Execution isolation

[gVisor](https://gvisor.dev/docs/architecture_guide/intro/) is designed to run
untrusted code and integrates with OCI tooling through `runsc`. It adds a kernel
boundary beyond an ordinary container. Use it, or an equivalent microVM-backed
managed runner, for production browser validation.

### Artifact storage and telemetry

A content-addressed persistent filesystem is sufficient for the initial and
target deployment model. Atomic same-filesystem renames publish completed
revisions, while read-only mounts separate validation and preview from writers.
PostgreSQL stores lineage and references, not binary bundles. Quotas, retention,
off-host backups, and restore tests replace object-store lifecycle features.

The application still owns an `ArtifactStore` interface so storage mechanics do
not leak into generation, validation, or publication logic.

[OpenTelemetry](https://opentelemetry.io/docs/concepts/signals/) gives a
vendor-neutral correlation layer for traces, metrics, and logs across API,
workflow, model, storage, and sandbox boundaries.

## Synthesis

The strongest combined design is:

1. an explicit PostgreSQL-backed workflow dispatched through Celery rather than
   a free-running swarm;
2. mechanics-first routing to trusted, versioned template hooks;
3. a structured specification with rubrics and test scenarios created before
   code;
4. narrow file, skill, asset, and quick-check tools inside generation;
5. immutable revision lineage and content-addressed artifacts;
6. layered static, deterministic bridge, black-box browser, and visual checks;
7. bounded targeted repair from typed findings;
8. a separate sandboxed execution plane and isolated preview origin; and
9. a golden-prompt evaluation flywheel measuring playability, quality, cost,
   and latency.

Within a generation stage, a bounded harness produces one candidate through
narrow file tools. Candidate commit, authoritative validation, and repair
selection remain application-owned so the harness does not become a second
workflow engine.

No reviewed system demonstrates that unconstrained one-shot generation or a
large collection of autonomous agents is the reliable path. The evidence favors
strong runtime structure plus actual play.
