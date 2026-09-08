"""One trip through all five versions, measured the same way.

This is the script behind the table at the top of the README. It exists so
that claim is reproducible rather than asserted: run it against your own
Bedrock account and you get your own numbers, in your own region, at your own
latency.

Two decisions in here matter for whether the numbers mean anything.

**It measures at the Agent Protocol boundary**, not by importing the graphs.
Every version is driven through `POST /threads/{id}/runs/wait` exactly as the
frontend drives it, so the wall clock includes Aegra's checkpoint writes,
state serialisation and HTTP round-trips — the cost a real caller pays. An
in-process measurement would be faster and would describe a deployment nobody
runs.

**Agent time, calls and tokens are read out of the persisted state**, from the
`agent_runs` list each agent appends to. That is the same telemetry the Live
tab renders, so there is no second accounting path that could quietly disagree
with what the UI shows you.

v4 and v5 pause. To keep the comparison like-for-like, this accepts the plan
review and declines the booking offer — so what is timed is "produce a plan",
for all five, and not "produce a plan, then browse Goibibo for ten minutes".

    uv run scripts/measure_versions.py
    uv run scripts/measure_versions.py --base-url http://127.0.0.1:2026 --repeat 3

Needs a running server (`./scripts/run_all.sh`) and real Bedrock credentials.
It spends money — roughly 140k tokens of Nova for a full sweep.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import time
from typing import Any

import httpx

from travel_planner.core.config import GraphVersion

#: The five graphs, in the order they were built. Taken from the type that
#: defines them so this cannot drift from what the server actually serves.
VERSIONS: tuple[str, ...] = GraphVersion.__args__  # type: ignore[attr-defined]

#: One brief, held constant. Deliberately ordinary: a request with a hard
#: constraint ("reachable by train") and a soft one ("street food"), which is
#: what separates the versions — v1 has to guess at both.
TRIP: dict[str, Any] = {
    "request": "forts and street food, reachable by train",
    "origin": "Delhi",
    "days": 3,
    "travelers": 2,
    "budget_level": "mid-range",
    "interests": ["history", "food"],
    "season": "November",
}


async def _interrupt_kind(client: httpx.AsyncClient, thread: str) -> str | None:
    """What the run is waiting for, or None if it has finished."""
    state = (await client.get(f"/threads/{thread}/state")).json()
    tasks = state.get("tasks") or []
    if not tasks or not tasks[0].get("interrupts"):
        return None
    payload = tasks[0]["interrupts"][0].get("value") or {}
    return payload.get("type") or "unknown"


async def measure(client: httpx.AsyncClient, graph: str) -> dict[str, Any]:
    """Run one trip through one version and report what it cost."""
    found = (await client.post("/assistants/search", json={"graph_id": graph, "limit": 1})).json()
    if not found:
        raise RuntimeError(f"no assistant registered for {graph}")
    assistant = found[0]["assistant_id"]
    thread = (await client.post("/threads", json={})).json()["thread_id"]

    started = time.time()
    await client.post(
        f"/threads/{thread}/runs/wait", json={"assistant_id": assistant, "input": TRIP}
    )

    # v4 stops once (the plan review); v5 stops twice (review, then the booking
    # offer). Answering by what the interrupt actually is, rather than by
    # version, keeps this correct if a version gains or loses a pause.
    answers = {"section_review": "accept", "booking_offer": "skip"}
    for _ in range(4):
        kind = await _interrupt_kind(client, thread)
        if kind is None:
            break
        await client.post(
            f"/threads/{thread}/runs/wait",
            json={
                "assistant_id": assistant,
                "command": {"resume": [{"type": answers.get(kind, "skip")}]},
            },
        )
    wall = time.time() - started

    values = (await client.get(f"/threads/{thread}/state")).json()["values"]
    runs = values.get("agent_runs") or []
    return {
        "graph": graph,
        "wall": wall,
        "agent_s": sum(r["duration_ms"] for r in runs) / 1000,
        "calls": len(runs),
        "tokens": sum(r["input_tokens"] + r["output_tokens"] for r in runs),
        "repairs": sum(r["repairs"] for r in runs),
        "escalations": sum(1 for r in runs if r["escalated"]),
        "budget": (values.get("budget") or {}).get("total"),
        "plan_chars": len(values.get("final_plan") or ""),
    }


HEADER = (
    f"{'version':<17}{'wall':>8}{'agent':>8}{'calls':>7}{'tokens':>9}"
    f"{'repair':>8}{'esc':>5}{'budget':>11}{'plan':>8}"
)


def row(r: dict[str, Any]) -> str:
    budget = f"{r['budget']:,.0f}" if r["budget"] else "—"
    return (
        f"{r['graph']:<17}{r['wall']:7.1f}s{r['agent_s']:7.1f}s{r['calls']:7}"
        f"{r['tokens']:9,}{r['repairs']:8}{r['escalations']:5}"
        f"{budget:>11}{r['plan_chars']:8,}"
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("AEGRA_URL", "http://127.0.0.1:2026"))
    parser.add_argument("--token", default=os.getenv("AEGRA_API_TOKEN", "local-dev"))
    parser.add_argument("--repeat", type=int, default=1, help="runs per version; medians reported")
    parser.add_argument("--only", nargs="*", default=list(VERSIONS), choices=list(VERSIONS))
    args = parser.parse_args()

    headers = {"Authorization": f"Bearer {args.token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(base_url=args.base_url, headers=headers, timeout=900) as client:
        try:
            await client.get("/info")
        except httpx.ConnectError:
            print(f"No server at {args.base_url}. Start one with ./scripts/run_all.sh")
            return 1

        print(HEADER)
        print("-" * len(HEADER))
        failures = 0
        for graph in args.only:
            samples: list[dict[str, Any]] = []
            for attempt in range(args.repeat):
                try:
                    samples.append(await measure(client, graph))
                except Exception as exc:  # a failed version is a result, not a crash
                    failures += 1
                    print(f"{graph:<17} run {attempt + 1} failed: {type(exc).__name__}: {exc}")
            if not samples:
                continue
            merged = dict(samples[0])
            for key in ("wall", "agent_s", "calls", "tokens", "repairs", "escalations"):
                merged[key] = statistics.median(s[key] for s in samples)
            print(row(merged))

        if args.repeat > 1:
            print(f"\nMedian of {args.repeat} runs per version.")
        return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
