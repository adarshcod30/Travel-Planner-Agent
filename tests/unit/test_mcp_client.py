"""MCP connection construction and the toolset's degradation behaviour."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from travel_planner.core.config import Settings, get_settings
from travel_planner.tools.mcp.browser import (
    BLOCK_SIGNALS,
    BlockedError,
    browse_chain,
    looks_blocked,
    mcp_text,
    research_destination,
    research_hotels,
    snapshot_body,
)
from travel_planner.tools.mcp.client import McpToolset, browser_capacity, build_connections


async def _async_value(v):
    return v


def _settings(**overrides) -> Settings:
    return Settings(**{**get_settings().model_dump(), **overrides})


# --- connections ----------------------------------------------------------------


def test_default_servers_are_configured():
    conns = build_connections(_settings())
    assert set(conns) == {"playwright", "fetch", "travel", "tavily"}


def test_tavily_is_remote_not_a_subprocess():
    """Tavily is hosted: an HTTPS endpoint, no launcher, nothing spawned."""
    conns = build_connections(_settings(mcp_enabled_servers="tavily", tavily_api_key="k"))
    assert conns["tavily"]["transport"] == "streamable_http"
    assert conns["tavily"]["url"].startswith("https://mcp.tavily.com/")


def test_tavily_is_skipped_without_a_key():
    """An unset key must drop the server, not produce a URL ending in '='."""
    assert build_connections(_settings(mcp_enabled_servers="tavily", tavily_api_key="")) == {}


def test_redact_hides_the_key_from_anything_loggable():
    """Tavily carries its key in the query string, so a raw connection in a log
    line or an error message would leak it."""
    from travel_planner.tools.mcp.client import redact

    conn = build_connections(_settings(mcp_enabled_servers="tavily", tavily_api_key="tvly-secret"))[
        "tavily"
    ]
    assert "tvly-secret" in conn["url"], "precondition: the real URL carries the key"
    assert "tvly-secret" not in str(redact(conn))
    assert redact(conn)["url"].endswith("?<redacted>")


def test_http_client_logging_is_suppressed():
    """httpx logs every request URL at INFO. With Tavily's key in the query
    string that writes the credential to the server log on every call."""
    import logging

    from travel_planner.core.logging import configure_logging

    configure_logging()
    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).level >= logging.WARNING, name


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


def _page(body: str) -> str:
    """A Playwright-shaped snapshot with `body` as the accessibility tree."""
    return "### Page - Page URL: https://x ### Snapshot ```yaml\n" + body + "\n```"


REAL_PAGE = _page("\n".join(f'  - link "result {i}" [ref=e{i}]' for i in range(40)))


def _toolset(nav_outcomes, snap_outcomes):
    ts = McpToolset()
    ts.tools = {
        "browser_navigate": _FakeTool(nav_outcomes),
        "browser_snapshot": _FakeTool(snap_outcomes),
    }
    return ts


CHAIN = [("primary", "https://a"), ("second", "https://b"), ("third", "https://c")]


async def test_first_target_wins():
    ts = _toolset(["ok"], [REAL_PAGE])
    r = await browse_chain(ts, CHAIN)
    assert r["ok"] and r["fallback_used"] is False and r["source_used"] == "primary"
    assert r["attempts"] == []


async def test_block_advances_the_chain_and_records_it():
    ts = _toolset(["ok", "ok"], [_page("please verify you are a human"), REAL_PAGE])
    r = await browse_chain(ts, CHAIN)
    assert r["ok"] and r["fallback_used"] and r["source_used"] == "second"
    assert r["attempts"] == [{"target": "primary", "outcome": "blocked"}]


async def test_empty_page_is_treated_as_a_block():
    """A real URL with an empty tree: HTTP 200, nothing rendered."""
    ts = _toolset(["ok", "ok"], [_page("  "), REAL_PAGE])
    r = await browse_chain(ts, CHAIN)
    assert r["source_used"] == "second"
    assert r["attempts"][0]["outcome"] == "blocked"


async def test_about_blank_is_treated_as_a_block():
    ts = _toolset(
        ["ok", "ok"], ["### Page - Page URL: about:blank ### Snapshot ```yaml  ```", REAL_PAGE]
    )
    r = await browse_chain(ts, CHAIN)
    assert r["source_used"] == "second"


async def test_transport_error_advances_the_chain():
    ts = _toolset([RuntimeError("connection reset"), "ok"], [REAL_PAGE])
    r = await browse_chain(ts, CHAIN)
    assert r["ok"] and r["source_used"] == "second"
    assert "RuntimeError" in r["attempts"][0]["outcome"]


async def test_every_target_failing_degrades_rather_than_raises():
    ts = _toolset(["ok"] * 3, [_page("captcha")] * 3)
    r = await browse_chain(ts, CHAIN)
    assert r["ok"] is False and r["content_excerpt"] == ""
    assert [a["target"] for a in r["attempts"]] == ["primary", "second", "third"]


async def test_missing_browser_tools_degrade_rather_than_raise():
    r = await browse_chain(McpToolset(), CHAIN)
    assert r["ok"] is False
    assert BlockedError  # referenced so the import is meaningful to a reader


async def test_destination_chain_leads_with_wikivoyage():
    ts = _toolset(["ok"], [REAL_PAGE])
    r = await research_destination(ts, "Kyoto", "temples")
    assert r["source_used"] == "wikivoyage"
    assert "wikivoyage.org/wiki/Kyoto" in r["url_used"]


async def test_hotel_chain_leads_with_booking():
    ts = _toolset(["ok"], [REAL_PAGE])
    r = await research_hotels(ts, "Kyoto, Japan", 3, "mid-range", 2)
    assert r["source_used"] == "booking.com"
    assert "booking.com" in r["url_used"]


def test_snapshot_body_strips_the_envelope():
    assert snapshot_body(_page('  - link "a"')) == '- link "a"'
    assert snapshot_body("no envelope here") == "no envelope here"


# --- browser concurrency cap -----------------------------------------------------
#
# Aegra's queue — Redis or LocalExecutor — limits concurrent *runs*. It cannot
# limit browsers, because v1-v4 launch none and v5 launches one per run. A run
# limit low enough to protect memory would throttle the cheap versions; one high
# enough for them would let browsers pile up. Hence a separate cap on the scarce
# resource, tested here for the property that matters: it is never exceeded.


def test_capacity_reports_the_configured_limit():
    from travel_planner.tools.mcp.client import browser_capacity

    cap = browser_capacity(_settings(max_concurrent_browsers=3))
    assert cap == {"limit": 3, "in_use": 0, "free": 3}


async def test_cap_is_never_exceeded_under_concurrency(monkeypatch):
    """Six simultaneous sessions against a cap of two."""
    import travel_planner.tools.mcp.client as mod

    settings = _settings(max_concurrent_browsers=2)
    live = 0
    peak = 0

    @asynccontextmanager
    async def fake_launch(*_a, **_k):
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        try:
            yield McpToolset()
        finally:
            live -= 1

    # Replace only the launch, keeping the real semaphore logic under test.
    monkeypatch.setattr(
        mod, "MultiServerMCPClient", lambda *_a, **_k: SimpleNamespace(session=fake_launch)
    )
    monkeypatch.setattr(mod, "load_mcp_tools", lambda *_a, **_k: _async_value([]))
    mod._browser_slots.clear()

    async def one():
        async with mod.browser_session(settings):
            await asyncio.sleep(0.05)

    await asyncio.gather(*(one() for _ in range(6)))
    assert peak <= 2, f"cap breached: {peak} concurrent browsers"
    assert browser_capacity(settings)["in_use"] == 0, "a slot leaked"


async def test_slot_is_released_when_the_session_fails_to_start(monkeypatch):
    """A launch failure must not permanently consume a slot."""
    import travel_planner.tools.mcp.client as mod

    settings = _settings(max_concurrent_browsers=1)
    mod._browser_slots.clear()

    def boom(*_a, **_k):
        raise RuntimeError("playwright would not start")

    monkeypatch.setattr(mod, "MultiServerMCPClient", boom)
    async with mod.browser_session(settings) as ts:
        assert ts is None
    assert browser_capacity(settings)["free"] == 1, "the slot was not returned"


async def test_slot_is_released_when_the_caller_raises(monkeypatch):
    import travel_planner.tools.mcp.client as mod

    settings = _settings(max_concurrent_browsers=1)
    mod._browser_slots.clear()

    @asynccontextmanager
    async def fake_launch(*_a, **_k):
        yield McpToolset()

    monkeypatch.setattr(
        mod, "MultiServerMCPClient", lambda *_a, **_k: SimpleNamespace(session=fake_launch)
    )
    monkeypatch.setattr(mod, "load_mcp_tools", lambda *_a, **_k: _async_value([]))

    with pytest.raises(ValueError):
        async with mod.browser_session(settings):
            raise ValueError("the caller blew up mid-browse")

    assert browser_capacity(settings)["free"] == 1, "the slot was not returned"


async def test_waiting_for_a_slot_times_out_rather_than_hanging(monkeypatch):
    import travel_planner.tools.mcp.client as mod

    settings = _settings(max_concurrent_browsers=1, browser_slot_timeout_seconds=0.1)
    mod._browser_slots.clear()
    mod._slots(1)  # occupy the only slot
    await mod._slots(1).acquire()

    async with mod.browser_session(settings) as ts:
        assert ts is None, "a caller that cannot get a slot must degrade, not hang"
    mod._slots(1).release()
