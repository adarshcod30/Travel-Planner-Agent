# travel-mcp

An MCP server exposing **ten travel reference tools**, five of them specific to
travel within India. Built for the [Travel Planner Agent](../../README.md)'s v5
graph, but standalone — it depends on nothing from the planner and works with
any MCP client.

It exists because the alternative is asking a language model to recall a rail
fare. It will answer, fluently, and be wrong by a factor of three.

---

## Tools

### General travel

| Tool | Arguments | What it answers |
|---|---|---|
| `get_weather_forecast` | `city`, `country`, `month` | Typical seasonal climate for a destination and month. Climatology, not a forecast |
| `convert_currency` | `amount`, `from_currency`, `to_currency` | Convert between 28 currencies at approximate reference rates. Accepts ISO codes or country names |
| `check_visa_requirements` | `passport_country`, `destination_country` | Entry requirements for a passport/destination pair, across 10 common passports |
| `estimate_flight_cost` | `origin`, `destination`, `cabin`, `travelers` | Round-trip airfare range from a distance band, with cabin multipliers |
| `search_destinations_catalog` | `query`, `budget_level`, `interests` | Rank 40 curated destinations against a free-text query, budget level and interests |

### Travel within India

These are what let the planner quote a figure in rupees instead of a range in
dollars.

| Tool | Arguments | What it answers |
|---|---|---|
| `get_indian_city_info` | `city` | IRCTC rail station code, airport code, region, and the months worth visiting |
| `estimate_domestic_travel` | `origin`, `destination`, `travelers` | Train against flight for a domestic journey — fare, duration and class, in rupees |
| `estimate_bus_fare` | `origin`, `destination`, `travelers` | Intercity coach fare, often the only option where rail does not run |
| `estimate_trip_budget` | `city`, `days`, `travelers`, `budget_level` | A costed breakdown with **hotel GST applied at the right slab** |
| `check_festivals` | `month`, `region` | Festivals that move prices and close attractions in a given month |

The GST detail is the sort of thing that decides whether a budget is usable:
Indian hotel tariffs are taxed in bands, so a room at ₹7,000 and one at ₹7,600
are not 9% apart on the bill. The slab is applied per night, per band.

---

## The design rule

Every response reports **where its answer came from** — an exact table hit, a
latitude-band estimate, or a documented conservative default — and never
presents reference data as a live quote.

That matters because the consumer is a language model. A tool that quietly
guesses is indistinguishable, to the model reading it, from one that knows; the
model will state both with equal confidence. Making provenance part of the
payload lets the planner weight the two differently, and lets a reader of the
finished plan see which figures are soft.

An unknown visa pair returns `"visa required in advance"` labelled
`conservative-default` rather than a plausible-sounding guess. A city outside
the 32 in the table returns a latitude-band estimate and says so.

---

## Running it

```bash
# stdio — the client spawns this process (what the planner does by default)
uv run python -m travel_mcp.server

# http — listen on a port
uv run python -m travel_mcp.server --transport http --port 8932
```

### Wiring it into any MCP client

```jsonc
{
  "mcpServers": {
    "travel": {
      "command": "python",
      "args": ["-m", "travel_mcp.server"]
    }
  }
}
```

The planner spawns it with the **current interpreter** rather than `python` from
`PATH`, because those are not necessarily the same one — a test pins that.

---

## Reference data

Two modules, both approximate by design and both labelled as such.

| Module | Holds |
|---|---|
| [`data.py`](src/travel_mcp/data.py) | 40 destinations with per-quarter climate · 28 currency rates · visa rules for 10 passports · 52-country region map · 5 flight distance bands · 6 latitude climate bands |
| [`india.py`](src/travel_mcp/india.py) | 32 cities with rail and airport codes · rail fares across 7 classes · bus fare bands · 3 hotel tariff tiers with their GST slabs · daily cost bands · 9 festivals · 7 seasons |

---

## Testing

```bash
uv run pytest mcp-servers/travel-mcp/tests -q      # 35 tests
```

Tests drive the server through FastMCP's **in-memory client** rather than
calling the functions directly, so tool registration, the schemas derived from
the signatures, and result serialisation are all covered — a tool that stops
being registered, or whose signature no longer produces a valid schema, fails
here rather than at run time inside an agent.

---

## License

MIT — see the [root LICENSE](../../LICENSE).
