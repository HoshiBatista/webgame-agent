# Security Policy

## Reporting a vulnerability

Do not disclose suspected vulnerabilities in public issues, pull requests, or
generated game examples. Report them privately to the repository owner through
GitHub's private vulnerability-reporting feature when it is enabled. If that
channel is unavailable, contact the maintainer through a private channel listed
on their GitHub profile.

Include a concise description, affected component, reproduction steps, likely
impact, and any suggested mitigation. Do not include real credentials or data
that does not belong to you.

No response-time commitment is published while the project is in its bootstrap
stage. This section should be updated before a public deployment.

## Threat model

Prompt2Play processes three untrusted inputs:

1. user prompts and retrieved context;
2. model responses; and
3. generated HTML, CSS, JavaScript, and assets.

The main risks are prompt injection, path traversal, secret disclosure,
arbitrary code execution, network access from previews, denial of service, and
misleading validation results.

## Required controls

- Validate structured inputs and model responses against explicit schemas.
- Normalize artifact paths and prevent writes outside the assigned artifact
  root.
- Never pass raw prompt or model text to a shell.
- Run generated games in an isolated browser context with restrictive sandbox,
  Content Security Policy, network, and resource settings.
- Separate generation and validation workers from application secrets and
  privileged internal services.
- Give only the model worker an OpenAI project service-account credential and
  public egress; scope that credential to response creation where supported.
- Publish only the nginx gateway. Keep FastAPI, PostgreSQL, Redis and workers on
  an internal network, and terminate public TLS at the deployment ingress.
- Run runtime containers as non-root with a read-only root filesystem, dropped
  capabilities, `no-new-privileges`, bounded processes/CPU/memory and the
  narrowest artifact mount mode needed by the role.
- Bound generation size, execution time, repair attempts, browser resources,
  and retained artifacts.
- Redact secrets and sensitive prompt content from logs and diagnostics.
- Treat validation as evidence with recorded checks, not a guarantee of safety.

An iframe alone is not considered sufficient isolation.

## Supported versions

There are no released versions yet. Security fixes currently target the default
branch only.
