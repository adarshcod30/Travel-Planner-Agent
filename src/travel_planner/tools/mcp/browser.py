"""Real browsing over Playwright MCP, with block detection and fallback.

Each function here is one call from the graph's point of view even though it
drives several real MCP calls underneath — navigate, snapshot, and, if the
first target looks like a bot-block, a second navigate and snapshot against a
more automation-friendly search engine.

That bundling is deliberate and was learned the hard way in the prototype this
is based on: handing a model a pile of generic `browser_*` tools and asking it
to orchestrate the retry itself produced hung and looping runs. Keeping the
whole "try the real site, detect a block, fall back" choreography in
deterministic Python means the browsing is entirely real while nothing depends
on a small model driving a browser correctly.

Every result reports which source actually answered and whether the fallback
fired, so a substitution is never silent.
"""

import asyncio
from typing import Any
from urllib.parse import quote, urlencode

from travel_planner.core.logging import get_logger
from travel_planner.tools.mcp.client import McpToolset

log = get_logger(__name__)

#: Content-level signals that a page is a bot wall rather than the real thing.
BLOCK_SIGNALS = (
    "captcha",
    "recaptcha",
    "are you a human",
    "verify you are a human",
    "unusual traffic",
    "access denied",
    "403 forbidden",
    "checking your browser",
    "cloudflare",
    "robot check",
    "detected unusual activity",
    "enable javascript and cookies",
)

EXCERPT_CHARS = 3000


class BlockedError(Exception):
    """The page loaded but its content is a block/CAPTCHA page.

    Distinct from a transport failure on purpose: the MCP session is healthy,
    the site simply refused an automated visitor. That is an expected outcome
    that should trigger the fallback, not be reported as a broken connection.
    """


def mcp_text(result: Any) -> str:
    """Flatten an MCP tool result to text.

    Results arrive either as a list of content blocks or as an already-flat
    string depending on the server and adapter version, so callers should not
    have to care which.
    """
    if isinstance(result, list):
        parts = []
        for item in result:
            if isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(result)


def looks_blocked(text: str) -> bool:
    lowered = text.lower()
    if lowered.lstrip().startswith("### error") or "\nerror:" in lowered[:200]:
        return True
    return any(signal in lowered for signal in BLOCK_SIGNALS)


async def _navigate_and_snapshot(toolset: McpToolset, url: str, timeout: float) -> str:
    nav = toolset.get("browser_navigate")
    snap = toolset.get("browser_snapshot")
    if nav is None or snap is None:
        raise RuntimeError("playwright MCP did not expose browser_navigate/browser_snapshot")

    log.info("browser_navigate", url=url)
    nav_text = mcp_text(await asyncio.wait_for(nav.ainvoke({"url": url}), timeout=timeout))
    snap_text = mcp_text(await asyncio.wait_for(snap.ainvoke({}), timeout=timeout))

    if looks_blocked(nav_text) or looks_blocked(snap_text):
        raise BlockedError(url)
    return snap_text


async def browse_with_fallback(
    toolset: McpToolset,
    *,
    primary_url: str,
    fallback_url: str,
    primary_label: str,
    fallback_label: str = "duckduckgo",
    timeout: float = 45.0,
) -> dict[str, Any]:
    """Try the real target, fall back to a search engine, always say which.

    Never raises: a total failure comes back as `ok: False` with the reason,
    because a failed browse should degrade the plan's research, not abort the
    run.
    """
    try:
        text = await _navigate_and_snapshot(toolset, primary_url, timeout)
        return {
            "ok": True,
            "source_used": primary_label,
            "url_used": primary_url,
            "fallback_used": False,
            "content_excerpt": text[:EXCERPT_CHARS],
        }
    except BlockedError:
        log.info(
            "browser_fallback",
            reason="primary looks blocked",
            primary=primary_label,
            to=fallback_label,
        )
    except Exception as exc:
        log.warning(
            "browser_primary_failed",
            primary=primary_label,
            error=f"{type(exc).__name__}: {str(exc)[:160]}",
        )

    try:
        text = await _navigate_and_snapshot(toolset, fallback_url, timeout)
        return {
            "ok": True,
            "source_used": fallback_label,
            "url_used": fallback_url,
            "fallback_used": True,
            "content_excerpt": text[:EXCERPT_CHARS],
        }
    except Exception as exc:
        log.warning("browser_fallback_failed", error=f"{type(exc).__name__}: {str(exc)[:160]}")
        return {
            "ok": False,
            "source_used": None,
            "url_used": fallback_url,
            "fallback_used": True,
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            "content_excerpt": "",
        }


async def research_destination(
    toolset: McpToolset, query: str, timeout: float = 45.0
) -> dict[str, Any]:
    """Search the live web for destination guidance matching a place or interest."""
    q = f"{query.strip()} travel guide best things to do"
    return await browse_with_fallback(
        toolset,
        primary_url=f"https://www.google.com/search?q={quote(q)}",
        fallback_url=f"https://duckduckgo.com/html/?q={quote(q)}",
        primary_label="google",
        timeout=timeout,
    )


async def research_hotels(
    toolset: McpToolset,
    destination: str,
    nights: int,
    budget_level: str,
    travelers: int = 2,
    timeout: float = 45.0,
) -> dict[str, Any]:
    """Search live hotel availability and prices.

    Commercial booking sites block automated browsers routinely, so the
    fallback firing here is the normal case, not a defect.
    """
    primary = "https://www.booking.com/searchresults.html?" + urlencode(
        {"ss": destination, "group_adults": max(1, travelers), "no_rooms": 1}
    )
    q = f"{destination} {budget_level} hotels prices {nights} nights"
    return await browse_with_fallback(
        toolset,
        primary_url=primary,
        fallback_url=f"https://duckduckgo.com/html/?q={quote(q)}",
        primary_label="booking.com",
        timeout=timeout,
    )
