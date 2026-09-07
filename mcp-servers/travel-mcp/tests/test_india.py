"""Indian travel tools, through a real in-memory MCP client."""

import pytest
from fastmcp import Client
from travel_mcp.server import mcp


@pytest.fixture
async def client():
    async with Client(mcp) as c:
        yield c


async def _call(client, name, **kwargs):
    return (await client.call_tool(name, kwargs)).data


async def test_city_info_gives_the_codes_a_traveller_needs(client):
    r = await _call(client, "get_indian_city_info", city="Jaipur")
    assert r["station_code"] == "JP"  # what IRCTC wants
    assert r["airport_code"] == "JAI"
    assert r["state"] == "Rajasthan"
    assert "May" in r["season_avoid"]  # pre-monsoon heat
    assert r["source"] == "reference-table"


async def test_unknown_city_lists_what_is_known(client):
    r = await _call(client, "get_indian_city_info", city="Atlantis")
    assert "error" in r and "Jaipur" in r["known_cities"]


async def test_train_beats_flight_on_an_overnight_route(client):
    r = await _call(
        client, "estimate_domestic_travel", origin="Delhi", destination="Goa", travelers=2
    )
    assert r["overnight_train_possible"] is True
    assert "train" in r["recommendation"].lower()
    assert r["rail"]["3A"]["total"] == r["rail"]["3A"]["fare_per_person"] * 2
    assert r["currency"] == "INR"


async def test_rail_classes_are_ordered_by_price(client):
    r = await _call(client, "estimate_domestic_travel", origin="Delhi", destination="Jaipur")
    fares = [r["rail"][c]["fare_per_person"] for c in ("SL", "3A", "2A")]
    assert fares == sorted(fares), "sleeper must be cheaper than 3A, which is cheaper than 2A"


async def test_budget_applies_the_right_gst_slab(client):
    """Nil below ₹1,000, 12% to ₹7,500, 18% above — a real and missed cost."""
    budget = await _call(
        client,
        "estimate_trip_budget",
        destination="Jaipur",
        days=4,
        travelers=2,
        budget_level="budget",
    )
    mid = await _call(
        client,
        "estimate_trip_budget",
        destination="Jaipur",
        days=4,
        travelers=2,
        budget_level="mid-range",
    )
    lux = await _call(
        client,
        "estimate_trip_budget",
        destination="Jaipur",
        days=4,
        travelers=2,
        budget_level="luxury",
    )

    assert budget["hotel"]["gst_rate"] == 0.12  # ₹1,650 average tariff
    assert mid["hotel"]["gst_rate"] == 0.12  # ₹4,750
    assert lux["hotel"]["gst_rate"] == 0.18  # ₹18,500
    assert budget["total"] < mid["total"] < lux["total"]
    assert all(r["currency"] == "INR" for r in (budget, mid, lux))


async def test_budget_rooms_are_shared(client):
    """Two to a room — costing a couple for two rooms would inflate everything."""
    r = await _call(client, "estimate_trip_budget", destination="Goa", days=3, travelers=2)
    assert r["rooms"] == 1
    assert (await _call(client, "estimate_trip_budget", destination="Goa", days=3, travelers=4))[
        "rooms"
    ] == 2


async def test_budget_excludes_intercity_travel(client):
    r = await _call(client, "estimate_trip_budget", destination="Goa", days=3)
    assert "estimate_domestic_travel" in r["note"]


async def test_festivals_that_actually_move_prices(client):
    nov = await _call(client, "check_festivals", month="November")
    names = [f["name"] for f in nov["festivals"]]
    assert "Diwali" in names
    assert any("sell out" in f["effect"] or "peak" in f["effect"] for f in nov["festivals"])


async def test_festivals_filter_by_region(client):
    r = await _call(client, "check_festivals", month="December", region="Goa")
    assert any("Goa" in f["where"] or f["where"] == "nationwide" for f in r["festivals"])


async def test_bus_fare_scales_with_service(client):
    fares = [
        (await _call(client, "estimate_bus_fare", hours=6, service=s))["fare_per_person"]
        for s in ("ordinary", "ac_seater", "ac_sleeper")
    ]
    assert fares == sorted(fares)


async def test_bus_rejects_an_unknown_service(client):
    r = await _call(client, "estimate_bus_fare", hours=4, service="rocket")
    assert "error" in r


async def test_ten_tools_are_registered(client):
    tools = await client.list_tools()
    assert len(tools) == 10, sorted(t.name for t in tools)
    assert {
        "get_indian_city_info",
        "estimate_domestic_travel",
        "estimate_trip_budget",
        "check_festivals",
        "estimate_bus_fare",
    } <= {t.name for t in tools}
