"""Settings: environment mapping, tier helpers, and the process-wide cache.

`get_settings()` is `lru_cache`d, so every test that varies the environment
clears the cache on both sides — otherwise a value from one test leaks into
the next through the cached instance rather than through `os.environ`.
"""

import pytest

from travel_planner.core.config import Settings, get_settings

_TIER_ENV = {
    "BEDROCK_MODEL_TIER_HIGH": "env-high",
    "BEDROCK_MODEL_TIER_MID": "env-mid",
    "BEDROCK_MODEL_TIER_LOW": "env-low",
    "BEDROCK_MODEL_FALLBACK": "env-fb",
}


def _settings(**overrides) -> Settings:
    """Build a Settings object from explicit values, ignoring `.env` entirely."""
    values = {
        "bedrock_model_tier_high": "m-high",
        "bedrock_model_tier_mid": "m-mid",
        "bedrock_model_tier_low": "m-low",
        "bedrock_model_fallback": "m-fb",
        "bedrock_max_tokens_high": 4096,
        "bedrock_max_tokens_mid": 2048,
        "bedrock_max_tokens_low": 1024,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def scripted_env(monkeypatch):
    """Point every tier at a sentinel model id and vary a few other tunables."""
    for key, value in _TIER_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("BEDROCK_MAX_TOKENS_LOW", "333")
    monkeypatch.setenv("STRUCTURED_OUTPUT_MAX_REPAIRS", "2")
    monkeypatch.setenv("STRUCTURED_OUTPUT_ESCALATE_TIER", "false")
    monkeypatch.setenv("TRAVEL_MCP_ARGS", "-m travel_mcp.server --verbose")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --- environment mapping ------------------------------------------------------------


def test_settings_reads_model_ids_from_env(scripted_env):
    settings = get_settings()
    assert settings.bedrock_model_tier_high == "env-high"
    assert settings.bedrock_model_tier_mid == "env-mid"
    assert settings.bedrock_model_tier_low == "env-low"
    assert settings.bedrock_model_fallback == "env-fb"


def test_settings_reads_and_coerces_other_env_values(scripted_env):
    settings = get_settings()
    assert settings.bedrock_max_tokens_low == 333
    assert settings.structured_output_max_repairs == 2
    assert settings.structured_output_escalate_tier is False
    assert settings.travel_mcp_args == "-m travel_mcp.server --verbose"


def test_env_overrides_dotenv(scripted_env):
    """Process environment wins over `.env`: the sentinel ids must survive `load_dotenv`."""
    assert get_settings().model_id_for("low") == "env-low"


def test_settings_ignores_unknown_keys():
    """Aegra and Postgres share the `.env`; their keys must not fail validation."""
    settings = _settings(aegra_config="aegra.json", database_url="postgres://x")
    assert not hasattr(settings, "aegra_config")


# --- tier helpers -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("tier", "expected"),
    [
        ("high", "m-high"),
        ("mid", "m-mid"),
        ("low", "m-low"),
        ("fallback", "m-fb"),
    ],
)
def test_model_id_for_maps_every_tier(tier, expected):
    assert _settings().model_id_for(tier) == expected


@pytest.mark.parametrize(
    ("tier", "expected"),
    [
        ("high", 4096),
        ("mid", 2048),
        ("low", 1024),
        ("fallback", 4096),  # fallback is a high-tier substitute, so it gets the high budget
    ],
)
def test_max_tokens_for_maps_every_tier(tier, expected):
    assert _settings().max_tokens_for(tier) == expected


def test_max_tokens_for_fallback_tracks_high_budget():
    settings = _settings(bedrock_max_tokens_high=777)
    assert settings.max_tokens_for("fallback") == 777
    assert settings.max_tokens_for("high") == 777


def test_unknown_tier_raises():
    with pytest.raises(KeyError):
        _settings().model_id_for("ultra")  # type: ignore[arg-type]


# --- travel_mcp_arg_list --------------------------------------------------------------


def test_travel_mcp_arg_list_splits_on_whitespace():
    settings = _settings(travel_mcp_args="-m travel_mcp.server --port 8000")
    assert settings.travel_mcp_arg_list == ["-m", "travel_mcp.server", "--port", "8000"]


def test_travel_mcp_arg_list_collapses_extra_whitespace():
    settings = _settings(travel_mcp_args="  -m   travel_mcp.server\t--flag  ")
    assert settings.travel_mcp_arg_list == ["-m", "travel_mcp.server", "--flag"]


def test_travel_mcp_arg_list_empty_when_unset():
    assert _settings(travel_mcp_args="").travel_mcp_arg_list == []


def test_travel_mcp_arg_list_default():
    assert _settings().travel_mcp_arg_list == ["-m", "travel_mcp.server"]


# --- caching --------------------------------------------------------------------------


def test_get_settings_returns_same_object_twice(scripted_env):
    first = get_settings()
    second = get_settings()
    assert first is second


def test_get_settings_cache_clear_rebuilds(scripted_env, monkeypatch):
    first = get_settings()
    monkeypatch.setenv("BEDROCK_MODEL_TIER_LOW", "env-low-2")
    # Still cached: the environment change is invisible until the cache is cleared.
    assert get_settings() is first
    assert get_settings().bedrock_model_tier_low == "env-low"

    get_settings.cache_clear()
    rebuilt = get_settings()
    assert rebuilt is not first
    assert rebuilt.bedrock_model_tier_low == "env-low-2"
