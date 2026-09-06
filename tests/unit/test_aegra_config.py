"""aegra.json — the wiring that nothing else type-checks.

Every value in this file is a string path resolved by Aegra at startup. A typo
in one is invisible to the linter, to mypy and to every other test: the failure
surfaces only when the server boots, and for the auth path it surfaces as a
server that starts and then behaves subtly differently.

These tests import each target the way Aegra does, so a broken path fails here
instead of on a deploy.
"""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONFIG = json.loads((ROOT / "aegra.json").read_text())

EXPECTED_GRAPHS = {"v1_linear", "v2_parallel", "v3_orchestrator", "v4_hitl", "v5_mcp"}


def _load(spec: str):
    """Resolve a `./path/to/file.py:name` reference the way Aegra does."""
    file_part, _, export = spec.partition(":")
    path = (ROOT / file_part).resolve()
    assert path.is_file(), f"{spec} → missing file {path}"
    module_spec = importlib.util.spec_from_file_location(f"aegra_cfg_{path.stem}", path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    assert hasattr(module, export), f"{spec} → {path.name} has no attribute {export!r}"
    return getattr(module, export)


def test_declares_exactly_the_five_graphs():
    assert set(CONFIG["graphs"]) == EXPECTED_GRAPHS


@pytest.mark.parametrize("graph_id", sorted(EXPECTED_GRAPHS))
def test_every_graph_path_resolves(graph_id):
    obj = _load(CONFIG["graphs"][graph_id])
    assert obj is not None


def test_v5_is_a_factory_and_the_rest_are_compiled():
    """Only v5 may be a callable: Aegra invokes factories per request.

    If v5 were exported compiled, its MCP sessions would be built once at
    startup and shared across every concurrent run. If v1-v4 were factories,
    they would be rebuilt on every request for no benefit.
    """
    assert callable(_load(CONFIG["graphs"]["v5_mcp"])), "v5 must export a factory"
    for graph_id in EXPECTED_GRAPHS - {"v5_mcp"}:
        assert not callable(_load(CONFIG["graphs"][graph_id])), (
            f"{graph_id} must export a compiled graph"
        )


def test_auth_path_resolves_to_an_auth_object():
    auth = _load(CONFIG["auth"]["path"])
    assert hasattr(auth, "authenticate"), "the auth export must be a langgraph_sdk Auth instance"


def test_custom_routes_path_resolves_to_an_app():
    app = _load(CONFIG["http"]["app"])
    paths = {r.path for r in app.routes}
    assert {"/versions", "/agents", "/health/deep"} <= paths


def test_dependencies_exist():
    for dep in CONFIG.get("dependencies", []):
        assert (ROOT / dep).is_dir(), f"dependency path {dep} does not exist"


def test_cors_does_not_use_a_wildcard_with_credentials():
    """`allow_origins: ["*"]` plus credentials is rejected by browsers anyway."""
    cors = CONFIG.get("http", {}).get("cors", {})
    if cors.get("allow_credentials"):
        assert "*" not in cors.get("allow_origins", []), (
            "wildcard origin cannot be combined with credentials"
        )
