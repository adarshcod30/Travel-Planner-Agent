"""MCP connection construction and the toolset's degradation behaviour."""

import pytest

from travel_planner.core.config import Settings, get_settings
from travel_planner.tools.mcp.browser import (
    BLOCK_SIGNALS,
    BlockedError,
    browse_with_fallback,
    looks_blocked,
    mcp_text,
)
from travel_planner.tools.mcp.client import McpToolset, build_connections


def _settings(**overrides) -> Settings:
    return Settings(**{**get_settings().model_dump(), **overrides})


# --- connections ----------------------------------------------------------------


def test_all_four_servers_are_configured_by_default():
    conns = build_connections(_settings())
    assert set(conns) == {"playwright", "filesystem", "fetch", "travel"}
    assert all(c["transport"] == "stdio" for c in conns.values())


def test_enabled_servers_is_honoured():
    assert set(build_connections(_settings(mcp_enabled_servers="travel"))) == {"travel"}


def test_http_mode_switches_playwright_transport_only():
    conns = build_connections(_settings(mcp_mode="http"))
    assert conns["playwright"]["transport"] == "streamable_http"
    assert conns["playwright"]["url"].startswith("http")
    assert conns["travel"]["transport"] == "stdio"


def test_headless_flag_is_appended_once():
    args = _settings(playwright_mcp_headless=True).playwright_mcp_arg_list
    assert args.count("--headless") == 1
    assert "--headless" not in _settings(playwright_mcp_headless=False).playwright_mcp_arg_list


def test_filesystem_sandbox_root_is_passed_as_the_last_argument():
    args = _settings(filesystem_mcp_root="/tmp/sandbox").filesystem_mcp_arg_list
    assert args[-1] == "/tmp/sandbox"


def test_travel_server_uses_this_interpreter():
    """`python` on PATH is not necessarily the venv's python."""
    import sys

    assert (
        build_connections(_settings(mcp_enabled_servers="travel"))["travel"]["command"]
        == sys.executable
    )


def test_unknown_server_name_is_dropped_not_fatal():
    assert build_connections(_settings(mcp_enabled_servers="travel,nonsense")).keys() == {"travel"}


def test_missing_launcher_is_dropped():
    conns = build_connections(
        _settings(mcp_enabled_servers="fetch", fetch_mcp_command="definitely-not-installed-xyz")
    )
    assert conns == {}


# --- toolset --------------------------------------------------------------------


def test_toolset_get_matches_exact_then_suffix():
    class T:
        def __init__(self, name):
            self.name = name

    ts = McpToolset()
    ts.tools = {"browser_navigate": T("browser_navigate"), "travel__convert_currency": T("x")}
    assert ts.get("browser_navigate").name == "browser_navigate"
    assert ts.get("convert_currency") is not None, "suffix match for namespaced tools"
    assert ts.get("nope") is None
    assert ts.get("nope", "browser_navigate") is not None


def test_empty_toolset_is_falsy_by_length():
    assert len(McpToolset()) == 0


# --- browser helpers ------------------------------------------------------------


@pytest.mark.parametrize("signal", BLOCK_SIGNALS)
def test_every_block_signal_is_detected(signal):
    assert looks_blocked(f"Sorry — {signal.upper()} — please try again")


def test_error_pages_are_detected():
    assert looks_blocked("### Error: navigation failed")
    assert not looks_blocked("Kyoto travel guide: temples, food and autumn colour")


def test_mcp_text_flattens_content_blocks():
    assert mcp_text([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]) == "a\nb"
    assert mcp_text("plain") == "plain"
    assert mcp_text([1, 2]) == "1\n2"


class _FakeTool:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    async def ainvoke(self, args):
        self.calls.append(args)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _toolset(nav_outcomes, snap_outcomes):
    ts = McpToolset()
    ts.tools = {
        "browser_navigate": _FakeTool(nav_outcomes),
        "browser_snapshot": _FakeTool(snap_outcomes),
    }
    return ts


async def test_primary_success_reports_no_fallback():
    ts = _toolset(["ok"], ["Kyoto travel guide with temples"])
    r = await browse_with_fallback(
        ts, primary_url="https://a", fallback_url="https://b", primary_label="google"
    )
    assert r["ok"] and r["fallback_used"] is False and r["source_used"] == "google"


async def test_block_triggers_the_fallback_and_says_so():
    ts = _toolset(["ok", "ok"], ["please verify you are a human", "real results here"])
    r = await browse_with_fallback(
        ts, primary_url="https://a", fallback_url="https://b", primary_label="google"
    )
    assert r["ok"] and r["fallback_used"] is True and r["source_used"] == "duckduckgo"
    assert "real results" in r["content_excerpt"]


async def test_transport_error_also_triggers_the_fallback():
    ts = _toolset([RuntimeError("connection reset"), "ok"], ["real results"])
    r = await browse_with_fallback(
        ts, primary_url="https://a", fallback_url="https://b", primary_label="booking.com"
    )
    assert r["ok"] and r["fallback_used"] is True


async def test_both_paths_failing_degrades_rather_than_raises():
    ts = _toolset([RuntimeError("x"), RuntimeError("y")], [])
    r = await browse_with_fallback(
        ts, primary_url="https://a", fallback_url="https://b", primary_label="google"
    )
    assert r["ok"] is False and "error" in r and r["content_excerpt"] == ""


async def test_missing_browser_tools_degrade_rather_than_raise():
    r = await browse_with_fallback(
        McpToolset(), primary_url="https://a", fallback_url="https://b", primary_label="g"
    )
    assert r["ok"] is False
    assert BlockedError  # referenced so the import is meaningful to a reader
