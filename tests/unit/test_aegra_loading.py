"""What Aegra does with `aegra.json`, as opposed to what the file says.

`test_aegra_config.py` reads the manifest and checks that every path in it
resolves. That is a test of the file. This is a test of the *server*: it drives
Aegra's own loader over this project's manifest and asserts what the loader
ends up holding.

The gap between the two is where v5 lives. The manifest says `v5_mcp` points at
`make_graph` rather than `graph`, and a reader can confirm that; only the loader
can tell you that Aegra therefore treats it as a factory, keeps the callable
without calling it, and rebuilds the graph per request. That behaviour is what
gives v5 per-run browser and MCP lifetime, and nothing else in the suite touches
it.

**These bind to Aegra's internals on purpose.** `_base_graph_cache` and
`_graph_factories` are private, and an upgrade that renames them will fail these
tests. That is the intent: the behaviour they protect is not observable without
a running server, and an Aegra upgrade that quietly started caching factories
would break v5 in a way that looks like a browser bug three layers down. A
failing test on upgrade is the cheapest possible version of that discovery.

Hermetic: no database, no network, no credentials. The loader touches the
database only when registering default assistants, which is a later step than
anything here.
"""

import json
from pathlib import Path
from uuid import UUID, uuid5

import pytest

from travel_planner.routes.custom import assistant_id_for

ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / "aegra.json").read_text())
GRAPHS: list[str] = list(CONFIG["graphs"])

#: v1-v4 register a compiled graph; v5 registers a factory. The whole point.
STATIC = ("v1_linear", "v2_parallel", "v3_orchestrator", "v4_hitl")
FACTORY = ("v5_mcp",)


@pytest.fixture(scope="module")
async def loaded():
    """Aegra's loader, run over this project's manifest, stopped before the DB.

    `initialize()` would go on to register default assistants, which needs
    Postgres. These three calls are exactly the prefix of it that loads graphs.
    """
    from aegra_api.services.langgraph_service import LangGraphService

    svc = LangGraphService()
    svc.config_path = ROOT / "aegra.json"
    svc.config = CONFIG
    svc._setup_dependencies()
    svc._load_graph_registry()
    await svc._load_all_graph_modules()
    return svc


async def test_every_declared_graph_is_loaded(loaded):
    """Nothing in the manifest is silently skipped."""
    held = set(loaded._base_graph_cache) | set(loaded._graph_factories)
    assert held == set(GRAPHS), f"declared {set(GRAPHS)}, loaded {held}"


@pytest.mark.parametrize("graph_id", STATIC)
async def test_static_graphs_are_compiled_once_and_cached(loaded, graph_id):
    """v1-v4 exist as compiled graphs before any request arrives."""
    assert graph_id in loaded._base_graph_cache
    assert graph_id not in loaded._graph_factories
    assert loaded._base_graph_cache[graph_id].nodes, "a compiled graph with no nodes"


@pytest.mark.parametrize("graph_id", FACTORY)
async def test_the_factory_graph_is_held_uncalled(loaded, graph_id):
    """v5 must NOT be compiled at boot.

    Aegra calls a factory per request so it can pass the caller's config. If it
    were cached like a static graph, every run would share one graph built with
    `user=None` — and, worse here, one MCP session and one browser opened at
    server start rather than per run.
    """
    assert graph_id in loaded._graph_factories
    assert graph_id not in loaded._base_graph_cache, (
        "the factory was compiled at load time; v5's per-run browser lifetime depends on it not being"
    )
    assert callable(loaded._graph_factories[graph_id])


async def test_the_five_topologies_actually_differ(loaded):
    """Cumulative versions: each is at least as large as the one before it.

    A copy-paste that left two versions pointing at the same builder would pass
    every other test in this file.
    """
    sizes = {g: len(loaded._base_graph_cache[g].nodes) for g in STATIC}
    ordered = [sizes[g] for g in STATIC]
    assert ordered == sorted(ordered), f"versions are not cumulative: {sizes}"
    assert len(set(ordered)) == len(ordered), f"two versions have identical node counts: {sizes}"


@pytest.mark.parametrize("graph_id", GRAPHS)
def test_assistant_ids_match_aegras_own_derivation(graph_id):
    """`/versions` hands clients an assistant_id it computes itself.

    Aegra looks assistants up strictly by id — `graph_id` is only a name — so if
    this derivation drifts from Aegra's, every run request 404s. Recomputed here
    from Aegra's namespace constant rather than from the same helper, so the two
    are compared rather than one being asserted against itself.
    """
    from aegra_api.constants import ASSISTANT_NAMESPACE_UUID

    assert assistant_id_for(graph_id) == str(uuid5(ASSISTANT_NAMESPACE_UUID, graph_id))
    UUID(assistant_id_for(graph_id))  # parses as a uuid


def test_the_namespace_fallback_matches_the_real_constant():
    """custom.py falls back to a literal namespace if Aegra's import moves.

    A stale fallback would be invisible: it is only reached when the import
    fails, and then every assistant id would be wrong at once.
    """
    from aegra_api.constants import ASSISTANT_NAMESPACE_UUID

    import travel_planner.routes.custom as custom

    assert custom._NS == ASSISTANT_NAMESPACE_UUID
