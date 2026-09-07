"""v1's single agent.

One model call produces the whole trip. No specialists, no tools, no research —
which is the point: it establishes what a good model does unaided, so every
later version is a measurable delta against it rather than an assertion.
"""

from typing import ClassVar

from travel_planner.agents.base import BaseAgent, render_trip_context
from travel_planner.core.config import ModelTier
from travel_planner.core.state import TripState, WrittenPlan
from travel_planner.prompts.planner import SYSTEM_PROMPT


class PlannerAgent(BaseAgent):
    """The whole plan, in one pass."""

    name: ClassVar[str] = "planner"
    # High tier deliberately: this is the fairest possible showing for a single
    # unaided pass. Whatever v2 improves on cannot then be dismissed as v1
    # having been handicapped by a cheaper model.
    tier: ClassVar[ModelTier] = "high"
    schema: ClassVar[type] = WrittenPlan
    state_key: ClassVar[str] = "written_plan"
    system_prompt: ClassVar[str] = SYSTEM_PROMPT

    def user_prompt(self, state: TripState) -> str:
        lines = [render_trip_context(state), ""]
        days = state.get("days") or 3
        lines.append(
            f"Write the complete plan now: a summary, exactly {days} day paragraphs, "
            "a rupee cost range with its assumptions, and the caveats a reader "
            "should check before booking."
        )
        return "\n".join(lines)
