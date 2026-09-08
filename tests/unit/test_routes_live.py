"""The HTTP surface for a live browser, and for finished trips.

The handover routes point at a real Chromium held open inside a running node,
so what matters is that they are precise about *which* failure happened: a
thread that never had a handover, a moment that has passed, and an instruction
that was never valid are three different answers and a client behaves
differently for each.
"""

import pytest
from fastapi.testclient import TestClient

from travel_planner.routes.custom import app
from travel_planner.tools.mcp import control, handover


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_leaked_handovers():
    yield
    handover._open.clear()


# --- nothing waiting ------------------------------------------------------------


def test_no_handovers_is_an_empty_list_not_an_error(client):
    r = client.get("/handover")
    assert r.status_code == 200
    assert r.json() == {"waiting": [], "count": 0}


def test_reading_a_handover_that_does_not_exist_is_a_404(client):
    assert client.get("/handover/nope").status_code == 404


def test_driving_a_browser_that_has_moved_on_is_a_409(client):
    """404 would say the thread never existed. 409 says the moment passed,
    which is what actually happened and what a client should retry against."""
    r = client.post("/handover/nope/action", json={"kind": "press", "key": "Enter"})
    assert r.status_code == 409
    assert "no handover is open" in r.json()["detail"]


def test_releasing_nothing_is_honest_rather_than_an_error(client):
    assert client.post("/handover/nope/release").json() == {"released": False}


# --- one waiting ----------------------------------------------------------------


@pytest.fixture
def open_handover():
    h = handover._open_handover("t-live", "login", "https://x.test/login", "sign in please")
    h.page = {
        "url": "https://x.test/login",
        "title": "Sign in",
        "elements": [{"ref": "e2", "role": "textbox", "name": "Email"}],
    }
    return h


def test_a_waiting_handover_describes_the_page(client, open_handover):
    body = client.get("/handover/t-live").json()
    assert body["reason"] == "login"
    assert body["url"] == "https://x.test/login"
    assert body["terminal"] is False
    # So a client can offer buttons without driving the browser itself.
    assert body["elements"][0]["name"] == "Email"


def test_a_payment_handover_says_it_is_terminal(client):
    handover._open_handover("t-pay", "payment", None, "")
    assert client.get("/handover/t-pay").json()["terminal"] is True


def test_it_appears_in_the_list(client, open_handover):
    body = client.get("/handover").json()
    assert body["count"] == 1 and body["waiting"][0]["thread_id"] == "t-live"


def test_an_invalid_instruction_is_refused_before_the_browser_sees_it(client, open_handover):
    """422, not 409: the handover is open and ready — the instruction is the
    thing that was wrong."""
    r = client.post("/handover/t-live/action", json={"kind": "launch_missiles"})
    assert r.status_code == 422
    assert "unknown action" in r.json()["detail"]


def test_the_action_set_the_route_accepts_matches_the_one_that_runs(client):
    """The route model and `control.Action` are written separately, so this is
    the test that stops them drifting apart and rejecting something valid."""
    from travel_planner.routes.custom import HandoverAction

    allowed = set(control.Action.__dataclass_fields__) - {"kind"}
    assert set(HandoverAction.model_fields) - {"kind"} == allowed


def test_releasing_wakes_the_run(client, open_handover):
    assert client.post("/handover/t-live/release").json() == {"released": True}
    assert open_handover.released.is_set()


# --- trips ----------------------------------------------------------------------


def test_a_missing_trip_is_a_404(client, monkeypatch):
    async def none(trip_id, owner="local-dev"):
        return None

    monkeypatch.setattr("travel_planner.routes.custom.get_trip", none)
    assert client.get("/trips/00000000-0000-0000-0000-000000000000").status_code == 404


def test_the_trip_list_is_shaped_for_the_history_view(client, monkeypatch):
    async def two(limit=50, owner="local-dev"):
        return [{"trip_id": "a", "destination": "Jaipur"}, {"trip_id": "b", "destination": "Goa"}]

    monkeypatch.setattr("travel_planner.routes.custom.list_trips", two)
    body = client.get("/trips").json()
    assert body["count"] == 2
    assert [t["destination"] for t in body["trips"]] == ["Jaipur", "Goa"]


def test_completing_a_trip_is_not_confused_with_fetching_one(client, monkeypatch):
    """`/trips/complete` is a POST and `/trips/{id}` is a GET, declared in that
    order. Getting the order or the methods wrong would route an archive
    request into the lookup."""
    seen = {}

    async def complete(thread_id, graph_id, state, owner="local-dev"):
        seen["thread_id"] = thread_id
        return {"archived": True, "purged": True}

    monkeypatch.setattr("travel_planner.routes.custom.complete_trip", complete)
    r = client.post(
        "/trips/complete",
        json={"thread_id": "t-1", "graph_id": "v5_mcp", "state": {"final_plan": "# x"}},
    )
    assert r.status_code == 200
    assert seen["thread_id"] == "t-1"
