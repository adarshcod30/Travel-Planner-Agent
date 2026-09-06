"""Shared graph state and the structured output schema for every agent.

All five versions read and write the same `TripState`, which is what makes a
version switch a one-field change at the API boundary rather than a different
data contract per version.

Two deliberate constraints shape this module:

**Every non-`messages` key is `NotRequired`.** `str | None` says a *present*
key may be `None`; it does not permit the key to be absent. Fields like `review`
genuinely do not exist in the state dict at the moment an early node runs, so
without `NotRequired` Pydantic validation fails with "Field required" the first
time a tool or node receives the state — and LangGraph surfaces that as a blank
error rather than the real cause, which makes it expensive to diagnose.

`TypedDict` comes from `typing_extensions` rather than `typing`: Pydantic cannot
introspect a stdlib `TypedDict` below Python 3.12, and while this project's floor
is 3.12 the `typing_extensions` import is what Pydantic documents and costs
nothing. `NotRequired` itself is safe from `typing` on that floor.

The related trap — a `from __future__ import annotations` that quietly undoes all
of the above — is documented at the import block below.

**Output schemas are at most one level deep.** From v2 onward these are produced
by `with_structured_output()`, which is implemented as tool-calling under the
hood, and tool-calling reliability degrades sharply with nesting depth — more so
on small models than large ones. Flat shapes are a correctness measure here, not
a style preference.
"""

# NOTE: `from __future__ import annotations` must NOT be added to this module.
# It turns every annotation into a string, and `TypedDict` resolves
# `NotRequired` at class-creation time — so with it, every key silently lands in
# `__required_keys__`, `__optional_keys__` comes back empty, and Pydantic then
# rejects any state dict that omits a key. Verified directly: the same class is
# correct without the import and wrong with it, on both stdlib and
# typing_extensions `TypedDict`. `X | None` needs no future import on this
# project's Python floor, so there is nothing to gain by adding it.

import operator
from typing import Annotated, Literal, NotRequired

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

BudgetLevel = Literal["budget", "mid-range", "luxury"]
ReviewVerdict = Literal["approved", "needs_revision"]
HumanDecision = Literal["accept", "edit", "response", "ignore"]

#: Specialist agents the orchestrator is allowed to re-run. Constraining the
#: literal set means an orchestrator hallucinating an agent name fails schema
#: validation instead of silently routing nowhere.
AgentName = Literal[
    "destination",
    "weather",
    "attraction",
    "budget",
    "hotel",
    "customs",
    "packing",
    "itinerary",
]


# ---------------------------------------------------------------------------
# Agent output schemas — flat by design (see module docstring)
# ---------------------------------------------------------------------------


class DestinationChoice(BaseModel):
    """Resolved destination for the trip."""

    city: str = Field(description="City name")
    country: str = Field(description="Country name")
    reason: str = Field(description="Why this destination fits the request")


class WeatherReport(BaseModel):
    """Expected conditions for the destination and season."""

    summary: str = Field(description="One-paragraph outlook for the season")
    temperature_range: str = Field(description="Expected range, e.g. '12-19 C'")
    clothing: list[str] = Field(description="What to wear")
    tips: list[str] = Field(description="Weather-driven travel advice")


class Attraction(BaseModel):
    name: str
    category: str = Field(description="e.g. museum, nature, food, nightlife")
    description: str
    duration_hours: float = Field(description="Typical visit length in hours")


class AttractionList(BaseModel):
    attractions: list[Attraction]


class BudgetBreakdown(BaseModel):
    """Whole-trip cost estimate. Flat floats — no nested currency objects."""

    hotel: float
    food: float
    transport: float
    activities: float
    miscellaneous: float
    total: float
    currency: str = Field(default="USD")


class Hotel(BaseModel):
    name: str
    tier: str = Field(description="e.g. hostel, 3-star, boutique, 5-star")
    price_per_night: float
    rating: float = Field(ge=0, le=5)
    note: str


class HotelList(BaseModel):
    hotels: list[Hotel]


class PackingGroup(BaseModel):
    """One packing category.

    Modelled as a list of (category, items) rather than a `dict[str, list[str]]`
    because open-ended object keys are markedly less reliable to generate than a
    list of fixed-shape records.
    """

    category: str
    items: list[str]


class PackingList(BaseModel):
    groups: list[PackingGroup]


class DayPlan(BaseModel):
    day: int
    morning: str
    afternoon: str
    evening: str
    meals: list[str]


class Itinerary(BaseModel):
    summary: str
    days: list[DayPlan]


class LocalCustoms(BaseModel):
    greetings: str
    tipping: str
    dress_code: str
    dos: list[str]
    donts: list[str]
    phrases: list[str] = Field(description="Useful local phrases with translations")


class Review(BaseModel):
    """Automated audit of the assembled draft."""

    verdict: ReviewVerdict
    budget_realistic: bool
    pacing_reasonable: bool
    issues: list[str] = Field(description="Concrete problems found; empty if approved")
    suggestions: list[str] = Field(description="Specific fixes for the issues")


class OrchestratorDecision(BaseModel):
    """Which specialists to re-run, and why."""

    agents_to_rerun: list[AgentName] = Field(
        description="Specialists whose output must change. Empty means the plan is done."
    )
    reasoning: str = Field(description="Why these agents specifically")


# ---------------------------------------------------------------------------
# Telemetry — accumulated across concurrent branches
# ---------------------------------------------------------------------------


class AgentRun(BaseModel):
    """One specialist execution. Powers the frontend run timeline."""

    agent: str
    model_id: str
    tier: str
    duration_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
    repairs: int = Field(default=0, description="Structured-output repair attempts used")
    escalated: bool = Field(default=False, description="Whether the model tier was raised")


class AgentError(BaseModel):
    agent: str
    error_type: str
    message: str


# ---------------------------------------------------------------------------
# Graph state
# ---------------------------------------------------------------------------


class TripState(TypedDict):
    """State shared by all five graph versions.

    `messages`, `agent_runs` and `errors` carry reducers because the fan-out
    versions write them from several branches within a single superstep; every
    other key is owned by exactly one node, which is the cheaper way to avoid
    concurrent-update conflicts.

    Every key is `NotRequired`, reducer-backed ones included — verified that a
    reducer still merges concurrent writes through the `NotRequired` wrapper.
    That keeps the API input contract honest: a caller posts the trip request,
    not empty telemetry arrays the server is about to fill in itself.
    """

    messages: NotRequired[Annotated[list[BaseMessage], add_messages]]

    # --- request ---
    request: NotRequired[str | None]
    days: NotRequired[int | None]
    interests: NotRequired[list[str] | None]
    budget_level: NotRequired[BudgetLevel | None]
    season: NotRequired[str | None]
    travelers: NotRequired[int | None]

    # --- specialist outputs ---
    destination: NotRequired[DestinationChoice | None]
    weather: NotRequired[WeatherReport | None]
    attractions: NotRequired[AttractionList | None]
    budget: NotRequired[BudgetBreakdown | None]
    hotels: NotRequired[HotelList | None]
    customs: NotRequired[LocalCustoms | None]
    packing: NotRequired[PackingList | None]
    itinerary: NotRequired[Itinerary | None]

    # --- audit and orchestration (v3+) ---
    review: NotRequired[Review | None]
    orchestrator_decision: NotRequired[OrchestratorDecision | None]
    iteration: NotRequired[int | None]

    # --- human-in-the-loop (v4+) ---
    human_decision: NotRequired[HumanDecision | None]
    human_feedback: NotRequired[str | None]

    # --- research provenance (v5) ---
    research_notes: NotRequired[list[str] | None]

    # --- result ---
    final_plan: NotRequired[str | None]

    # --- telemetry (reduced across branches) ---
    agent_runs: NotRequired[Annotated[list[AgentRun], operator.add]]
    errors: NotRequired[Annotated[list[AgentError], operator.add]]
