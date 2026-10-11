# CLAUDE.md — Claude Code Instructions for Prompt2Play

Read [AGENTS.md](AGENTS.md) first. It contains the repository-wide product
contract, security boundary, engineering standards, and definition of done.
This file adds instructions specific to Claude Code and does not override the
repository guide.

## Objective

Move Prompt2Play toward a demonstrable end-to-end flow:

> enter a prompt → generate a game → validate and repair it → preview and play

Every implementation task should improve that flow or provide evidence that it
works.

## Starting work

1. Inspect the repository before proposing a stack or changing architecture.
   Read the README, manifests, relevant source files, tests, and local
   `AGENTS.md` files.
2. Follow [ADR 0003](docs/adr/0003-hybrid-adoption.md) and the phase dependencies in
   [the development plan](docs/development-plan.md). The target layout is guidance,
   not a request to reorganize working code or recreate superseded stack choices.
3. For architectural or multi-file changes, provide a concise plan that names
   the intended files and verification steps.
4. Ask only questions that block safe implementation. Otherwise, use a
   conservative and reversible assumption and state it.

## Implementation approach

- Prefer the smallest vertical slice that works from user input to observable
  output.
- Keep pipeline stages explicit: specification, plan, generation, validation,
  bounded repair, and packaging.
- Request schema-constrained model responses where supported and validate every
  external or model-produced value.
- Treat generated source as untrusted. Keep model generation separate from
  browser execution and application privileges.
- Use predictable artifact directories and sanitized filenames. Do not overwrite
  user files or read outside the authorized workspace.
- Keep provider and model selection configurable through a narrow adapter.
- Do not add an agent framework, database, job queue, or frontend framework
  without a concrete requirement.
- Make generated games touch-friendly and self-contained by default.
- Keep behavior-critical prompts, templates, schemas, and fixtures under version
  control.
- Preserve evidence boundaries during adoption: recorded source is not a fresh
  model result, static-only validation cannot deliver a ready game, and historical
  passes cannot validate changed code. Keep failed candidates and prior playable
  revisions separate.

## Tool discipline

- Read before writing and search for existing conventions before adding a new
  utility.
- Use repository-local commands and dependencies. Do not install global tools or
  alter machine-wide configuration.
- After a change, run the smallest relevant lint, type, test, or build command
  documented by the repository.
- When browser tooling is available, use it to check rendering, console errors,
  local resources, input, and restart behavior. A successful build alone does
  not establish playability.
- Never report a command, browser check, or model call as completed unless it was
  actually run.
- Avoid destructive commands and unrelated cache clearing.
- Do not expose credentials in command output, generated games, fixtures, logs,
  or commits.

## Feature acceptance

For an end-to-end feature, try to establish that:

- a prompt can enter through the API or UI;
- the result contains a working `index.html` and all referenced local files;
- the browser reports no blocking startup error or missing resource;
- meaningful content renders and at least one control changes game state;
- a mobile-sized viewport remains usable;
- validation failures cause a bounded, observable repair attempt or a clear
  failure result; and
- previewing generated code does not grant access to application secrets.

Mark anything not actually checked as **unverified**.

## Generated-game tasks

When asked to implement a game, deliver:

1. a runnable, self-contained HTML5 game or local bundle with `index.html`;
2. visible instructions and start/restart behavior;
3. responsive rendering and touch support;
4. no required runtime CDN or remote-image access unless requested; and
5. a short manual smoke-test list plus any automated results actually obtained.

Use Canvas and vanilla JavaScript for straightforward arcade mechanics. Add a
library only for a specific capability that would be costly or unreliable to
implement directly.

## Generation-system tasks

Prioritize improvements in this order:

1. repair a broken end-to-end flow;
2. add evidence and observability for pipeline stages and browser behavior;
3. strengthen structured specifications, validation, and targeted repair;
4. expand mechanics and themes through reviewed shared infrastructure and freshly
   generated rules, rather than a fixed catalog of genre templates; and
5. optimize latency, model usage, and interface polish.

Measure changes against a compact golden-prompt set, such as a tap-to-jump
runner, a grid puzzle, and a simple space shooter. Judge the playable result,
not only the validity of the generated source.

## Completion response

After coding, report:

- **Changes:** modified files and resulting behavior.
- **Verification:** exact commands and browser checks with outcomes.
- **Remaining issues:** known limitations and skipped checks.
- **Next step:** the single highest-value follow-up.

Distinguish clearly between implemented behavior and recommendations. Optimize
for a reliable live demonstration before architectural breadth.
