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
    r"^(?P<indent>\s*)-\s+(?P<role>[a-z]+)"  # role, e.g. button / link / generic
    r'(?:\s+"(?P<name>[^"]*)")?'  # accessible name, when it has one
    # Any number of bracketed attributes may sit between the name and the ref
    # — `[active]`, `[checked]`, `[cursor=pointer]`. Excluding "[" here instead
    # was a real bug: Google's search box renders as
    # `combobox "Search" [active] [ref=e40]`, so the one element a person most
    # wants to click was the one element the takeover panel could not see.
    r"(?P<attrs>(?:\s*\[[^\]]*\])*?)"
    # Refs inside an iframe carry a frame prefix: `f4e19`, not `e19`.
    r"\s*\[ref=(?P<ref>[a-z]*\d*e\d+)\]"
    # Text content sits after the colon: `- generic [ref=e72]: Where to`.
    r"\s*:?\s*(?P<text>.*)$"
)

#: Roles that are unambiguously worth acting on.
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
    "spinbutton",
)

#: Roles that are usually containers — and sometimes the entire search widget.
#:
#: goibibo's "Where to" field is not an input. It renders as
#: `generic [ref=e72]: Where to`, a div with a click handler, and so do its
#: date fields and its SEARCH button. Excluding generics made the one thing
#: that page exists for invisible, and a browsing loop given that page could
#: only click the nav bar over and over — which is exactly what it did.
_CONTAINER_ROLES = ("generic", "paragraph", "heading", "listitem", "cell", "img", "image")

#: Labels a card puts on its own controls. They are not the card.
_CONTROL_PHRASES = (
    "price per night",
    "check availability",
    "view deal",
    "select room",
    "see availability",
    "view rooms",
    "book now",
    "show prices",
)

#: Words that mark a container as part of a search or booking widget. Short
#: label text on a div is the shape those widgets take.
_WIDGET_WORDS = (
    "search",
    "where",
    "check-in",
    "check in",
    "checkout",
    "check-out",
    "guest",
    "room",
    "adult",
    "child",
    "date",
    "depart",
    "return",
    "book",
    "select",
    "continue",
    "apply",
    "done",
    "next",
    "submit",
    "login",
    "sign in",
    "accept",
    "agree",
    "close",
    "dismiss",
    "got it",
    "price",
    "night",
    "view",
)


#: A real price: a currency and an amount, not part of a range and not the
#: label on a filter. "₹0 to ₹1000" is a checkbox; "₹5,719" is a hotel.
_REAL_PRICE = re.compile(r"(?:₹|Rs\.?|INR)\s?[0-9][0-9,]{2,}")
_PRICE_RANGE = re.compile(
    r"(?:₹|Rs\.?|INR)\s?[0-9][0-9,]*\s*(?:-|\u2013|to)\s*(?:₹|Rs\.?|INR)?\s?[0-9][0-9,]*"
)

#: How far from a price an element can be and still belong to that result.
#: A card is a dozen or so lines of tree; beyond that is the next card.
_PRICE_WINDOW = 14


#: Text on a line, whether it is an accessible name or content after the colon.
_TEXT_ON_LINE = re.compile(r'(?:"([^"]{2,60})")|(?::\s*(.{2,60}?)\s*$)')

#: Bracketed attributes, which are metadata rather than anything a reader sees.
_ATTRS = re.compile(r"\[[^\]]*\]")


#: Fragments that are furniture, not the name of anything. A card's first few
#: text nodes are its image carousel and its rating badge, so taking them in
#: document order labelled every hotel on the page "View All · 4".
_FURNITURE = frozenset(
    {
        "view all",
        "ad",
        "copy",
        "new",
        "more",
        "read more",
        "see all",
        "next",
        "previous",
        "close",
        "share",
        "save",
        "sold out",
        "%",
        "off",
    }
)


def _looks_like_a_name(text: str) -> bool:
    stripped = text.strip().strip('"').strip()
    if len(stripped) < 6 or stripped.lower() in _FURNITURE:
        return False
    # A rating, a review count, a price on its own — a number is never a name.
    return not re.fullmatch(r"[\d.,()₹%+\-\s]+", stripped)


def _shared_run(fragments: list[str], minimum: int = 8) -> str:
    """The longest phrase two or more fragments have in common.

    Some sites build a card entirely out of image alt text — agoda's read
    "Exterior view, Hotel Taj Inn in Agra" and "Public areas, Hotel Taj Inn in
    Agra" — so no single fragment is the hotel's name, but every one of them
    contains it. What repeats across them is the thing they are all pictures
    of, and that is exactly the name.
    """
    if len(fragments) < 2:
        return ""
    first, best = fragments[0], ""
    for other in fragments[1:]:
        # Longest common substring of two fragments, walking the shorter one.
        for start in range(len(first)):
            for end in range(len(first), start + len(best), -1):
                piece = first[start:end]
                if len(piece) > len(best) and piece in other:
                    best = piece
                    break
    return _snap_to_word(best) if len(_snap_to_word(best)) >= minimum else ""


def _snap_to_word(text: str) -> str:
    """Trim a common substring back to where a word actually starts.

    A longest-common-substring does not respect word boundaries: "Recreational
    facilities, Hotel Sahibs Royal Ville" and "Exterior view, Hotel Sahibs
    Royal Ville" share the trailing "n" of two different words, so the run came
    out as "n, Hotel Sahibs Royal Ville in Agra".
    """
    trimmed = text.strip(" ,.-·|")
    # A partial word followed by a comma is the common case: "n, Hotel …".
    trimmed = re.sub(r"^[a-z]*[,;]\s*", "", trimmed)
    # Otherwise start at the first capitalised word, if one is close by.
    if trimmed[:1].islower() and (m := re.search(r"\b[A-Z]", trimmed[:25])):
        trimmed = trimmed[m.start() :]
    return trimmed.strip(" ,.-·|")


def _name_first(fragments: list[str]) -> list[str]:
    """Put the fragment that reads like a name in front.

    A card's fragments come out as "| 11.3 km drive to Taj Mahal" and "Lemon
    Tree Hotel Agra", and longest-first put the distance first — so the model
    read a list of directions rather than a list of hotels. What it is called
    is the part that decides whether to open it.
    """

    def name_like(text: str) -> int:
        first = text.lstrip("|·-— ")[:1]
        return 0 if first.isupper() and not text.lstrip("|·-— ")[:1].isdigit() else 1

    return sorted(fragments, key=lambda f: (name_like(f), -len(f)))


def _label_from_children(lines: list[str], index: int, indent: int) -> str:
    """Name an unnamed container from the best text inside it.

    Booking sites build a result card as a clickable div wrapping a dozen
    unnamed divs: the hotel's name, its rating and its price are all
    descendants and the card itself has no accessible name. Dropping unnamed
    elements therefore dropped every result on the page and left the agent
    choosing between filters — which is exactly what it did, concluding that a
    filter called "Book @ ₹0" was a cheap hotel.

    Longest-first rather than document order, because the first fragments in a
    card are its carousel arrows and its rating badge, and the longest is
    almost always the name.
    """
    parts: list[str] = []
    for line in lines[index + 1 : index + 30]:
        if not line.strip():
            continue
        depth = len(line) - len(line.lstrip())
        if depth <= indent:
            break  # out of this element and into its sibling
        if (m := _TEXT_ON_LINE.search(line.rstrip())) is None:
            continue
        text = _ATTRS.sub("", m.group(1) or m.group(2) or "").strip().strip('"')
        if _looks_like_a_name(text) and text not in parts:
            parts.append(text)

    cleaned = [p.lstrip("|·-— ").strip() for p in parts]

    # When the fragments are all descriptions of the same thing, what they
    # share is its name — and that beats any one of them. The first version
    # skipped this whenever the shared phrase was *also* a fragment on its own,
    # which is backwards: a card that says "Hotel Taj Inn in Agra" outright and
    # then six more times inside its image captions is the clearest case there
    # is, and it was the only case that mattered.
    if shared := _shared_run(cleaned):
        rest = [f for f in cleaned if shared not in f][:1]
        return " · ".join([shared, *rest])[:90]

    return " · ".join(_name_first(cleaned)[:2])[:90]


def _price_anchors(lines: list[str]) -> set[int]:
    """Line numbers where a real, individual price appears.

    This is what tells a results page apart from a search form. A listing page
    puts its filters at the top — every sort option, every amenity, every price
    band — and its actual results four hundred lines down. Ranked by role
    alone, the filters win every slot and the results are never seen at all,
    which is precisely how a browsing loop ends up clicking "Book @ ₹0" (a
    filter) and concluding it had found a cheap hotel.
    """
    anchors: set[int] = set()
    for i, line in enumerate(lines):
        if not _REAL_PRICE.search(line) or _PRICE_RANGE.search(line):
            continue
        if any(role in line for role in ("checkbox", "radio", "slider")):
            continue
        anchors.add(i)
    return anchors


def _near_price(index: int, anchors: set[int]) -> bool:
    return any(abs(index - a) <= _PRICE_WINDOW for a in anchors)


def _score(role: str, name: str, clickable: bool, borrowed: bool = False) -> int:
    """How likely this element is to be the thing you want to act on.

    Ranking rather than filtering, because a page's most important control is
    routinely a div and its first forty elements are routinely a nav bar. In
    document order the useful half never survives truncation.
    """
    lowered = name.lower()
    # A clickable container that had to borrow its label from four separate
    # descendants is a card — a hotel, a flight, a room. Nothing else on a page
    # has that shape, and on a results page it is the only thing worth
    # clicking. Scored above every filter and every input deliberately: the
    # first version ranked inputs highest and buried all 429 hotels beneath a
    # sort dropdown and a list of amenity checkboxes.
    if borrowed and clickable:
        # A card's own controls sit in clickable boxes too, and they read like
        # labels rather than names. agoda's "Avg price per night · Check
        # availability" is the price block *of* a card, and it outranked every
        # hotel on the page.
        if any(phrase in lowered for phrase in _CONTROL_PHRASES):
            return 30
        # An amenity filter — "Guaranteed Late Check-out" — is a clickable box
        # with one phrase in it, and the phrase is about booking mechanics.
        if any(w in lowered for w in _WIDGET_WORDS):
            return 30
        # What is left is content: either several distinct fragments, or one
        # long enough to be a name rather than a label.
        return 140 if " · " in name or len(name) > 18 else 25
    if role in ("textbox", "searchbox", "combobox", "spinbutton"):
        return 100
    if role == "button" and name:
        return 90 if any(w in lowered for w in _WIDGET_WORDS) else 70
    if clickable and any(w in lowered for w in _WIDGET_WORDS):
        return 85
    if role in _CONTAINER_ROLES and name and len(name) < 40:
        return 80 if any(w in lowered for w in _WIDGET_WORDS) else 20
    if role in ("checkbox", "radio", "option", "tab", "menuitem", "switch", "slider"):
        return 60
    if clickable:
        return 40
    if role == "link" and name:
        return 30
    return 0


def interactive_elements(snapshot: str, limit: int = 40) -> list[dict[str, str]]:
    """The things on the page worth clicking or typing into, best first.

    Parsed from the snapshot rather than fetched separately, because the
    snapshot is already taken and a second round trip would describe a page
    that may have moved on.
    """
    found: list[tuple[int, int, dict[str, str]]] = []
    seen: set[str] = set()

    lines = snapshot_body(snapshot).splitlines()
    anchors = _price_anchors(lines)

    for order, line in enumerate(lines):
        m = _REF_LINE.match(line)
        if not m:
            continue
        ref = m["ref"]
        if ref in seen:
            continue

        role = m["role"]
        # `[cursor=pointer]` sits on either side of the ref depending on what
        # else the node carries, so the whole line is what has to be checked.
        # Looking only at the attributes before the ref made every clickable
        # card on a listing page read as unclickable.
        clickable = "cursor=pointer" in line
        raw = m["name"] or _ATTRS.sub("", m["text"] or "")
        name = raw.strip().strip(":").strip()

        # A clickable container with no name of its own is a card. Borrow one
        # from its contents so it can be seen, ranked and clicked.
        borrowed = False
        if not name and clickable:
            name = _label_from_children(lines, order, len(m["indent"]))
            borrowed = bool(name)

        score = _score(role, name, clickable, borrowed)
        # A named element sitting beside a real price is a result — a hotel, a
        # flight, a room — and on a results page those are the only things
        # worth acting on. Weighted above every filter deliberately.
        if name and _near_price(order, anchors):
            score += 95
        if score <= 0:
            continue
        # An unnamed link is nothing a model can reason about; an unnamed input
        # still is, because its role says what it is for.
        if not name and role not in ("textbox", "searchbox", "combobox"):
            continue

        seen.add(ref)
        found.append((-score, order, {"ref": ref, "role": role, "name": name[:90]}))

    found.sort(key=lambda x: (x[0], x[1]))
    return [item for _, _, item in found[:limit]]


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


#: Every DOM query in this module is built on this, and it is not optional.
#:
#: `document.querySelector` does not cross a shadow root. goibibo — and most
#: modern booking sites — render their entire page inside shadow DOM, so
#: `document.querySelectorAll('div')` returns **zero** on a page visibly full
#: of them. Everything built on a plain query was therefore blind on exactly
#: the sites that matter: the login gate never fired, the overlay was never
#: seen, and a coordinate click resolved to the shadow host rather than the
#: thing under the cursor. Playwright's own snapshot pierces shadow roots,
#: which is why the accessibility tree looked healthy while the DOM looked
#: empty — and why this took so long to notice.
_DEEP = """
const deepAll = (selector, root = document) => {
  const out = [];
  const walk = (node) => {
    if (!node) return;
    try { out.push(...node.querySelectorAll(selector)); } catch {}
    const kids = node.querySelectorAll ? node.querySelectorAll('*') : [];
    for (const el of kids) if (el.shadowRoot) walk(el.shadowRoot);
  };
  walk(root);
  return out;
};
const deep = (selector) => deepAll(selector)[0] || null;
const deepText = () => {
  const parts = [];
  const walk = (node) => {
    if (!node) return;
    for (const el of node.querySelectorAll ? node.querySelectorAll('*') : []) {
      if (el.shadowRoot) walk(el.shadowRoot);
    }
  };
  walk(document);
  return document.body ? document.body.innerText || '' : '';
};
"""


#: What the page is asked about itself. Matching text in the accessibility tree
#: was the first attempt and was wrong in the most ordinary case: every
#: Wikipedia-family article carries a "Log in" link in its header, so every
#: article looked like a login page. A link that says "log in" is not a login
#: page — a password field is.
_GATE_JS = (
    """() => {"""
    + _DEEP
    + """
  const q = (s) => { try { return !!deep(s); } catch { return false; } };
  const text = (document.body ? document.body.innerText || '' : '').toLowerCase();
  return {
    url: location.href,
    path: location.pathname.toLowerCase(),
    password: q('input[type=password]'),
    otp: q('input[autocomplete*="one-time-code"], input[name*="otp" i], input[id*="otp" i]'),
    // A phone-number login. Indian booking sites sign you in by mobile number
    // rather than a password, so "is there a password field" missed the single
    // most common login wall on every site this planner actually uses.
    phone: q('input[type=tel], input[autocomplete*="tel"], input[name*="mobile" i], input[name*="phone" i]'),
    // Whether a credential field is actually what this page is *for*, rather
    // than a sign-in widget parked in the header. Every travel site has one of
    // those on every page, so "there is a phone input somewhere" flagged the
    // flight search as a login wall. A real one is in a dialog, or on a page
    // with almost nothing else on it.
    credentialInModal: (() => {
      const field = deep('input[type=password], input[type=tel], input[autocomplete*="one-time-code"]');
      if (!field) return false;
      for (let el = field.parentElement; el; el = el.parentElement) {
        const s = getComputedStyle(el);
        if ((s.position === 'fixed' || s.position === 'absolute') &&
            ((+s.zIndex || 0) > 100 || el.getAttribute('role') === 'dialog' || el.tagName === 'DIALOG')) {
          return true;
        }
      }
      return false;
    })(),
    inputCount: deepAll('input').length,
    card: q('input[autocomplete*="cc-number"], input[name*="cardnumber" i], input[name*="card-number" i], input[name*="card_number" i]'),
    upi: q('input[name*="upi" i], input[id*="upi" i]'),
    payText: /proceed to pay|pay now|card number|cvv|net banking/.test(text),
  };
}"""
)


#: Path fragments that only appear on a real authentication page.
AUTH_PATHS = ("/login", "/signin", "/sign-in", "/auth/", "/account/login")

#: Path fragments that mean money is about to move.
PAYMENT_PATHS = ("/payment", "/checkout/pay", "/paymentoptions", "-booking/", "/booking/")

#: Pages that talk about cards without asking for one. Every Indian travel site
#: markets a co-branded credit card, and those pages are thick with "card
#: number", "CVV" and "net banking" — a run once stopped on
#: `makemytrip.com/cards/makemytrip-icici-bank-credit-card` and reported it had
#: reached the payment page.
_CARD_MARKETING = ("/cards/", "/credit-card", "/offers/", "/blog/")


#: Whether a modal is sitting over the page, and whether it can be closed.
#:
#: This is the difference between "hand the browser to a person" and "press the
#: X and carry on". Booking sites throw a Login/Signup panel over their listing
#: within seconds of arriving — it is promotional, it is dismissible, and it
#: swallows every click aimed at the page behind it. Treating it as a login
#: wall would stop a run that only needed one click; ignoring it left the agent
#: clicking a hotel card over and over while the overlay ate every one.
_OVERLAY_JS = """() => {
  const vw = innerWidth, vh = innerHeight;
  const looksModal = (el) => {
    const s = getComputedStyle(el);
    if (s.position !== 'fixed' && s.position !== 'absolute') return false;
    if (s.visibility === 'hidden' || s.display === 'none' || +s.opacity === 0) return false;
    const r = el.getBoundingClientRect();
    if (r.width < vw * 0.2 || r.height < vh * 0.2) return false;
    if (r.bottom < 0 || r.top > vh || r.right < 0 || r.left > vw) return false;
    // A dialog role or a stacking context above the page is the usual tell,
    // but a promotional login panel often has neither until it is shown — so
    // "large, floating, on screen, and closable" counts too.
    return true;
  };
  const closerFor = (el) => el.querySelector(
      '[aria-label*="close" i],[title*="close" i],[class*="close" i],[data-testid*="close" i],button.close'
    ) || [...el.querySelectorAll('button,span,div[role=button],svg,i')].find(
      n => ['\u00d7', '\u2715', '\u2716', '\u274c', 'x', 'close'].includes(
        (n.textContent || n.getAttribute('aria-label') || '').trim().toLowerCase())
    );

  const candidates = [...document.querySelectorAll('div,section,aside,dialog')].filter(looksModal);
  if (!candidates.length) return { present: false };
  const scored = candidates
    .map(el => ({ el, z: +getComputedStyle(el).zIndex || 0, closer: closerFor(el) }))
    .filter(c => c.closer || c.z > 100 || c.el.getAttribute('role') === 'dialog')
    .sort((a, b) => b.z - a.z);
  if (!scored.length) return { present: false };
  const top = scored[0];
  return {
    present: true,
    z: top.z,
    text: (top.el.innerText || '').replace(/\\s+/g, ' ').slice(0, 160),
    closable: !!top.closer,
  };
}"""


async def dismiss_overlay(toolset: McpToolset, timeout: float = DEFAULT_TIMEOUT) -> str | None:
    """Close a modal sitting over the page. Returns what it closed, or None.

    Only ever presses a close control that the modal itself provides — it does
    not click through, around, or past anything. A modal with no way out is
    left alone, because that is a wall and walls are a person's business.
    """
    ev = toolset.get("browser_evaluate")
    if ev is None:
        return None
    try:
        found = _result_json(
            mcp_text(await asyncio.wait_for(ev.ainvoke({"function": _OVERLAY_JS}), timeout=timeout))
        )
    except Exception:
        return None
    if not found.get("present") or not found.get("closable"):
        return None

    clicked = _result_json(
        mcp_text(await asyncio.wait_for(ev.ainvoke({"function": _CLOSE_JS}), timeout=timeout))
    )
    if clicked.get("ok"):
        summary = " ".join(str(found.get("text", "")).split())[:60]
        log.info("overlay_dismissed", text=summary)
        events.browser_action("dismiss", detail=f"closed an overlay: {summary}")
        return summary
    return None


#: Press the modal's own close control. Kept separate from finding it so the
#: page is not mutated by a query that was only meant to look.
_CLOSE_JS = """() => {
  const vw = innerWidth, vh = innerHeight;
  const looksModal = (el) => {
    const s = getComputedStyle(el);
    if (s.position !== 'fixed' && s.position !== 'absolute') return false;
    if (s.visibility === 'hidden' || s.display === 'none' || +s.opacity === 0) return false;
    const r = el.getBoundingClientRect();
    return r.width >= vw * 0.2 && r.height >= vh * 0.2
      && r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw;
  };
  const closerFor = (el) => el.querySelector(
      '[aria-label*="close" i],[title*="close" i],[class*="close" i],[data-testid*="close" i],button.close'
    ) || [...el.querySelectorAll('button,span,div[role=button],svg,i')].find(
      n => ['\u00d7', '\u2715', '\u2716', '\u274c', 'x', 'close'].includes(
        (n.textContent || n.getAttribute('aria-label') || '').trim().toLowerCase())
    );

  const scored = [...document.querySelectorAll('div,section,aside,dialog')]
    .filter(looksModal)
    .map(el => ({ el, z: +getComputedStyle(el).zIndex || 0, closer: closerFor(el) }))
    .filter(c => c.closer)
    .sort((a, b) => b.z - a.z);
  if (!scored.length) return { ok: false };
  const target = scored[0].closer;
  (target.closest('button,[role=button]') || target).click();
  return { ok: true };
}"""


def classify_gate(signals: dict[str, Any]) -> str | None:
    """Whether this page needs a person, and why.

    Two cases, and they are not the same. A login can be handed to whoever is
    watching and the run continues afterwards. A payment page is where
    automation stops for good — entering someone's card details is not
    something this system does, on any approval.

    Kept pure so the classification can be tested without a browser.
    """
    path = str(signals.get("path") or "")

    # A real card or UPI field is decisive wherever it appears, and it is
    # checked before anything that could wave a page through. Getting this
    # order wrong is the one mistake here that matters: it would let an
    # exemption for marketing pages carry a genuine card form with it.
    if signals.get("card") or signals.get("upi"):
        return "payment"

    if any(marketing in path for marketing in _CARD_MARKETING):
        return None  # an advert for a credit card is not a request for one

    if any(p in path for p in PAYMENT_PATHS):
        return "payment"
    # Payment *words* are not enough on their own — they are all over a
    # marketing page. They count only where money is plausibly moving.
    if signals.get("payText") and any(
        p in path for p in ("/checkout", "/book", "/review", "/pay", "/order")
    ):
        return "payment"
    if any(p in path for p in AUTH_PATHS):
        return "login"
    # A credential field only counts when signing in is what the page is
    # asking for: inside a modal, or on a page with almost nothing else. Every
    # travel site parks a sign-in widget in its header, and treating that as a
    # login wall stopped a run on the flight search page.
    has_credential = signals.get("password") or signals.get("otp") or signals.get("phone")
    if has_credential and (
        signals.get("credentialInModal") or int(signals.get("inputCount") or 0) <= 6
    ):
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


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
#
# Search results and booking sites open things in new tabs constantly, and a
# tab that opens is almost always the thing you just asked for. Ignoring that
# leaves you reading the page you clicked *from* — which looks like the click
# silently failed, or worse, like it went somewhere else entirely.

_TAB_LINE = re.compile(
    r"^\s*-\s+(?P<index>\d+):\s*(?P<current>\(current\)\s*)?\[(?P<title>[^\]]*)\]\((?P<url>[^)]*)\)"
)


def parse_tabs(listing: str) -> list[dict[str, Any]]:
    """The open tabs, as Playwright describes them."""
    out: list[dict[str, Any]] = []
    for line in listing.splitlines():
        m = _TAB_LINE.match(line)
        if m:
            out.append(
                {
                    "index": int(m["index"]),
                    "current": bool(m["current"]),
                    "title": m["title"],
                    "url": m["url"],
                }
            )
    return out


async def list_tabs(toolset: McpToolset, timeout: float = DEFAULT_TIMEOUT) -> list[dict[str, Any]]:
    tool = toolset.get("browser_tabs")
    if tool is None:
        return []
    try:
        return parse_tabs(
            mcp_text(await asyncio.wait_for(tool.ainvoke({"action": "list"}), timeout=timeout))
        )
    except Exception as exc:
        log.debug("tabs_list_failed", error=f"{type(exc).__name__}: {str(exc)[:120]}")
        return []


async def select_tab(toolset: McpToolset, index: int, timeout: float = DEFAULT_TIMEOUT) -> bool:
    tool = toolset.get("browser_tabs")
    if tool is None:
        return False
    try:
        await asyncio.wait_for(tool.ainvoke({"action": "select", "index": index}), timeout=timeout)
        return True
    except Exception as exc:
        log.debug("tab_select_failed", index=index, error=type(exc).__name__)
        return False


async def close_tab(
    toolset: McpToolset, index: int | None = None, timeout: float = DEFAULT_TIMEOUT
) -> bool:
    tool = toolset.get("browser_tabs")
    if tool is None:
        return False
    args: dict[str, Any] = {"action": "close"}
    if index is not None:
        args["index"] = index
    try:
        await asyncio.wait_for(tool.ainvoke(args), timeout=timeout)
        return True
    except Exception as exc:
        log.debug("tab_close_failed", index=index, error=type(exc).__name__)
        return False


async def follow_new_tab(
    toolset: McpToolset, before: list[dict[str, Any]], timeout: float = DEFAULT_TIMEOUT
) -> dict[str, Any] | None:
    """If an action opened a tab, move to it. Returns the tab moved to.

    Compared by index rather than by count: a click can close one tab and open
    another in the same step, which leaves the count unchanged and the content
    completely different.
    """
    after = await list_tabs(toolset, timeout)
    known = {tab["index"] for tab in before}
    fresh = [tab for tab in after if tab["index"] not in known]
    if not fresh:
        return None
    target = fresh[-1]
    if await select_tab(toolset, target["index"], timeout):
        events.browser_action("switch tab", detail=target["title"][:80] or target["url"][:80])
        return target
    return None


async def page_url_now(toolset: McpToolset, timeout: float = DEFAULT_TIMEOUT) -> str | None:
    """Just the address, without paying for a whole accessibility tree.

    Used after every action to answer "did anything happen", which is the one
    thing a browsing loop most needs to know and cannot infer.
    """
    for tab in await list_tabs(toolset, timeout):
        if tab["current"]:
            return str(tab["url"])
    return None


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
