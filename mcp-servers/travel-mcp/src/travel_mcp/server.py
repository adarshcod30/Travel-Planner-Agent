"""travel-mcp — an MCP server exposing five travel reference tools.

Written for the Travel Planner Agent's v5 graph, but standalone: it depends on
nothing from the planner and can be pointed at any MCP client.

Every tool answers from the static tables in `data.py` and every response says
where its answer came from — an exact table hit, a latitude-band fallback, or a
documented default. That honesty is the point. A tool that quietly guesses is
indistinguishable, to the model consuming it, from one that knows; making the
provenance part of the payload lets the planner tell the difference and lets a
reader of the final plan see which figures are soft.

Run it:
    python -m travel_mcp.server                      # stdio (default)
    python -m travel_mcp.server --transport http --port 8932
"""

import argparse
from typing import Any

from fastmcp import FastMCP

from travel_mcp.data import (
    ADJACENT_REGIONS,
    CABIN_MULTIPLIERS,
    CLIMATE_BY_LATITUDE,
    COUNTRY_CURRENCY,
    COUNTRY_REGION,
    CURRENCY_RATES,
    DESTINATION_BY_CITY,
    DESTINATIONS,
    DISCLAIMER,
    FLIGHT_BANDS,
    MONTH_TO_QUARTER,
    VISA_DEFAULT,
    VISA_RULES,
)

mcp = FastMCP(
    "travel-mcp",
    instructions=(
        "Travel reference tools: seasonal climate, currency conversion, visa guidance, "
        "flight cost estimates and destination search. All answers come from offline "
        "reference tables and report their own provenance; treat figures as approximate."
    ),
    version="0.1.0",
)


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _quarter_index(month: str) -> tuple[int, str]:
    """Map a month or season name to a quarter index, defaulting to Q2."""
    key = _norm(month)
    if key in MONTH_TO_QUARTER:
        return MONTH_TO_QUARTER[key], key
    for name, idx in MONTH_TO_QUARTER.items():
        if name in key:
            return idx, name
    return 1, "unspecified (assumed spring)"


_QUARTER_LABELS = ("January-March", "April-June", "July-September", "October-December")


@mcp.tool
def get_weather_forecast(city: str, country: str = "", month: str = "") -> dict[str, Any]:
    """Typical seasonal weather for a destination.

    This is climatology, not a forecast: it describes what that place is usually
    like in that part of the year, which is what trip planning needs. It does not
    know today's conditions.

    Args:
        city: City name, e.g. "Kyoto".
        country: Country name. Optional; disambiguates cities that share a name.
        month: Month ("November") or season ("autumn"). Defaults to spring.

    Returns:
        temperature_range_c, temperature_range_f, rainfall, period, source
        ("reference-table" for a known city, "latitude-band-estimate" otherwise),
        and for known cities best_months and tags.
    """
    idx, resolved_month = _quarter_index(month)
    entry = DESTINATION_BY_CITY.get(_norm(city))

    if entry and (not country or _norm(country) == _norm(entry["country"])):
        low, high, rain = entry["climate"][idx]
        return {
            "city": entry["city"],
            "country": entry["country"],
            "period": _QUARTER_LABELS[idx],
            "month_interpreted": resolved_month,
            "temperature_range_c": f"{low} to {high} C",
            "temperature_range_f": f"{round(low * 9 / 5 + 32)} to {round(high * 9 / 5 + 32)} F",
            "rainfall": rain,
            "best_months": entry["best_months"],
            "tags": entry["tags"],
            "source": "reference-table",
            "note": DISCLAIMER,
        }

    band = "temperate"
    region = COUNTRY_REGION.get(_norm(country), "")
    if region in ("southeast-asia", "central-america"):
        band = "tropical"
    elif region in ("south-asia", "middle-east"):
        band = "arid"
    elif region in ("east-asia", "europe", "north-america", "oceania"):
        band = "temperate"
    low, high, rain = CLIMATE_BY_LATITUDE[band][idx]
    return {
        "city": city,
        "country": country or "unknown",
        "period": _QUARTER_LABELS[idx],
        "month_interpreted": resolved_month,
        "temperature_range_c": f"{low} to {high} C",
        "temperature_range_f": f"{round(low * 9 / 5 + 32)} to {round(high * 9 / 5 + 32)} F",
        "rainfall": rain,
        "source": "latitude-band-estimate",
        "assumed_band": band,
        "note": f"{city} is not in the reference table; this is a {band}-band estimate. {DISCLAIMER}",
    }


@mcp.tool
def convert_currency(amount: float, from_currency: str, to_currency: str) -> dict[str, Any]:
    """Convert an amount between currencies at approximate reference rates.

    Rates are static and for planning estimates only — never for a transaction.
    Accepts ISO codes ("JPY") case-insensitively, or a country name ("Japan").

    Args:
        amount: Amount in the source currency.
        from_currency: ISO code or country name.
        to_currency: ISO code or country name.

    Returns:
        converted amount, the rate applied, and the resolved codes; or an error
        listing the supported codes when one cannot be resolved.
    """

    def resolve(value: str) -> str | None:
        v = _norm(value)
        if v.upper() in CURRENCY_RATES:
            return v.upper()
        return COUNTRY_CURRENCY.get(v)

    src, dst = resolve(from_currency), resolve(to_currency)
    unknown = [x for x, r in ((from_currency, src), (to_currency, dst)) if r is None]
    if unknown:
        return {
            "error": f"unrecognised currency: {', '.join(unknown)}",
            "supported_codes": sorted(CURRENCY_RATES),
        }
    if amount < 0:
        return {"error": "amount must not be negative"}

    rate = CURRENCY_RATES[dst] / CURRENCY_RATES[src]
    return {
        "amount": amount,
        "from": src,
        "to": dst,
        "rate": round(rate, 6),
        "converted": round(amount * rate, 2),
        "source": "static-reference-rates",
        "note": f"Approximate rate, {DISCLAIMER.lower()}",
    }


@mcp.tool
def check_visa_requirements(passport_country: str, destination_country: str) -> dict[str, Any]:
    """Entry requirements for a passport-and-destination pair.

    Covers ten common passports against major destinations. Any pair not in the
    table returns the conservative default (visa required in advance) and says
    so explicitly, so an unknown pair is never mistaken for a confirmed
    visa-free result.

    Args:
        passport_country: Country that issued the traveller's passport.
        destination_country: Country being visited.

    Returns:
        requirement, max_stay_days, source ("reference-table" or
        "conservative-default"), and a verification note.
    """
    p, d = _norm(passport_country), _norm(destination_country)
    if p == d:
        return {
            "passport_country": passport_country,
            "destination_country": destination_country,
            "requirement": "no visa needed (citizen)",
            "max_stay_days": None,
            "source": "same-country",
            "note": DISCLAIMER,
        }

    rules = VISA_RULES.get(p)
    if rules and d in rules:
        requirement, days = rules[d]
        source = "reference-table"
    else:
        requirement, days = VISA_DEFAULT
        source = "conservative-default"

    note = DISCLAIMER
    if source == "conservative-default":
        note = (
            f"This passport/destination pair is not in the reference table, so the "
            f"conservative default is returned rather than a guess. {DISCLAIMER}"
        )
    return {
        "passport_country": passport_country,
        "destination_country": destination_country,
        "requirement": requirement,
        "max_stay_days": days,
        "source": source,
        "note": note,
    }


@mcp.tool
def estimate_flight_cost(
    origin_city: str, destination_city: str, cabin: str = "economy"
) -> dict[str, Any]:
    """Round-trip airfare estimate from a distance band, not a live fare search.

    Cities are resolved to countries and then regions; the band ladder runs
    same-city, domestic, same-region, nearby-region, intercontinental. Cabin
    multipliers scale the economy band.

    Args:
        origin_city: Departure city.
        destination_city: Arrival city.
        cabin: economy, premium, business or first.

    Returns:
        low_usd/high_usd, the band and cabin applied, and how each city was
        resolved.
    """
    cabin_key = _norm(cabin) or "economy"
    if cabin_key not in CABIN_MULTIPLIERS:
        return {"error": f"unknown cabin {cabin!r}", "supported_cabins": sorted(CABIN_MULTIPLIERS)}

    def resolve(city: str) -> tuple[str, str, str]:
        entry = DESTINATION_BY_CITY.get(_norm(city))
        if entry:
            return (
                entry["country"],
                COUNTRY_REGION.get(_norm(entry["country"]), "unknown"),
                "reference-table",
            )
        return "unknown", "unknown", "unresolved"

    o_country, o_region, o_src = resolve(origin_city)
    d_country, d_region, d_src = resolve(destination_city)

    if _norm(origin_city) == _norm(destination_city):
        band = "same-city"
    elif o_region == "unknown" or d_region == "unknown":
        band = "intercontinental"
    elif o_country == d_country:
        band = "domestic"
    elif o_region == d_region:
        band = "same-region"
    elif d_region in ADJACENT_REGIONS.get(o_region, set()):
        band = "nearby-region"
    else:
        band = "intercontinental"

    low, high = FLIGHT_BANDS[band]
    mult = CABIN_MULTIPLIERS[cabin_key]
    note = DISCLAIMER
    if "unresolved" in (o_src, d_src):
        note = f"One or both cities are not in the reference table, so the widest band was assumed. {DISCLAIMER}"

    return {
        "origin_city": origin_city,
        "destination_city": destination_city,
        "origin_country": o_country,
        "destination_country": d_country,
        "band": band,
        "cabin": cabin_key,
        "low_usd": round(low * mult),
        "high_usd": round(high * mult),
        "currency": "USD",
        "source": "distance-band-estimate",
        "resolution": {"origin": o_src, "destination": d_src},
        "note": note,
    }


@mcp.tool
def search_destinations_catalog(
    query: str = "", budget_level: str = "mid-range", interests: list[str] | None = None
) -> dict[str, Any]:
    """Rank the catalogue of 40 destinations against a query, budget and interests.

    Useful when the request is open-ended ("somewhere warm with good food") and a
    concrete shortlist is needed before any other planning can start.

    Args:
        query: Free text, e.g. "warm beaches in winter" or a city or country name.
        budget_level: budget, mid-range or luxury. Non-matching entries are not
            excluded, only ranked lower.
        interests: Tags such as beach, food, temples, nightlife, nature, museums,
            history, family, adventure, shopping, wellness.

    Returns:
        Up to eight matches, each with a score and the reasons it matched.
    """
    q = _norm(query)
    wanted = {_norm(i) for i in (interests or []) if i}
    level = _norm(budget_level) or "mid-range"
    q_words = {w for w in q.replace(",", " ").split() if len(w) > 2}

    scored = []
    for entry in DESTINATIONS:
        score = 0.0
        reasons: list[str] = []

        city_l, country_l = _norm(entry["city"]), _norm(entry["country"])
        if q and (city_l in q or country_l in q or q in city_l):
            score += 10
            reasons.append("named in the query")

        tag_hits = wanted & set(entry["tags"])
        if tag_hits:
            score += 3 * len(tag_hits)
            reasons.append("matches interests: " + ", ".join(sorted(tag_hits)))

        word_hits = q_words & set(entry["tags"])
        if word_hits:
            score += 2 * len(word_hits)
            reasons.append("query mentions: " + ", ".join(sorted(word_hits)))

        if q_words & {_norm(entry["region"]), *entry["region"].split("-")}:
            score += 2
            reasons.append(f"in {entry['region']}")

        if level in entry["budget_fit"]:
            score += 2
            reasons.append(f"suits a {level} budget")
        else:
            score -= 1

        if score > 0:
            scored.append(
                {
                    "city": entry["city"],
                    "country": entry["country"],
                    "region": entry["region"],
                    "tags": entry["tags"],
                    "best_months": entry["best_months"],
                    "budget_fit": entry["budget_fit"],
                    "score": round(score, 1),
                    "why": reasons,
                }
            )

    scored.sort(key=lambda m: (-m["score"], m["city"]))
    return {
        "query": query,
        "budget_level": level,
        "interests": sorted(wanted),
        "match_count": len(scored),
        "matches": scored[:8],
        "catalogue_size": len(DESTINATIONS),
        "source": "reference-catalogue",
        "note": "A curated offline catalogue, not a live search over all destinations.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="travel-mcp", description="Travel reference MCP server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default="stdio",
        help="stdio (default) for a client that spawns this process; http to listen on a port",
    )
    parser.add_argument(
        "--port", type=int, default=8932, help="port for --transport http (default 8932)"
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind address for --transport http")
    args = parser.parse_args()

    # The banner is suppressed on stdio: the client spawns this process once per
    # session and the decoration is pure noise in its logs.
    if args.transport == "http":
        mcp.run(transport="http", host=args.host, port=args.port)
    else:
        mcp.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
