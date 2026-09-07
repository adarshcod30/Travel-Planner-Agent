"""Attraction specialist: real, named things to see and do at the destination.

Reads the resolved destination and the traveler's interests, trip length,
budget level, season and any reviewer feedback; writes an `AttractionList` to
`state["attractions"]`. Runs on the mid tier because choosing good, real places
for a specific interest mix needs genuine world knowledge, while the output
shape is flat and easy for the model to hold.
"""

from travel_planner.agents.base import BaseAgent, render_trip_context
from travel_planner.core.state import AttractionList, TripState
from travel_planner.prompts.attraction import SYSTEM_PROMPT

_MIN_ATTRACTIONS = 6
_MAX_ATTRACTIONS = 10


def _target_count(days: int | None) -> int:
    """Roughly two picks per day, clamped to the 6-10 range the role requires."""
    if not days or days < 1:
        return _MIN_ATTRACTIONS
    return max(_MIN_ATTRACTIONS, min(_MAX_ATTRACTIONS, days * 2))


class AttractionAgent(BaseAgent):
    """Recommend 6-10 real attractions matching interests, budget, season and length."""

    name = "attraction"
    tier = "mid"
    schema = AttractionList
    state_key = "attractions"
    system_prompt = SYSTEM_PROMPT

    def user_prompt(self, state: TripState) -> str:
        lines = [render_trip_context(state), "", "Inputs for the attraction shortlist:"]

        dest = state.get("destination")
        if dest:
            lines.append(
                f"Destination detail: {dest.city}, {dest.country}. Chosen because: {dest.reason}"
            )
        else:
            lines.append(
                "Destination detail: not available (use the original request above to infer it)"
            )

        interests = state.get("interests")
        if interests:
            lines.append(f"Interests to cover: {', '.join(interests)}")
        else:
            lines.append("Interests to cover: not available (choose a balanced mix of highlights)")

        days = state.get("days")
        target = _target_count(days)
        if days:
            lines.append(f"Trip length: {days} days")
        else:
            lines.append("Trip length: not available")
        lines.append(
            f"Target count: {target} attractions "
            f"(never fewer than {_MIN_ATTRACTIONS}, never more than {_MAX_ATTRACTIONS})"
        )

        budget = state.get("budget_level")
        if budget:
            lines.append(f"Budget level: {budget}")
        else:
            lines.append("Budget level: not available (assume mid-range)")

        season = state.get("season")
        if season:
            lines.append(f"Season: {season}")
        else:
            lines.append("Season: not available (avoid strongly seasonal picks)")

        feedback = state.get("human_feedback")
        if feedback:
            lines.append(f"Feedback to apply: {feedback}")
        else:
            lines.append("Feedback: none")

        lines.append("")
        lines.append("Produce the attraction list now.")
        return "\n".join(lines)
