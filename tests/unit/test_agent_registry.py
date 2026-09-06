"""The agent registry — the contract every version depends on."""

import pytest

from travel_planner.agents import AGENT_REGISTRY, SPECIALIST_NAMES, BaseAgent
from travel_planner.core.state import AgentName, TripState

EXPECTED_TIERS = {
    "orchestrator": "high",
    "review": "high",
    "itinerary": "high",
    "destination": "mid",
    "hotel": "mid",
    "attraction": "mid",
    "budget": "mid",
    "weather": "low",
    "packing": "low",
    "customs": "low",
}


def test_registry_holds_exactly_the_ten_agents():
    assert set(AGENT_REGISTRY) == set(EXPECTED_TIERS)


@pytest.mark.parametrize("name", sorted(EXPECTED_TIERS))
def test_agent_contract(name):
    cls = AGENT_REGISTRY[name]
    assert issubclass(cls, BaseAgent)
    assert cls.name == name, "the registry key must be the class's own name"
    assert cls.tier == EXPECTED_TIERS[name]
    assert cls.state_key in TripState.__optional_keys__
    assert cls.system_prompt and len(cls.system_prompt) > 200, "prompt looks like a placeholder"


@pytest.mark.parametrize("name", sorted(EXPECTED_TIERS))
def test_agent_builds_messages_from_empty_state(name):
    """Every agent must survive a state where nothing upstream has run."""
    agent = AGENT_REGISTRY[name]()
    messages = agent.messages({})
    assert len(messages) == 2
    assert messages[0].type == "system" and messages[1].type == "human"
    assert messages[1].content.strip()


@pytest.mark.parametrize("name", sorted(EXPECTED_TIERS))
def test_to_update_targets_the_declared_key(name):
    cls = AGENT_REGISTRY[name]
    sentinel = object()
    assert cls().to_update(sentinel) == {cls.state_key: sentinel}


def test_specialist_names_are_the_orchestrators_valid_targets():
    """The orchestrator's schema and the re-runnable set must not drift apart."""
    from typing import get_args

    assert set(SPECIALIST_NAMES) == set(get_args(AgentName))
    assert "review" not in SPECIALIST_NAMES
    assert "orchestrator" not in SPECIALIST_NAMES


def test_every_specialist_is_registered():
    assert set(SPECIALIST_NAMES) <= set(AGENT_REGISTRY)


def test_state_keys_are_unique_except_where_shared_by_design():
    keys = [cls.state_key for cls in AGENT_REGISTRY.values()]
    assert len(keys) == len(set(keys)), "two agents writing one key would race in the fan-out"
