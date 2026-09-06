"""Invariants on the shared state schema.

These guard against a class of silent failure that has bitten this design
before: a state key that is required when it should be optional does not raise
at import time — it surfaces as an opaque Pydantic "Field required" error deep
inside a tool call, on the first run that omits the key.
"""

import operator

from pydantic import TypeAdapter

from travel_planner.core import state as state_mod
from travel_planner.core.state import AgentRun, TripState


def test_every_state_key_is_optional():
    """No key may be required: a caller posts a trip request, nothing more."""
    assert TripState.__required_keys__ == frozenset(), sorted(TripState.__required_keys__)
    assert len(TripState.__optional_keys__) > 20


def test_pydantic_accepts_minimal_state():
    """The exact failure mode: an early node receives state with most keys absent."""
    TypeAdapter(TripState).validate_python({"request": "beach trip", "days": 3})


def test_pydantic_accepts_empty_state():
    TypeAdapter(TripState).validate_python({})


def test_state_module_has_no_future_annotations():
    """`from __future__ import annotations` silently neutralises NotRequired.

    Verified directly: with the import present, every key lands in
    __required_keys__ regardless of the NotRequired wrapper. This test makes
    re-adding it a CI failure rather than a runtime surprise.
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(state_mod))
    future_imports = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "__future__"
        for alias in node.names
    ]
    assert "annotations" not in future_imports


def test_reducer_fields_survive_not_required():
    """Reducer metadata must be visible through the NotRequired wrapper."""
    from typing import get_args, get_origin, get_type_hints

    hints = get_type_hints(TripState, include_extras=True)
    for key in ("agent_runs", "errors"):
        outer = hints[key]
        # include_extras keeps the NotRequired wrapper; unwrap it to reach Annotated.
        assert get_origin(outer).__name__ == "NotRequired", key
        (inner,) = get_args(outer)
        assert get_origin(inner).__name__ == "Annotated", key
        _, reducer = get_args(inner)
        assert reducer is operator.add, key


def test_orchestrator_agent_names_are_constrained():
    """A hallucinated agent name must fail validation, not route nowhere."""
    import pytest
    from pydantic import ValidationError

    from travel_planner.core.state import OrchestratorDecision

    OrchestratorDecision(agents_to_rerun=["weather", "hotel"], reasoning="ok")
    with pytest.raises(ValidationError):
        OrchestratorDecision(agents_to_rerun=["flights"], reasoning="no such agent")


def test_agent_run_defaults():
    run = AgentRun(agent="x", model_id="m", tier="low", duration_ms=1)
    assert run.repairs == 0 and run.escalated is False
