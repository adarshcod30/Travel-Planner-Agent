"""Base class every specialist agent derives from.

A specialist is four class attributes and one method: a name, a model tier, an
output schema, the state key it owns, and `user_prompt()` which renders the
request into a prompt. Everything else — building messages, invoking the model
with repair and escalation, recording telemetry, and turning a failure into a
state entry the graph can route around — is shared here so it is implemented,
tested and tuned exactly once.

An agent instance is a valid LangGraph node: `graph.add_node("weather",
WeatherAgent())`. Versions differ in how nodes are wired, not in the nodes.
"""

from abc import ABC, abstractmethod
from typing import Any, ClassVar

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from travel_planner.core.bedrock import invoke_structured
from travel_planner.core.config import ModelTier
from travel_planner.core.exceptions import TravelPlannerError
from travel_planner.core.logging import get_logger
from travel_planner.core.state import AgentError, TripState

log = get_logger(__name__)


def render_trip_context(state: TripState) -> str:
    """Render the request fields every specialist needs, in one stable shape.

    Centralised so all agents see the same facts phrased the same way — which
    matters for prompt caching later, and for not having nine slightly
    different descriptions of the same trip.
    """
    dest = state.get("destination")
    where = f"{dest.city}, {dest.country}" if dest else "(destination not yet chosen)"
    interests = ", ".join(state.get("interests") or []) or "not specified"
    lines = [
        f"Destination: {where}",
        f"Duration: {state.get('days') or 'unspecified'} days",
        f"Season / dates: {state.get('season') or 'unspecified'}",
        f"Travelers: {state.get('travelers') or 1}",
        f"Budget level: {state.get('budget_level') or 'mid-range'}",
        f"Interests: {interests}",
    ]
    if req := state.get("request"):
        lines.append(f"Original request: {req}")
    if fb := state.get("human_feedback"):
        lines.append(f"Reviewer feedback to incorporate: {fb}")
    if notes := state.get("research_notes"):
        # v5 only. Real, freshly-gathered material outranks the model's priors,
        # so it is stated as such rather than offered as background.
        lines.append(
            "\nLive research gathered for this trip — prefer these facts over your own "
            "recollection where they conflict:\n" + "\n\n".join(notes)
        )
    return "\n".join(lines)


class BaseAgent(ABC):
    """One specialist. Subclasses set the class attributes and `user_prompt`."""

    name: ClassVar[str]
    tier: ClassVar[ModelTier]
    schema: ClassVar[type[BaseModel]]
    state_key: ClassVar[str]
    system_prompt: ClassVar[str]

    @abstractmethod
    def user_prompt(self, state: TripState) -> str:
        """Render the task for this agent from the current state."""

    def messages(self, state: TripState) -> list[BaseMessage]:
        return [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=self.user_prompt(state)),
        ]

    def to_update(self, value: BaseModel) -> dict[str, Any]:
        """Map the validated output onto state. Override for multi-key agents."""
        return {self.state_key: value}

    # ---- execution ----------------------------------------------------------------

    def run(self, state: TripState) -> dict[str, Any]:
        """Execute and return a state update. Raises on failure."""
        result = invoke_structured(
            self.schema,
            self.messages(state),
            tier=self.tier,
            agent=self.name,
        )
        update = self.to_update(result.value)
        update["agent_runs"] = [result.run]
        return update

    def safe_run(self, state: TripState) -> dict[str, Any]:
        """Execute, converting any failure into an `errors` entry.

        A specialist failing must not take the whole graph down: the itinerary
        agent can still work without a packing list. The error is recorded in
        state so the review and orchestrator stages — and the frontend — can see
        it, and the graph proceeds.
        """
        try:
            return self.run(state)
        except TravelPlannerError as exc:
            log.error(
                "agent_failed", agent=self.name, error=type(exc).__name__, detail=str(exc)[:200]
            )
            return {
                "errors": [
                    AgentError(
                        agent=self.name, error_type=type(exc).__name__, message=str(exc)[:500]
                    )
                ]
            }

    def __call__(self, state: TripState) -> dict[str, Any]:
        """LangGraph node entry point."""
        return self.safe_run(state)
