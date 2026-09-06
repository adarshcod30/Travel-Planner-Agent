# travel-mcp

An MCP server exposing five travel reference tools. Built for the
[Travel Planner Agent](../../README.md)'s v5 graph, but standalone — it depends on
nothing from the planner and works with any MCP client.

## Tools

| Tool | What it answers |
|---|---|
| `get_weather_forecast` | Typical seasonal climate for a destination and month. Climatology, not a forecast. |
| `convert_currency` | Convert between 28 currencies at approximate reference rates. Accepts ISO codes or country names. |
| `check_visa_requirements` | Entry requirements for a passport/destination pair, across 10 common passports. |
| `estimate_flight_cost` | Round-trip airfare range from a distance band, with cabin multipliers. |
| `search_destinations_catalog` | Rank 40 curated destinations against a free-text query, budget level and interests. |

## The design rule

Every response reports **where its answer came from** — an exact table hit, a
latitude-band estimate, or a documented conservative default — and never presents
reference data as a live quote.

That matters because the consumer is a language model. A tool that quietly guesses
is indistinguishable, to the model reading it, from one that knows; the model will
state both with equal confidence. Making provenance part of the payload lets the
planner weight the two differently, and lets a reader of the finished plan see
which figures are soft. An unknown visa pair returns "visa required in advance"
labelled `conservative-default` rather than a plausible-sounding guess.

## Running it

```bash
# stdio — the client spawns this process (what the planner does by default)
uv run python -m travel_mcp.server

# http — listen on a port
uv run python -m travel_mcp.server --transport http --port 8932
```

## Testing

```bash
uv run pytest mcp-servers/travel-mcp/tests -q
```

Tests drive the server through FastMCP's in-memory client rather than calling the
functions directly, so tool registration, the schemas derived from the signatures,
and result serialisation are all covered.

## Data

All reference tables live in [`data.py`](src/travel_mcp/data.py): 40 destinations
with per-quarter climate, 28 currency rates, visa rules for 10 passports, and a
country-to-region map for the flight bands. Approximate by design, and every
figure is labelled as such.

## License

MIT
