"""Pure, deterministic tools for the travel planner.

These four tools make no network calls and hold no state: the same inputs always
produce the same output, so they can be unit-tested exhaustively and handed to a
model at no cost. They cover the arithmetic and sanity checks a planner would
otherwise ask the LLM to do in its head - currency conversion, budget splitting,
request validation and a rough flight-cost band - where a wrong number is worse
than no number.

Every tool returns a plain dict. A failure is reported as a dict with an
``error`` key rather than raised, so a model can read the problem and correct its
call instead of taking the graph down.

Rates, region membership and cost bands are static reference tables, not live
data. They are deliberately approximate and every result says so.
"""

# NOTE: `from __future__ import annotations` must NOT be added to this module.
# The `@tool` decorator builds each argument schema by introspecting the live
# annotations on the function signature; stringified annotations are resolved
# later and less reliably. See core/state.py for the parallel state-schema trap.

from typing import Any

from langchain_core.tools import tool

# ---------------------------------------------------------------------------
# Reference tables
# ---------------------------------------------------------------------------

#: Units of each currency per 1 USD. Approximate reference values, not live rates.
_UNITS_PER_USD: dict[str, float] = {
    "USD": 1.0,
    "EUR": 0.92,
    "GBP": 0.79,
    "JPY": 150.0,
    "CNY": 7.25,
    "INR": 83.5,
    "AUD": 1.52,
    "CAD": 1.36,
    "CHF": 0.88,
    "SGD": 1.35,
    "HKD": 7.82,
    "NZD": 1.64,
    "SEK": 10.6,
    "MXN": 17.2,
    "BRL": 5.0,
    "KRW": 1340.0,
    "THB": 36.0,
    "AED": 3.67,
}

_RATE_NOTE = "Rates are approximate static reference values for planning, not live market rates."

#: Canonical lower-case country name -> region. Used only to pick a flight band.
_REGION_BY_COUNTRY: dict[str, str] = {
    # North America
    "united states": "north america",
    "canada": "north america",
    "mexico": "north america",
    # South America
    "brazil": "south america",
    "argentina": "south america",
    "chile": "south america",
    "peru": "south america",
    "colombia": "south america",
    # Europe
    "united kingdom": "europe",
    "ireland": "europe",
    "france": "europe",
    "germany": "europe",
    "spain": "europe",
    "portugal": "europe",
    "italy": "europe",
    "netherlands": "europe",
    "belgium": "europe",
    "switzerland": "europe",
    "austria": "europe",
    "greece": "europe",
    "sweden": "europe",
    "norway": "europe",
    "denmark": "europe",
    "poland": "europe",
    "czech republic": "europe",
    "turkey": "europe",
    # Middle East
    "united arab emirates": "middle east",
    "qatar": "middle east",
    "saudi arabia": "middle east",
    "israel": "middle east",
    "jordan": "middle east",
    # Africa
    "egypt": "africa",
    "morocco": "africa",
    "south africa": "africa",
    "kenya": "africa",
    "tanzania": "africa",
    # Asia
    "japan": "asia",
    "south korea": "asia",
    "china": "asia",
    "hong kong": "asia",
    "taiwan": "asia",
    "india": "asia",
    "sri lanka": "asia",
    "nepal": "asia",
    "thailand": "asia",
    "vietnam": "asia",
    "malaysia": "asia",
    "singapore": "asia",
    "indonesia": "asia",
    "philippines": "asia",
    # Oceania
    "australia": "oceania",
    "new zealand": "oceania",
    "fiji": "oceania",
}

#: Common spellings and abbreviations, already normalised, -> canonical name.
_COUNTRY_ALIASES: dict[str, str] = {
    "usa": "united states",
    "us": "united states",
    "america": "united states",
    "united states of america": "united states",
    "uk": "united kingdom",
    "britain": "united kingdom",
    "great britain": "united kingdom",
    "england": "united kingdom",
    "scotland": "united kingdom",
    "wales": "united kingdom",
    "uae": "united arab emirates",
    "emirates": "united arab emirates",
    "korea": "south korea",
    "republic of korea": "south korea",
    "holland": "netherlands",
    "czechia": "czech republic",
    "turkiye": "turkey",
    "viet nam": "vietnam",
    "prc": "china",
}

#: Economy, per person, return trip, USD: (low, high) for each distance band.
_FLIGHT_BANDS_USD: dict[str, tuple[int, int]] = {
    "domestic": (80, 400),
    "regional": (150, 800),
    "intercontinental": (600, 2000),
}

#: Multiplier applied to the economy band for each cabin class.
_CABIN_MULTIPLIERS: dict[str, float] = {
    "economy": 1.0,
    "premium": 1.75,
    "business": 3.5,
    "first": 5.5,
}

_CABIN_ALIASES: dict[str, str] = {
    "coach": "economy",
    "economy class": "economy",
    "premium economy": "premium",
    "premium economy class": "premium",
    "business class": "business",
    "first class": "first",
}

_FLIGHT_NOTE = (
    "Heuristic per-person return-trip range from static distance bands; "
    "real fares vary widely with route, season and booking lead time."
)

_BUDGET_LEVELS: tuple[str, ...] = ("budget", "mid-range", "luxury")
_MIN_DAYS, _MAX_DAYS = 1, 30
_MIN_TRAVELERS, _MAX_TRAVELERS = 1, 12


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise_country(name: str) -> str:
    """Lower-case, drop punctuation, collapse spaces, strip a leading 'the'."""
    cleaned = " ".join(str(name).lower().replace(".", "").replace("-", " ").split())
    cleaned = cleaned.removeprefix("the ")
    return _COUNTRY_ALIASES.get(cleaned, cleaned)


def _normalise_cabin(cabin: str) -> str:
    cleaned = " ".join(str(cabin).lower().replace("_", " ").replace("-", " ").split())
    return _CABIN_ALIASES.get(cleaned, cleaned)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool(parse_docstring=True)
def convert_currency(amount: float, from_currency: str, to_currency: str) -> dict[str, Any]:
    """Convert a money amount between two major currencies using a static reference rate table.

    Supports 18 major currencies (USD, EUR, GBP, JPY, CNY, INR, AUD, CAD, CHF, SGD,
    HKD, NZD, SEK, MXN, BRL, KRW, THB, AED). Codes are ISO 4217 and are matched
    case-insensitively. Rates are approximate reference values, not live market
    rates, so use the result for planning rather than settlement. On success the
    result holds ``converted_amount`` (rounded to 2 decimals) and ``rate`` (units
    of to_currency per 1 unit of from_currency) plus a ``note`` about accuracy.
    An unknown code or a negative amount returns a dict with an ``error`` key and
    the list of supported codes instead.

    Args:
        amount: Amount of money expressed in from_currency. Must be zero or positive.
        from_currency: ISO 4217 code of the source currency, e.g. "USD" or "eur".
        to_currency: ISO 4217 code of the target currency, e.g. "JPY" or "gbp".

    Returns:
        A dict with amount, from_currency, to_currency, rate, converted_amount and
        note; or a dict with error and supported_currencies.
    """
    source = str(from_currency).strip().upper()
    target = str(to_currency).strip().upper()
    supported = sorted(_UNITS_PER_USD)

    unknown = [code for code in (source, target) if code not in _UNITS_PER_USD]
    if unknown:
        return {
            "error": f"Unknown currency code(s): {', '.join(unknown)}.",
            "supported_currencies": supported,
        }
    if amount < 0:
        return {
            "error": f"Amount must be zero or positive, got {amount}.",
            "supported_currencies": supported,
        }

    rate = _UNITS_PER_USD[target] / _UNITS_PER_USD[source]
    return {
        "amount": float(amount),
        "from_currency": source,
        "to_currency": target,
        "rate": round(rate, 6),
        "converted_amount": round(float(amount) * rate, 2),
        "note": _RATE_NOTE,
    }


@tool(parse_docstring=True)
def calculate_daily_budget(total_usd: float, days: int, travelers: int) -> dict[str, Any]:
    """Split a whole-trip budget in US dollars into per-day and per-person-per-day amounts.

    All money values are USD and are rounded to 2 decimals. The result holds
    ``per_day_usd`` (total divided by days), ``per_person_per_day_usd`` (total
    divided by days and travelers) and ``per_person_total_usd`` (total divided
    by travelers), echoing the inputs alongside. total_usd must be greater than
    zero and days and travelers must be positive whole numbers; anything else
    returns a dict with an ``error`` key.

    Args:
        total_usd: Whole-trip budget in US dollars for all travelers combined. Must be > 0.
        days: Trip length in whole days. Must be at least 1.
        travelers: Number of people sharing the budget. Must be at least 1.

    Returns:
        A dict with total_usd, days, travelers, per_day_usd, per_person_per_day_usd
        and per_person_total_usd; or a dict with error.
    """
    problems: list[str] = []
    if not total_usd > 0:
        problems.append(f"total_usd must be greater than 0, got {total_usd}")
    if days < 1:
        problems.append(f"days must be at least 1, got {days}")
    if travelers < 1:
        problems.append(f"travelers must be at least 1, got {travelers}")
    if problems:
        return {"error": "; ".join(problems) + "."}

    total = float(total_usd)
    return {
        "total_usd": round(total, 2),
        "days": int(days),
        "travelers": int(travelers),
        "per_day_usd": round(total / days, 2),
        "per_person_per_day_usd": round(total / days / travelers, 2),
        "per_person_total_usd": round(total / travelers, 2),
    }


@tool(parse_docstring=True)
def validate_trip_request(days: int, travelers: int, budget_level: str) -> dict[str, Any]:
    """Check whether a trip request is within the ranges the planner supports.

    The rules are days 1 to 30 inclusive, travelers 1 to 12 inclusive, and
    budget_level one of "budget", "mid-range" or "luxury" (matched
    case-insensitively with surrounding whitespace ignored). The result holds
    ``valid`` (true only when every rule passes) and ``issues``, a list of
    human-readable problems that is empty when the request is valid. This tool
    never raises; an impossible value such as a negative day count is reported
    as an issue.

    Args:
        days: Trip length in whole days. The supported range is 1 to 30.
        travelers: Number of people travelling together. The supported range is 1 to 12.
        budget_level: Spending tier, one of "budget", "mid-range" or "luxury".

    Returns:
        A dict with valid (bool) and issues (list of str).
    """
    issues: list[str] = []

    if not _MIN_DAYS <= days <= _MAX_DAYS:
        issues.append(f"days must be between {_MIN_DAYS} and {_MAX_DAYS}, got {days}")
    if not _MIN_TRAVELERS <= travelers <= _MAX_TRAVELERS:
        issues.append(
            f"travelers must be between {_MIN_TRAVELERS} and {_MAX_TRAVELERS}, got {travelers}"
        )
    level = str(budget_level).strip().lower()
    if level not in _BUDGET_LEVELS:
        issues.append(
            f"budget_level must be one of {', '.join(_BUDGET_LEVELS)}, got {budget_level!r}"
        )

    return {"valid": not issues, "issues": issues}


@tool(parse_docstring=True)
def estimate_flight_cost(
    origin_country: str, destination_country: str, cabin: str = "economy"
) -> dict[str, Any]:
    """Estimate a per-person return airfare range in US dollars between two countries.

    This is a coarse heuristic, not a fare search. Each country is mapped to a
    region (north america, south america, europe, middle east, africa, asia,
    oceania) and the pair is placed in one of three distance bands:
    ``domestic`` (same country, 80-400 USD economy), ``regional`` (same region,
    150-800 USD economy) or ``intercontinental`` (different regions, 600-2000 USD
    economy). The band is then scaled by the cabin multiplier: economy x1.0,
    premium x1.75, business x3.5, first x5.5. Country names and cabin classes
    are matched case-insensitively and common aliases such as "USA", "UK" and
    "premium economy" are accepted. The result holds ``low_usd``, ``high_usd``,
    the ``band`` used and both regions. A country outside the ~50 supported or an
    unknown cabin returns a dict with an ``error`` key and the supported values.

    Args:
        origin_country: Country the trip departs from, e.g. "United States" or "uk".
        destination_country: Country the trip flies to, e.g. "Japan".
        cabin: Cabin class, one of "economy", "premium", "business" or "first". Defaults to economy.

    Returns:
        A dict with origin_country, destination_country, origin_region,
        destination_region, band, cabin, cabin_multiplier, low_usd, high_usd,
        currency and note; or a dict with error and the supported values.
    """
    origin = _normalise_country(origin_country)
    destination = _normalise_country(destination_country)
    cabin_key = _normalise_cabin(cabin)

    unknown = [
        raw
        for raw, key in ((origin_country, origin), (destination_country, destination))
        if key not in _REGION_BY_COUNTRY
    ]
    if unknown:
        return {
            "error": f"Unknown country name(s): {', '.join(repr(u) for u in unknown)}.",
            "supported_countries": sorted(_REGION_BY_COUNTRY),
        }
    if cabin_key not in _CABIN_MULTIPLIERS:
        return {
            "error": f"Unknown cabin class {cabin!r}.",
            "supported_cabins": list(_CABIN_MULTIPLIERS),
        }

    origin_region = _REGION_BY_COUNTRY[origin]
    destination_region = _REGION_BY_COUNTRY[destination]
    if origin == destination:
        band = "domestic"
    elif origin_region == destination_region:
        band = "regional"
    else:
        band = "intercontinental"

    low, high = _FLIGHT_BANDS_USD[band]
    multiplier = _CABIN_MULTIPLIERS[cabin_key]
    return {
        "origin_country": origin,
        "destination_country": destination,
        "origin_region": origin_region,
        "destination_region": destination_region,
        "band": band,
        "cabin": cabin_key,
        "cabin_multiplier": multiplier,
        "low_usd": round(low * multiplier),
        "high_usd": round(high * multiplier),
        "currency": "USD",
        "note": _FLIGHT_NOTE,
    }


TOOLS = [convert_currency, calculate_daily_budget, validate_trip_request, estimate_flight_cost]
