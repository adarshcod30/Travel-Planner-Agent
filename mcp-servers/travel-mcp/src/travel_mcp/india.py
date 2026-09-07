"""Indian travel reference data.

Trips in this system start in India, which changes what the planner needs to
know. Distance decides train versus flight rather than which airline; hotel
tariffs carry a GST slab that depends on the room rate; the best month for a
place is set by the monsoon and the festival calendar rather than by
temperature alone.

Approximate and offline, like the rest of `data.py` — every tool that reads
this says where its answer came from.
"""

from typing import Any

# ---------------------------------------------------------------------------
# Cities: IRCTC station codes, airports, region, and what they are good for
# ---------------------------------------------------------------------------


def _c(city, state, station, airport, region, tags, best, rail_hours_from_delhi):
    return {
        "city": city,
        "state": state,
        "station_code": station,
        "airport_code": airport,
        "region": region,
        "tags": tags,
        "best_months": best,
        "rail_hours_from_delhi": rail_hours_from_delhi,
    }


CITIES: list[dict[str, Any]] = [
    _c(
        "Delhi",
        "Delhi",
        "NDLS",
        "DEL",
        "north",
        ["history", "food", "shopping", "museums"],
        ["October", "November", "February", "March"],
        0,
    ),
    _c(
        "Agra",
        "Uttar Pradesh",
        "AGC",
        "AGR",
        "north",
        ["history", "architecture"],
        ["October", "November", "February", "March"],
        2,
    ),
    _c(
        "Jaipur",
        "Rajasthan",
        "JP",
        "JAI",
        "north",
        ["history", "shopping", "culture", "food"],
        ["October", "November", "December", "February"],
        5,
    ),
    _c(
        "Udaipur",
        "Rajasthan",
        "UDZ",
        "UDR",
        "north",
        ["history", "romance", "lakes"],
        ["September", "October", "November", "February", "March"],
        12,
    ),
    _c(
        "Jodhpur",
        "Rajasthan",
        "JU",
        "JDH",
        "north",
        ["history", "desert", "shopping"],
        ["October", "November", "December", "February"],
        11,
    ),
    _c(
        "Jaisalmer",
        "Rajasthan",
        "JSM",
        "JSA",
        "north",
        ["desert", "history", "adventure"],
        ["November", "December", "January", "February"],
        18,
    ),
    _c(
        "Amritsar",
        "Punjab",
        "ASR",
        "ATQ",
        "north",
        ["spiritual", "food", "history"],
        ["October", "November", "February", "March"],
        6,
    ),
    _c(
        "Rishikesh",
        "Uttarakhand",
        "RKSH",
        "DED",
        "north",
        ["spiritual", "adventure", "wellness", "nature"],
        ["September", "October", "March", "April"],
        5,
    ),
    _c(
        "Manali",
        "Himachal Pradesh",
        "JUC",
        "KUU",
        "north",
        ["mountains", "adventure", "nature"],
        ["March", "April", "May", "October"],
        12,
    ),
    _c(
        "Shimla",
        "Himachal Pradesh",
        "SML",
        "SLV",
        "north",
        ["mountains", "colonial", "nature"],
        ["March", "April", "May", "October"],
        8,
    ),
    _c(
        "Leh",
        "Ladakh",
        "",
        "IXL",
        "north",
        ["mountains", "adventure", "nature", "monasteries"],
        ["June", "July", "August", "September"],
        0,
    ),
    _c(
        "Varanasi",
        "Uttar Pradesh",
        "BSB",
        "VNS",
        "north",
        ["spiritual", "history", "culture"],
        ["October", "November", "February", "March"],
        12,
    ),
    _c(
        "Khajuraho",
        "Madhya Pradesh",
        "KURJ",
        "HJR",
        "central",
        ["history", "architecture"],
        ["October", "November", "February", "March"],
        11,
    ),
    _c(
        "Mumbai",
        "Maharashtra",
        "CSMT",
        "BOM",
        "west",
        ["food", "nightlife", "colonial", "shopping"],
        ["November", "December", "January", "February"],
        16,
    ),
    _c(
        "Pune",
        "Maharashtra",
        "PUNE",
        "PNQ",
        "west",
        ["food", "history", "nightlife"],
        ["October", "November", "February", "March"],
        20,
    ),
    _c(
        "Goa",
        "Goa",
        "MAO",
        "GOI",
        "west",
        ["beach", "nightlife", "food", "wellness"],
        ["November", "December", "January", "February"],
        26,
    ),
    _c(
        "Ahmedabad",
        "Gujarat",
        "ADI",
        "AMD",
        "west",
        ["history", "food", "architecture"],
        ["November", "December", "January", "February"],
        14,
    ),
    _c(
        "Bengaluru",
        "Karnataka",
        "SBC",
        "BLR",
        "south",
        ["food", "nightlife", "shopping", "parks"],
        ["October", "November", "December", "January"],
        34,
    ),
    _c(
        "Mysuru",
        "Karnataka",
        "MYS",
        "BLR",
        "south",
        ["history", "palaces", "culture"],
        ["October", "November", "December", "January"],
        38,
    ),
    _c(
        "Hampi",
        "Karnataka",
        "HPT",
        "HBX",
        "south",
        ["history", "ruins", "adventure"],
        ["November", "December", "January", "February"],
        30,
    ),
    _c(
        "Chennai",
        "Tamil Nadu",
        "MAS",
        "MAA",
        "south",
        ["food", "temples", "beach", "culture"],
        ["December", "January", "February"],
        32,
    ),
    _c(
        "Madurai",
        "Tamil Nadu",
        "MDU",
        "IXM",
        "south",
        ["temples", "food", "culture"],
        ["December", "January", "February"],
        40,
    ),
    _c(
        "Ooty",
        "Tamil Nadu",
        "UAM",
        "CJB",
        "south",
        ["mountains", "nature", "colonial"],
        ["March", "April", "May", "September", "October"],
        42,
    ),
    _c(
        "Kochi",
        "Kerala",
        "ERS",
        "COK",
        "south",
        ["backwaters", "food", "colonial", "beach"],
        ["November", "December", "January", "February"],
        40,
    ),
    _c(
        "Alleppey",
        "Kerala",
        "ALLP",
        "COK",
        "south",
        ["backwaters", "wellness", "nature"],
        ["November", "December", "January", "February"],
        42,
    ),
    _c(
        "Munnar",
        "Kerala",
        "ALLP",
        "COK",
        "south",
        ["mountains", "nature", "tea", "wellness"],
        ["September", "October", "November", "March"],
        44,
    ),
    _c(
        "Kolkata",
        "West Bengal",
        "HWH",
        "CCU",
        "east",
        ["food", "colonial", "culture", "museums"],
        ["November", "December", "January", "February"],
        17,
    ),
    _c(
        "Darjeeling",
        "West Bengal",
        "NJP",
        "IXB",
        "east",
        ["mountains", "tea", "nature", "colonial"],
        ["March", "April", "May", "October", "November"],
        22,
    ),
    _c(
        "Puri",
        "Odisha",
        "PURI",
        "BBI",
        "east",
        ["beach", "temples", "spiritual"],
        ["November", "December", "January", "February"],
        23,
    ),
    _c(
        "Shillong",
        "Meghalaya",
        "GHY",
        "SHL",
        "northeast",
        ["mountains", "nature", "waterfalls"],
        ["October", "November", "March", "April"],
        30,
    ),
    _c(
        "Gangtok",
        "Sikkim",
        "NJP",
        "PYG",
        "northeast",
        ["mountains", "nature", "monasteries"],
        ["March", "April", "May", "October"],
        24,
    ),
    _c(
        "Port Blair",
        "Andaman",
        "",
        "IXZ",
        "islands",
        ["beach", "diving", "nature"],
        ["November", "December", "January", "February", "March"],
        0,
    ),
]

CITY_BY_NAME = {c["city"].lower(): c for c in CITIES}

# ---------------------------------------------------------------------------
# Seasons — the monsoon is the fact that most changes a plan
# ---------------------------------------------------------------------------

#: region -> (label, months to avoid, why)
SEASONS: dict[str, dict[str, Any]] = {
    "north": {
        "peak": ["October", "November", "December", "February", "March"],
        "avoid": ["May", "June"],
        "why": "May and June are extreme heat; July to September is monsoon",
    },
    "west": {
        "peak": ["November", "December", "January", "February"],
        "avoid": ["June", "July", "August"],
        "why": "the southwest monsoon is heaviest on this coast",
    },
    "south": {
        "peak": ["November", "December", "January", "February"],
        "avoid": ["April", "May"],
        "why": "April and May are hot and humid; October to November brings the retreating monsoon",
    },
    "east": {
        "peak": ["November", "December", "January", "February"],
        "avoid": ["June", "July", "August"],
        "why": "monsoon, and cyclone risk on the coast in October and November",
    },
    "northeast": {
        "peak": ["October", "November", "March", "April"],
        "avoid": ["June", "July", "August"],
        "why": "among the wettest places on earth during the monsoon",
    },
    "central": {
        "peak": ["October", "November", "February", "March"],
        "avoid": ["May", "June"],
        "why": "extreme pre-monsoon heat",
    },
    "islands": {
        "peak": ["November", "December", "January", "February", "March"],
        "avoid": ["June", "July", "August"],
        "why": "monsoon and rough seas suspend most water activities",
    },
}

# ---------------------------------------------------------------------------
# Festivals — they move prices and availability more than the weather does
# ---------------------------------------------------------------------------

FESTIVALS: list[dict[str, Any]] = [
    {
        "name": "Diwali",
        "months": ["October", "November"],
        "where": "nationwide",
        "effect": "trains and flights sell out weeks ahead and hotel tariffs peak; many shops shut for two days",
    },
    {
        "name": "Holi",
        "months": ["March"],
        "where": "north and west",
        "effect": "one day of heavy crowds; some transport suspended locally",
    },
    {
        "name": "Durga Puja",
        "months": ["September", "October"],
        "where": "West Bengal, Kolkata",
        "effect": "Kolkata is exceptionally busy and hotels book out; the city is also at its most spectacular",
    },
    {
        "name": "Pushkar Camel Fair",
        "months": ["November"],
        "where": "Rajasthan",
        "effect": "Pushkar and nearby Ajmer are full; Jaipur hotels fill as an overflow",
    },
    {
        "name": "Onam",
        "months": ["August", "September"],
        "where": "Kerala",
        "effect": "peak domestic travel within Kerala; boat races draw large crowds",
    },
    {
        "name": "Ganesh Chaturthi",
        "months": ["August", "September"],
        "where": "Maharashtra, Mumbai, Pune",
        "effect": "processions close roads in Mumbai and Pune for several days",
    },
    {
        "name": "Navratri and Garba",
        "months": ["September", "October"],
        "where": "Gujarat",
        "effect": "Ahmedabad and Vadodara are booked out for nine nights",
    },
    {
        "name": "Christmas and New Year",
        "months": ["December"],
        "where": "Goa, Kerala, hill stations",
        "effect": "the single most expensive week of the year in Goa; tariffs commonly triple",
    },
    {
        "name": "Kumbh or Magh Mela",
        "months": ["January", "February"],
        "where": "Prayagraj, Haridwar, Ujjain, Nashik",
        "effect": "enormous crowds in the host city; book far ahead or avoid entirely",
    },
]

# ---------------------------------------------------------------------------
# Costs — rupee bands that actually reflect Indian travel
# ---------------------------------------------------------------------------

#: Rail fare per person by class, as rupees per hour of journey. Indian rail
#: pricing is distance-based and remarkably linear, so an hourly rate estimates
#: well across the network.
RAIL_FARE_PER_HOUR: dict[str, int] = {
    "2S": 12,
    "SL": 22,
    "3A": 60,
    "2A": 85,
    "1A": 145,
    "CC": 70,
    "EC": 130,
}

RAIL_CLASS_NAMES: dict[str, str] = {
    "2S": "Second Sitting",
    "SL": "Sleeper",
    "3A": "AC 3 Tier",
    "2A": "AC 2 Tier",
    "1A": "AC First Class",
    "CC": "AC Chair Car",
    "EC": "Executive Chair Car",
}

#: Domestic air fare, one way per person, by how far ahead it is booked.
AIR_FARE_BANDS: dict[str, tuple[int, int]] = {
    "short": (2200, 4500),  # under ~700 km, e.g. Delhi-Jaipur
    "medium": (3500, 7500),  # 700-1500 km, e.g. Delhi-Mumbai
    "long": (5000, 11000),  # over 1500 km, e.g. Delhi-Kochi
}

#: Hotel tariff per night, by budget level, as (low, high) rupees.
HOTEL_TARIFF: dict[str, tuple[int, int]] = {
    "budget": (800, 2500),
    "mid-range": (2500, 7000),
    "luxury": (7000, 30000),
}

#: GST on hotel accommodation, by tariff per night. Slabs, so a room a hundred
#: rupees cheaper can fall into a lower bracket — worth surfacing on a plan.
HOTEL_GST_SLABS: list[tuple[int, int, float]] = [
    (0, 1000, 0.0),
    (1000, 7500, 0.12),
    (7500, 10**9, 0.18),
]

#: Per person per day, excluding hotel and intercity transport.
DAILY_COSTS: dict[str, dict[str, tuple[int, int]]] = {
    "budget": {"food": (300, 600), "local_transport": (150, 400), "activities": (100, 500)},
    "mid-range": {"food": (700, 1500), "local_transport": (400, 900), "activities": (500, 1500)},
    "luxury": {"food": (2000, 5000), "local_transport": (1500, 4000), "activities": (1500, 5000)},
}

#: Intercity bus, rupees per hour per person.
BUS_FARE_PER_HOUR = {"ordinary": 25, "ac_seater": 45, "ac_sleeper": 70}

DISCLAIMER_IN = (
    "Approximate reference figures for planning, not live fares or tariffs. "
    "Confirm on IRCTC, the airline, or the hotel before booking."
)


def gst_rate(tariff_per_night: float) -> float:
    """The GST slab a nightly tariff falls into."""
    for low, high, rate in HOTEL_GST_SLABS:
        if low <= tariff_per_night < high:
            return rate
    return 0.18


def region_of(city: str) -> str | None:
    entry = CITY_BY_NAME.get(city.strip().lower())
    return entry["region"] if entry else None
