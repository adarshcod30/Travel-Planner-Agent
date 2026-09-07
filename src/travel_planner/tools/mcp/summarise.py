"""Turning MCP tool results into sentences a model will actually act on.

Tool results arrive as JSON. Pasting them into a prompt technically supplies the
facts and functionally hides them: the budget agent was handed a correct
reference total of ₹27,140 inside a 700-character JSON blob, among six other
JSON blobs, and produced ₹3,980 from its own guess instead.

A model reads a prompt the way a person reads a page. Facts have to be legible,
not merely present. Each function here renders one tool's output as the sentence
a knowledgeable colleague would have written, with the numbers already in
rupees.

Every one falls back to the raw text if the shape is not what it expects — a
changed tool schema should cost legibility, never the fact itself.
"""

import json
from typing import Any

from travel_planner.core.money import rupees


def _load(raw: str) -> dict[str, Any] | None:
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def city_info(raw: str) -> str:
    d = _load(raw)
    if not d or "error" in d:
        return raw[:300]
    bits = [f"{d.get('city')} is in {d.get('state')}"]
    if code := d.get("station_code"):
        bits.append(f"rail station code {code}")
    if air := d.get("airport_code"):
        bits.append(f"airport {air}")
    if best := d.get("best_months"):
        bits.append(f"best months are {', '.join(best)}")
    if avoid := d.get("season_avoid"):
        bits.append(f"avoid {', '.join(avoid)} — {d.get('season_note', '')}")
    return ". ".join(bits) + "."


def domestic_travel(raw: str) -> str:
    d = _load(raw)
    if not d or "error" in d:
        return raw[:300]
    hours = d.get("estimated_rail_hours")
    parts = [f"{d.get('origin')} to {d.get('destination')} is about {hours} hours by train"]
    rail = d.get("rail") or {}
    fares = [f"{v.get('class')} {rupees(v.get('fare_per_person', 0))}" for v in rail.values()]
    if fares:
        parts.append("per person: " + ", ".join(fares))
    air = d.get("air", {}).get("one_way_per_person") or {}
    if air:
        parts.append(
            f"flights run {rupees(air.get('low', 0))}-{rupees(air.get('high', 0))} one way"
        )
    if rec := d.get("recommendation"):
        parts.append(f"recommendation: {rec}")
    return ". ".join(parts) + "."


def trip_budget(raw: str) -> str:
    """The one that mattered: this note was being ignored as JSON."""
    d = _load(raw)
    if not d or "error" in d:
        return raw[:300]
    h = d.get("hotel") or {}
    gst = f" including {int(h.get('gst_rate', 0) * 100)}% GST" if h.get("gst_rate") else ""
    return (
        f"For {d.get('days')} days and {d.get('travelers')} travellers at a "
        f"{d.get('budget_level')} level, the reference budget is "
        f"hotel {rupees(h.get('total', 0))}{gst} "
        f"({rupees(h.get('tariff_per_night', 0))} a night for {h.get('nights')} nights), "
        f"food {rupees(d.get('food', 0))}, local transport {rupees(d.get('local_transport', 0))}, "
        f"activities {rupees(d.get('activities', 0))}. "
        f"Total {rupees(d.get('total', 0))}, which is "
        f"{rupees(d.get('per_person_per_day', 0))} per person per day. "
        "This excludes travel to the destination."
    )


def festivals(raw: str) -> str:
    d = _load(raw)
    if not d:
        return raw[:300]
    items = d.get("festivals") or []
    if not items:
        return f"No major festivals fall in {d.get('month', 'these dates')}."
    return "Festivals in this period: " + " ".join(
        f"{f['name']} ({f['where']}) — {f['effect']}." for f in items
    )


def current_time(raw: str) -> str:
    d = _load(raw)
    if not d:
        return raw[:200]
    dt = d.get("datetime") or d.get("current_time") or ""
    return f"Today in India it is {dt[:16].replace('T', ' ')} IST." if dt else raw[:200]


def inr_rate(raw: str) -> str:
    """The fetch result wraps the JSON body in explanatory text.

    Slicing from the first brace is not enough — `json.loads` rejects trailing
    content, and fetch appends its own notes after the payload. The last brace
    bounds it.
    """
    start, end = raw.find("{"), raw.rfind("}")
    d = _load(raw[start : end + 1]) if 0 <= start < end else None
    rate = ((d or {}).get("rates") or {}).get("INR")
    if rate:
        return f"Today one US dollar is about {rupees(rate)} (live rate)."
    return raw[:200]


def weather(raw: str) -> str:
    d = _load(raw)
    if not d or "error" in d:
        return raw[:300]
    bits = [f"{d.get('city')} in {d.get('period', 'this season')}: {d.get('temperature_range_c')}"]
    if rain := d.get("rainfall"):
        bits.append(f"rainfall {rain}")
    if d.get("source") == "latitude-band-estimate":
        bits.append("(a band estimate, not a table entry)")
    return ", ".join(bits) + "."
