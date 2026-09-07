"""Structured logging via structlog.

Local and development modes render human-readable console lines; production
emits JSON so a log shipper can index fields without parsing prose. Either way
every event carries key/value pairs rather than an interpolated string, which is
what makes "show me every escalation for agent=itinerary" a filter instead of a
regex.
"""

import logging
import sys

import structlog

from travel_planner.core.config import get_settings

_CONFIGURED = False


def configure_logging() -> None:
    """Configure structlog once for the process. Safe to call repeatedly."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    settings = get_settings()
    level = logging.getLevelName(settings.log_level.upper())
    if not isinstance(level, int):
        level = logging.INFO

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    # langchain-aws logs "Using Bedrock Converse API to generate response" at
    # INFO on every call; that is noise in a nine-agent graph.
    logging.getLogger("langchain_aws").setLevel(logging.WARNING)

    # httpx logs every request line at INFO, including the full URL. Tavily's
    # MCP endpoint carries its API key as a query parameter, so that would write
    # the key into the server log and into journald on every single call. This
    # is a credential leak, not noise — raise the level before anything connects.
    for noisy in ("httpx", "httpcore", "mcp.client.streamable_http"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    renderer = (
        structlog.processors.JSONRenderer()
        if settings.env_mode == "PRODUCTION"
        else structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())
    )

    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a bound logger, configuring structlog on first use."""
    configure_logging()
    return structlog.get_logger(name)
