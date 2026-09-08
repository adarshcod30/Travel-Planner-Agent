"""Searching the open web and following what comes back.

`browser.py` walks a fixed list of URLs someone wrote down in advance, which is
right when you know exactly which page answers your question — Wikivoyage for a
city guide, an aggregator's listing for room rates. It is wrong for everything
else, because a hardcoded URL only survives until the site changes its routing,
and it can only ever find what was anticipated.

This does what a person does instead: searches, reads the results, opens the
promising ones, scrolls far enough to see the substance, and goes back. It
finds pages nobody listed — a district tourism site, a rail operator's own
timetable, this year's festival dates on an organiser's page — and it keeps
working when an aggregator reshuffles its URLs.

Every step is a real click through `control.perform`, so it emits events and
captures frames like everything else: the search, each result opened, each
scroll. Watching it is watching someone browse.

Two judgements are made in Python rather than by a model, for the same reason
the rest of this package is:

**Which results are worth opening.** A results page is mostly navigation,
adverts and the search engine's own links. Scoring by host and by how well the
link text matches the query is cheap, deterministic, and does not hang a run on
a small model's opinion.

**When a page has been read.** Scroll until the accessibility tree stops
growing or the budget runs out, rather than guessing a number of scrolls.
"""

import asyncio
import json
import re
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlsplit

from travel_planner.core import events
from travel_planner.core.logging import get_logger
from travel_planner.tools.mcp import control
from travel_planner.tools.mcp.browser import BLOCK_SIGNALS, mcp_text, snapshot_body
from travel_planner.tools.mcp.client import McpToolset

log = get_logger(__name__)

#: Search engines, in the order they are worth trying, with the home page to
#: fall back to when the query URL is refused.
#:
#: Google leads. It was last here on the assumption that it fights automated
#: browsers hardest, and measuring that turned out to contradict it: a headed
#: Chromium gets a full results page from Google with no consent wall and no
#: CAPTCHA, and its results are better than the alternatives'. The assumption
#: was doing real damage — Google was never reached, because DuckDuckGo
#: answered first with a page of adverts.
SEARCH_ENGINES: tuple[tuple[str, str, str], ...] = (
    ("google", "https://www.google.com/search?q={q}", "https://www.google.com"),
    ("bing", "https://www.bing.com/search?q={q}", "https://www.bing.com"),
    ("duckduckgo", "https://duckduckgo.com/html/?q={q}", "https://duckduckgo.com"),
)

#: Hosts that are never the answer: the search engine's own surfaces, social
#: sites, and aggregators whose content is behind a login or an app wall.
_SKIP_HOSTS = (
    "bing.com",
    "duckduckgo.com",
    "google.com",
    "googleusercontent",
    "youtube.com",
    "facebook.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "pinterest.",
    "linkedin.com",
    "reddit.com",
    "quora.com",
    "tripadvisor.",  # interstitial-heavy and hostile to automation
)

#: Hosts worth opening first. Official tourism boards, transport operators and
#: reference sites answer a travel question directly and do not fight a browser.
_PREFERRED = (
    ".gov.in",
    ".nic.in",
    "tourism",
    "wikivoyage",
    "wikipedia",
    "irctc",
    "indianrail",
    "incredibleindia",
    "makemytrip",
    "goibibo",
    "holidify",
    "thrillophilia",
)

#: Pulled from the DOM rather than the accessibility tree. The tree carries
#: hrefs as a separate `- /url:` line which is relative on Bing
#: (`/?FORM=Z9FD1`) and a redirect wrapper on DuckDuckGo — and its refs are
#: frame-prefixed (`f4e19`), which a naive pattern misses entirely. The
#: browser has already resolved every one of those, so asking it is both
#: simpler and correct.
_LINKS_JS = """() => {
  const engine = location.host.replace(/^www\\./, '');
  const containers = ['#rso', '#search', '#b_results', '.results', '#links', 'main'];
  const scope = containers.map(s => document.querySelector(s)).find(Boolean) || document.body;
  return [...scope.querySelectorAll('a[href]')]
    .map(a => ({
      href: a.href,
      text: (a.innerText || a.textContent || '').trim().slice(0, 160),
      // A link back into the engine's own search is a "related searches"
      // suggestion, not a result — and it echoes the query, so it would
      // otherwise outscore every real answer.
      selfSearch: a.href.includes(engine) && /[?&]q=/.test(a.href),
    }))
    .filter(l => l.href.startsWith('http') && l.text.length > 7 && !l.selfSearch)
    .slice(0, 120);
}"""


def _unwrap(url: str) -> str:
    """Follow a search engine's redirect wrapper to the page it points at.

    DuckDuckGo hands out `//duckduckgo.com/l/?uddg=<encoded>` rather than the
    destination, so ranking by host would score every result identically and
    skipping its own domain would discard all of them.
    """
    parsed = urlsplit(url)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        if target.startswith("http"):
            return unquote(target)
    return url


async def collect_links(toolset: McpToolset, timeout: float = 30.0) -> list[dict[str, str]]:
    """Every outbound link on the current page, resolved and de-wrapped."""
    ev = toolset.get("browser_evaluate")
    if ev is None:
        return []
    try:
        raw = mcp_text(await asyncio.wait_for(ev.ainvoke({"function": _LINKS_JS}), timeout=timeout))
    except Exception as exc:
        log.debug("collect_links_failed", error=f"{type(exc).__name__}: {str(exc)[:120]}")
        return []
    body = raw.split("### Result", 1)[-1].split("### Ran", 1)[0].strip()
    try:
        links = json.loads(body)
    except Exception:
        return []
    return [
        {"href": _unwrap(str(link.get("href", ""))), "text": str(link.get("text", ""))}
        for link in links
        if isinstance(link, dict)
    ]


def rank_results(links: list[dict[str, str]], query: str, limit: int = 5) -> list[dict[str, str]]:
    """The links worth actually opening.

    A results page is mostly chrome: the engine's own navigation, adverts and a
    footer. Scoring by title overlap and by host keeps the browsing pointed at
    pages that answer the question, without asking a model which blue link
    looks promising.

    A candidate may carry a usable `href`, a clickable `ref`, or both. Google
    supplies only the second — see `follow`.
    """
    words = {w for w in re.findall(r"[a-z]{4,}", query.lower())}
    seen: set[str] = set()
    found: list[dict[str, Any]] = []

    for link in links:
        url, text = link.get("href", ""), (link.get("text") or "").strip()
        if len(text) < 8:
            continue  # "Next", "Images", "Sign in"
        if not url and not link.get("ref"):
            continue  # nothing to open it with

        # A redirect wrapper's host is the *engine*, not the destination —
        # `google.com/goto?url=<token>` is a result, not a Google page. Judging
        # it by that host discarded every real result Google returned, since
        # google.com is on the skip list. The destination is unknowable until
        # it is opened, so it is judged then instead.
        host = urlsplit(url).netloc.lower() if url.startswith("http") else ""
        if _REDIRECT.search(url):
            host, url = "", ""
        elif host and any(skip in host for skip in _SKIP_HOSTS):
            continue

        # One page per host, and one per title: ten links into the same site
        # are one source, and the other nine crowd out everything else.
        key = host or text.lower()[:60]
        if key in seen:
            continue
        seen.add(key)

        lowered = text.lower()
        score = sum(1 for w in words if w in lowered)
        if host and any(pref in host for pref in _PREFERRED):
            score += 3
        if score <= 0:
            continue  # nothing in the title relates to what was asked
        found.append(
            {
                "url": url,
                "ref": link.get("ref", ""),
                "title": text[:120],
                "host": host or "(unknown until opened)",
                "score": score,
            }
        )

    found.sort(key=lambda r: -r["score"])
    return [{k: str(v) for k, v in r.items()} for r in found[:limit]]


def snapshot_links(snapshot: str) -> list[dict[str, str]]:
    """Result links as (ref, text) pairs, straight off the accessibility tree.

    This exists because of Google specifically. Its results carry
    `href="/goto?url=<opaque token>"` — the destination is encoded server-side
    and cannot be unwrapped, so there is no URL to extract and follow. The only
    way to reach a Google result is to click it and let the redirect happen,
    which needs a ref rather than a href.
    """
    out: list[dict[str, str]] = []
    for line in snapshot_body(snapshot).splitlines():
        m = _REF_LINK.match(line)
        if m:
            out.append({"ref": m.group("ref"), "text": m.group("name").strip(), "href": ""})
    return out


#: A search engine's own redirect, wrapping a destination it will not publish.
_REDIRECT = re.compile(r"/(?:goto|url|aclk|ck/a)\?")

_REF_LINK = re.compile(
    r'^\s*-\s+link\s+"(?P<name>[^"]{4,200})"'
    r"(?:\s*\[[^\]]*\])*?\s*\[ref=(?P<ref>[a-z]*\d*e\d+)\]"
)


def _with_refs(
    dom_links: list[dict[str, str]], tree_links: list[dict[str, str]]
) -> list[dict[str, str]]:
    """Join what the DOM knows to what the accessibility tree can click.

    The DOM has hrefs and can tell a result from the engine's own navigation;
    the tree has the refs a click needs. Neither alone is enough for Google,
    whose destinations are tokens — so they are matched on the one thing both
    carry, the link's visible text.
    """
    by_text = {_key(link["text"]): link["ref"] for link in tree_links}
    out = [{**link, "ref": by_text.get(_key(link.get("text", "")), "")} for link in dom_links]

    # The DOM decides what counts as a result; the tree only says how to click
    # it. Adding the tree's leftovers back in was actively harmful: it cannot
    # tell a result from the engine's own "related searches", and those echo
    # the query word for word, so they outscored every real answer and the
    # first two pages opened were always another Google search.
    return out or tree_links


def _key(text: str) -> str:
    """Match DOM text to tree text. Both collapse whitespace differently, and
    the tree truncates long names, so neither is byte-identical to the other."""
    return " ".join((text or "").split()).lower()[:60]


async def search(
    toolset: McpToolset,
    query: str,
    *,
    thread_id: str | None = None,
    timeout: float = 45.0,
) -> dict[str, Any]:
    """Run a search and return the results worth opening.

    Tries each engine until one answers with links. Returns an empty result
    list rather than raising — a search that finds nothing should thin the
    research, not end the run.
    """
    for engine, template, home in SEARCH_ENGINES:
        events.phase("searching", f"{engine}: {query}")
        for how in ("url", "typed"):
            try:
                if how == "url":
                    await control.perform(
                        toolset,
                        control.Action(kind="navigate", url=template.format(q=quote(query))),
                        thread_id=thread_id,
                    )
                elif not await type_into_search_box(toolset, home, query, thread_id=thread_id):
                    break
                snap = toolset.get("browser_snapshot")
                text = mcp_text(await snap.ainvoke({}))
            except Exception as exc:
                log.info("search_engine_failed", engine=engine, how=how, error=type(exc).__name__)
                continue

            if any(sig in text.lower() for sig in BLOCK_SIGNALS):
                events.browser_blocked(engine, "the search engine wants a person")
                continue  # a typed search sometimes gets past what a query URL does not

            # Two ways to name a result, because engines differ. Bing and
            # DuckDuckGo publish real hrefs; Google publishes an opaque
            # `/goto?url=<token>` that cannot be unwrapped, so its results are
            # reachable only by clicking them.
            # A result needs a href to navigate to *or* a ref to click. Google
            # gives neither directly — its hrefs are opaque `/goto?url=<token>`
            # values — so the DOM's link text is matched back to the
            # accessibility tree's refs, and the click is what opens it.
            candidates = _with_refs(await collect_links(toolset), snapshot_links(text))
            results = rank_results(candidates, query)
            if results:
                log.info("search_results", engine=engine, how=how, count=len(results))
                return {"engine": engine, "how": how, "query": query, "results": results}

    log.warning("search_found_nothing", query=query)
    return {"engine": None, "how": None, "query": query, "results": []}


async def type_into_search_box(
    toolset: McpToolset,
    home: str,
    query: str,
    *,
    thread_id: str | None = None,
) -> bool:
    """Search the way a person does: open the site, type, press Enter.

    A query URL is one request that announces exactly what it is. Loading the
    home page, clicking into the box and typing is several, and it produces the
    focus, input and key events a real visit produces — which is sometimes the
    difference between a results page and a consent wall.

    Returns False when there is no box to type into, so the caller can move on
    rather than guess.
    """
    await control.perform(toolset, control.Action(kind="navigate", url=home), thread_id=thread_id)
    page = await control.read_page(toolset)
    box = next(
        (
            e
            for e in page["elements"]
            if e["role"] in ("combobox", "searchbox", "textbox")
            and "search" in (e["name"] or "").lower()
        ),
        None,
    ) or next(
        (e for e in page["elements"] if e["role"] in ("combobox", "searchbox", "textbox")),
        None,
    )
    if box is None:
        log.info("search_box_not_found", home=home)
        return False

    label = box["name"] or "the search box"
    await control.perform(
        toolset, control.Action(kind="click", ref=box["ref"], label=label), thread_id=thread_id
    )
    await control.perform(
        toolset,
        control.Action(kind="type", ref=box["ref"], label=label, text=query),
        thread_id=thread_id,
    )
    await control.perform(toolset, control.Action(kind="press", key="Enter"), thread_id=thread_id)
    # Results arrive asynchronously; a snapshot taken immediately sees the box.
    await control.perform(toolset, control.Action(kind="wait", seconds=3), thread_id=thread_id)
    return True


#: The readable page, not its markup. An accessibility tree is the right thing
#: to *act* on — it carries the refs a click needs — and the wrong thing to
#: read: two thousand characters of it is a navigation menu and a cookie
#: banner. A specialist's prompt wants the prose.
_TEXT_JS = """() => {
  const drop = 'nav, header, footer, aside, script, style, noscript, form, iframe';
  const root = document.querySelector('article, main, [role=main]') || document.body;
  const clone = root.cloneNode(true);
  clone.querySelectorAll(drop).forEach(n => n.remove());
  return (clone.innerText || '').replace(/\\n{3,}/g, '\\n\\n').trim().slice(0, 6000);
}"""


async def page_text(toolset: McpToolset, timeout: float = 30.0) -> str:
    """The current page as prose, with the furniture stripped out."""
    ev = toolset.get("browser_evaluate")
    if ev is None:
        return ""
    try:
        raw = mcp_text(await asyncio.wait_for(ev.ainvoke({"function": _TEXT_JS}), timeout=timeout))
    except Exception as exc:
        log.debug("page_text_failed", error=f"{type(exc).__name__}: {str(exc)[:120]}")
        return ""
    body = raw.split("### Result", 1)[-1].split("### Ran", 1)[0].strip()
    try:
        parsed = json.loads(body)
    except Exception:
        return body[:6000]
    return parsed if isinstance(parsed, str) else str(parsed)[:6000]


async def read_page_fully(
    toolset: McpToolset,
    *,
    thread_id: str | None = None,
    max_scrolls: int = 4,
) -> str:
    """Scroll until the page stops giving up new text, then return what it said.

    Pages load as you scroll, so a single read sees a header and a cookie
    banner. Stopping when the text stops growing reads a short page without
    spending four scrolls on it, and still reaches the bottom of a long one.
    """
    best = await page_text(toolset)
    for _ in range(max_scrolls):
        previous = len(best)
        try:
            await control.perform(
                toolset, control.Action(kind="scroll", y=900), thread_id=thread_id
            )
            current = await page_text(toolset)
        except Exception:
            break
        if len(current) <= previous + 200:
            return current if len(current) > previous else best
        best = current
    return best


async def explore(
    toolset: McpToolset,
    query: str,
    *,
    thread_id: str | None = None,
    open_count: int = 2,
    excerpt_chars: int = 1400,
) -> dict[str, Any]:
    """Search, open the best results, read them, and come back.

    The whole loop a person would do, in one call: search, pick, open, scroll
    until the page stops giving up text, go back, pick the next. Never raises —
    every outcome is a report, because thinner research is an acceptable
    result and a failed run is not.
    """
    found = await search(toolset, query, thread_id=thread_id)
    pages: list[dict[str, str]] = []
    opened = 0

    for result in found["results"]:
        if opened >= open_count:
            break
        events.phase("reading", result["title"][:70])
        try:
            landed = await follow(toolset, result, thread_id=thread_id)
        except Exception as exc:
            log.info("explore_page_failed", title=result["title"][:60], error=type(exc).__name__)
            continue
        if landed is None:
            continue

        host = urlsplit(landed["url"]).netloc.lower()
        if any(skip in host for skip in _SKIP_HOSTS):
            # Only discoverable after opening it, when the engine hid the
            # destination behind a redirect.
            log.debug("explore_skipped_host", host=host)
        elif any(sig in landed["text"].lower() for sig in BLOCK_SIGNALS):
            events.browser_blocked(host, "this page wants a person")
        else:
            opened += 1
            pages.append(
                {
                    "title": result["title"],
                    "url": landed["url"],
                    "host": host,
                    "excerpt": " ".join(landed["text"].split())[:excerpt_chars],
                }
            )

        # Back to the results, so the next pick starts where a person would be
        # looking. A result that opened in its own tab has already been closed,
        # and going Back from the results page would leave the search behind.
        if not landed.get("new_tab"):
            try:
                await control.perform(toolset, control.Action(kind="back"), thread_id=thread_id)
                await control.perform(
                    toolset, control.Action(kind="wait", seconds=1.5), thread_id=thread_id
                )
            except Exception:
                break

    return {
        "query": query,
        "engine": found["engine"],
        "how": found.get("how"),
        "considered": found["results"],
        "pages": pages,
        "ok": bool(pages),
    }


async def _tabs(toolset: McpToolset, action: str, **extra: Any) -> str:
    """Ask Playwright about tabs. Never raises — a tab query is not worth a run."""
    tool = toolset.get("browser_tabs")
    if tool is None:
        return ""
    try:
        return mcp_text(await tool.ainvoke({"action": action, **extra}))
    except Exception as exc:
        log.debug("tabs_failed", action=action, error=f"{type(exc).__name__}: {str(exc)[:100]}")
        return ""


def _tab_count(listing: str) -> int:
    """How many tabs a `browser_tabs list` reply describes."""
    return len(re.findall(r"^\s*-\s+\d+:", listing, flags=re.MULTILINE))


async def follow(
    toolset: McpToolset,
    result: dict[str, str],
    *,
    thread_id: str | None = None,
) -> dict[str, str] | None:
    """Open one result, however it can be opened, and read where it went.

    A real href is navigated to directly. A result that has only a ref is
    *clicked* — which is the only way to open a Google result, since its
    destination is an opaque token rather than a URL. Either way the landed
    address is read back afterwards rather than assumed, because a click
    through a redirect is precisely a case where you do not know in advance
    where you ended up.
    """
    url = result.get("url", "")
    opened_tab = False

    # A `/goto?url=<token>` href cannot be navigated to — the destination is
    # encoded server-side. Following it needs a real click, which is the only
    # way Google will hand over a result at all.
    if url.startswith("http") and "/goto?" not in url:
        await control.perform(
            toolset,
            control.Action(kind="navigate", url=url, label=result["title"]),
            thread_id=thread_id,
        )
    elif result.get("ref"):
        before = _tab_count(await _tabs(toolset, "list"))
        await control.perform(
            toolset,
            control.Action(kind="click", ref=result["ref"], label=result["title"]),
            thread_id=thread_id,
        )
        await control.perform(toolset, control.Action(kind="wait", seconds=3), thread_id=thread_id)
        # Search results carry target="_blank", so the click lands in a new tab
        # while the tab being read stays on the results page — which is what
        # made every click come back as about:blank.
        listing = await _tabs(toolset, "list")
        if _tab_count(listing) > before:
            await _tabs(toolset, "select", index=_tab_count(listing) - 1)
            opened_tab = True
    else:
        return None

    text = await read_page_fully(toolset, thread_id=thread_id)
    snap = toolset.get("browser_snapshot")
    landed = url
    if snap is not None:
        landed = control.page_url(mcp_text(await snap.ainvoke({}))) or url

    if opened_tab:
        # Close it and return to the results, so the next pick has something to
        # click. Left open, these would accumulate for the whole run.
        await _tabs(toolset, "close")
        await _tabs(toolset, "select", index=0)
    return {"url": landed, "text": text, "new_tab": "yes" if opened_tab else ""}


def summarise(found: dict[str, Any]) -> str | None:
    """Render an exploration as the note a specialist reads.

    Names the pages it actually opened. A specialist told to prefer live
    research over its own recollection should be able to see where the research
    came from, and a reader of the finished plan should be able to check it.
    """
    if not found.get("pages"):
        return None
    lines = [f'Searched the web for "{found["query"]}" and read:']
    for page in found["pages"]:
        lines.append(f"\n- {page['title']} ({page['host']})\n  {page['excerpt'][:900]}")
    return "\n".join(lines)
