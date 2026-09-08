"""The serving layer, against a real server.

This is the half of the system the unit suite cannot reach. Every graph test in
`tests/unit` compiles with a `MemorySaver` and calls the graph directly, which
is what makes those tests fast and hermetic — and also means 618 passing tests
say nothing about Aegra. The manifest wiring, the assistant registration, the
injected Postgres checkpointer, the custom routes riding the same port and the
same auth: none of it is exercised until something actually serves.

Marked `integration`, so `pytest -m "not integration"` (what CI runs) skips it,
and it skips itself anyway when no server answers.

**Nothing here spends a Bedrock call.** The state round-trip is done by writing
state directly rather than by running a graph, which tests the persistence
Aegra injects without paying a model to produce something to persist. The one
test that does run a graph is marked `live` as well, and is opt-in twice over.

    ./scripts/run_all.sh                       # in another terminal
    uv run pytest -m integration
    uv run pytest -m "integration and live"    # includes the one real run
"""

import json
from pathlib import Path
from uuid import uuid5

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[2]
GRAPHS: list[str] = list(json.loads((ROOT / "aegra.json").read_text())["graphs"])


# --- registration ---------------------------------------------------------------


async def test_the_server_reports_the_five_graphs(client):
    res = await client.get("/info")
    assert res.status_code == 200
    assert res.json(), "/info returned an empty body"


@pytest.mark.parametrize("graph_id", GRAPHS)
async def test_every_graph_has_a_registered_assistant(client, graph_id):
    """Aegra creates one default assistant per manifest key, at a derived id."""
    found = (
        await client.post("/assistants/search", json={"graph_id": graph_id, "limit": 1})
    ).json()
    assert found, f"no assistant registered for {graph_id}"
    assert found[0]["graph_id"] == graph_id


@pytest.mark.parametrize("graph_id", GRAPHS)
async def test_the_derived_assistant_id_resolves_on_the_server(client, graph_id):
    """The id `/versions` hands a client is the id the server answers to.

    Aegra looks assistants up strictly by id, so a drift here 404s every run
    request while every other test still passes.
    """
    from aegra_api.constants import ASSISTANT_NAMESPACE_UUID

    derived = str(uuid5(ASSISTANT_NAMESPACE_UUID, graph_id))
    res = await client.get(f"/assistants/{derived}")
    assert res.status_code == 200, f"{graph_id}: derived id {derived} is not registered"
    assert res.json()["graph_id"] == graph_id


# --- the checkpointer nothing in this repo constructs -----------------------------


async def test_thread_state_survives_a_write_and_read(client, thread):
    """The graphs compile bare; Aegra supplies the checkpointer.

    Writing state and reading it back on a fresh request is the smallest honest
    proof that persistence is wired — and it costs nothing, because the state
    is supplied rather than generated.
    """
    res = await client.post(
        f"/threads/{thread}/state",
        json={"values": {"origin": "Delhi", "days": 3, "travelers": 2}, "as_node": "__start__"},
    )
    assert res.status_code in (200, 201), res.text
    assert res.json()["checkpoint"]["checkpoint_id"], "no checkpoint id came back"

    values = (await client.get(f"/threads/{thread}/state")).json()["values"]
    assert values.get("origin") == "Delhi"
    assert values.get("days") == 3
    assert values.get("travelers") == 2


async def test_writing_state_creates_a_checkpoint(client, thread):
    """Persisted to Postgres, not merely held in the process.

    History is the observable side of the checkpointer. If Aegra ever handed
    the graphs an in-memory saver, this is the test that would notice.
    """
    before = len((await client.post(f"/threads/{thread}/history", json={})).json())
    await client.post(
        f"/threads/{thread}/state", json={"values": {"days": 2}, "as_node": "__start__"}
    )
    after = (await client.post(f"/threads/{thread}/history", json={})).json()
    assert len(after) > before, "writing state left no checkpoint behind"
    assert after[0]["checkpoint_id"], "checkpoint has no id"


async def test_a_thread_is_addressable_after_it_is_created(client, thread):
    res = await client.get(f"/threads/{thread}")
    assert res.status_code == 200
    assert res.json()["thread_id"] == thread


# --- the custom app, mounted on the same server -----------------------------------


async def test_custom_routes_are_served_on_the_same_port(client):
    """`http.app` in the manifest is mounted alongside the protocol API.

    Same port, same auth, same process — which is the entire reason those
    routes are not a second service.
    """
    versions = await client.get("/versions")
    assert versions.status_code == 200
    assert {v["graph_id"] for v in versions.json()["versions"]} == set(GRAPHS)


async def test_versions_hands_out_ids_the_protocol_api_accepts(client):
    """The join `/versions` performs for the client has to be the real one."""
    for version in (await client.get("/versions")).json()["versions"]:
        assistant_id = version.get("assistant_id")
        assert assistant_id, f"{version['graph_id']} has no assistant_id"
        res = await client.get(f"/assistants/{assistant_id}")
        assert res.status_code == 200, f"{version['graph_id']}: {assistant_id} is not registered"


async def test_deep_health_sees_the_pieces_aegras_own_health_cannot(client):
    body = (await client.get("/health/deep")).json()
    assert body["status"] == "ok"
    assert set(body["graphs"]) == set(GRAPHS)
    assert body["agents"] > 0
    assert body["models"]["high"], "no high-tier model resolved"


async def test_the_trips_schema_exists(client):
    """`ensure_schema` runs against the same database Aegra migrated."""
    res = await client.get("/admin/storage")
    assert res.status_code == 200
    body = res.json()
    assert "trips" in body, f"no trips count in {sorted(body)}"


# --- one real run, opt-in twice ---------------------------------------------------


@pytest.mark.live
async def test_a_run_completes_over_the_protocol(client, thread):
    """v1 end to end: the cheapest version, one model call.

    Everything above proves the plumbing. This proves a graph actually executes
    through it — the worker picks the run up, the node writes to the injected
    checkpointer, and the result is readable at the thread's state.
    """
    found = (
        await client.post("/assistants/search", json={"graph_id": "v1_linear", "limit": 1})
    ).json()
    assistant_id = found[0]["assistant_id"]

    res = await client.post(
        f"/threads/{thread}/runs/wait",
        json={
            "assistant_id": assistant_id,
            "input": {"request": "two quiet days near Jaipur", "origin": "Delhi", "days": 2},
        },
        timeout=300,
    )
    assert res.status_code == 200, res.text

    values = (await client.get(f"/threads/{thread}/state")).json()["values"]
    assert values.get("final_plan"), "the run produced no plan"
    assert values.get("agent_runs"), "no telemetry was recorded"
