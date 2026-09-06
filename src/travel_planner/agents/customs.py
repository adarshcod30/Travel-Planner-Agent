"""Customs specialist: local etiquette for the chosen destination.

Reads only the resolved destination and produces `LocalCustoms` — greetings,
tipping norms, dress code, concrete dos and don'ts, and a handful of useful
phrases. Sits on the low tier: the output is a short, flat record of
well-known facts, which is extraction-shaped work rather than reasoning.
"""

from typing import ClassVar

from pydantic import BaseModel

from travel_planner.agents.base import BaseAgent, render_trip_context
from travel_planner.core.config import ModelTier
from travel_planner.core.state import LocalCustoms, TripState
from travel_planner.prompts.customs import SYSTEM_PROMPT


class CustomsAgent(BaseAgent):
    """Summarise local etiquette and useful phrases for the destination."""

    name: ClassVar[str] = "customs"
    tier: ClassVar[ModelTier] = "low"
    schema: ClassVar[type[BaseModel]] = LocalCustoms
    state_key: ClassVar[str] = "customs"
    system_prompt: ClassVar[str] = SYSTEM_PROMPT

    def user_prompt(self, state: TripState) -> str:
        lines = [render_trip_context(state), ""]

        dest = state.get("destination")
        if dest:
            lines.append(
                f"Destination detail: {dest.city}, {dest.country}. Chosen because: {dest.reason}"
            )
        else:
            lines.append(
                "Destination detail: not available. Brief on the region the request implies."
            )

        lines.append("")
        lines.append(
            "Produce the etiquette briefing for this trip: greetings, tipping, dress code, "
            "dos, donts, and 5 to 8 useful phrases with translations."
        )
        return "\n".join(lines)
