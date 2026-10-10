# CLAUDE.md — Claude Code Instructions for Prompt2Play

Read `AGENT.md` first. It defines the product contract, security requirements, validation criteria, and general engineering workflow. This file adds Claude Code-specific working instructions.

## Objective
Help ship an end-to-end **text-to-playable-HTML5-game** hackathon prototype. Each feature should move the system closer to: **enter prompt → generate game → validate it → preview/play in a WebView**.

## Starting a task
1. Inspect the repository (`README`, manifests, source tree, tests) before recommending technologies or making changes.
2. Respect existing implementation choices. The layout in `AGENT.md` is a suggestion, not a command to restructure the repo.
3. For multi-file or architectural work, give a concise plan with intended files and how success will be verified.
4. Ask only questions that block implementation; otherwise make conservative, reversible assumptions and state them.

## Implementation behavior
- Prefer the smallest end-to-end implementation that demonstrably works.
- Keep the generation pipeline explicit: **specification → plan → code generation → validation → bounded repair → artifact**.
- Prefer schema-constrained LLM responses for plans and manifests. Validate all external/model inputs.
- Do not treat model output as trusted code. Keep generation and browser execution isolated from application privileges.
- Use predictable artifact paths and safe filenames. Never overwrite user files or access directories outside the authorized workspace.
- Make model calls configurable; do not hardcode API keys, model names, or pricing assumptions.
- When possible, keep generation provider-independent via a small adapter interface.
- Do not introduce an agent framework, database, queue, or frontend framework without a concrete need.
- Build touch-friendly, offline-capable games without runtime external asset dependencies by default.
- Keep prompts/templates under version control when their behavior affects generation quality.

## Tool and command discipline
- Read before write; search for established conventions before adding new utilities.
- Run safe, targeted checks after changes (lint, typing, tests, build) using commands found in the repository.
- For generated games, use browser automation if available to check rendering, console errors, and input behavior. A successful build alone does **not** prove playability.
- Do not claim to have run a tool or test unless it was actually executed.
- Do not run destructive commands, clear caches, install unnecessary global dependencies, or change environment configuration without justification.
- Keep credentials out of logs, generated output, example fixtures, and commits.

## Quality and acceptance
For each feature, aim to verify:
- A user can supply a prompt to the API/UI.
- The returned bundle contains a working `index.html` and any referenced local files.
- Browser load produces no blocking errors or missing assets.
- Game rendering and at least one control input work in a desktop and mobile-sized viewport.
- Validation errors trigger a bounded, observable repair attempt or a clear failure report.
- Artifacts can be previewed without granting generated code access to application secrets.

Mark checks not actually executed as **not verified**.

## When asked to implement a generated game
Deliver:
1. A self-contained runnable HTML5 game (or local bundle with `index.html`).
2. Clear controls and start/restart behavior.
3. Responsive rendering with touch support.
4. No required runtime CDN calls or external images unless requested.
5. A quick manual smoke-test checklist and the actual automated test results, if any.

Prefer Canvas/vanilla JS for straightforward arcade games. Use libraries only for a specific gameplay need.

## When asked to improve the generation system
Prioritize in this order:
1. Fix broken end-to-end flow.
2. Add observability (traceable stages, failures, browser evidence).
3. Improve structured game specifications and targeted repair.
4. Expand supported mechanics and themes using reusable templates.
5. Optimize latency, model usage, and UI polish.

Measure improvements using a small golden-prompt suite. Good examples include a tap-to-jump runner, a grid puzzle, and a simple space shooter. Check actual playability, not just syntactic validity.

## Response format after coding
Provide a compact summary with:
- **Changes:** files modified and key behavior.
- **Verification:** commands/browser checks executed with pass/fail status.
- **Remaining issues:** known limitations and skipped checks.
- **Next step:** the single highest-value follow-up.

Be precise about what is built versus proposed. Optimize for a strong live hackathon demo, not architectural complexity for its own sake.
