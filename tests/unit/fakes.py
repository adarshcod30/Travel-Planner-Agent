"""A scripted stand-in for `invoke_structured`, so graphs run without Bedrock.

Every specialist gets a fixed, valid instance of its schema. The two agents
whose output steers routing — review and orchestrator — pop from scripted
sequences so a test can say "needs_revision, then approved" and "re-run hotel".
The recorder also counts calls per agent, which is how the tests prove that a
node ran exactly once, or was skipped on a targeted revision.
"""

from types import SimpleNamespace

from travel_planner.core.state import (
    AgentRun,
    Attraction,
    AttractionList,
    BudgetBreakdown,
    DayPlan,
    DestinationChoice,
    Hotel,
    HotelList,
    Itinerary,
    LocalCustoms,
    OrchestratorDecision,
    PackingGroup,
    PackingList,
    Review,
    WeatherReport,
)

APPROVED = Review(
    verdict="approved", budget_realistic=True, pacing_reasonable=True, issues=[], suggestions=[]
)
NEEDS_REVISION = Review(
    verdict="needs_revision",
    budget_realistic=False,
    pacing_reasonable=True,
    issues=["Hotel prices exceed the budget."],
    suggestions=["Choose cheaper hotels."],
)


def decision(*agents: str) -> OrchestratorDecision:
    return OrchestratorDecision(agents_to_rerun=list(agents), reasoning="scripted")


_FIXED = {
    DestinationChoice: DestinationChoice(city="Kyoto", country="Japan", reason="scripted"),
    WeatherReport: WeatherReport(
        summary="Cool.", temperature_range="8-16 C", clothing=["layers"], tips=["umbrella"]
    ),
    AttractionList: AttractionList(
        attractions=[
            Attraction(
                name="Fushimi Inari", category="temple", description="gates", duration_hours=2.0
            )
        ]
    ),
    BudgetBreakdown: BudgetBreakdown(
        hotel=400, food=200, transport=80, activities=60, miscellaneous=40, total=780
    ),
    HotelList: HotelList(
        hotels=[Hotel(name="Gion Inn", tier="3-star", price_per_night=200, rating=4.2, note="ok")]
    ),
    LocalCustoms: LocalCustoms(
        greetings="bow",
        tipping="none",
        dress_code="modest",
        dos=["queue"],
        donts=["tip"],
        phrases=["arigatou"],
    ),
    PackingList: PackingList(groups=[PackingGroup(category="Clothing", items=["layers"])]),
    Itinerary: Itinerary(
        summary="s", days=[DayPlan(day=1, morning="m", afternoon="a", evening="e", meals=["ramen"])]
    ),
}


class FakeModel:
    """Callable with the `invoke_structured` signature. Install with `.install(monkeypatch)`."""

    def __init__(self, reviews=(), decisions=()):
        self.calls: list[str] = []
        self.reviews = list(reviews)
        self.decisions = list(decisions)

    def __call__(self, schema, messages, *, tier, agent, settings=None):
        self.calls.append(agent)
        if schema is Review:
            value = self.reviews.pop(0) if self.reviews else APPROVED
        elif schema is OrchestratorDecision:
            value = self.decisions.pop(0) if self.decisions else decision()
        else:
            value = _FIXED[schema]
        return SimpleNamespace(
            value=value, run=AgentRun(agent=agent, model_id="fake", tier=tier, duration_ms=1)
        )

    def count(self, agent: str) -> int:
        return self.calls.count(agent)

    def install(self, monkeypatch):
        import travel_planner.agents.base as base

        monkeypatch.setattr(base, "invoke_structured", self)
        return self


def full_state(**overrides):
    """A state dict with every specialist's output present.

    Node-level tests need a plan to reason about without running a graph to
    produce one; this is that plan, built from the same fixtures the scripted
    model returns.
    """
    state = {
        "request": "temples and food",
        "origin": "Delhi",
        "days": 2,
        "travelers": 2,
        "budget_level": "mid-range",
        "interests": ["history"],
        **{
            key: _FIXED[cls]
            for cls, key in (
                (DestinationChoice, "destination"),
                (WeatherReport, "weather"),
                (AttractionList, "attractions"),
                (BudgetBreakdown, "budget"),
                (HotelList, "hotels"),
                (LocalCustoms, "customs"),
                (PackingList, "packing"),
                (Itinerary, "itinerary"),
            )
        },
        "review": APPROVED,
    }
    state.update(overrides)
    return state
