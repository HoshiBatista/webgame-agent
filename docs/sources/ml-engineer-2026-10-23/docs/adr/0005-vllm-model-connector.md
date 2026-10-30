# ADR 0005: vLLM as the default replaceable model connector

## Status

Accepted, superseding the default-provider choice in ADR 0003. ADR 0003 remains
as historical context for the first prototype.

## Decision

The application workflow depends only on the project-owned `ModelGateway` port.
The default adapter connects to a separately operated vLLM server through its
OpenAI-compatible Responses API and requests JSON Schema structured output for
both `GameSpec` and `GeneratedGame`.

`P2P_MODEL_PROVIDER` selects `vllm` or the optional hosted `openai` fallback.
The vLLM base URL, served-model name, API key and timeout are deployment
configuration. Only `worker-models` receives either provider credential and
network egress. Prompts, credentials and generated source are never logged by
the connector.

The vLLM deployment itself is outside this repository. It must be protected by
network policy or an authenticating reverse proxy; an API key alone is not
treated as the corporate trust boundary. Deployment guidance follows the
[official vLLM OpenAI-compatible server documentation](https://docs.vllm.ai/en/latest/serving/openai_compatible_server/).

## Consequences

- The customer's internal model can replace the demo model without workflow,
  database or UI changes.
- Candidate models must support the Responses API and `json_schema` structured
  output exposed by the selected vLLM version.
- Model-specific reasoning parsers and sampling policy belong to the vLLM
  deployment, not Prompt2Play application code.
