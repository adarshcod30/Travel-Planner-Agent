"""Orchestration machinery shared by v3, v4 and v5.

Three problems are solved here once rather than per version:

**Targeted re-runs through a static fan-in.** LangGraph's list-form join
(`add_edge([a, b, c, d], target)`) fires once when all four sources complete —
which is what the initial pass needs — but it cannot wait for a *subset*, so a
revision that should re-run only `hotel` cannot simply route to `hotel`. The
solution is to route to the whole fan-out layer and let each node gate itself:
`rerun_aware()` wraps a specialist so that, in revision mode, it returns an
empty update unless the orchestrator named it (or something it depends on).
Skipped nodes still "complete", so the join fires exactly as it did on the
first pass. Verified empirically before this was written; see the v3 tests.

**A bounded revision loop.** `make_orchestrator_node()` increments the
iteration counter and forces an empty decision past the configured maximum, so
the loop terminates even if the reviewer never approves.

**The human gate.** `human_gate_node()` pauses with `interrupt()` and maps the
four resume types Aegra documents — accept, edit, response, ignore — onto state
and routing. It accepts both Aegra's list-shaped resume payload and a bare dict.
"""

from collections.abc import Callable
from typing import Any

from langgraph.graph import END
from langgraph.types import interrupt

from travel_planner.agents.base import BaseAgent
from travel_planner.agents.orchestrator import OrchestratorAgent
from travel_planner.core.config import get_settings
from travel_planner.core.logging import get_logger
from travel_planner.core.state import OrchestratorDecision, TripState
from travel_planner.versions.common import render_plan_markdown

log = get_logger(__name__)

#: The first parallel layer. On revision the orchestrator routes to all of
#: these; each decides for itself whether it has work.
FANOUT: tuple[str, ...] = ("weather", "attraction", "budget", "customs")

#: A specialist re-runs if it is named, or if something it consumes is named.
DEPENDS_ON: dict[str, tuple[str, ...]] = {
    "packing": ("weather",),
    "hotel": ("budget",),
}


# ---------------------------------------------------------------------------
# Self-gating specialists
# ---------------------------------------------------------------------------


def rerun_aware(agent: BaseAgent) -> Callable[[TripState], dict[str, Any]]:
    """Wrap a specialist so it skips itself on revisions it was not asked to join."""

    def node(state: TripState) -> dict[str, Any]:
        decision = state.get("orchestrator_decision")
        if decision is None:
            return agent(state)  # initial pass: everyone runs
        targets = set(decision.agents_to_rerun)
        wanted = (
            "destination" in targets  # a new destination invalidates everything
            or agent.name in targets
            or any(dep in targets for dep in DEPENDS_ON.get(agent.name, ()))
        )
        if not wanted:
            log.debug("agent_skipped", agent=agent.name, iteration=state.get("iteration"))
            return {}
        return agent(state)

    node.__name__ = agent.name
    node.__qualname__ = f"rerun_aware({agent.name})"
    return node


# ---------------------------------------------------------------------------
# Orchestrator node and routing
# ---------------------------------------------------------------------------


def make_orchestrator_node(
    max_iterations: int | None = None,
) -> Callable[[TripState], dict[str, Any]]:
    """Build the orchestrator node with a hard iteration ceiling."""
    limit = (
        max_iterations if max_iterations is not None else get_settings().max_orchestrator_iterations
    )
    agent = OrchestratorAgent()

    def node(state: TripState) -> dict[str, Any]:
        iteration = (state.get("iteration") or 0) + 1
        if iteration > limit:
            log.warning("orchestrator_max_iterations", iteration=iteration, limit=limit)
            return {
                "iteration": iteration,
                "orchestrator_decision": OrchestratorDecision(
                    agents_to_rerun=[],
                    reasoning=f"Reached the revision limit ({limit}); finalizing the current draft.",
                ),
            }
        update = agent.safe_run(state)
        update["iteration"] = iteration
        if "orchestrator_decision" not in update:
            # The agent failed and recorded an error; do not loop on a failure.
            update["orchestrator_decision"] = OrchestratorDecision(
                agents_to_rerun=[],
                reasoning="Orchestrator could not produce a decision; finalizing.",
            )
        return update

    node.__name__ = "orchestrator"
    return node


def route_after_review(state: TripState) -> str:
    """Approved drafts skip the orchestrator entirely."""
    review = state.get("review")
    if review is None or review.verdict == "approved":
        return "finalize"
    return "orchestrator"


def route_after_orchestrator(state: TripState) -> str | list[str]:
    """Finalize, restart from destination, or re-enter the self-gating fan-out."""
    decision = state.get("orchestrator_decision")
    if decision is None or not decision.agents_to_rerun:
        return "finalize"
    if "destination" in decision.agents_to_rerun:
        return "destination"
    return list(FANOUT)


# ---------------------------------------------------------------------------
# Human-in-the-loop gate (v4+)
# ---------------------------------------------------------------------------

_RESUME_TYPES = ("accept", "edit", "response", "ignore")


def parse_resume(payload: Any) -> tuple[str, Any]:
    """Normalise a resume payload to (type, args).

    Aegra's documented shape is a list with one entry, `[{"type": ..., "args":
    ...}]`; a bare dict or a bare type string are accepted too.
    """
    if isinstance(payload, list):
        if not payload:
            raise ValueError("empty resume payload")
        payload = payload[0]
    if isinstance(payload, str):
        payload = {"type": payload}
    if not isinstance(payload, dict) or "type" not in payload:
        raise ValueError(f"unrecognised resume payload: {payload!r}")
    kind = str(payload["type"]).lower()
    if kind not in _RESUME_TYPES:
        raise ValueError(f"unknown resume type {kind!r}; expected one of {_RESUME_TYPES}")
    return kind, payload.get("args")


def human_gate_node(state: TripState) -> dict[str, Any]:
    """Pause for a human decision on the current draft.

    The interrupt payload carries the rendered draft and the reviewer's audit
    so a client can show both without a second request. On resume:

    - accept   → finalize the draft as-is
    - edit     → args["final_plan"] replaces the rendered plan; done
    - response → args (a string, or {"feedback": ...}) becomes human_feedback
                 and the orchestrator decides what to re-run
    - ignore   → abandon; no final plan is produced
    """
    review = state.get("review")
    payload = {
        "type": "plan_review",
        "iteration": state.get("iteration") or 0,
        "draft": render_plan_markdown(state),
        "review": review.model_dump() if review else None,
        "config": {
            "allow_accept": True,
            "allow_edit": True,
            "allow_respond": True,
            "allow_ignore": True,
        },
    }
    kind, args = parse_resume(interrupt(payload))
    log.info("human_decision", decision=kind)

    update: dict[str, Any] = {"human_decision": kind}
    if kind == "edit":
        text = args.get("final_plan") if isinstance(args, dict) else args
        if not isinstance(text, str) or not text.strip():
            raise ValueError("edit requires args.final_plan (non-empty string)")
        update["final_plan"] = text
    elif kind == "response":
        text = args.get("feedback") if isinstance(args, dict) else args
        if not isinstance(text, str) or not text.strip():
            raise ValueError("response requires feedback text")
        update["human_feedback"] = text.strip()
    elif kind == "ignore":
        update["final_plan"] = None
    return update


def route_after_human_gate(state: TripState) -> str:
    match state.get("human_decision"):
        case "accept":
            return "finalize"
        case "response":
            return "orchestrator"
        case "edit" | "ignore":
            return END
        case other:
            raise ValueError(f"human gate produced no decision: {other!r}")
