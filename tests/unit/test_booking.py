"""Taking an approved plan to a real booking page.

Nothing here buys anything. What is under test is that the search is aimed at
real dates, that a rupee price is told apart from a pincode, and — the part
that matters most — that a page asking for card details ends the automation
rather than being driven through.
"""

from datetime import date

import pytest

from travel_planner.tools.mcp import booking, handover

# --- dates ----------------------------------------------------------------------

TODAY = date(2026, 9, 8)


def test_a_month_becomes_two_real_dates():
    """A booking search needs actual dates and the planner asks for a month.
    Deriving it here rather than asking a model: a date is arithmetic."""
    checkin, checkout = booking.resolve_dates("November", 3, today=TODAY)
    assert checkin == date(2026, 11, 8)
    assert checkout == date(2026, 11, 11)


def test_a_month_already_past_rolls_to_next_year():
    checkin, _ = booking.resolve_dates("March", 2, today=TODAY)
    assert checkin == date(2027, 3, 8)


def test_the_current_month_is_used_when_it_has_not_passed():
    checkin, _ = booking.resolve_dates("September", 2, today=date(2026, 9, 2))
    assert checkin == date(2026, 9, 8)


def test_the_current_month_rolls_over_once_the_date_is_gone():
    checkin, _ = booking.resolve_dates("September", 2, today=date(2026, 9, 20))
    assert checkin == date(2027, 9, 8)


def test_an_iso_date_is_taken_literally():
    checkin, checkout = booking.resolve_dates("2026-12-24", 2, today=TODAY)
    assert checkin == date(2026, 12, 24) and checkout == date(2026, 12, 26)


def test_no_season_still_produces_a_bookable_window():
    checkin, checkout = booking.resolve_dates(None, 4, today=TODAY)
    assert checkin > TODAY and (checkout - checkin).days == 4


@pytest.mark.parametrize("days,expected", [(None, 3), (0, 3), (1, 1), (999, 30)])
def test_night_counts_are_clamped(days, expected):
    """0 means unspecified here, the same as everywhere else in the planner —
    `intake_node` reads day counts with the same `or DEFAULT_DAYS` convention."""
    checkin, checkout = booking.resolve_dates("November", days, today=TODAY)
    assert (checkout - checkin).days == expected


# --- where to look --------------------------------------------------------------


def test_indian_aggregators_lead_the_chain():
    """They are what a traveller here books through, and they quote rupees
    natively — so nothing sits between the plan's budget and the real price."""
    targets = booking.stay_targets("Jaipur, India", date(2026, 11, 8), date(2026, 11, 11), 2)
    assert [t[0] for t in targets][:2] == ["makemytrip", "goibibo"]


def test_the_search_carries_the_real_dates():
    url = dict(booking.stay_targets("Goa, India", date(2026, 11, 8), date(2026, 11, 11), 2))[
        "makemytrip"
    ]
    assert "checkin=11082026" in url and "checkout=11112026" in url


def test_a_city_becomes_a_usable_slug():
    url = dict(booking.stay_targets("New Delhi, India", TODAY, TODAY, 1))["goibibo"]
    assert "hotels-in-new-delhi-ct" in url


def test_travel_targets_need_an_origin():
    assert booking.travel_targets(None, "Jaipur", TODAY) == []
    assert booking.travel_targets("Delhi", "Jaipur", TODAY)[0][0] == "ixigo trains"


# --- reading prices -------------------------------------------------------------

LISTING = """### Snapshot
```yaml
- list [ref=e1]:
  - listitem [ref=e2]: Hotel Pearl Palace ₹1,850 per night
  - listitem [ref=e3]: Umaid Bhawan Palace ₹45,000 per night
  - listitem [ref=e4]: Call us on 1800 123 4567
  - listitem [ref=e5]: PIN 302001
  - listitem [ref=e6]: Rs 2,400 Zostel Jaipur
  - listitem [ref=e7]: 1,240 reviews
```
"""


def test_prices_are_read_off_the_listing():
    prices = booking.extract_prices(LISTING)
    amounts = {p["price_inr"] for p in prices}
    assert "1850" in amounts and "45000" in amounts and "2400" in amounts


def test_numbers_that_are_not_prices_are_left_alone():
    """A listing page is full of numbers; only the ones marked as currency
    are prices. A phone number read as a price would be a plausible-looking
    lie about what a hotel costs."""
    lines = " ".join(p["line"] for p in booking.extract_prices(LISTING))
    assert "1800 123 4567" not in lines
    assert "302001" not in lines
    assert "1,240 reviews" not in lines


def test_prices_outside_a_believable_range_are_dropped():
    assert booking.extract_prices("- item: ₹12") == []
    assert booking.extract_prices("- item: ₹9,999,999") == []


def test_the_same_listing_twice_is_read_once():
    """Listing pages repeat cards — a sticky header, a "recently viewed" strip.
    The same hotel at the same price is one result, not three."""
    repeated = "- listitem: Hotel Pearl Palace ₹1,850\n" * 3
    assert len(booking.extract_prices(repeated)) == 1


def test_price_extraction_is_capped():
    many = "\n".join(f"- item{i}: ₹{1000 + i} Hotel {i}" for i in range(40))
    assert len(booking.extract_prices(many, limit=5)) == 5


# --- the run --------------------------------------------------------------------


class FakeTool:
    def __init__(self, results):
        self.results, self.calls = list(results), []

    async def ainvoke(self, args):
        self.calls.append(args)
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]


class FakeBrowser:
    """A browser scripted page by page, so a booking walk can be driven offline."""

    def __init__(self, pages, gates=None):
        self.tools = {
            "browser_navigate": FakeTool(["ok"]),
            "browser_snapshot": FakeTool(pages),
            "browser_evaluate": FakeTool(gates or ['### Result\n{"path": "/x"}\n### Ran']),
            "browser_take_screenshot": FakeTool([None]),
        }

    def get(self, *names):
        for n in names:
            if n in self.tools:
                return self.tools[n]
        return None


@pytest.fixture(autouse=True)
def _no_leaked_handovers():
    yield
    handover._open.clear()


async def test_the_first_site_with_prices_wins(monkeypatch):
    ts = FakeBrowser([LISTING])
    out = await booking.open_booking(ts, thread_id="t", targets=[("goibibo", "https://x.test/a")])
    assert out["ok"] is True
    assert out["site"] == "goibibo"
    assert len(out["prices"]) >= 3
    assert "from about Rs 1,850" in out["note"]


async def test_the_site_being_offered_is_not_listed_as_a_failure(monkeypatch):
    """It is the page you are being handed, not one that did not answer."""

    async def fake_serve(toolset, thread_id, **kw):
        return "expired"

    monkeypatch.setattr(booking.handover, "serve", fake_serve)
    ts = FakeBrowser(["### Snapshot\n```yaml\n- generic: nothing here\n```"])
    out = await booking.open_booking(
        ts, thread_id="t", targets=[("makemytrip", "https://x.test/a")]
    )
    assert out["site"] == "makemytrip"
    assert out["attempts"] == []


async def test_sites_that_really_did_fail_are_still_listed(monkeypatch):
    async def fake_serve(toolset, thread_id, **kw):
        return "expired"

    monkeypatch.setattr(booking.handover, "serve", fake_serve)
    ts = FakeBrowser(["### Snapshot\n```yaml\n- generic: nothing here\n```"])
    out = await booking.open_booking(
        ts,
        thread_id="t",
        targets=[("makemytrip", "https://x.test/a"), ("goibibo", "https://x.test/b")],
    )
    assert out["site"] == "makemytrip", "the first that loaded is the one offered"
    assert [a["site"] for a in out["attempts"]] == ["goibibo"]


async def test_a_page_that_loaded_without_prices_is_offered_to_a_person(monkeypatch):
    """The common case, and the one worth getting right: every aggregator
    serves its search form to an automated browser and quotes nothing. That
    form has the city and dates already in it and is one click from real
    results — a click a person can make and the automation cannot."""
    handed: dict = {}

    async def fake_serve(toolset, thread_id, **kw):
        handed.update(kw)
        return "released"

    monkeypatch.setattr(booking.handover, "serve", fake_serve)
    # Empty first, then the person finishes the search and prices appear.
    ts = FakeBrowser(["### Snapshot\n```yaml\n- generic: a search form\n```", LISTING])
    out = await booking.open_booking(ts, thread_id="t", targets=[("agoda", "https://x.test/s")])

    assert handed["reason"] == "assist"
    assert out["ok"] is True
    assert out["prices"], "the page is re-read once they are done"
    assert "You finished the search on agoda" in out["note"]


async def test_nobody_taking_the_offered_page_is_reported_plainly(monkeypatch):
    async def fake_serve(toolset, thread_id, **kw):
        return "expired"

    monkeypatch.setattr(booking.handover, "serve", fake_serve)
    ts = FakeBrowser(["### Snapshot\n```yaml\n- generic: a search form\n```"])
    out = await booking.open_booking(ts, thread_id="t", targets=[("agoda", "https://x.test/s")])
    assert out["ok"] is False
    assert "nobody took it" in out["note"]


async def test_a_payment_page_hands_over_and_does_not_come_back(monkeypatch):
    """The rule everywhere: card, UPI and bank details are not something this
    system types. Reaching one ends the automated part."""
    handed: dict = {}

    async def fake_serve(toolset, thread_id, **kw):
        handed.update(kw)
        return "released"

    monkeypatch.setattr(booking.handover, "serve", fake_serve)
    ts = FakeBrowser([LISTING], gates=['### Result\n{"card": true, "path": "/pay"}\n### Ran'])
    out = await booking.open_booking(
        ts, thread_id="t", targets=[("makemytrip", "https://x.test/pay")]
    )
    assert handed["reason"] == "payment"
    assert out["handed_over"] == "released"
    assert out["prices"] == [], "a payment page is not scraped for prices"


async def test_a_login_wall_becomes_the_handover(monkeypatch):
    """The research pass treats a block as a reason to try the next target.
    Booking treats it as the moment to hand over — the browser is already on
    the right site with the right search."""
    calls: list[str] = []

    async def fake_serve(toolset, thread_id, **kw):
        calls.append(kw["reason"])
        return "released"

    monkeypatch.setattr(booking.handover, "serve", fake_serve)
    ts = FakeBrowser([LISTING], gates=['### Result\n{"password": true, "path": "/login"}\n### Ran'])
    out = await booking.open_booking(
        ts, thread_id="t", targets=[("goibibo", "https://x.test/login")]
    )
    assert calls == ["login"]
    assert out["handed_over"] == "released"
    # After they sign in, the page is read again — that is the whole point.
    assert out["prices"], "the page should be re-read once the person is done"


async def test_nobody_coming_advances_the_chain(monkeypatch):
    async def fake_serve(toolset, thread_id, **kw):
        return "expired"

    monkeypatch.setattr(booking.handover, "serve", fake_serve)
    ts = FakeBrowser([LISTING], gates=['### Result\n{"password": true, "path": "/login"}\n### Ran'])
    out = await booking.open_booking(ts, thread_id="t", targets=[("goibibo", "https://x.test/l")])
    assert out["ok"] is False
    assert "needed a person (expired)" in out["attempts"][0]["outcome"]


async def test_every_site_failing_is_a_report_not_an_exception():
    """Booking is the last thing a run does and it is optional, so even total
    failure comes back as something to show."""
    out = await booking.open_booking(FakeBrowser(["nothing"]), thread_id="t", targets=[])
    assert out["ok"] is False and out["site"] is None
    assert "No booking site could be opened" in out["note"]


# --- what a listing page is lying about -----------------------------------------

REAL_PAGE = """### Snapshot
```yaml
- checkbox "₹0 to ₹1000" [ref=e1]
- generic [ref=e2]: ₹0 to ₹1000
- paragraph [ref=e3]: ₹0-₹1500, ₹1500-₹2500,...
- paragraph [ref=e4]: Grab Up to ₹25,000 OFF* on Flights & Hotels.
- generic [ref=e5]: ₹ 500 - ₹ 7,000+
- group "Original price ₹ 17,097. Current price ₹ 5,813." [ref=e6]
- listitem [ref=e7]: Hotel Pearl Palace ₹1,850 per night
```
"""


def test_a_price_filter_is_not_a_hotel_price():
    """Every aggregator has a "price per night" filter and its options read
    exactly like prices. Reporting one as the cheapest hotel is a
    plausible-looking lie about what a trip costs — worse than finding nothing.
    Taken from a live goibibo listing page."""
    lines = [p["line"] for p in booking.extract_prices(REAL_PAGE)]
    assert not any("to ₹1000" in x for x in lines)
    assert not any("₹0-₹1500" in x for x in lines)
    assert not any("500 - ₹ 7,000" in x for x in lines)


def test_a_discount_banner_is_not_a_hotel_price():
    assert not any("25,000" in p["price_inr"] for p in booking.extract_prices(REAL_PAGE))


def test_a_discounted_room_reports_what_you_would_pay():
    """ "Original price ₹17,097. Current price ₹5,813." is two amounts but not a
    range — the second is the one you are charged."""
    prices = {p["price_inr"] for p in booking.extract_prices(REAL_PAGE)}
    assert "5813" in prices and "17097" not in prices


def test_the_real_listing_survives_all_of_that():
    assert "1850" in {p["price_inr"] for p in booking.extract_prices(REAL_PAGE)}


def test_an_en_dash_range_is_a_range_too():
    # \u2013 is an en dash: sites write it as often as a hyphen.
    assert booking.extract_prices("- generic: \u20b9 500 \u2013 \u20b9 7,000") == []


# --- naming the failure ---------------------------------------------------------


def test_an_http2_reset_is_named_as_the_refusal_it_is():
    """Measured against the live sites: makemytrip and goibibo complete the TLS
    handshake and then reset the HTTP/2 stream, on their home pages as well as
    deep links. Headed Chromium loads both, so it is client fingerprinting."""
    why = booking._why_it_failed(RuntimeError("net::ERR_HTTP2_PROTOCOL_ERROR at https://x"))
    assert "resets the HTTP/2 stream" in why
    assert "headed rather than headless" in why


def test_dns_and_timeouts_are_told_apart():
    assert "DNS" in booking._why_it_failed(RuntimeError("net::ERR_NAME_NOT_RESOLVED"))
    assert "in time" in booking._why_it_failed(RuntimeError("net::ERR_CONNECTION_TIMED_OUT"))


def test_an_unrecognised_failure_still_says_something_useful():
    assert "ValueError" in booking._why_it_failed(ValueError("something odd"))


def test_a_redirect_away_from_the_search_is_not_no_prices():
    """agoda bounces a deep link to its home page. Calling that "showed no
    prices" hides the cause, which is that the search never happened."""
    out = booking._what_it_showed("https://agoda.com/search?city=Agra", "https://agoda.com/en-gb/")
    assert "redirected away" in out


def test_a_dropped_query_string_is_named():
    out = booking._what_it_showed(
        "https://booking.com/searchresults.html?ss=Agra", "https://booking.com/searchresults.html"
    )
    assert "dropped the search terms" in out


def test_the_right_page_with_no_prices_says_exactly_that():
    same = "https://goibibo.com/hotels/hotels-in-agra-ct/"
    assert "quoted no prices" in booking._what_it_showed(same, same)


@pytest.mark.parametrize(
    "line,what",
    [
        ("- generic : ₹5500+", "an open-ended filter bound"),
        ("- generic : Bank offer | ₹646 off", "a bank discount"),
        ("- paragraph : +₹1,382 taxes &fees", "taxes added to a rate"),
        ("- paragraph : +₹501 taxes &fees", "the line that became a headline"),
    ],
)
def test_money_that_is_not_a_room_rate_is_ignored(line, what):
    """All four taken from one live goibibo listing page. The last one is the
    reason this exists: at Rs 501 it was the cheapest figure on the page, so
    the booking panel reported "from about Rs 501" — a tax line presented as
    the cheapest hotel in Agra."""
    assert booking.extract_prices(line) == [], what


@pytest.mark.parametrize("line", ["- paragraph : ₹9,200", "- paragraph : ₹3,310"])
def test_a_plain_room_rate_still_gets_through(line):
    assert len(booking.extract_prices(line)) == 1
