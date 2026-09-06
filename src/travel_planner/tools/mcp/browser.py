"""Real browsing over Playwright MCP, with block detection and a target chain.

Each function here is one call from the graph's point of view even though it
drives several real MCP calls underneath — navigate, snapshot, and, when a
target turns out to be a bot wall, the same pair again against the next target.

That bundling is deliberate and was learned in the prototype this is based on:
handing a model a pile of generic `browser_*` tools and asking it to orchestrate
the retry itself produced hung and looping runs. Keeping the whole "try, detect
a block, move on" choreography in deterministic Python means the browsing is
entirely real while nothing depends on a small model driving a browser
correctly.

Two things make it work in practice:

**A chain, not a fallback.** The major search engines refuse automated browsers
routinely, so a two-step primary/fallback simply fails twice. Each research
function supplies an ordered list of targets and the first one to return real
content wins.

**Content-level block detection.** A bot wall returns HTTP 200 with a page
saying "verify you are a human". Only reading the page catches that, so a
snapshot is checked against known signals rather than trusting the status code.

Every result names the target that actually answered and lists the ones that did
not, so a substitution is never silent.
"""

import asyncio
from collections.abc import Sequence
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
    "bots use duckduckgo",
    "anomaly in the request",
)

EXCERPT_CHARS = 3000

#: A snapshot shorter than this, once the boilerplate header is stripped, is a
#: page that rendered nothing. Real pages produce hundreds of accessibility-tree
#: lines; a site refusing an automated client often returns HTTP 200, a real URL
#: and an empty body, which no status code or URL check would catch.
MIN_USEFUL_SNAPSHOT_CHARS = 200


class BlockedError(Exception):
    """The page loaded but its content is a block or CAPTCHA page.

    Distinct from a transport failure on purpose: the MCP session is healthy and
    the browser worked, the site simply refused an automated visitor. That is an
    expected outcome that should advance the chain, not be reported as a broken
    connection.
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


def snapshot_body(text: str) -> str:
    """The accessibility tree from a Playwright snapshot, minus the header.

    Playwright MCP wraps the tree in a `### Page … ### Snapshot ```yaml … ``` `
    envelope. The envelope is present even when the page rendered nothing, so
    emptiness has to be measured on the body, not the whole response.
    """
    marker = "```yaml"
    if marker in text:
        body = text.split(marker, 1)[1]
        return body.rsplit("```", 1)[0].strip() if "```" in body else body.strip()
    return text.strip()


def looks_empty(text: str) -> bool:
    return len(snapshot_body(text)) < MIN_USEFUL_SNAPSHOT_CHARS


async def _navigate_and_snapshot(toolset: McpToolset, url: str, timeout: float) -> str:
    """Navigate and read the page — the two calls that must share one session.

    With a session per tool call the navigate happens in one browser and the
    snapshot reads a second, freshly-launched one, which returns `about:blank`
    every time without erroring. `browser_session()` is what keeps them
    together.
    """
    nav = toolset.get("browser_navigate")
    snap = toolset.get("browser_snapshot")
    if nav is None or snap is None:
        raise RuntimeError("playwright MCP did not expose browser_navigate/browser_snapshot")

    log.info("browser_navigate", url=url)
    nav_text = mcp_text(await asyncio.wait_for(nav.ainvoke({"url": url}), timeout=timeout))
    snap_text = mcp_text(await asyncio.wait_for(snap.ainvoke({}), timeout=timeout))

    if looks_blocked(nav_text) or looks_blocked(snap_text):
        raise BlockedError(url)
    if "about:blank" in snap_text[:200]:
        raise BlockedError(f"{url} (navigated nowhere)")
    if looks_empty(snap_text):
        # A real URL with an empty tree: the site answered and rendered nothing.
        raise BlockedError(f"{url} (rendered an empty page)")
    return snap_text


async def browse_chain(
    toolset: McpToolset, targets: Sequence[tuple[str, str]], *, timeout: float = 45.0
) -> dict[str, Any]:
    """Try each (label, url) in order until one returns real content.

    Never raises. A total failure comes back as `ok: False` — a failed browse
    should degrade the research, not abort the run.
    """
    attempts: list[dict[str, str]] = []

    for index, (label, url) in enumerate(targets):
        try:
            text = await _navigate_and_snapshot(toolset, url, timeout)
            return {
                "ok": True,
                "source_used": label,
                "url_used": url,
                "fallback_used": index > 0,
                "attempts": attempts,
                "content_excerpt": text[:EXCERPT_CHARS],
            }
        except BlockedError:
            attempts.append({"target": label, "outcome": "blocked"})
            log.info("browser_blocked", target=label, remaining=len(targets) - index - 1)
        except Exception as exc:
            attempts.append({"target": label, "outcome": f"{type(exc).__name__}: {str(exc)[:120]}"})
            log.warning("browser_target_failed", target=label, error=type(exc).__name__)

    log.warning("browser_all_targets_failed", tried=[a["target"] for a in attempts])
    return {
        "ok": False,
        "source_used": None,
        "url_used": None,
        "fallback_used": True,
        "attempts": attempts,
        "error": "every target was blocked or errored",
        "content_excerpt": "",
    }


def _wikivoyage_url(city: str) -> str:
    return "https://en.m.wikivoyage.org/wiki/" + quote(city.strip().replace(" ", "_"))


async def research_destination(
    toolset: McpToolset, city: str, query: str = "", *, timeout: float = 45.0
) -> dict[str, Any]:
    """Read live destination guidance for a city.

    Wikivoyage leads the chain deliberately. It is a real, live site being really
    browsed — and unlike a search engine it publishes structured travel content
    and does not fight automated clients, so it both succeeds more often and
    returns better material than a page of search results would.
    """
    q = " ".join(x for x in (city, query, "travel guide things to do") if x).strip()
    return await browse_chain(
        toolset,
        [
            ("wikivoyage", _wikivoyage_url(city)),
            ("bing", f"https://www.bing.com/search?q={quote(q)}"),
            ("duckduckgo", f"https://duckduckgo.com/html/?q={quote(q)}"),
            ("google", f"https://www.google.com/search?q={quote(q)}"),
        ],
        timeout=timeout,
    )


async def research_hotels(
    toolset: McpToolset,
    destination: str,
    nights: int,
    budget_level: str,
    travelers: int = 2,
    *,
    timeout: float = 45.0,
) -> dict[str, Any]:
    """Search live hotel availability and prices.

    Commercial booking sites block automated browsers as a matter of course, so
    the chain continuing past booking.com is the normal case here, not a defect.
    """
    booking = "https://www.booking.com/searchresults.html?" + urlencode(
        {"ss": destination, "group_adults": max(1, travelers), "no_rooms": 1}
    )
    q = f"{destination} {budget_level} hotels prices {nights} nights"
    return await browse_chain(
        toolset,
        [
            ("booking.com", booking),
            ("bing", f"https://www.bing.com/search?q={quote(q)}"),
            ("duckduckgo", f"https://duckduckgo.com/html/?q={quote(q)}"),
        ],
        timeout=timeout,
    )
