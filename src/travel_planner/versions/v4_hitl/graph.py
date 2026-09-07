"""v4 — v3 turned into something two parties work on.

    ... -> review -> section_gate ──accept───> finalize -> remember -> END
                                  ──comments─> [ the specialists that own
                                                 the commented sections ]
                                                 -> itinerary -> review -> ...
                                  ──response─> orchestrator -> ... (v3's path)
                                  ──edit─────> END   (args.final_plan is the plan)
                                  ──ignore───> END   (no plan produced)

v3's loop is steered by a model reading prose. v4's is steered by a person
pointing at a section, and the two paths coexist here deliberately: `comments`
routes deterministically because the section already names its specialist,
while `response` still goes through the orchestrator for objections that are
not about any one section.

The gate sits after *every* review, approved or not. `interrupt()` pauses the
run and Aegra persists the checkpoint, so the answer can come minutes or days
later and execution resumes from exactly that node with nothing before it
recomputed — which is what makes a multi-round review practical rather than a
reason to re-run the whole plan.
"""

from langgraph.graph import END, StateGraph

from travel_planner.core.state import TripState
from travel_planner.versions.orchestration import FANOUT
from travel_planner.versions.v3_orchestrator.graph import add_specialist_dag
from travel_planner.versions.v4_hitl.gate import make_section_gate_node, route_after_section_gate

VERSION = "v4_hitl"


def build(*, max_iterations: int | None = None) -> StateGraph:
    g = StateGraph(TripState)
    add_specialist_dag(g, max_iterations=max_iterations)
    g.add_node("section_gate", make_section_gate_node(max_iterations))
    g.add_edge("review", "section_gate")
    # The comment path reaches the fan-out directly, which is exactly what the
    # orchestrator's own routing does — minus the model call that used to
    # decide it.
    g.add_conditional_edges(
        "section_gate",
        route_after_section_gate,
        ["finalize", "orchestrator", "destination", *FANOUT, END],
    )
    return g


graph = build().compile(name=VERSION)
