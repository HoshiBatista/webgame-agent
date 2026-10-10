# Prompt2Play MVP Architecture

## Goal

The MVP converts a natural-language request into a playable HTML5 game and
provides evidence that the result loaded, rendered, and responded to input. It
must fail safely and explain what went wrong when it cannot produce a valid
artifact.

## System flow

```text
Prompt
  │
  ▼
Validated game specification
  │
  ▼
Implementation plan
  │
  ▼
Generated local bundle ───────┐
  │                           │
  ▼                           │ targeted, bounded repair
Static and browser validation ├──────────────────────────┘
  │
  ▼
Artifact + validation report + isolated preview
```

Each transition should accept and return a typed value. The orchestrator owns
stage order, cancellation, deadlines, and the repair-attempt limit.

## Component boundaries

### Contracts

Shared schemas define the prompt request, game specification, generation plan,
artifact manifest, validation findings, attempt history, and final result. All
external and model-produced structured values are validated at runtime.

### Generator

The generator builds provider requests from versioned prompts and templates. A
small provider interface should isolate authentication, model selection,
timeouts, cancellation, usage metadata, and provider-specific failures.

The generator writes only through an artifact-store interface. It does not
execute generated JavaScript.

### Artifact store

Every generation receives a unique directory below a configured artifact root.
The store accepts normalized relative paths, enforces size and file-count
limits, and returns a manifest. The initial implementation may use local disk;
the interface should not assume that local disk is permanent.

Suggested bundle shape:

```text
<artifact-id>/
├── index.html
├── game.js             # optional when scripts are not inline
├── styles.css          # optional when styles are not inline
├── assets/             # optional local assets
└── result.json         # specification, attempts, and validation summary
```

### Validator

Validation has two layers:

1. **Static checks:** required files, allowed paths, size limits, local-resource
   references, and obvious prohibited behavior.
2. **Browser checks:** isolated load, console and page errors, missing resources,
   meaningful rendering, basic interaction, restart behavior, and a
   mobile-sized viewport.

Browser evidence should include structured findings and, when practical,
screenshots and captured console output. A syntax-only result must not be called
playable.

### Repair loop

Repair receives the current artifact and specific validation findings. It asks
for the smallest targeted correction, creates a new attempt record, and reruns
the relevant checks. A low, configurable maximum prevents open-ended model use.

### API and web interface

The API accepts a prompt, starts generation, exposes status, and returns the
result without leaking internal paths or secrets. The web interface collects
the prompt, shows pipeline progress and failures, and embeds only the isolated
preview origin or sandbox.

The MVP may run work in-process if generation duration permits it. Introduce a
queue only after real latency, reliability, or concurrency requirements demand
one.

## Security boundaries

Generated code must not share privileges with the API or web application. In a
deployment, prefer a separate preview origin and validation worker with no
secrets, no trusted internal-network access, a read-only or disposable
filesystem, and strict time and memory limits.

Preview policy should deny network access by default. If later features require
remote assets, make access explicit and allowlisted rather than broadly enabled.

## Observability

Record a correlation identifier and structured events for each pipeline stage:
start, completion, duration, outcome, attempt number, validation findings, and
provider usage metadata when available. Redact prompts and model output unless
their retention is explicitly safe and necessary.

## Golden prompts

Maintain a small regression set covering different interaction styles:

- a tap-to-jump endless runner;
- a keyboard-and-touch grid puzzle; and
- a pointer-controlled space shooter.

Each fixture should define observable acceptance checks instead of relying on a
snapshot of generated source.

## Proposed implementation sequence

The Python package, dependency lock, quality tools, and CI matrix are in place.
Continue with the product in this order:

1. Define schemas and a deterministic fake model provider.
2. Implement artifact creation and a single self-contained game fixture.
3. Select the smallest suitable HTTP framework and add API orchestration.
4. Add static validation.
5. Add isolated browser validation with captured evidence.
6. Add one bounded repair attempt driven by structured findings.
7. Add the prompt UI and safe playable preview.
8. Run the golden prompts and document demo limitations.

The first slice should use a fake provider or fixture so the pipeline can be
tested without credentials, cost, or network variability. A real provider can
then be added behind the same interface.

## Decisions still open

The bootstrap intentionally leaves these choices unresolved:

- HTTP framework and web-interface stack;
- model provider and default model;
- browser automation library;
- artifact persistence beyond local development;
- asynchronous job infrastructure; and
- deployment platform.

Resolve each choice when implementing the capability it supports. Record the
reason, alternatives, and operational consequences for decisions that are hard
to reverse.
