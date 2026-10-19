# ADR 0004: Role-specific containers and a single nginx edge

- **Status:** Accepted
- **Date:** 2026-10-12

## Context

The Python package is a modular monolith, but its API, model generation,
workflow dispatch and browser validation have different dependencies and trust
requirements. A shared Compose `env_file` previously made every role eligible
to receive provider credentials, and publishing FastAPI beside the frontend
bypassed a single place for rate limits and security headers.

## Decision

Keep one application package and build it into independent Docker targets:
`api`, `migration`, `model-worker`, `workflow-worker`, `beat` and
`validation-worker`. Only the validation target installs Chromium. Only the
model worker receives the selected provider credential and joins the
`model-egress` network.
Validation, API and workflow roles use the internal backend network; validation
and API mount artifacts read-only.

Publish only the unprivileged nginx/React container. It reverse-proxies FastAPI,
SSE, preview and share routes over the internal network, applies edge limits and
serves immutable frontend assets. Public TLS terminates at the deployment
ingress or load balancer, while nginx honors forwarded HTTPS provenance for
HSTS.

Do not add an internal AI HTTP service. Celery queues already provide the
required asynchronous isolation, time limits, retries and independent scaling.
An HTTP boundary would add authentication, schema versioning and another
availability dependency without establishing a new current owner or consumer.

## Consequences

- Provider credential exposure and outbound network access are limited to one
  role.
- API and lightweight workers no longer carry Chromium system packages.
- Browser validation has defense-in-depth egress denial beyond Playwright
  request interception.
- nginx is the only host-facing port and the single operational edge policy.
- More Compose services and Docker targets must be built and health-checked.
- A future independent model platform can replace the model worker behind the
  existing `ModelGateway` only after an actual cross-product requirement.
