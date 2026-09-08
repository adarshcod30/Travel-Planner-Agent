"""Driving the browser one action at a time, and showing the work.

`browser.py` bundles whole choreographies — navigate, snapshot, detect a block,
move to the next target — because letting a small model orchestrate a retry
loop produced hung runs. This module is the other half: the individual actions,
each emitting an event and a frame, so that both the graph and a *person* can
drive the same session and a watcher sees every step.

Two ways to name an element, for two different callers:

**By ref** — `[ref=e42]` from a snapshot's accessibility tree. This is what the
graph uses. It is precise, survives re-layout, and Playwright resolves it
against the tree it just produced.

**By coordinate** — where someone clicked on the screenshot. This is what a
person uses, because a person is looking at a picture, not at a YAML tree.
Playwright MCP exposes no coordinate click, so it goes through
`browser_evaluate` and `document.elementFromPoint`. That works here because the
screenshots are viewport-sized at devicePixelRatio 1, so screenshot pixels and
page coordinates are the same numbers — verified against the running server
rather than assumed.

Every action captures a frame afterwards. That is the whole point of the
module: the browsing is not a black box that reports a conclusion, it is
something you watch happen.
"""

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any

from travel_planner.core import events
from travel_planner.core.logging import get_logger
from travel_planner.tools.mcp.browser import mcp_text, snapshot_body
from travel_planner.tools.mcp.client import McpToolset
from travel_planner.tools.mcp.frames import capture

log = get_logger(__name__)

DEFAULT_TIMEOUT = 30.0

#: What a caller — the graph or a person — may ask the browser to do.
#: Deliberately closed: an open action set would mean validating arbitrary
#: instructions arriving over HTTP against a live browser.
ACTIONS = (
    "navigate",
    "click",
    "click_at",
    "type",
    "type_at",
    "press",
    "select",
    "scroll",
    "back",
    "wait",
    "snapshot",
)


class ControlError(Exception):
    """An action could not be carried out. Never fatal to a run."""


@dataclass
class Action:
    """One browser instruction.

    `ref` and `(x, y)` are alternative ways of naming a target; `label` is a
    human description that Playwright wants alongside a ref and that also makes
    the action log readable.
    """

    kind: str
    ref: str | None = None
    label: str = ""
    text: str = ""
    url: str = ""
    key: str = ""
    x: int | None = None
    y: int | None = None
    values: list[str] = field(default_factory=list)
    seconds: float = 1.0

    def __post_init__(self) -> None:
        if self.kind not in ACTIONS:
            raise ControlError(
                f"unknown action {self.kind!r}; expected one of {', '.join(ACTIONS)}"
            )

    @classmethod
    def parse(cls, payload: Any) -> "Action":
        """Build an action from a client's JSON, rejecting anything unexpected.

        Unknown keys are refused rather than ignored: this arrives over HTTP and
        aims at a live browser, so a typo should be an error the caller sees,
        not an instruction quietly reshaped into something else.
        """
        if not isinstance(payload, dict):
            raise ControlError(f"an action must be an object; got {type(payload).__name__}")
        kind = payload.get("kind") or payload.get("action")
        if not kind:
            raise ControlError("an action needs a 'kind'")
        allowed = {f for f in cls.__dataclass_fields__ if f != "kind"}
        unknown = set(payload) - allowed - {"kind", "action"}
        if unknown:
            raise ControlError(f"unexpected keys {sorted(unknown)}; allowed: {sorted(allowed)}")
        return cls(kind=str(kind), **{k: v for k, v in payload.items() if k in allowed})


# ---------------------------------------------------------------------------
# Reading the page
# ---------------------------------------------------------------------------

_REF_LINE = re.compile(
    r"^\s*-\s+(?P<role>[a-z]+)"  # role, e.g. button / link / textbox
    r'(?:\s+"(?P<name>[^"]*)")?'  # optional accessible name
    # Any number of bracketed attributes may sit between the name and the ref
    # — `[active]`, `[checked]`, `[expanded]`, `[cursor=pointer]`. Excluding
    # "[" here instead was a real bug: Google's search box renders as
    # `combobox "Search" [active] [ref=e40]`, so the one element a person most
    # wants to click was the one element the takeover panel could not see.
    r"(?:\s*\[[^\]]*\])*?"
    # Refs inside an iframe carry a frame prefix: `f4e19`, not `e19`.
    r"\s*\[ref=(?P<ref>[a-z]*\d*e\d+)\]",
)

#: Roles a person can meaningfully act on. The tree is mostly `generic`
#: containers; listing those would bury the six things worth clicking.
ACTIONABLE_ROLES = (
    "button",
    "link",
    "textbox",
    "searchbox",
    "combobox",
    "checkbox",
    "radio",
    "menuitem",
    "option",
    "tab",
    "switch",
    "slider",
)


def interactive_elements(snapshot: str, limit: int = 60) -> list[dict[str, str]]:
    """The things on the page someone could click or type into.

    Parsed from the snapshot rather than fetched separately, because the
    snapshot is already taken and a second round trip would describe a page
    that may have moved on.
    """
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for line in snapshot_body(snapshot).splitlines():
        m = _REF_LINE.match(line)
        if not m or m["role"] not in ACTIONABLE_ROLES:
            continue
        ref = m["ref"]
        if ref in seen:
            continue
        seen.add(ref)
        out.append({"ref": ref, "role": m["role"], "name": (m["name"] or "").strip()})
        if len(out) >= limit:
            break
    return out


def page_url(snapshot: str) -> str | None:
    for line in snapshot.splitlines()[:8]:
        if line.startswith("- Page URL:"):
            return line.split(":", 1)[1].strip()
    return None


def page_title(snapshot: str) -> str | None:
    for line in snapshot.splitlines()[:8]:
        if line.startswith("- Page Title:"):
            return line.split(":", 1)[1].strip()
    return None


#: What the page is asked about itself. Matching text in the accessibility tree
#: was the first attempt and was wrong in the most ordinary case: every
#: Wikipedia-family article carries a "Log in" link in its header, so every
#: article looked like a login page. A link that says "log in" is not a login
#: page — a password field is.
_GATE_JS = """() => {
  const q = (s) => { try { return !!document.querySelector(s); } catch { return false; } };
  const text = (document.body ? document.body.innerText || '' : '').toLowerCase();
  return {
    url: location.href,
    path: location.pathname.toLowerCase(),
    password: q('input[type=password]'),
    otp: q('input[autocomplete*="one-time-code"], input[name*="otp" i], input[id*="otp" i]'),
    card: q('input[autocomplete*="cc-number"], input[name*="cardnumber" i], input[name*="card-number" i], input[name*="card_number" i]'),
    upi: q('input[name*="upi" i], input[id*="upi" i]'),
    payText: /proceed to pay|pay now|card number|cvv|net banking/.test(text),
  };
}"""

#: Path fragments that only appear on a real authentication page.
AUTH_PATHS = ("/login", "/signin", "/sign-in", "/auth/", "/account/login")

#: Path fragments that mean money is about to move.
PAYMENT_PATHS = ("/payment", "/checkout/pay", "/paymentoptions")


def classify_gate(signals: dict[str, Any]) -> str | None:
    """Whether this page needs a person, and why.

    Two cases, and they are not the same. A login can be handed to whoever is
    watching and the run continues afterwards. A payment page is where
    automation stops for good — entering someone's card details is not
    something this system does, on any approval.

    Kept pure so the classification can be tested without a browser.
    """
    path = str(signals.get("path") or "")
    if signals.get("card") or signals.get("upi") or any(p in path for p in PAYMENT_PATHS):
        return "payment"
    if signals.get("payText"):
        return "payment"
    if signals.get("password") or signals.get("otp"):
        return "login"
    if any(p in path for p in AUTH_PATHS):
        return "login"
    return None


async def page_gate(toolset: McpToolset, timeout: float = DEFAULT_TIMEOUT) -> str | None:
    """Ask the live page whether it needs a person. None when it does not.

    Degrades to None rather than raising: a browser that cannot answer should
    let the automation continue and be caught by the next check, not stop a run
    on a failed introspection.
    """
    try:
        ev = toolset.get("browser_evaluate")
        if ev is None:
            return None
        signals = _result_json(
            mcp_text(await asyncio.wait_for(ev.ainvoke({"function": _GATE_JS}), timeout=timeout))
        )
    except Exception as exc:
        log.debug("gate_check_failed", error=f"{type(exc).__name__}: {str(exc)[:120]}")
        return None
    return classify_gate(signals)


async def read_page(toolset: McpToolset, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Snapshot the page and describe it — url, title, and what is clickable."""
    snap = toolset.get("browser_snapshot")
    if snap is None:
        raise ControlError("this session has no browser_snapshot")
    text = mcp_text(await asyncio.wait_for(snap.ainvoke({}), timeout=timeout))
    return {
        "url": page_url(text),
        "title": page_title(text),
        "elements": interactive_elements(text),
        "needs_person": await page_gate(toolset, timeout),
        "snapshot": text,
    }


# ---------------------------------------------------------------------------
# Doing something
# ---------------------------------------------------------------------------

#: Click whatever is at a point, walking up to the nearest thing that actually
#: handles a click. `elementFromPoint` returns the innermost node, which for a
#: button containing a label is the span — clicking that works by bubbling, but
#: focusing the real control first makes typing afterwards land where expected.
_CLICK_AT_JS = """(coords) => {
  const el = document.elementFromPoint(coords.x, coords.y);
  if (!el) return { ok: false, reason: 'nothing at that point' };
  const target = el.closest('a,button,input,select,textarea,[role=button],[role=link],[onclick],[tabindex]') || el;
  target.scrollIntoView({ block: 'center', behavior: 'instant' });
  if (typeof target.focus === 'function') target.focus();
  target.click();
  return { ok: true, tag: target.tagName, text: (target.innerText || target.value || '').slice(0, 80) };
}"""

#: Type into whatever is focused. The native setter is used rather than
#: assigning `.value`, because React tracks the last value it wrote and ignores
#: a plain assignment — the field would look right and submit empty.
_TYPE_AT_JS = """(payload) => {
  const el = document.activeElement;
  if (!el || !('value' in el)) return { ok: false, reason: 'nothing focused that accepts text' };
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement : HTMLInputElement;
  const setter = Object.getOwnPropertyDescriptor(proto.prototype, 'value').set;
  setter.call(el, payload.text);
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  return { ok: true, tag: el.tagName };
}"""

_SCROLL_JS = "(p) => { window.scrollBy({ top: p.dy, behavior: 'instant' }); return { ok: true, y: window.scrollY }; }"


def _result_json(text: str) -> dict[str, Any]:
    """Pull the JSON out of a `### Result … ### Ran Playwright code` reply."""
    body = text.split("### Result", 1)[-1].split("### Ran", 1)[0].strip()
    try:
        parsed = json.loads(body)
    except Exception:
        return {"ok": True, "raw": body[:200]}
    return parsed if isinstance(parsed, dict) else {"ok": True, "value": parsed}


async def _evaluate(toolset: McpToolset, fn: str, arg: Any, timeout: float) -> dict[str, Any]:
    ev = toolset.get("browser_evaluate")
    if ev is None:
        raise ControlError("this session has no browser_evaluate")
    # The function is called with one argument, so the payload is baked into the
    # source rather than passed separately — `browser_evaluate` takes no args.
    source = f"() => ({fn})({json.dumps(arg)})"
    return _result_json(
        mcp_text(await asyncio.wait_for(ev.ainvoke({"function": source}), timeout=timeout))
    )


async def perform(
    toolset: McpToolset,
    action: Action,
    *,
    thread_id: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Carry out one action, emit what happened, and capture a frame.

    Raises `ControlError` on a bad instruction — a caller sending nonsense
    should hear about it — but a failed screenshot is only ever a lost frame.
    """
    events.browser_action(action.kind, detail=_describe(action), url=action.url or None)
    result: dict[str, Any]

    match action.kind:
        case "navigate":
            if not action.url:
                raise ControlError("navigate needs a url")
            result = await _invoke(toolset, "browser_navigate", {"url": action.url}, timeout)
        case "click":
            result = await _invoke_on_ref(
                toolset,
                "browser_click",
                action.ref,
                {"element": action.label or action.ref or "element"},
                timeout,
            )
        case "click_at":
            result = await _evaluate(toolset, _CLICK_AT_JS, {"x": action.x, "y": action.y}, timeout)
        case "type":
            result = await _invoke_on_ref(
                toolset,
                "browser_type",
                action.ref,
                {"element": action.label or action.ref or "field", "text": action.text},
                timeout,
            )
        case "type_at":
            result = await _evaluate(toolset, _TYPE_AT_JS, {"text": action.text}, timeout)
        case "press":
            result = await _invoke(
                toolset, "browser_press_key", {"key": action.key or "Enter"}, timeout
            )
        case "select":
            result = await _invoke_on_ref(
                toolset,
                "browser_select_option",
                action.ref,
                {"element": action.label or action.ref or "select", "values": action.values},
                timeout,
            )
        case "scroll":
            dy = int(action.y if action.y is not None else 400)
            result = await _evaluate(toolset, _SCROLL_JS, {"dy": dy}, timeout)
        case "back":
            result = await _invoke(toolset, "browser_navigate_back", {}, timeout)
        case "wait":
            args = {"time": min(float(action.seconds), 10.0)}
            if action.text:
                args = {"text": action.text}
            result = await _invoke(toolset, "browser_wait_for", args, timeout)
        case "snapshot":
            result = {"ok": True}
        case _:  # pragma: no cover — Action.__post_init__ already refused it
            raise ControlError(f"unhandled action {action.kind!r}")

    if thread_id and (path := await capture(toolset, thread_id, events.next_seq())) is not None:
        events.browser_frame(path, note=_describe(action))
    return result


def _schema_keys(tool: Any) -> set[str]:
    schema = getattr(tool, "args_schema", None)
    if isinstance(schema, dict):
        return set(schema.get("properties") or {})
    return set(getattr(schema, "model_fields", {}) or {})


#: What Playwright MCP calls the argument naming an element from a snapshot.
#: It is `target` on the version pinned here and `ref` on others, and passing
#: the wrong one is not an error — the call succeeds having acted on nothing.
#: Reading it off the tool's own schema is what makes that impossible.
_REF_KEYS = ("target", "ref", "element_ref", "selector")


async def _invoke_on_ref(
    toolset: McpToolset,
    name: str,
    ref: str | None,
    args: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    """Invoke a tool that acts on one element, naming the ref the way it expects."""
    tool = toolset.get(name)
    if tool is None:
        raise ControlError(f"this session has no {name}")
    if not ref:
        raise ControlError(f"{name} needs a ref naming the element to act on")
    keys = _schema_keys(tool)
    key = next((k for k in _REF_KEYS if k in keys), None)
    if key is None:
        raise ControlError(f"{name} exposes no element argument; it takes {sorted(keys)}")
    return await _invoke(toolset, name, {**args, key: ref}, timeout)


async def _invoke(
    toolset: McpToolset, name: str, args: dict[str, Any], timeout: float
) -> dict[str, Any]:
    tool = toolset.get(name)
    if tool is None:
        raise ControlError(f"this session has no {name}")
    clean = {k: v for k, v in args.items() if v is not None}
    try:
        text = mcp_text(await asyncio.wait_for(tool.ainvoke(clean), timeout=timeout))
    except TimeoutError as exc:
        raise ControlError(f"{name} timed out after {timeout:g}s") from exc
    except Exception as exc:
        raise ControlError(f"{name} failed: {type(exc).__name__}: {str(exc)[:160]}") from exc
    return {"ok": True, "detail": text[:400]}


def _describe(a: Action) -> str:
    """The action as a line in a log someone is reading."""
    match a.kind:
        case "navigate":
            return a.url
        case "click":
            return a.label or a.ref or "an element"
        case "click_at":
            return f"at ({a.x}, {a.y})"
        case "type" | "type_at":
            # Never the text itself: a person taking over a login types into
            # this, and the action log is streamed, stored and screenshotted.
            return f"{len(a.text)} characters into {a.label or 'the focused field'}"
        case "press":
            return a.key or "Enter"
        case "select":
            return f"{a.label or a.ref}: {', '.join(a.values)}"
        case "scroll":
            return f"{a.y or 400}px"
        case "wait":
            return a.text or f"{a.seconds:g}s"
        case _:
            return a.label or ""
