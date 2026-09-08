"""Shared fixtures for the tests that need a real server.

Everything here is skipped, not failed, when there is nothing to talk to. An
integration suite that fails on a laptop with no Postgres teaches people to
ignore it.
"""

import os

import httpx
import pytest

BASE_URL = os.getenv("AEGRA_URL", "http://127.0.0.1:2026")
TOKEN = os.getenv("AEGRA_API_TOKEN", "local-dev")
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


def _server_is_up() -> bool:
    try:
        return httpx.get(f"{BASE_URL}/info", headers=HEADERS, timeout=3).status_code == 200
    except Exception:
        return False


@pytest.fixture(scope="session")
def base_url() -> str:
    if not _server_is_up():
        pytest.skip(f"no Aegra server at {BASE_URL} — start one with ./scripts/run_all.sh")
    return BASE_URL


@pytest.fixture
async def client(base_url):
    async with httpx.AsyncClient(base_url=base_url, headers=HEADERS, timeout=120) as c:
        yield c


@pytest.fixture
async def thread(client):
    """A thread bound to a graph, which cleans up after itself.

    The `graph_id` in metadata is what lets state be written without first
    running anything: Aegra needs to know whose state schema to validate
    against, and a thread with no runs has no graph associated. Binding it here
    is what keeps this suite free of model calls.
    """
    created = (await client.post("/threads", json={"metadata": {"graph_id": "v1_linear"}})).json()[
        "thread_id"
    ]
    yield created
    await client.delete(f"/threads/{created}")
