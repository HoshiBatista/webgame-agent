# Prompt2Play

Prompt2Play is an AI-powered platform that turns a natural-language description
into a complete, playable HTML5 browser game.

The intended experience is simple:

> describe a game → generate it → validate and repair it → play it immediately

## Project status

**Planning / repository bootstrap.** The product contract and initial
architecture are documented, but no application code or technology stack has
been selected yet.

This status is intentional: framework, provider, and deployment choices should
be made alongside the first end-to-end implementation rather than encoded as
unused scaffolding.

## MVP

The first demonstrable version should:

1. accept a game prompt;
2. turn it into a structured, validated specification;
3. generate a self-contained HTML/CSS/JavaScript bundle;
4. validate the bundle statically and in an isolated browser;
5. make a limited repair attempt when validation fails; and
6. expose a safe preview with an honest validation report.

A generated game is successful only if it renders, responds to input, and
supports an appropriate completion, failure, or restart flow.

## Design constraints

- Generated code is untrusted and must be isolated from secrets and application
  privileges.
- Games should work offline at runtime and avoid remote assets by default.
- Mobile WebViews and touch controls are first-class targets.
- Model providers and model identifiers must be configurable.
- Validation must measure playability, not only successful compilation.
- Repair attempts must be bounded and observable.

See [docs/architecture.md](docs/architecture.md) for component boundaries,
artifact shape, and the proposed delivery sequence.

## Repository contents

```text
.
├── AGENTS.md            # Repository-wide engineering and agent guidance
├── CLAUDE.md            # Claude Code-specific working instructions
├── CONTRIBUTING.md      # Contribution workflow and quality expectations
├── SECURITY.md          # Security policy and generated-code threat model
├── docs/
│   └── architecture.md  # MVP architecture and implementation sequence
└── README.md
```

Application directories will be added with the first working vertical slice.
The likely boundaries are an API, web interface, shared contracts, generator,
validator, templates, and tests; the final layout should follow the chosen
toolchain rather than this preliminary list.

## Getting started

There is not yet a runnable application. To contribute at this stage:

1. read [AGENTS.md](AGENTS.md) and [docs/architecture.md](docs/architecture.md);
2. choose work that advances the first end-to-end vertical slice;
3. document any new runtime, package-manager, or provider requirement; and
4. include tests and exact verification results with implementation changes.

Once a stack is selected, this section must be updated in the same change with
the exact install, run, test, lint, and build commands.

## Contributing and security

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a change. Do not publish a
suspected vulnerability in a public issue; follow [SECURITY.md](SECURITY.md)
instead.

## License

No license has been selected. Until a license file is added, the repository is
not offered under an open-source license.
