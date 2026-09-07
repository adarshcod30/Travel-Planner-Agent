"""v4's review gate — the plan as a document someone marks up.

v3 already had a revision loop, but only a model could steer it: the reviewer
wrote prose, the orchestrator read that prose and guessed which specialists it
implicated. v4's gate removes the guess. A comment arrives already attached to
a section, and a section has exactly one specialist behind it, so the routing
decision is a dictionary lookup:

    "the hotel line is too high"  +  section "budget"  ->  re-run `budget`

That is the difference between v3 and v4 in one line, and it is worth more than
it looks. The model call disappears from the loop, so a revision round costs
nothing and cannot be misrouted; the human's intent stops being paraphrased;
and because the target set is exact, the fan-out re-runs one specialist rather
than a plausible-sounding four.

Free-text feedback is still accepted — `response` routes to the orchestrator
exactly as v3 does — because not every objection is about one section. The two
paths sitting side by side are the point: one deterministic, one inferred.

Everything the human does is recorded as a `Revision`, so a plan that took four
rounds can say so instead of arriving looking like a first draft.
"""

from collections.abc import Callable
from typing import Any

from langgraph.graph import END
from langgraph.types import interrupt

from travel_planner.core import events
from travel_planner.core.config import get_settings
from travel_planner.core.logging import get_logger
from travel_planner.core.state import (
    AgentName,
    OrchestratorDecision,
    Revision,
    SectionComment,
    TripState,
)
from travel_planner.versions.common import PlanSection, plan_sections, render_plan_markdown
from travel_planner.versions.orchestration import parse_resume, route_after_orchestrator

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Parsing what came back from the client
# ---------------------------------------------------------------------------


def parse_comments(args: Any, commentable: dict[str, PlanSection]) -> list[SectionComment]:
    """Normalise a `comments` resume payload against the sections that were offered.

    Three shapes are accepted, because all three are natural for a client to
    send: `{"comments": [...]}`, a bare list of `{section, comment}`, and a
    plain `{section: comment}` mapping.

    An unknown section key is an error rather than a silently dropped comment.
    Losing a person's words because a key was misspelled is the one failure
    mode a review tool cannot have — they would watch the run resume and
    quietly ignore them.
    """
    if isinstance(args, dict) and "comments" in args:
        args = args["comments"]

    raw: list[tuple[Any, Any]]
    if isinstance(args, dict):
        raw = list(args.items())
    elif isinstance(args, list):
        raw = []
        for item in args:
            if not isinstance(item, dict) or "section" not in item:
                raise ValueError(f"each comment needs a 'section' key; got {item!r}")
            raw.append((item["section"], item.get("comment")))
    else:
        raise ValueError(f"comments must be a list or a mapping; got {type(args).__name__}")

    if not raw:
        raise ValueError("comments requires at least one comment")

    offered = ", ".join(sorted(commentable)) or "(none — this draft has no revisable sections)"
    out: list[SectionComment] = []
    for key, text in raw:
        if key not in commentable:
            raise ValueError(f"unknown section {key!r}; this draft offers: {offered}")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"the comment on {key!r} is empty")
        out.append(SectionComment(section=str(key), comment=text.strip()))
    return out


def feedback_block(comments: list[SectionComment], sections: dict[str, PlanSection]) -> str:
    """Render comments as the instruction the re-running specialists receive.

    The closing sentence earns its place: without it a specialist handed
    feedback tends to rewrite its whole section, and the human loses parts of
    the draft they never objected to.
    """
    lines = ["The traveller reviewed the draft section by section and asked for these changes:"]
    lines += [f"- {sections[c.section].title}: {c.comment}" for c in comments]
    lines.append("Change only what these comments ask for; keep everything else as it is.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The node
# ---------------------------------------------------------------------------


def make_section_gate_node(
    max_iterations: int | None = None,
) -> Callable[[TripState], dict[str, Any]]:
    """Build the gate with a hard ceiling on comment rounds.

    The ceiling lives here rather than in the orchestrator because on this path
    the orchestrator never runs — v4's comment loop bypasses it entirely, so it
    would otherwise be unbounded.
    """
    limit = (
        max_iterations if max_iterations is not None else get_settings().max_orchestrator_iterations
    )

    def node(state: TripState) -> dict[str, Any]:
        sections = plan_sections(state)
        by_key = {s.key: s for s in sections}
        commentable = {s.key: s for s in sections if s.owner}
        iteration = state.get("iteration") or 0
        review = state.get("review")
        history = list(state.get("revisions") or [])

        events.needs_human(
            reason="plan_review",
            prompt=f"Draft {iteration + 1} is ready for your review.",
        )
        payload = {
            "type": "section_review",
            "iteration": iteration,
            "sections": [
                {"key": s.key, "title": s.title, "owner": s.owner, "body": s.body} for s in sections
            ],
            # The whole document as well, so a client that only wants to show a
            # plan does not have to reassemble one.
            "draft": render_plan_markdown(state),
            "review": review.model_dump() if review else None,
            "revisions": [r.model_dump() for r in history],
            "config": {
                "allow_accept": True,
                "allow_comments": bool(commentable),
                "allow_edit": True,
                "allow_respond": True,
                "allow_ignore": True,
                "revision_rounds_left": max(0, limit - iteration),
            },
        }

        kind, args = parse_resume(interrupt(payload))
        log.info("human_decision", decision=kind, iteration=iteration)

        update: dict[str, Any] = {"human_decision": kind}
        revision = Revision(iteration=iteration, decision=kind)

        if kind == "comments":
            comments = parse_comments(args, commentable)
            revision.comments = comments
            update["section_comments"] = comments
            update["iteration"] = iteration + 1

            if iteration + 1 > limit:
                # Out of rounds. Recorded honestly as a comment round that
                # could not be acted on, rather than rewritten as an accept.
                log.warning("section_gate_max_iterations", iteration=iteration + 1, limit=limit)
                update["orchestrator_decision"] = OrchestratorDecision(
                    agents_to_rerun=[],
                    reasoning=f"Reached the revision limit ({limit}); finalizing the current draft.",
                )
            else:
                owners: list[AgentName] = sorted({commentable[c.section].owner for c in comments})  # type: ignore[misc]
                revision.agents_rerun = owners
                update["orchestrator_decision"] = OrchestratorDecision(
                    agents_to_rerun=owners,
                    reasoning="Re-running the specialists behind the sections you commented on: "
                    + ", ".join(by_key[c.section].title for c in comments)
                    + ".",
                )
                update["human_feedback"] = feedback_block(comments, by_key)

        elif kind == "edit":
            text = args.get("final_plan") if isinstance(args, dict) else args
            if not isinstance(text, str) or not text.strip():
                raise ValueError("edit requires args.final_plan (non-empty string)")
            update["final_plan"] = text

        elif kind == "response":
            text = args.get("feedback") if isinstance(args, dict) else args
            if not isinstance(text, str) or not text.strip():
                raise ValueError("response requires feedback text")
            update["human_feedback"] = text.strip()
            revision.feedback = text.strip()

        elif kind == "ignore":
            update["final_plan"] = None

        update["revisions"] = [*history, revision]
        return update

    node.__name__ = "section_gate"
    return node


def route_after_section_gate(state: TripState) -> str | list[str]:
    """Where a reviewed draft goes next.

    The `comments` branch defers to `route_after_orchestrator` — the same
    routing v3 uses — because by this point the decision it reads was already
    made, just by a person instead of a model. Reusing it keeps one definition
    of what a decision means, including the empty-decision case that finalizes
    a draft whose revision rounds have run out.
    """
    match state.get("human_decision"):
        case "accept":
            return "finalize"
        case "comments":
            return route_after_orchestrator(state)
        case "response":
            return "orchestrator"
        case "edit" | "ignore":
            return END
        case other:
            raise ValueError(f"review gate produced no decision: {other!r}")
