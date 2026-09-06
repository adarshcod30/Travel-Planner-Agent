"""Exception hierarchy.

Every failure the graphs can raise derives from `TravelPlannerError`, so a node
can distinguish "this system failed" from an unexpected bug with one `except`.
The structured-output errors carry enough context to drive the repair and
escalation loop without re-parsing messages.
"""


class TravelPlannerError(Exception):
    """Base class for every error raised by this package."""


class ConfigurationError(TravelPlannerError):
    """A required setting is missing or invalid."""


class ModelInvocationError(TravelPlannerError):
    """Bedrock returned an error the retry policy did not absorb."""

    def __init__(self, model_id: str, cause: BaseException) -> None:
        self.model_id = model_id
        self.cause = cause
        super().__init__(f"{model_id}: {type(cause).__name__}: {str(cause)[:200]}")


class StructuredOutputError(TravelPlannerError):
    """The model could not produce output matching the requested schema.

    Raised only after the repair loop and any tier escalation are exhausted.
    `attempts` records every (model_id, error) pair tried, for telemetry.
    """

    def __init__(self, schema_name: str, attempts: list[tuple[str, str]]) -> None:
        self.schema_name = schema_name
        self.attempts = attempts
        tried = ", ".join(m for m, _ in attempts)
        super().__init__(
            f"{schema_name}: no valid output after {len(attempts)} attempt(s) on [{tried}]"
        )


class AgentExecutionError(TravelPlannerError):
    """A specialist agent failed in a way the graph should record and route around."""

    def __init__(self, agent: str, cause: BaseException) -> None:
        self.agent = agent
        self.cause = cause
        super().__init__(f"{agent}: {type(cause).__name__}: {str(cause)[:200]}")


class OrchestrationError(TravelPlannerError):
    """The orchestrator produced a decision the graph cannot act on."""
