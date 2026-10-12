"""Durable eligibility for one additional dispatch after local Codex cleanup.

This marker does not establish zero remote spend: unknown usage stays reserved.
Network errors, cancellation and worker death never receive this marker.
"""

CODEX_TIMEOUT_RECEIPT = {"interruption": "codex_wall_timeout"}
TIMEOUT_RETRY_SUFFIX = ":retry:1"
