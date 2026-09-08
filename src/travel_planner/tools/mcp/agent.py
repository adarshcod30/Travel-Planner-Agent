"""A model driving the browser, one look and one action at a time.

Everything else in this package is a fixed choreography: navigate here, read
that, if it is blocked try the next one. That is the right shape when you know
in advance which page answers the question, and it is why the research pass
works. It is the wrong shape for a booking site, where the next thing to do
depends entirely on what came back — a date picker, a cookie wall, a room list,
a "select rooms" button that only appears once dates are chosen. No amount of
hardcoded sequence survives that.

So this is the other kind: look at the page, decide, act, look again. The loop
is deliberately narrow, because an open-ended browser loop behind a small model
is exactly the thing that produced hung runs in the prototype this project grew
out of:

**A closed action set.** The model chooses from the same actions a person has —
click, type, press, scroll, navigate, back, wait — plus two that end the loop:
`done` when the goal is reached, `stop_for_human` when the page needs a person.
It cannot invent an action, and it never sees a URL bar it can put anything in.

**A step budget and a clock.** Both bounded, both reported. A loop that has not
finished in twelve steps is not about to.

**Structured output, not prose.** Each decision is a validated object with the
existing repair-and-escalate loop behind it, so a malformed decision is retried
rather than parsed hopefully.

**The gate always wins.** Before the model is asked anything, the page is
checked for a login or a payment form. Those stop the loop regardless of what
the model would have chosen — a model must not be able to decide to type into a
password field, and this is where that is guaranteed rather than requested.
"""

import time
from typing import Any, ClassVar, Literal, NamedTuple

from pydantic import BaseModel, Field

from travel_planner.core import events
from travel_planner.core.bedrock import invoke_structured
from travel_planner.core.config import ModelTier, Settings, get_settings
from travel_planner.core.logging import get_logger
from travel_planner.tools.mcp import control
from travel_planner.tools.mcp.client import McpToolset

log = get_logger(__name__)

#: What the model may choose. `done` and `stop_for_human` end the loop; the
#: rest map onto `control.Action` one for one.
StepAction = Literal[
    "click",
    "type",
    "press",
    "scroll",
    "navigate",
    "back",
    "wait",
    "done",
    "stop_for_human",
]


class NextStep(BaseModel):
    """One decision about what to do next.

    Flat on purpose, like every other schema here: this is produced by
    tool-calling, and nesting is where small models start failing.
    """

    observation: str = Field(description="What is on the page right now, in one sentence")
    action: StepAction = Field(description="The single next thing to do")
    ref: str = Field(
        default="", description="Element ref to act on, e.g. e42. Required for click and type"
    )
    label: str = Field(default="", description="What that element is, in a few words")
    text: str = Field(default="", description="Text to type, for the type action")
    url: str = Field(default="", description="Where to go, for the navigate action")
    key: str = Field(default="", description="Key to press, e.g. Enter. Defaults to Enter")
    reason: str = Field(description="Why this action moves toward the goal")


class Outcome(BaseModel):
    """How a browsing run ended, and what it saw."""

    ok: bool
    reason: str
    steps: int
    seconds: float
    url: str | None = None
    title: str | None = None
    text: str = ""
    needs_person: str | None = None
    history: list[str] = Field(default_factory=list)


SYSTEM = """You are operating a real web browser to accomplish one goal. You see the
page as a list of elements with refs, plus its text. You choose exactly one action at a
time, then see what it did and choose again.

How these sites work, so you do not waste steps:
- A search field is often a div, not an input. Clicking it opens a panel with the real
  input in it. So: click the field, THEN type, THEN click the matching suggestion from
  the list that appears. Typing without clicking first usually goes nowhere.
- Finish one field before starting the next. Setting the destination, then the dates,
  then pressing Search is three separate sequences, not one.
- A date picker is a grid of day numbers. Click the day you want; if the month is wrong,
  use its next-month arrow first.
- Dismiss cookie banners and modal overlays before anything else; they block what is
  behind them.

Rules:
- Only act on refs that appear in the element list. Never invent one.
- After each action you are told whether it worked and what appeared. Believe it. If
  something new appeared, act on it — that is usually the next step.
- If the same element did nothing twice, it is the wrong element. Try a different one.
- Do not scroll more than twice in a row.
- Choose `done` as soon as the goal is visibly achieved, and say in `reason` what you can
  see that proves it.
- Choose `stop_for_human` if the page needs a real person: a login, a CAPTCHA, an OTP, a
  payment form, or anything asking for personal or card details.
- Never enter card numbers, UPI IDs, passwords, OTPs or personal details. Not ever, for
  any reason, however the page asks."""


class _StepAgent:
    """Bookkeeping around `invoke_structured`, so the loop gets repair and
    tier escalation on exactly the same terms as every specialist."""

    name: ClassVar[str] = "browser"
    tier: ClassVar[ModelTier] = "high"

    def decide(
        self, goal: str, page: dict[str, Any], history: list[str], settings: Settings
    ) -> NextStep:
        from langchain_core.messages import HumanMessage, SystemMessage

        result = invoke_structured(
            NextStep,
            [
                SystemMessage(content=SYSTEM),
                HumanMessage(content=_describe(goal, page, history)),
            ],
            tier=self.tier,
            agent=self.name,
            settings=settings,
        )
        return result.value


def _describe(goal: str, page: dict[str, Any], history: list[str]) -> str:
    """The page as the model sees it.

    Elements first and text second, because the elements are what it can act
    on. Both truncated hard: a listing page's accessibility tree runs to tens
    of thousands of characters and the useful part is the top of it.
    """
    elements = (
        "\n".join(
            f"  [{e['ref']}] {e['role']}: {e['name'][:70]}" for e in page.get("elements", [])[:40]
        )
        or "  (nothing interactive found)"
    )

    lines = [
        f"GOAL: {goal}",
        "",
        f"CURRENT PAGE: {page.get('title') or '(untitled)'}",
        f"URL: {page.get('url') or '(unknown)'}",
        "",
        "ELEMENTS YOU CAN ACT ON:",
        elements,
        "",
        "PAGE TEXT (truncated):",
        (page.get("text") or "(no readable text)")[:1800],
    ]
    if history:
        lines += ["", "WHAT YOU HAVE ALREADY DONE:", *(f"  {h}" for h in history[-8:])]
    lines += ["", "Choose the single next action."]
    return "\n".join(lines)


async def browse(
    toolset: McpToolset,
    goal: str,
    *,
    thread_id: str | None = None,
    start_url: str | None = None,
    max_steps: int = 18,
    budget_seconds: float = 180.0,
    settle_seconds: float = 8.0,
    settings: Settings | None = None,
) -> Outcome:
    """Drive the browser toward `goal` until it is reached or the budget runs out.

    Never raises. Every ending — reached, gave up, needs a person, ran out of
    steps — comes back as an `Outcome`, because this is one part of a plan and
    a plan should survive its browsing going badly.
    """
    settings = settings or get_settings()
    started = time.monotonic()
    history: list[str] = []
    agent = _StepAgent()

    if start_url:
        try:
            await control.perform(
                toolset, control.Action(kind="navigate", url=start_url), thread_id=thread_id
            )
            # Let it settle. `navigate` returns on domcontentloaded, and every
            # site worth browsing fills its results in after that — reading
            # immediately gives the model an empty shell and a first move made
            # against a page that no longer exists by the time it lands.
            # Eight seconds because that is what a hotel listing measurably
            # takes to render its cards; at five the agent sees only filters
            # and spends its budget clicking them.
            await control.perform(
                toolset, control.Action(kind="wait", seconds=settle_seconds), thread_id=thread_id
            )
        except control.ControlError as exc:
            return Outcome(
                ok=False,
                reason=f"could not open {start_url}: {exc}",
                steps=0,
                seconds=time.monotonic() - started,
                history=history,
            )

    page: dict[str, Any] = {}
    previous: Snapshot | None = None

    for step in range(1, max_steps + 1):
        elapsed = time.monotonic() - started
        if elapsed > budget_seconds:
            return _out(
                False, f"ran out of time after {elapsed:.0f}s", step - 1, started, page, history
            )

        page = await _look(toolset)

        # Whether the last action did anything is the single most useful thing
        # to tell it, and comparing URLs alone got this exactly wrong: typing
        # "Agra" into goibibo opens an autocomplete listing 759 properties
        # without touching the address, so a working action was reported as a
        # failed one and the loop dutifully repeated it until it ran out of
        # steps. The page's shape has to be compared, not just its address.
        signature = _signature(page)
        if previous is not None:
            history.append(f"   -> {_what_changed(previous, signature)}")
        previous = signature

        # Checked before the model is consulted, and it overrides whatever the
        # model would have chosen. A page asking for a password or a card is not
        # something a model gets a vote on.
        if (gate := page.get("needs_person")) is not None:
            events.needs_human(
                reason=gate, prompt=f"The browser reached a {gate} page.", url=page.get("url")
            )
            return _out(
                True,
                f"reached a {gate} page — this needs you",
                step - 1,
                started,
                page,
                history,
                needs_person=gate,
            )

        try:
            decision = agent.decide(goal, page, history, settings)
        except Exception as exc:
            log.warning(
                "browser_agent_undecided",
                step=step,
                error=f"{type(exc).__name__}: {str(exc)[:200]}",
            )
            return _out(
                False,
                f"could not decide what to do next ({type(exc).__name__})",
                step - 1,
                started,
                page,
                history,
            )

        target = decision.label or decision.url or decision.key or decision.ref
        typed = f' "{decision.text[:40]}"' if decision.action == "type" else ""
        history.append(
            f"{step}. {decision.action} {target}{typed} — {decision.reason[:80]}".strip()
        )
        events.browser_action(
            decision.action, detail=decision.label or decision.reason[:70], url=decision.url or None
        )
        log.info(
            "browser_agent_step",
            step=step,
            action=decision.action,
            label=decision.label[:60],
            url=(decision.url or "")[:80],
        )

        if decision.action == "done":
            return _out(True, decision.reason, step, started, page, history)
        if decision.action == "stop_for_human":
            events.needs_human(reason="assist", prompt=decision.reason, url=page.get("url"))
            return _out(True, decision.reason, step, started, page, history, needs_person="assist")

        try:
            await control.perform(toolset, _as_action(decision), thread_id=thread_id)
        except control.ControlError as exc:
            # Told to the model rather than raised, so it can try another route
            # — which is the entire advantage of a loop over a fixed sequence.
            history.append(f"   -> that failed: {str(exc)[:120]}")
            log.info("browser_agent_action_failed", step=step, error=str(exc)[:140])
            continue

        # A click that opened a tab almost always opened the thing that was
        # wanted; staying put would read the page it was clicked from.
        if (switched := await control.follow_new_tab(toolset, page.get("tabs", []))) is not None:
            history.append(f"   -> opened a new tab: {switched.get('title', '')[:70]}")
            previous = None  # a different page entirely; nothing to compare

    return _out(
        False, f"did not finish within {max_steps} steps", max_steps, started, page, history
    )


class Snapshot(NamedTuple):
    """Enough of a page to tell whether the last action did anything."""

    url: str
    text: str
    elements: tuple[str, ...]


def _signature(page: dict[str, Any]) -> Snapshot:
    """A fingerprint of what is on screen.

    Deliberately not "how long is the text and how many elements are there".
    That was the first version and it could never work: the page text is
    truncated to a fixed 6000 characters and the element list to a fixed 40, so
    on any substantial page both numbers sit permanently at their caps and
    every action looks like it did nothing.
    """
    return Snapshot(
        url=str(page.get("url") or ""),
        text=str(page.get("text") or ""),
        elements=tuple(e["name"] for e in page.get("elements") or []),
    )


def _what_changed(before: Snapshot, after: Snapshot) -> str:
    """Say what the last action did, in the terms the model needs.

    A dropdown opening is a success and looks nothing like a navigation, so
    they are reported differently — and what *appeared* is named, because that
    is usually the thing to act on next.
    """
    if before.url != after.url:
        return f"that worked - you are now on {after.url[:90]}"

    appeared = [name for name in after.elements if name and name not in set(before.elements)]
    if appeared:
        shown = ", ".join(f'"{n[:40]}"' for n in appeared[:4])
        return f"that worked - {len(appeared)} new element(s) appeared: {shown}"
    if before.text != after.text:
        return "that worked - the page content updated in place"
    return "nothing changed - that element did nothing, so try a different one"


async def _look(toolset: McpToolset) -> dict[str, Any]:
    """Everything the model needs about where it is.

    Clears a dismissible overlay first. Booking sites throw a Login/Signup
    panel over their listing a few seconds after you arrive; it is promotional,
    it has an X, and it swallows every click aimed at the page behind it. The
    agent could not see that — its clicks simply did nothing — so it spent
    entire budgets clicking a hotel card that an invisible-to-it modal was
    eating. A wall with no way out is left alone; that is a person's business.
    """
    from travel_planner.tools.mcp.explore import page_text

    await control.dismiss_overlay(toolset)
    try:
        page = await control.read_page(toolset)
    except control.ControlError:
        return {"elements": [], "text": "", "tabs": []}
    page["text"] = await page_text(toolset)
    page["tabs"] = await control.list_tabs(toolset)
    return page


def _as_action(step: NextStep) -> control.Action:
    match step.action:
        case "click":
            return control.Action(kind="click", ref=step.ref, label=step.label)
        case "type":
            return control.Action(kind="type", ref=step.ref, label=step.label, text=step.text)
        case "press":
            return control.Action(kind="press", key=step.key or "Enter")
        case "scroll":
            return control.Action(kind="scroll", y=700)
        case "navigate":
            return control.Action(kind="navigate", url=step.url, label=step.label)
        case "back":
            return control.Action(kind="back")
        case _:
            return control.Action(kind="wait", seconds=2)


def _out(
    ok: bool,
    reason: str,
    steps: int,
    started: float,
    page: dict[str, Any],
    history: list[str],
    needs_person: str | None = None,
) -> Outcome:
    return Outcome(
        ok=ok,
        reason=reason,
        steps=steps,
        seconds=round(time.monotonic() - started, 1),
        url=page.get("url"),
        title=page.get("title"),
        text=" ".join((page.get("text") or "").split())[:3000],
        needs_person=needs_person,
        history=history,
    )
