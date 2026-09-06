"""Orchestrator: decides which specialists must re-run after a review or human feedback.

Unlike the research specialists, this agent produces no travel content. It
reads the reviewer's verdict, the human's feedback (v4+) and the list of
specialists that failed, then names the smallest set of agents whose output
must change. The graph routes on that list, so the schema constrains it to the
valid specialist names and a hallucinated target fails validation instead of
routing nowhere.

Every upstream field is optional. When one is missing the prompt says so in a
single line rather than dropping it silently, so the model decides from what is
actually known instead of inventing a review that never happened.
"""

from typing import ClassVar

from pydantic import BaseModel

from travel_planner.agents.base import BaseAgent, render_trip_context
from travel_planner.core.config import ModelTier
from travel_planner.core.state import (
    AgentError,
    DestinationChoice,
    OrchestratorDecision,
    Review,
    TripState,
)
from travel_planner.prompts.orchestrator import SYSTEM_PROMPT


def _yes_no(flag: bool) -> str:
    return "yes" if flag else "no"


def _render_iteration(iteration: int | None) -> str:
    if iteration is None:
        return "Iteration: not available (treat this as the first revision pass)"
    return f"Iteration: {iteration}"


def _render_destination(destination: DestinationChoice | None) -> str:
    if destination is None:
        return "Destination choice: not available"
    return (
        f"Destination choice: {destination.city}, {destination.country}. "
        f"Chosen because: {destination.reason}"
    )


def _render_days(days: int | None) -> str:
    if not days:
        return "Trip length: not specified"
    return f"Trip length: {days} days"


def _render_review(review: Review | None) -> str:
    if review is None:
        return "Review: not available (no automated audit has run yet)"
    lines = [
        f"Review verdict: {review.verdict} "
        f"(budget realistic: {_yes_no(review.budget_realistic)}; "
        f"pacing reasonable: {_yes_no(review.pacing_reasonable)})"
    ]
    if review.issues:
        lines.append("Review issues:")
        lines.extend(f"- {issue}" for issue in review.issues)
    else:
        lines.append("Review issues: none")
    if review.suggestions:
        lines.append("Review suggestions:")
        lines.extend(f"- {suggestion}" for suggestion in review.suggestions)
    else:
        lines.append("Review suggestions: none")
    return "\n".join(lines)


def _render_feedback(feedback: str | None) -> str:
    if feedback:
        return f"Human feedback (outranks the review): {feedback}"
    return "Human feedback: none"


def _render_errors(errors: list[AgentError] | None) -> str:
    if not errors:
        return "Failed specialists: none"
    lines = ["Failed specialists (each must be re-run):"]
    lines.extend(f"- {err.agent}: {err.error_type}: {err.message}" for err in errors)
    return "\n".join(lines)


class OrchestratorAgent(BaseAgent):
    """Choose which specialists re-run to address the review and human feedback."""

    name: ClassVar[str] = "orchestrator"
    tier: ClassVar[ModelTier] = "high"
    schema: ClassVar[type[BaseModel]] = OrchestratorDecision
    state_key: ClassVar[str] = "orchestrator_decision"
    system_prompt: ClassVar[str] = SYSTEM_PROMPT

    def user_prompt(self, state: TripState) -> str:
        sections = [
            render_trip_context(state),
            "",
            _render_iteration(state.get("iteration")),
            _render_destination(state.get("destination")),
            _render_days(state.get("days")),
            "",
            _render_review(state.get("review")),
            "",
            _render_feedback(state.get("human_feedback")),
            _render_errors(state.get("errors")),
            "",
            "Decide which specialists must re-run now. Return an empty list if nothing needs to change.",
        ]
        return "\n".join(sections)
