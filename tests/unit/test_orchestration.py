"""The orchestration machinery shared by v3, v4 and v5, tested in isolation."""

import pytest
from langgraph.graph import END

from travel_planner.core.state import AgentError
from travel_planner.versions import orchestration as orch
from travel_planner.versions.orchestration import (
    FANOUT,
    human_gate_node,
    make_orchestrator_node,
    parse_resume,
    rerun_aware,
    route_after_human_gate,
    route_after_orchestrator,
    route_after_review,
)

from .fakes import APPROVED, NEEDS_REVISION, decision

# --- parse_resume ---------------------------------------------------------------


@pytest.mark.parametrize(
    "payload,expected",
    [
        ([{"type": "accept", "args": None}], ("accept", None)),
        ({"type": "edit", "args": {"final_plan": "x"}}, ("edit", {"final_plan": "x"})),
        ("ignore", ("ignore", None)),
        ([{"type": "RESPONSE", "args": "more temples"}], ("response", "more temples")),
    ],
)
def test_parse_resume_accepts_documented_shapes(payload, expected):
    assert parse_resume(payload) == expected


@pytest.mark.parametrize("payload", [[], {}, {"args": 1}, [{"type": "approve"}], 42])
def test_parse_resume_rejects_garbage(payload):
    with pytest.raises(ValueError):
        parse_resume(payload)


# --- rerun_aware ----------------------------------------------------------------


class _Stub:
    def __init__(self, name):
        self.name = name
        self.calls = 0

    def __call__(self, state):
        self.calls += 1
        return {"ran": self.name}


def test_initial_pass_runs_everyone():
    stub = _Stub("weather")
    assert rerun_aware(stub)({}) == {"ran": "weather"}
    assert stub.calls == 1


def test_revision_skips_unnamed_agent():
    stub = _Stub("weather")
    state = {"orchestrator_decision": decision("hotel")}
    assert rerun_aware(stub)(state) == {}
    assert stub.calls == 0


def test_revision_runs_named_agent():
    stub = _Stub("hotel")
    assert rerun_aware(stub)({"orchestrator_decision": decision("hotel")}) == {"ran": "hotel"}


def test_revision_runs_dependents_of_named_agent():
    """packing consumes weather, so re-running weather must re-run packing."""
    packing = _Stub("packing")
    assert rerun_aware(packing)({"orchestrator_decision": decision("weather")}) == {
        "ran": "packing"
    }
    hotel = _Stub("hotel")
    assert rerun_aware(hotel)({"orchestrator_decision": decision("budget")}) == {"ran": "hotel"}


def test_new_destination_reruns_everyone():
    for name in ("weather", "customs", "packing", "hotel"):
        stub = _Stub(name)
        assert rerun_aware(stub)({"orchestrator_decision": decision("destination")}) == {
            "ran": name
        }


def test_wrapper_keeps_agent_name():
    assert rerun_aware(_Stub("budget")).__name__ == "budget"


# --- orchestrator node ----------------------------------------------------------


def _patch_orchestrator_agent(monkeypatch, outcome):
    """Replace OrchestratorAgent with one whose safe_run returns `outcome`."""

    class Fake:
        def safe_run(self, state):
            return dict(outcome)

    monkeypatch.setattr(orch, "OrchestratorAgent", Fake)


def test_orchestrator_node_increments_iteration(monkeypatch):
    _patch_orchestrator_agent(monkeypatch, {"orchestrator_decision": decision("hotel")})
    node = make_orchestrator_node(max_iterations=3)
    out = node({"iteration": 0})
    assert out["iteration"] == 1
    assert out["orchestrator_decision"].agents_to_rerun == ["hotel"]


def test_orchestrator_node_enforces_ceiling(monkeypatch):
    calls = []

    class Fake:
        def safe_run(self, state):
            calls.append(1)
            return {"orchestrator_decision": decision("hotel")}

    monkeypatch.setattr(orch, "OrchestratorAgent", Fake)
    node = make_orchestrator_node(max_iterations=2)
    out = node({"iteration": 2})  # third call
    assert out["iteration"] == 3
    assert out["orchestrator_decision"].agents_to_rerun == []
    assert "limit" in out["orchestrator_decision"].reasoning
    assert calls == [], "the model must not be called past the ceiling"


def test_orchestrator_failure_does_not_loop(monkeypatch):
    _patch_orchestrator_agent(
        monkeypatch,
        {
            "errors": [
                AgentError(agent="orchestrator", error_type="StructuredOutputError", message="x")
            ]
        },
    )
    out = make_orchestrator_node(max_iterations=3)({"iteration": 0})
    assert out["orchestrator_decision"].agents_to_rerun == []
    assert out["errors"][0].agent == "orchestrator"


# --- routers --------------------------------------------------------------------


def test_route_after_review():
    assert route_after_review({}) == "finalize"
    assert route_after_review({"review": APPROVED}) == "finalize"
    assert route_after_review({"review": NEEDS_REVISION}) == "orchestrator"


def test_route_after_orchestrator():
    assert route_after_orchestrator({}) == "finalize"
    assert route_after_orchestrator({"orchestrator_decision": decision()}) == "finalize"
    assert (
        route_after_orchestrator({"orchestrator_decision": decision("destination", "hotel")})
        == "destination"
    )
    assert route_after_orchestrator({"orchestrator_decision": decision("hotel")}) == list(FANOUT)


def test_route_after_human_gate():
    assert route_after_human_gate({"human_decision": "accept"}) == "finalize"
    assert route_after_human_gate({"human_decision": "response"}) == "orchestrator"
    assert route_after_human_gate({"human_decision": "edit"}) == END
    assert route_after_human_gate({"human_decision": "ignore"}) == END
    with pytest.raises(ValueError):
        route_after_human_gate({})


# --- human gate -----------------------------------------------------------------


def _gate_with(monkeypatch, resume_payload):
    captured = {}

    def fake_interrupt(payload):
        captured["payload"] = payload
        return resume_payload

    monkeypatch.setattr(orch, "interrupt", fake_interrupt)
    return captured


def test_gate_payload_carries_draft_and_review(monkeypatch):
    captured = _gate_with(monkeypatch, [{"type": "accept", "args": None}])
    state = {"review": NEEDS_REVISION, "iteration": 1, "days": 2}
    out = human_gate_node(state)
    p = captured["payload"]
    assert p["type"] == "plan_review"
    assert p["iteration"] == 1
    assert p["draft"].startswith("# Travel Plan")
    assert p["review"]["verdict"] == "needs_revision"
    assert set(p["config"]) == {"allow_accept", "allow_edit", "allow_respond", "allow_ignore"}
    assert out == {"human_decision": "accept"}


def test_gate_edit_sets_final_plan(monkeypatch):
    _gate_with(monkeypatch, {"type": "edit", "args": {"final_plan": "# Mine"}})
    assert human_gate_node({}) == {"human_decision": "edit", "final_plan": "# Mine"}


def test_gate_edit_requires_text(monkeypatch):
    _gate_with(monkeypatch, {"type": "edit", "args": {}})
    with pytest.raises(ValueError):
        human_gate_node({})


def test_gate_response_sets_feedback(monkeypatch):
    _gate_with(monkeypatch, {"type": "response", "args": "  more temples "})
    assert human_gate_node({}) == {"human_decision": "response", "human_feedback": "more temples"}
    _gate_with(monkeypatch, {"type": "response", "args": {"feedback": "cheaper"}})
    assert human_gate_node({})["human_feedback"] == "cheaper"


def test_gate_response_requires_text(monkeypatch):
    _gate_with(monkeypatch, {"type": "response", "args": ""})
    with pytest.raises(ValueError):
        human_gate_node({})


def test_gate_ignore_clears_plan(monkeypatch):
    _gate_with(monkeypatch, "ignore")
    assert human_gate_node({"final_plan": "old"}) == {
        "human_decision": "ignore",
        "final_plan": None,
    }
