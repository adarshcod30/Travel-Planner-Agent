"""v4 — v3 with a human gate.

    ... -> review -> human_gate ──accept──> finalize -> END
                                ──edit──> END        (args.final_plan is the plan)
                                ──response──> orchestrator -> ... -> review -> human_gate
                                ──ignore──> END      (no plan produced)

The gate sits after *every* review, approved or not: the human sees each draft
together with the reviewer's audit and decides. `interrupt()` pauses the run
and Aegra persists the checkpoint, so the human can answer minutes or days
later and execution resumes from exactly that node. Nothing before the gate is
re-executed on resume.
"""

from langgraph.graph import END, StateGraph

from travel_planner.core.state import TripState
from travel_planner.versions.orchestration import human_gate_node, route_after_human_gate
from travel_planner.versions.v3_orchestrator.graph import add_specialist_dag

VERSION = "v4_hitl"


def build(*, max_iterations: int | None = None) -> StateGraph:
    g = StateGraph(TripState)
    add_specialist_dag(g, max_iterations=max_iterations)
    g.add_node("human_gate", human_gate_node)
    g.add_edge("review", "human_gate")
    g.add_conditional_edges(
        "human_gate",
        route_after_human_gate,
        {"finalize": "finalize", "orchestrator": "orchestrator", END: END},
    )
    return g


graph = build().compile(name=VERSION)
