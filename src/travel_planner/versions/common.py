"""Nodes and helpers shared by every graph version.

The versions differ in how specialists are wired — sequentially, in parallel,
under an orchestrator, behind a human gate, over MCP — not in how a request is
normalised on the way in or how a plan is rendered on the way out. Those two
ends live here so they are identical across versions, which is what makes a
cross-version comparison of the *middle* meaningful.
"""

from dataclasses import dataclass
from typing import Any

from travel_planner.core.logging import get_logger
from travel_planner.core.money import compact_rupees, per_person_per_day, rupees
from travel_planner.core.state import AgentName, TripState

log = get_logger(__name__)

DEFAULT_DAYS = 3
DEFAULT_TRAVELERS = 1
DEFAULT_BUDGET_LEVEL = "mid-range"


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------


def intake_node(state: TripState) -> dict[str, Any]:
    """Normalise the incoming request and fill defaults.

    Deterministic by design. Interpreting a vague request ("somewhere warm")
    is the destination agent's job; this node only guarantees every downstream
    node sees well-formed values — clamped day counts, a known budget level, a
    positive traveler count, interests as a list — and resets the orchestration
    counter so a reused thread starts a fresh revision loop.
    """
    days = state.get("days") or DEFAULT_DAYS
    days = max(1, min(int(days), 30))

    travelers = state.get("travelers") or DEFAULT_TRAVELERS
    travelers = max(1, min(int(travelers), 12))

    level = (state.get("budget_level") or DEFAULT_BUDGET_LEVEL).strip().lower()
    if level not in ("budget", "mid-range", "luxury"):
        level = DEFAULT_BUDGET_LEVEL

    raw_interests = state.get("interests") or []
    if isinstance(raw_interests, str):
        raw_interests = [i.strip() for i in raw_interests.split(",")]
    interests = [i for i in (s.strip() for s in raw_interests) if i]

    request = (state.get("request") or "").strip() or None
    origin = (state.get("origin") or "").strip() or None

    update: dict[str, Any] = {
        "request": request,
        "origin": origin,
        "days": days,
        "travelers": travelers,
        "budget_level": level,
        "interests": interests,
        "season": (state.get("season") or "").strip() or None,
        "iteration": 0,
    }
    # A reused thread carries the previous trip's outputs. Left in place they
    # would leak into every prompt ("Weather report: 8-16 C" for the wrong
    # city), so a new request starts from a clean slate. Resumed runs never
    # re-enter intake, so this cannot disturb a paused human review.
    update.update(dict.fromkeys(GENERATED_KEYS))
    return update


#: Everything a run produces, as opposed to what the caller supplies.
#: `origin` is deliberately absent — it is an input, and a reused thread should
#: keep it rather than ask again.
GENERATED_KEYS: tuple[str, ...] = (
    "written_plan",
    "destination",
    "weather",
    "attractions",
    "budget",
    "hotels",
    "customs",
    "packing",
    "itinerary",
    "review",
    "orchestrator_decision",
    "human_decision",
    "section_comments",
    "revisions",
    "research_notes",
    "final_plan",
)


# ---------------------------------------------------------------------------
# Finalize
# ---------------------------------------------------------------------------


#: What separates one section from the next in the rendered document.
SECTION_SEPARATOR = "\n\n---\n\n"


@dataclass(frozen=True)
class PlanSection:
    """One addressable part of a plan.

    `owner` names the specialist whose output produced it, or None where no
    single agent did — the header, the reviewer's own audit, the research
    provenance. v4 uses it to turn "this section is wrong" into a re-run
    without a model in the loop; v1 through v3 render the same sections and
    simply never look at the field.
    """

    key: str
    title: str
    owner: AgentName | None
    body: str


def _section(key: str, title: str, owner: str | None, body: str) -> PlanSection:
    return PlanSection(key=key, title=title, owner=owner, body=body)  # type: ignore[arg-type]


def _money(x: float, currency: str = "INR") -> str:
    """Rupees in Indian grouping; anything else falls back to plain grouping.

    The currency check matters because a model can still return USD despite the
    prompt, and silently printing "₹1,500" over a dollar figure would be worse
    than printing it honestly as USD.
    """
    if (currency or "INR").upper() == "INR":
        return rupees(x)
    return f"{x:,.0f} {currency}"


def plan_sections(state: TripState) -> list[PlanSection]:
    """The plan as titled, individually addressable sections.

    Every section is optional. A version that never ran the packing agent, or
    an agent that failed and was routed around, simply produces a document
    without that section — the renderer never assumes a field exists.

    v4 reviews these one at a time, which is why they carry an `owner`: a
    comment on the budget has exactly one specialist that can act on it, and
    knowing that is what lets v4 route without asking a model to guess.
    """
    parts: list[PlanSection] = []

    dest = state.get("destination")
    title = f"{dest.city}, {dest.country}" if dest else "Your trip"
    days = state.get("days")
    header = [f"# Travel Plan: {title}"]
    meta = []
    if days:
        meta.append(f"**Duration:** {days} day{'s' if days != 1 else ''}")
    if lvl := state.get("budget_level"):
        meta.append(f"**Budget:** {lvl}")
    if trav := state.get("travelers"):
        meta.append(f"**Travellers:** {trav}")
    if origin := state.get("origin"):
        meta.append(f"**From:** {origin}")
    if season := state.get("season"):
        meta.append(f"**When:** {season}")
    if ints := state.get("interests"):
        meta.append(f"**Interests:** {', '.join(ints)}")
    if meta:
        header.append(" | ".join(meta))
    if dest and dest.reason:
        header.append(f"\n_{dest.reason}_")
    parts.append(_section("overview", "Overview", "destination", "\n".join(header)))

    if w := state.get("weather"):
        parts.append(
            _section(
                "weather",
                "Weather",
                "weather",
                "## Weather\n"
                f"{w.summary}\n\n"
                f"**Temperature:** {w.temperature_range}\n\n"
                f"**Wear:** {', '.join(w.clothing)}\n\n"
                f"**Tips:** {'; '.join(w.tips)}",
            )
        )

    # v1 renders differently: prose days, a cost range, and stated caveats
    # rather than a structured itinerary and budget table.
    if wp := state.get("written_plan"):
        lines = ["## The plan", wp.summary, ""]
        for i, day in enumerate(wp.days, start=1):
            lines += [f"### Day {i}", day, ""]
        parts.append(_section("plan", "The plan", None, "\n".join(lines).rstrip()))
        parts.append(_section("plan_budget", "Budget", None, f"## Budget\n{wp.budget_note}"))
        if wp.caveats:
            # Surfaced rather than buried: this is what separates an honest
            # single-pass plan from one that merely sounds confident.
            parts.append(
                _section(
                    "caveats",
                    "Worth checking before you book",
                    None,
                    "## Worth checking before you book\n" + "\n".join(f"- {c}" for c in wp.caveats),
                )
            )

    if it := state.get("itinerary"):
        lines = ["## Itinerary", f"_{it.summary}_", ""]
        for d in it.days:
            lines += [
                f"### Day {d.day}",
                f"- **Morning:** {d.morning}",
                f"- **Afternoon:** {d.afternoon}",
                f"- **Evening:** {d.evening}",
            ]
            if d.meals:
                lines.append(f"- **Meals:** {', '.join(d.meals)}")
            lines.append("")
        parts.append(_section("itinerary", "Itinerary", "itinerary", "\n".join(lines).rstrip()))

    if a := state.get("attractions"):
        lines = ["## Attractions"]
        for x in a.attractions:
            lines.append(f"- **{x.name}** ({x.category}, ~{x.duration_hours:g}h) — {x.description}")
        parts.append(_section("attractions", "Attractions", "attraction", "\n".join(lines)))

    if h := state.get("hotels"):
        lines = ["## Where to stay"]
        for x in h.hotels:
            lines.append(
                f"- **{x.name}** · {x.tier} · {_money(x.price_per_night)}/night · {x.rating:g}/5 — {x.note}"
            )
        parts.append(_section("hotels", "Where to stay", "hotel", "\n".join(lines)))

    if b := state.get("budget"):
        c = b.currency
        budget_md = (
            "## Budget\n"
            "| Category | Amount |\n|---|---|\n"
            f"| Hotel | {_money(b.hotel, c)} |\n"
            f"| Food | {_money(b.food, c)} |\n"
            f"| Transport | {_money(b.transport, c)} |\n"
            f"| Activities | {_money(b.activities, c)} |\n"
            f"| Miscellaneous | {_money(b.miscellaneous, c)} |\n"
            f"| **Total** | **{_money(b.total, c)}** |"
        )
        # The per-day and per-person figures are what a reader actually budgets
        # against, and they are arithmetic — no reason to spend a model call, or
        # to trust one, for a division.
        days = state.get("days")
        travelers = state.get("travelers") or 1
        if days:
            headline = compact_rupees(b.total) if c.upper() == "INR" else _money(b.total, c)
            budget_md += f"\n\n**{headline}** total"
            if c.upper() == "INR":
                budget_md += f" · {rupees(b.total / days)} per day"
                if travelers > 1:
                    budget_md += (
                        f" · {per_person_per_day(b.total, days, travelers)} per person per day"
                    )
            else:
                budget_md += f" · {_money(b.total / days, c)} per day"
        parts.append(_section("budget", "Budget", "budget", budget_md))

    if lc := state.get("customs"):
        parts.append(
            _section(
                "customs",
                "Local customs",
                "customs",
                "## Local customs\n"
                f"**Greetings:** {lc.greetings}\n\n"
                f"**Tipping:** {lc.tipping}\n\n"
                f"**Dress:** {lc.dress_code}\n\n"
                f"**Do:** {'; '.join(lc.dos)}\n\n"
                f"**Don't:** {'; '.join(lc.donts)}\n\n"
                f"**Phrases:** {'; '.join(lc.phrases)}",
            )
        )

    if p := state.get("packing"):
        lines = ["## Packing list"]
        for g in p.groups:
            lines.append(f"**{g.category}:** {', '.join(g.items)}")
        parts.append(_section("packing", "Packing list", "packing", "\n".join(lines)))

    if r := state.get("review"):
        lines = [f"## Review — {r.verdict.replace('_', ' ')}"]
        lines.append(
            f"Budget realistic: {'yes' if r.budget_realistic else 'no'} · Pacing reasonable: {'yes' if r.pacing_reasonable else 'no'}"
        )
        if r.issues:
            lines.append("**Issues:** " + "; ".join(r.issues))
        if r.suggestions:
            lines.append("**Suggestions:** " + "; ".join(r.suggestions))
        parts.append(_section("review", "Review", None, "\n".join(lines)))

    if notes := state.get("research_notes"):
        # Only the provenance line of each note. The full note carries a page
        # excerpt — thousands of characters of raw accessibility tree — which is
        # exactly what a specialist needs in its prompt and exactly what a reader
        # of the finished plan does not.
        body = "## Research sources\n" + "\n".join(f"- {n.split(chr(10))[0]}" for n in notes)
        parts.append(_section("sources", "Research sources", None, body))

    if errs := state.get("errors"):
        lines = ["## Notes"]
        for e in errs:
            lines.append(
                f"- The {e.agent} step could not complete ({e.error_type}); this plan was assembled without it."
            )
        parts.append(_section("notes", "Notes", None, "\n".join(lines)))

    return parts


def render_plan_markdown(state: TripState) -> str:
    """The plan as one Markdown document — every version's final output.

    Sections are joined with a horizontal rule, which is also what makes the
    document splittable again: the separator is unambiguous.
    """
    return SECTION_SEPARATOR.join(s.body for s in plan_sections(state))


def finalize_node(state: TripState) -> dict[str, Any]:
    """Render the final plan. The last node of every version."""
    log.info(
        "finalize",
        has_itinerary=state.get("itinerary") is not None,
        errors=len(state.get("errors") or []),
    )
    return {"final_plan": render_plan_markdown(state)}
