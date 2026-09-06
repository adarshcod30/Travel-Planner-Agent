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

`get_tools()` on `MultiServerMCPClient` opens and closes a session per call in
stdio mode, so tools returned here are safe to hold across a run without
pinning a session open — which is what lets the v5 factory build its graph once
per request without leaking subprocesses.
"""

import asyncio
import shutil
import sys
from collections.abc import Sequence
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

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
}


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


async def load_toolset(settings: Settings | None = None) -> McpToolset:
    """Connect to every enabled server and collect its tools.

    Servers are loaded concurrently and independently: each gets its own
    client so a server that hangs or crashes on startup is isolated to its own
    entry in `failed`.
    """
    settings = settings or get_settings()
    connections = build_connections(settings)
    toolset = McpToolset()
    if not connections:
        log.warning("mcp_no_servers_configured")
        return toolset

    async def load_one(name: str, conn: dict[str, Any]) -> tuple[str, list[BaseTool] | str]:
        try:
            client = MultiServerMCPClient({name: conn})
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
