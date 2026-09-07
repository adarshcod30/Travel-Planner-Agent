"""travel-mcp tools, exercised through a real in-memory MCP client.

Calling the functions directly would test the logic but not the server: the
schemas FastMCP derives from the signatures, the tool registration, and the
serialisation of the return values are all part of the contract a client
depends on. The in-memory client covers all of it without a subprocess.
"""

import pytest
from fastmcp import Client
from travel_mcp.server import mcp

#: The general tools. The India-specific ones are covered in test_india.py.
EXPECTED_TOOLS = {
    "get_weather_forecast",
    "convert_currency",
    "check_visa_requirements",
    "estimate_flight_cost",
    "search_destinations_catalog",
}


@pytest.fixture
async def client():
    async with Client(mcp) as c:
        yield c


async def _call(client, name, **kwargs):
    result = await client.call_tool(name, kwargs)
    return result.data


# --- registration ---------------------------------------------------------------


async def test_every_tool_is_described(client):
    """A description is not documentation here — the model reads it to decide
    whether to call the tool at all."""
    tools = await client.list_tools()
    assert {t.name for t in tools} >= EXPECTED_TOOLS
    for t in tools:
        assert t.description and len(t.description) > 40, t.name
        assert t.inputSchema["type"] == "object"


# --- weather --------------------------------------------------------------------


async def test_weather_known_city_uses_the_table(client):
    r = await _call(client, "get_weather_forecast", city="Kyoto", country="Japan", month="November")
    assert r["source"] == "reference-table"
    assert r["temperature_range_c"] == "8 to 19 C"
    assert r["period"] == "October-December"
    assert "November" in r["best_months"]


async def test_weather_unknown_city_falls_back_and_says_so(client):
    r = await _call(client, "get_weather_forecast", city="Timbuktu", country="Mali", month="July")
    assert r["source"] == "latitude-band-estimate"
    assert "assumed_band" in r
    assert "not in the reference table" in r["note"]


async def test_weather_accepts_a_season(client):
    r = await _call(client, "get_weather_forecast", city="Kyoto", month="summer")
    assert r["period"] == "July-September"


async def test_weather_defaults_when_month_is_missing(client):
    r = await _call(client, "get_weather_forecast", city="Kyoto")
    assert r["period"] == "April-June"
    assert "assumed" in r["month_interpreted"]


# --- currency -------------------------------------------------------------------


async def test_currency_converts_by_code(client):
    r = await _call(client, "convert_currency", amount=100, from_currency="USD", to_currency="JPY")
    assert r["converted"] == pytest.approx(15200.0)
    assert r["from"] == "USD" and r["to"] == "JPY"


async def test_currency_resolves_a_country_name(client):
    r = await _call(
        client, "convert_currency", amount=10, from_currency="united states", to_currency="Japan"
    )
    assert r["to"] == "JPY"


async def test_currency_round_trip_is_stable(client):
    a = await _call(client, "convert_currency", amount=250, from_currency="EUR", to_currency="GBP")
    b = await _call(
        client, "convert_currency", amount=a["converted"], from_currency="GBP", to_currency="EUR"
    )
    assert b["converted"] == pytest.approx(250, rel=1e-3)


async def test_currency_rejects_unknown_code(client):
    r = await _call(client, "convert_currency", amount=1, from_currency="USD", to_currency="XYZ")
    assert "error" in r and "XYZ" in r["error"]
    assert "USD" in r["supported_codes"]


async def test_currency_rejects_negative_amount(client):
    r = await _call(client, "convert_currency", amount=-5, from_currency="USD", to_currency="EUR")
    assert "error" in r


# --- visas ----------------------------------------------------------------------


async def test_visa_known_pair(client):
    r = await _call(
        client,
        "check_visa_requirements",
        passport_country="United States",
        destination_country="Japan",
    )
    assert r["requirement"] == "visa-free"
    assert r["max_stay_days"] == 90
    assert r["source"] == "reference-table"


async def test_visa_unknown_pair_is_conservative(client):
    r = await _call(
        client,
        "check_visa_requirements",
        passport_country="Iceland",
        destination_country="Mongolia",
    )
    assert r["source"] == "conservative-default"
    assert r["requirement"] == "visa required in advance"
    assert "not in the reference table" in r["note"]


async def test_visa_same_country(client):
    r = await _call(
        client, "check_visa_requirements", passport_country="Japan", destination_country="japan"
    )
    assert r["source"] == "same-country"


# --- flights --------------------------------------------------------------------


async def test_flight_intercontinental_band(client):
    r = await _call(
        client, "estimate_flight_cost", origin_city="New York", destination_city="Kyoto"
    )
    assert r["band"] == "intercontinental"
    assert r["low_usd"] < r["high_usd"]


async def test_flight_domestic_band_is_cheaper_than_intercontinental(client):
    dom = await _call(
        client, "estimate_flight_cost", origin_city="New York", destination_city="San Francisco"
    )
    inter = await _call(
        client, "estimate_flight_cost", origin_city="New York", destination_city="Kyoto"
    )
    assert dom["band"] == "domestic"
    assert dom["high_usd"] < inter["high_usd"]


async def test_flight_same_region_band(client):
    r = await _call(client, "estimate_flight_cost", origin_city="Paris", destination_city="Rome")
    assert r["band"] == "same-region"


async def test_flight_cabins_are_ordered(client):
    prices = []
    for cabin in ("economy", "premium", "business", "first"):
        r = await _call(
            client,
            "estimate_flight_cost",
            origin_city="New York",
            destination_city="Kyoto",
            cabin=cabin,
        )
        prices.append(r["low_usd"])
    assert prices == sorted(prices) and len(set(prices)) == 4


async def test_flight_unknown_city_widens_the_band_and_says_so(client):
    r = await _call(
        client, "estimate_flight_cost", origin_city="Nowheresville", destination_city="Kyoto"
    )
    assert r["band"] == "intercontinental"
    assert r["resolution"]["origin"] == "unresolved"
    assert "not in the reference table" in r["note"]


async def test_flight_rejects_unknown_cabin(client):
    r = await _call(
        client,
        "estimate_flight_cost",
        origin_city="Paris",
        destination_city="Rome",
        cabin="spaceship",
    )
    assert "error" in r and "economy" in r["supported_cabins"]


# --- destination search ---------------------------------------------------------


async def test_search_ranks_by_interest_and_budget(client):
    r = await _call(
        client,
        "search_destinations_catalog",
        query="warm beaches",
        budget_level="budget",
        interests=["beach", "food"],
    )
    assert r["match_count"] > 0
    cities = [m["city"] for m in r["matches"]]
    assert "Goa" in cities or "Bali" in cities
    top = r["matches"][0]
    assert top["why"] and top["score"] > 0


async def test_search_finds_a_named_city_first(client):
    r = await _call(client, "search_destinations_catalog", query="kyoto")
    assert r["matches"][0]["city"] == "Kyoto"
    assert "named in the query" in r["matches"][0]["why"]


async def test_search_returns_at_most_eight(client):
    r = await _call(client, "search_destinations_catalog", query="food culture", interests=["food"])
    assert len(r["matches"]) <= 8
    assert r["catalogue_size"] == 40


async def test_search_budget_level_affects_ranking(client):
    lux = await _call(
        client, "search_destinations_catalog", query="", budget_level="luxury", interests=["nature"]
    )
    bud = await _call(
        client, "search_destinations_catalog", query="", budget_level="budget", interests=["nature"]
    )
    assert [m["city"] for m in lux["matches"]] != [m["city"] for m in bud["matches"]]
