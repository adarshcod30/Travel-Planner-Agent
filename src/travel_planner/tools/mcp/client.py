"""MCP connection management for v5.

Builds the connection map for the four servers v5 talks to and hands out
LangChain tools from them. Two transports are supported and the choice is a
setting, not a code path the caller has to know about:

**stdio** — this process spawns each server itself, per session. Nothing else
to run; nothing survives between sessions, so each research pass gets a clean
browser. This is the default because it has no operational prerequisites.

**streamable_http** — connect to an already-running server (Playwright only;
the others have no meaningful persistent mode here). The browser and anything
it navigated to survive across the whole run, at the cost of a second process
to manage.

**Two ways to get tools, and the difference matters.**

`load_toolset()` uses `get_tools()`, which opens and closes a session per tool
call. That is exactly right for stateless servers — travel-mcp, fetch,
filesystem — where every call is independent, and it means no subprocess is
held open between uses.

It is exactly wrong for a browser. `browser_navigate` and `browser_snapshot`
are two calls that only make sense against the *same* session: with a session
per call, the navigate happens in one browser and the snapshot reads a second,
freshly-launched one, which returns `about:blank` every time. Nothing errors —
the tools succeed, the page is just empty. `browser_session()` therefore holds
one session open across the whole browsing sequence.
"""

import asyncio
import shutil
import sys
from collections.abc import AsyncIterator, Sequence
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any, cast

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import Connection
from langchain_mcp_adapters.tools import load_mcp_tools

from travel_planner.core.config import Settings, get_settings
from travel_planner.core.logging import get_logger

log = get_logger(__name__)

#: Server name -> the tool-name prefixes it is expected to expose. Used to
#: report clearly when a server connects but offers nothing usable.
EXPECTED_TOOLS: dict[str, tuple[str, ...]] = {
    "playwright": ("browser_navigate", "browser_snapshot"),
    "filesystem": ("read_file", "write_file"),
    "fetch": ("fetch",),
    "travel": ("get_weather_forecast", "convert_currency"),
    "tavily": ("tavily_search",),
    "memory": ("create_entities", "search_nodes"),
    "time": ("get_current_time",),
}


def redact(conn: dict[str, Any]) -> dict[str, Any]:
    """A connection safe to log.

    Tavily carries its API key in the URL query string, so any log line, error
    message or debug dump that includes a raw connection would leak it.
    """
    safe = dict(conn)
    if "url" in safe:
        safe["url"] = safe["url"].split("?")[0] + ("?<redacted>" if "?" in safe["url"] else "")
    return safe


def _stdio(command: str, args: Sequence[str], **extra: Any) -> dict[str, Any]:
    return {"transport": "stdio", "command": command, "args": list(args), **extra}


def build_connections(settings: Settings | None = None) -> dict[str, dict[str, Any]]:
    """Build the connection map for every enabled server.

    A server whose launcher is not installed is dropped with a warning rather
    than failing the run: v5 degrades to the servers actually available, and
    `research_notes` records which ones were used.
    """
    settings = settings or get_settings()
    conns: dict[str, dict[str, Any]] = {}

    for name in settings.enabled_mcp_servers:
        match name:
            case "playwright":
                if settings.mcp_mode == "http":
                    conns[name] = {
                        "transport": "streamable_http",
                        "url": settings.playwright_mcp_url,
                    }
                else:
                    conns[name] = _stdio(
                        settings.playwright_mcp_command, settings.playwright_mcp_arg_list
                    )
            case "filesystem":
                conns[name] = _stdio(
                    settings.filesystem_mcp_command, settings.filesystem_mcp_arg_list
                )
            case "fetch":
                conns[name] = _stdio(settings.fetch_mcp_command, settings.fetch_mcp_arg_list)
            case "memory":
                # MEMORY_FILE_PATH is how this server is told where to persist;
                # without it the graph lives in a temp file and every trip
                # starts from nothing, which defeats the point.
                conns[name] = _stdio(
                    settings.memory_mcp_command,
                    settings.memory_mcp_arg_list,
                    env={"MEMORY_FILE_PATH": str(Path(settings.memory_file_path).resolve())},
                )
            case "time":
                conns[name] = _stdio(settings.time_mcp_command, settings.time_mcp_arg_list)
            case "tavily":
                # Hosted, so there is no launcher to check and nothing to spawn.
                url = settings.tavily_mcp_url
                if url is None:
                    log.warning("mcp_tavily_skipped", reason="TAVILY_API_KEY is not set")
                    continue
                conns[name] = {"transport": "streamable_http", "url": url}
            case "travel":
                # Launched with this interpreter so it resolves inside the venv
                # regardless of what `python` means on the caller's PATH.
                command = (
                    sys.executable
                    if settings.travel_mcp_command == "python"
                    else settings.travel_mcp_command
                )
                conns[name] = _stdio(command, settings.travel_mcp_arg_list)
            case unknown:
                log.warning("mcp_unknown_server", server=unknown)
                continue

    return {name: c for name, c in conns.items() if _launcher_available(name, c)}


def _launcher_available(name: str, conn: dict[str, Any]) -> bool:
    if conn.get("transport") != "stdio":
        return True
    command = conn["command"]
    if shutil.which(command) or command == sys.executable:
        return True
    log.warning("mcp_launcher_missing", server=name, command=command)
    return False


class McpToolset:
    """Tools from every reachable server, indexed by name.

    Built once per run by `load_toolset`. A server that fails to start is
    recorded in `failed` instead of raising, so one broken server cannot take
    the research pass down with it.
    """

    def __init__(self) -> None:
        self.tools: dict[str, BaseTool] = {}
        self.by_server: dict[str, list[str]] = {}
        self.failed: dict[str, str] = {}

    def get(self, *names: str) -> BaseTool | None:
        """First matching tool, by exact name then by suffix.

        Servers vary in whether they namespace tool names, so `get("fetch")`
        should also match a tool registered as `fetch__fetch`.
        """
        for n in names:
            if n in self.tools:
                return self.tools[n]
        for n in names:
            for key, tool in self.tools.items():
                if key.endswith(n) or key.endswith(n.replace("_", "-")):
                    return tool
        return None

    @property
    def servers(self) -> tuple[str, ...]:
        return tuple(self.by_server)

    def __len__(self) -> int:
        return len(self.tools)


#: Guards the number of live browsers, not the number of runs.
#:
#: Keyed by size so changing the limit in a test does not leave a stale
#: semaphore behind. Module-level state is right here: the cap is a property of
#: the machine's memory, shared by every run in the process.
_browser_slots: dict[int, asyncio.Semaphore] = {}


def _slots(limit: int) -> asyncio.Semaphore:
    if limit not in _browser_slots:
        _browser_slots[limit] = asyncio.Semaphore(limit)
    return _browser_slots[limit]


async def _release(sem: asyncio.Semaphore) -> None:
    """Hand a browser slot back.

    Registered on the exit stack so it runs whether the session ended normally,
    failed to start, or the caller's own block raised.
    """
    sem.release()


def browser_capacity(settings: Settings | None = None) -> dict[str, int]:
    """Current browser occupancy, for the health route and the UI."""
    settings = settings or get_settings()
    limit = settings.max_concurrent_browsers
    free = max(0, _slots(limit)._value)
    return {"limit": limit, "in_use": limit - free, "free": free}


@asynccontextmanager
async def browser_session(settings: Settings | None = None) -> AsyncIterator[McpToolset | None]:
    """Hold one Playwright MCP session open and yield tools bound to it.

    Yields None when Playwright is not configured or will not start, so a caller
    can degrade instead of branching on exceptions. The session — and the browser
    it owns — closes when the block exits, tying the browser's lifetime to the
    run rather than to the server process.

    Acquisition and use are separated on purpose. Wrapping the `yield` in the
    same `try/except` would catch exceptions raised by the *caller's* block,
    re-enter the generator, and yield a second time — which raises "generator
    didn't stop after athrow()" and buries the caller's real error. Only setup
    failures are handled here; anything the body raises propagates untouched.
    """
    settings = settings or get_settings()
    conn = build_connections(settings).get("playwright")
    if conn is None:
        log.warning(
            "browser_unavailable", reason="playwright is not enabled or its launcher is missing"
        )
        yield None
        return

    # Wait for a browser slot before spawning anything. Without this, Aegra
    # accepts every run immediately and five concurrent v5 runs become five
    # Chromes — roughly 6.5 GB — with nothing in between. A run queue caps runs;
    # this caps the resource that is actually scarce.
    sem = _slots(settings.max_concurrent_browsers)
    if sem.locked():
        log.info("browser_waiting_for_slot", **browser_capacity(settings))
    try:
        await asyncio.wait_for(sem.acquire(), timeout=settings.browser_slot_timeout_seconds)
    except TimeoutError:
        log.warning("browser_slot_timeout", waited=settings.browser_slot_timeout_seconds)
        yield None
        return

    stack = AsyncExitStack()
    stack.push_async_callback(_release, sem)
    try:
        client = MultiServerMCPClient({"playwright": cast(Connection, conn)})
        session = await stack.enter_async_context(client.session("playwright"))
        tools = await asyncio.wait_for(
            load_mcp_tools(session), timeout=settings.mcp_tool_timeout_seconds
        )
    except Exception as exc:
        await stack.aclose()
        log.warning("browser_session_failed", error=f"{type(exc).__name__}: {str(exc)[:200]}")
        yield None
        return

    toolset = McpToolset()
    toolset.by_server["playwright"] = [t.name for t in tools]
    for t in tools:
        toolset.tools[t.name] = t
    log.info("browser_session_open", tools=len(tools))

    try:
        yield toolset
    finally:
        await stack.aclose()  # also releases the slot
        log.info("browser_session_closed", **browser_capacity(settings))


async def load_toolset(settings: Settings | None = None) -> McpToolset:
    """Connect to every enabled server and collect its tools.

    Servers are loaded concurrently and independently: each gets its own
    client so a server that hangs or crashes on startup is isolated to its own
    entry in `failed`.

    Playwright is deliberately excluded — it needs a held session, which is
    what `browser_session()` provides.
    """
    settings = settings or get_settings()
    connections = {k: v for k, v in build_connections(settings).items() if k != "playwright"}
    toolset = McpToolset()
    if not connections:
        log.warning("mcp_no_servers_configured")
        return toolset

    async def load_one(name: str, conn: dict[str, Any]) -> tuple[str, list[BaseTool] | str]:
        try:
            client = MultiServerMCPClient({name: cast(Connection, conn)})
            tools = await asyncio.wait_for(
                client.get_tools(server_name=name), timeout=settings.mcp_tool_timeout_seconds
            )
            return name, tools
        except TimeoutError:
            return name, f"timed out after {settings.mcp_tool_timeout_seconds}s"
        except Exception as exc:  # a server that will not start must not fail the run
            return name, f"{type(exc).__name__}: {str(exc)[:200]}"

    results = await asyncio.gather(*(load_one(n, c) for n, c in connections.items()))
    for name, outcome in results:
        if isinstance(outcome, str):
            toolset.failed[name] = outcome
            log.warning("mcp_server_unavailable", server=name, reason=outcome)
            continue
        toolset.by_server[name] = [t.name for t in outcome]
        for t in outcome:
            toolset.tools.setdefault(t.name, t)
        missing = [e for e in EXPECTED_TOOLS.get(name, ()) if toolset.get(e) is None]
        log.info("mcp_server_ready", server=name, tools=len(outcome), missing=missing or None)

    return toolset
