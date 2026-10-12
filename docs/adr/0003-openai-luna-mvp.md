# ADR 0003: OpenAI GPT-6 Luna for the hackathon generation path

- **Status:** Accepted
- **Date:** 2026-10-12

## Context

The hackathon implementation needs one explicit provider and model while the
architecture requires provider details to remain outside application code.
Generation returns structured specifications and large self-contained HTML
documents, and failures must be observable and repairable.

## Decision

Use the official OpenAI Python SDK and Responses API behind the project-owned
`ModelGateway`. The default configurable model identifier is `gpt-6-luna`.
Both specification and game generation use SDK-native Pydantic Structured
Outputs. Requests have a configured timeout and bounded SDK retries; application
repair remains limited to two semantic attempts and is not delegated to the SDK.

The API key is read only by model workers from `OPENAI_API_KEY`. It is never
passed to generated games, validation evidence, Redis payloads, browser workers,
or creator responses. Model name, response ID, token use, and latency are stored
as provenance, while raw prompts and source are not written to telemetry.

## Consequences

- The demo has a single reproducible model target and cost/latency telemetry.
- Provider-specific code is limited to `adapters/openai_gateway.py`.
- Another provider can implement `ModelGateway` without changing workflow,
  storage, validation, or HTTP contracts.
- Live validation requires an account with model access and cannot be claimed
  from unit tests alone.
