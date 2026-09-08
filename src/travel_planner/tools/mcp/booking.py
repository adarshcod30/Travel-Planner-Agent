"""Taking an approved plan to a real booking page.

The research pass reads the web to *write* a plan. This does the opposite: the
plan already exists and was approved, and the job is to get a person in front
of a real, live, priced booking for it.

Three things shape the design.

**Commercial travel sites fight automated browsers, and that is fine here.**
The research pass treats a block as a reason to try the next target. Booking
treats it as the moment to hand over: the browser is already open on the right
site with the right search, and the person watching can simply take it. A block
stops being a failure and becomes the point of the feature.

**Automation stops at payment.** Card, UPI and net-banking details are not
something this system types, on any approval. When a page asks for them the
browser is handed over for good — `handover.serve` with reason `payment`, which
does not come back.

**Everything is watched.** Every navigation, click and page read emits an event
and a frame, so booking is not a black box that reports "done" — it is the same
live filmstrip as the research pass, on the pages that matter most.
"""

import contextlib
import re
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import quote, urlsplit

from travel_planner.core import events
from travel_planner.core.config import Settings, get_settings
from travel_planner.core.logging import get_logger
from travel_planner.tools.mcp import agent, control, handover
from travel_planner.tools.mcp.browser import looks_blocked, snapshot_body
from travel_planner.tools.mcp.client import McpToolset

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

_MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        (
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ),
        start=1,
    )
}


def resolve_dates(
    season: str | None, days: int | None, today: date | None = None
) -> tuple[date, date]:
    """Turn "November" and 3 days into two real dates.

    A booking search needs actual dates, and the planner asks for a month. The
    rule is the obvious one — the next occurrence of that month, starting on
    the 8th so the search lands in the middle of it rather than on a month
    boundary — and it is stated here rather than left to a model, because a
    date is arithmetic and a wrong one silently prices the wrong trip.
    """
    today = today or datetime.now(UTC).date()
    nights = max(1, min(int(days or 3), 30))

    month = _MONTHS.get((season or "").strip().lower()[:9])
    if month is None:
        # Explicit ISO date, if that is what the caller gave us.
        try:
            start = date.fromisoformat((season or "").strip()[:10])
        except ValueError:
            start = today + timedelta(days=21)
    else:
        year = today.year if month >= today.month else today.year + 1
        start = date(year, month, 8)
        if start <= today:
            start = date(year + 1, month, 8)

    if start <= today:
        start = today + timedelta(days=7)
    return start, start + timedelta(days=nights)


# ---------------------------------------------------------------------------
# Where to look
# ---------------------------------------------------------------------------


def _slug(city: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", city.split(",")[0].strip().lower()).strip("-")


#: Agoda addresses cities by country-suffixed path, not by search query — a
#: `/search?city=Agra` link bounces to the home page, while
#: `/city/agra-in.html` shows real rooms. Only the destinations this planner
#: actually reaches are worth listing; anything else falls back to India, which
#: is where the overwhelming majority of these trips go.
_AGODA_COUNTRY = {
    "india": "in",
    "nepal": "np",
    "sri lanka": "lk",
    "bhutan": "bt",
    "thailand": "th",
    "singapore": "sg",
    "malaysia": "my",
    "indonesia": "id",
    "vietnam": "vn",
    "united arab emirates": "ae",
    "uae": "ae",
    "japan": "jp",
}


def _country_code(city: str) -> str:
    """The two-letter code Agoda expects, from a "City, Country" string."""
    parts = [p.strip().lower() for p in city.split(",")]
    return _AGODA_COUNTRY.get(parts[-1], "in") if len(parts) > 1 else "in"


def stay_targets(city: str, checkin: date, checkout: date, travelers: int) -> list[tuple[str, str]]:
    """Booking pages to try, in order, for a place to stay.

    Indian aggregators lead: they are what a traveller here would actually book
    through and they quote rupees natively, so no conversion sits between the
    plan's budget and the real price.
    """
    slug = _slug(city)
    adults = max(1, travelers)
    mmt_in, mmt_out = (d.strftime("%m%d%Y") for d in (checkin, checkout))
    iso_in, iso_out = (d.isoformat() for d in (checkin, checkout))
    rooms = f"{adults}e0e"
    return [
        (
            "goibibo",
            f"https://www.goibibo.com/hotels/hotels-in-{slug}-ct/"
            f"?hquery=%7B%22ci%22%3A%22{iso_in}%22%2C%22co%22%3A%22{iso_out}%22%7D",
        ),
        (
            "makemytrip",
            f"https://www.makemytrip.com/hotels/hotel-listing/?checkin={mmt_in}&checkout={mmt_out}"
            f"&roomStayQualifier={rooms}&locusType=city&searchText={quote(city)}&country=IN",
        ),
        (
            # `no_rooms` and `group_children` are what make this a complete
            # search rather than a partial one it fills in from a cookie.
            "booking.com",
            f"https://www.booking.com/searchresults.html?ss={quote(city)}"
            f"&checkin={iso_in}&checkout={iso_out}&group_adults={adults}"
            f"&no_rooms=1&group_children=0&selected_currency=INR",
        ),
        (
            # A path, not a query. `/search?city=Agra` bounces to the home page;
            # this shows rooms.
            "agoda",
            f"https://www.agoda.com/en-in/city/{slug}-{_country_code(city)}.html"
            f"?checkIn={iso_in}&checkOut={iso_out}&adults={adults}",
        ),
    ]


def travel_targets(origin: str | None, city: str, when: date) -> list[tuple[str, str]]:
    """Pages for getting there. Rail first — for most Indian trips it is the answer."""
    if not origin:
        return []
    o, d = _slug(origin), _slug(city)
    iso = when.isoformat()
    return [
        ("ixigo trains", f"https://www.ixigo.com/trains/{o}-to-{d}?date={when.strftime('%d%m%Y')}"),
        ("makemytrip flights", f"https://www.makemytrip.com/flight/search?itinerary={o}-{d}-{iso}"),
        (
            "google flights",
            f"https://www.google.com/travel/flights?q=flights%20{quote(origin)}%20to%20{quote(city)}",
        ),
    ]


# ---------------------------------------------------------------------------
# Reading prices off a page
# ---------------------------------------------------------------------------

#: Rupee amounts, with or without grouping. Deliberately narrow: a listing page
#: is full of numbers and only the ones marked as currency are prices.
_PRICE = re.compile(r"(?:₹|Rs\.?|INR)\s?([0-9][0-9,]{2,})")

#: The role at the start of an accessibility-tree line, if it has one.
_ROLE = re.compile(r"^\s*-\s+([a-z]+)")

#: Roles that are controls for narrowing a search, not results of one. Every
#: aggregator has a "Price per night" filter, and its options read exactly like
#: prices — "₹0 to ₹1000" is a checkbox, not a hotel.
_FILTER_ROLES = frozenset(
    {"checkbox", "radio", "slider", "textbox", "searchbox", "combobox", "option", "spinbutton"}
)

#: Two amounts with a range separator between them. That is what a price
#: filter looks like once its role has been stripped away — and unanchored,
#: because aggregators render whole rows of them ("\u20b90-\u20b91500, \u20b91500-\u20b92500, ...").
#:
#: "Original price \u20b917,097. Current price \u20b95,813." survives this deliberately:
#: there are words between the two amounts, so it is a discount rather than a
#: range, and the second figure is what you would actually pay.
_BARE_RANGE = re.compile(
    "(?:\u20b9|Rs\\.?|INR)\\s?[0-9][0-9,]*\\s*(?:-|\u2013|to)\\s*(?:\u20b9|Rs\\.?|INR)?\\s?[0-9][0-9,]*"
)

#: Not a room rate: money coming off the price, or money added to it. Taken
#: from a live goibibo listing, where the cheapest "price" on the page was a
#: "+₹501 taxes & fees" line — which would have been reported as the cheapest
#: hotel in Agra.
_NOT_A_RATE = (
    "off*",
    " off",
    "up to",
    "save ",
    "discount",
    "cashback",
    "coupon",
    "offer",
    "tax",
    "fee",
)

#: An amount written as an addition ("+₹1,382") or an open-ended filter bound
#: ("₹5500+") is describing something other than the price of a room.
_ADDED = re.compile(r"\+\s*(?:₹|Rs\.?|INR)")
_OPEN_RANGE = re.compile(r"(?:₹|Rs\.?|INR)\s?[0-9][0-9,]*\s*\+")


def extract_prices(snapshot: str, limit: int = 12) -> list[dict[str, str]]:
    """Lines from a listing page that carry a real rupee price.

    Read off the accessibility tree rather than the rendered pixels, so this
    works on whatever the site actually served rather than on a guess about its
    markup.

    Most of this function is about what *not* to believe. A live listing page
    is covered in rupee figures that are not what a room costs — the price
    filter's own options, a banner offering money off, a struck-through
    "original price" — and reporting one of those as the cheapest hotel is a
    plausible-looking lie about what a trip costs, which is worse than
    returning nothing.
    """
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in snapshot_body(snapshot).splitlines():
        amounts = _PRICE.findall(raw)
        if not amounts:
            continue

        role_match = _ROLE.match(raw)
        if role_match and role_match.group(1) in _FILTER_ROLES:
            continue

        text = re.sub(r"\[[^\]]*\]", "", raw).strip(' -:"').strip()
        lowered = text.lower()
        if any(word in lowered for word in _NOT_A_RATE):
            continue
        if _BARE_RANGE.search(text) or _OPEN_RANGE.search(text) or _ADDED.search(text):
            continue

        # Several amounts on one line is normally "was X, now Y" — the last one
        # is what you would actually pay.
        amount = amounts[-1].replace(",", "")
        if not amount.isdigit() or not (300 <= int(amount) <= 500000):
            continue  # phone numbers, pincodes, review counts

        key = f"{amount}:{text[:40]}"
        if key in seen:
            continue
        seen.add(key)
        out.append({"price_inr": amount, "line": text[:160]})
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def stay_goal(city: str, checkin: date, checkout: date, travelers: int) -> str:
    """What the browsing agent is actually trying to achieve.

    Written as an instruction to a person, with the finish line stated
    explicitly — "prices per night are visible" is checkable from the page,
    where "find a hotel" is not, and a goal a model cannot tell it has reached
    is a goal it browses past.
    """
    nights = (checkout - checkin).days
    return (
        f"Search for hotels in {city} for {checkin.strftime('%-d %B %Y')} to "
        f"{checkout.strftime('%-d %B %Y')} ({nights} nights) for {travelers} adults. "
        "You are finished the moment a list of hotels with prices per night is on screen. "
        "Do not open an individual hotel and do not start a booking."
    )


async def search_by_hand(
    toolset: McpToolset,
    *,
    thread_id: str,
    city: str,
    checkin: date,
    checkout: date,
    travelers: int,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Drive a booking site the way a person would, rather than by URL.

    A crafted URL is one guess that either works or does not, and it stops
    working the week a site changes its routing. This fills the site's own
    search form — which is slower, and survives the change.
    """
    settings = settings or get_settings()
    for label, home in (
        ("goibibo", "https://www.goibibo.com/hotels/"),
        ("makemytrip", "https://www.makemytrip.com/hotels/"),
    ):
        events.phase("booking", f"searching {label} by hand")
        outcome = await agent.browse(
            toolset,
            stay_goal(city, checkin, checkout, travelers),
            thread_id=thread_id,
            start_url=home,
            max_steps=settings.browser_agent_max_steps,
            budget_seconds=settings.browser_agent_budget_seconds,
            settings=settings,
        )
        page = await control.read_page(toolset)
        prices = extract_prices(page.get("snapshot", ""))

        if outcome.needs_person:
            handed = await _hand_over(toolset, thread_id, outcome.needs_person, page, settings)
            if handed == "released":
                page = await control.read_page(toolset)
                prices = extract_prices(page.get("snapshot", ""))
            return _report(label, outcome.url or home, page, [], handed_over=handed, prices=prices)

        if prices:
            return _report(label, outcome.url or home, page, [], handed_over=None, prices=prices)

        log.info("booking_agent_no_prices", site=label, reason=outcome.reason[:120])

    return {}


async def proceed_toward_booking(
    toolset: McpToolset,
    *,
    thread_id: str,
    city: str,
    checkin: date,
    checkout: date,
    travelers: int,
    listing_url: str | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Carry on from a list of prices to the point a person has to take over.

    Finding prices is not booking. Stopping at the listing was the honest
    half-measure — it showed what a room costs and then left, which is exactly
    where someone still has everything to do. This goes further: open a
    well-priced room, start the booking, and stop the moment the site asks who
    you are.

    That stop is the deliverable, not a failure. Signing in is the traveller's
    to do and paying is theirs alone, so the useful thing this can do is get
    them to that page with the search already filled in.
    """
    settings = settings or get_settings()
    goal = (
        f"You are on a list of hotels in {city} for "
        f"{checkin.strftime('%-d %B')} to {checkout.strftime('%-d %B %Y')}, "
        f"{travelers} adults. Open a named hotel from the list — one whose name you can "
        "see, not a filter — and begin booking a room: choose the room and press whatever "
        "continues to the next step. Stop as soon as the site asks anyone to sign in, "
        "enter personal details, or pay. Do not fill in any of those."
    )

    # Two attempts, because the first is the one that lands on a listing still
    # settling and spends its budget on filters. A second run from a fresh load
    # is cheap next to reporting a dead end to someone who asked to book.
    outcome = await agent.browse(
        toolset,
        goal,
        thread_id=thread_id,
        # Back to the listing first. The pass that found the prices left the
        # browser wherever it finished, and starting from a half-scrolled page
        # with stale refs is how this failed the first time it was tried.
        start_url=listing_url,
        max_steps=settings.browser_agent_max_steps,
        budget_seconds=settings.browser_agent_budget_seconds,
        settings=settings,
    )

    page = await control.read_page(toolset)
    reason = outcome.needs_person or page.get("needs_person")

    if not reason and listing_url:
        log.info("booking_retry", why=outcome.reason[:120])
        events.phase("booking", "trying the booking once more from a fresh load")
        outcome = await agent.browse(
            toolset,
            goal,
            thread_id=thread_id,
            start_url=listing_url,
            max_steps=settings.browser_agent_max_steps,
            budget_seconds=settings.browser_agent_budget_seconds,
            settle_seconds=10.0,
            settings=settings,
        )
        page = await control.read_page(toolset)
        reason = outcome.needs_person or page.get("needs_person")

    if reason:
        handed = await _hand_over(toolset, thread_id, reason, page, settings)
        return {
            "reached": reason,
            "handed_over": handed,
            "url": page.get("url"),
            "steps": outcome.steps,
        }
    return {
        "reached": None,
        "handed_over": None,
        "url": page.get("url"),
        "steps": outcome.steps,
        "why": outcome.reason,
    }


async def open_booking(
    toolset: McpToolset,
    *,
    thread_id: str,
    targets: list[tuple[str, str]],
    settings: Settings | None = None,
    city: str = "",
    checkin: date | None = None,
    checkout: date | None = None,
    travelers: int = 2,
    by_hand: bool = True,
    go_further: bool = True,
) -> dict[str, Any]:
    """Walk the targets until one shows live prices or asks for a person.

    Never raises. Booking is the last thing a run does and it is optional, so
    every outcome here is a report — including "every site refused us, the
    browser is open on the last one, it is yours".
    """
    settings = settings or get_settings()
    by_hand = by_hand and bool(city and checkin and checkout)
    go_further = go_further and by_hand
    attempts: list[dict[str, str]] = []
    #: The best page that actually rendered. A site can load perfectly and
    #: still show no prices — its search form, with the city and dates already
    #: filled in, is one click from real results. That page is worth handing to
    #: a person, and it is the common case rather than the exception.
    #:
    #: The url is kept alongside it because the chain carries on browsing after
    #: this is recorded: by the time the loop ends the browser is on whichever
    #: site was tried last, and handing someone a page while naming a different
    #: one is worse than not offering it at all.
    landed: tuple[str, str, dict[str, Any]] | None = None

    for label, url in targets:
        events.phase("booking", f"opening {label}")
        try:
            await control.perform(
                toolset, control.Action(kind="navigate", url=url), thread_id=thread_id
            )
            page = await control.read_page(toolset)
        except Exception as exc:
            attempts.append({"site": label, "outcome": _why_it_failed(exc)})
            log.warning("booking_target_failed", site=label, error=str(exc)[:200])
            continue

        gate = page.get("needs_person")
        if gate == "payment":
            # Should not happen this early, but if a site jumps straight to it
            # the rule is the same everywhere: hand over and do not come back.
            outcome = await _hand_over(toolset, thread_id, "payment", page, settings)
            return _report(label, url, page, attempts, handed_over=outcome, prices=[])

        blocked = looks_blocked(page.get("snapshot", ""))
        if gate in ("login", "captcha") or blocked:
            reason = "captcha" if blocked and gate is None else (gate or "assist")
            events.browser_blocked(label, "this site wants a person, not an automated visitor")
            outcome = await _hand_over(toolset, thread_id, reason, page, settings)
            if outcome in ("released",):
                # They dealt with it; read whatever is on screen now.
                page = await control.read_page(toolset)
                prices = extract_prices(page.get("snapshot", ""))
                return _report(label, url, page, attempts, handed_over=outcome, prices=prices)
            attempts.append({"site": label, "outcome": f"needed a person ({outcome})"})
            continue

        prices = extract_prices(page.get("snapshot", ""))
        if prices:
            log.info("booking_prices_found", site=label, count=len(prices))
            report = _report(label, url, page, attempts, handed_over=None, prices=prices)
            if go_further:
                further = await proceed_toward_booking(
                    toolset,
                    thread_id=thread_id,
                    listing_url=url,
                    city=city,
                    checkin=checkin,  # type: ignore[arg-type]
                    checkout=checkout,  # type: ignore[arg-type]
                    travelers=travelers,
                    settings=settings,
                )
                report["handed_over"] = further.get("handed_over")
                report["url"] = further.get("url") or report["url"]
                report["note"] = _further_note(label, prices, further)
            return report

        attempts.append({"site": label, "outcome": _what_it_showed(url, page.get("url"))})
        if landed is None:
            landed = (label, url, page)

    # Nothing quoted a price, but something loaded. Rather than reporting a
    # dead end, put the person in front of it — the search is already set up,
    # and finishing it is a click they can make and the automation cannot.
    # Every crafted URL missed. Before giving up, do it the way a person would
    # — open the site and fill its own search form. Slower, and it survives the
    # week a site changes its routing.
    if by_hand:
        events.phase("booking", "no URL worked; searching the site by hand")
        agent_result = await search_by_hand(
            toolset,
            thread_id=thread_id,
            city=city,
            checkin=checkin,
            checkout=checkout,
            travelers=travelers,
            settings=settings,
        )
        if agent_result:
            agent_result["attempts"] = attempts + agent_result.get("attempts", [])
            return agent_result

    if landed is not None:
        label, url, page = landed
        events.phase("booking", f"{label} loaded but quoted nothing — offering you the browser")
        # Go back to it first. The chain kept browsing after this page was
        # recorded, so the browser is on whichever site was tried last.
        if page.get("url") != (await control.read_page(toolset)).get("url"):
            with contextlib.suppress(control.ControlError):
                await control.perform(
                    toolset, control.Action(kind="navigate", url=url), thread_id=thread_id
                )
                page = await control.read_page(toolset)

        # It is the site being offered, not one that failed.
        rest = [a for a in attempts if a["site"] != label]
        outcome = await _hand_over(toolset, thread_id, "assist", page, settings)
        if outcome == "released":
            page = await control.read_page(toolset)
            return _report(
                label,
                page.get("url") or url,
                page,
                rest,
                handed_over=outcome,
                prices=extract_prices(page.get("snapshot", "")),
            )
        return _report(label, url, page, rest, handed_over=outcome, prices=[])

    log.warning("booking_no_site_answered", tried=[a["site"] for a in attempts])
    return {
        "ok": False,
        "site": None,
        "url": None,
        "prices": [],
        "attempts": attempts,
        "handed_over": None,
        "note": "No booking site could be opened at all.",
    }


#: Chromium's own name for the failure, which is more informative than the
#: exception type wrapping it — and worth keeping, because these three mean
#: entirely different things to whoever reads the report.
_NET_ERRORS = {
    "ERR_HTTP2_PROTOCOL_ERROR": (
        "refused the connection — it completes the TLS handshake and then resets the "
        "HTTP/2 stream, which is how these sites turn away browsers they recognise as "
        "automated. Running headed rather than headless gets past it"
    ),
    "ERR_CONNECTION_REFUSED": "refused the connection outright",
    "ERR_NAME_NOT_RESOLVED": "could not be resolved — check DNS from this host",
    "ERR_CONNECTION_TIMED_OUT": "did not answer in time",
    "ERR_CERT": "presented a certificate this host would not accept",
}


def _why_it_failed(exc: Exception) -> str:
    """Name what actually went wrong, not just the exception class.

    "ControlError" tells a reader nothing. Whether a site reset the HTTP/2
    stream, could not be resolved, or simply timed out are three different
    problems with three different answers, and the browser already knows which
    one it was.
    """
    text = str(exc)
    for code, meaning in _NET_ERRORS.items():
        if code in text:
            return meaning
    return f"{type(exc).__name__}: {text[:120]}"


def _what_it_showed(asked: str, landed: str | None) -> str:
    """A site that loaded but gave us something other than what we asked for.

    Two aggregators do this rather than refusing: the query string is dropped,
    or the deep link bounces to the home page. Reporting that as "showed no
    prices" hides the actual cause, which is that the search never happened.
    """
    if not landed:
        return "opened but showed no prices"
    if _path_of(landed) != _path_of(asked):
        return "redirected away from the search, so no results were shown"
    if "?" in asked and "?" not in landed:
        return "dropped the search terms from the URL, so it showed an empty search"
    return "opened the right page but quoted no prices to an automated browser"


def _path_of(url: str) -> str:
    return urlsplit(url).path.rstrip("/").lower()


async def _hand_over(
    toolset: McpToolset,
    thread_id: str,
    reason: str,
    page: dict[str, Any],
    settings: Settings,
) -> str:
    return await handover.serve(
        toolset,
        thread_id,
        reason=reason,
        url=page.get("url"),
        timeout=settings.browser_handover_timeout_seconds,
    )


def _report(
    site: str,
    url: str,
    page: dict[str, Any],
    attempts: list[dict[str, str]],
    *,
    handed_over: str | None,
    prices: list[dict[str, str]],
) -> dict[str, Any]:
    return {
        "ok": bool(prices) or handed_over == "released",
        "site": site,
        "url": page.get("url") or url,
        "title": page.get("title"),
        "prices": prices,
        "attempts": attempts,
        "handed_over": handed_over,
        "note": _note(site, prices, handed_over),
    }


def _further_note(site: str, prices: list[dict[str, str]], further: dict[str, Any]) -> str:
    """What happened once it tried to actually book something."""
    cheapest = min(int(p["price_inr"]) for p in prices) if prices else 0
    found = f"{site} is showing {len(prices)} live prices, from about Rs {cheapest:,}."
    match (further.get("reached"), further.get("handed_over")):
        case ("payment", _):
            return f"{found} It reached the payment page — that part is yours."
        case (_, "released"):
            return f"{found} It got as far as the sign-in and you took over."
        case (_, "expired"):
            return f"{found} It reached a sign-in and waited, but nobody came."
        case (reason, _) if reason:
            return f"{found} It reached a {reason} page and is holding the browser for you."
        case _:
            return f"{found} It could not get further on its own without you."


def _note(site: str, prices: list[dict[str, str]], handed_over: str | None) -> str:
    if prices and handed_over == "released":
        cheapest = min(int(p["price_inr"]) for p in prices)
        return (
            f"You finished the search on {site}: {len(prices)} prices, from about Rs {cheapest:,}."
        )
    if prices:
        cheapest = min(int(p["price_inr"]) for p in prices)
        return f"{site} is showing {len(prices)} live prices, from about Rs {cheapest:,}."
    if handed_over == "expired":
        return f"{site} was open and waiting for you, but nobody took it before it timed out."
    if handed_over == "released":
        return f"You took over on {site}; the browser is where you left it."
    return f"{site} opened but showed no prices to an automated browser."
