"""Transport errors distinguish a known failure from an unknown paid outcome."""


class GenerationError(Exception):
    def __init__(
        self, code, message, *, usage=None, outcome_unknown=False, raw_response=None, provider_metadata=None
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.usage = usage
        self.outcome_unknown = outcome_unknown
        self.raw_response = raw_response
        self.provider_metadata = provider_metadata or {}


class ContractError(GenerationError):
    pass


class GenerationPending(Exception):
    """A durable external job still exists; retry delivery/polling, never inference."""

    def __init__(self, message, *, code="relay_pending", operator_required=False,
                 retry_after=5, metadata=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.operator_required = operator_required
        self.retry_after = retry_after
        self.metadata = metadata or {}
