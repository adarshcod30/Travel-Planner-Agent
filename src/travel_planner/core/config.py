"""Application settings, loaded from the environment and `.env`.

One `Settings` object is the single source of truth for every tunable in the
system. Nothing else reads `os.environ` directly, so a value has exactly one
name, one type, one default, and one place to look it up.
"""

from functools import lru_cache
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ModelTier = Literal["high", "mid", "low", "fallback"]
McpMode = Literal["stdio", "http"]
GraphVersion = Literal["v1_linear", "v2_parallel", "v3_orchestrator", "v4_hitl", "v5_mcp"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # Aegra and Postgres share the same .env; ignore their keys here
        case_sensitive=False,
    )

    # --- AWS / Bedrock -------------------------------------------------------
    aws_region: str = "us-east-1"
    aws_profile: str | None = None

    # Defaults, not requirements. These are cross-region inference profile IDs,
    # not secrets, and they are the ones this project was verified against — so
    # the package imports and the entire test suite runs on a machine with no
    # .env at all. Without defaults the tests pass locally purely because a
    # developer happens to have one, and fail everywhere else. Override in .env
    # for another account or region; scripts/resolve_bedrock_models.sh prints
    # what an account actually exposes.
    bedrock_model_tier_high: str = Field(
        default="us.amazon.nova-pro-v1:0", description="Reasoning-heavy agents"
    )
    bedrock_model_tier_mid: str = Field(
        default="us.amazon.nova-lite-v1:0", description="Moderate agents"
    )
    bedrock_model_tier_low: str = Field(
        default="us.amazon.nova-micro-v1:0", description="Extraction-shaped agents"
    )
    bedrock_model_fallback: str = Field(
        default="us.meta.llama3-3-70b-instruct-v1:0",
        description="Per-agent fallback for unreliable structured output",
    )

    # maxTokens is mandatory on every call: unset, Bedrock reserves the model
    # maximum against the account quota and small requests start throttling.
    bedrock_max_tokens_high: int = 4096
    bedrock_max_tokens_mid: int = 2048
    bedrock_max_tokens_low: int = 1024

    bedrock_temperature: float = 0.3
    bedrock_max_retries: int = 5
    bedrock_retry_mode: Literal["adaptive", "standard", "legacy"] = "adaptive"
    bedrock_read_timeout: int = 60

    # --- Structured-output resilience -----------------------------------------
    structured_output_max_repairs: int = Field(
        default=1,
        description="Re-prompts with the validator's error text before escalating",
    )
    structured_output_escalate_tier: bool = Field(
        default=True,
        description="Retry on the next tier up after repairs are exhausted",
    )

    # --- Application -----------------------------------------------------------
    max_orchestrator_iterations: int = 3
    default_version: GraphVersion = "v5_mcp"

    # --- MCP (v5) ----------------------------------------------------------------
    mcp_mode: McpMode = "stdio"
    mcp_enabled_servers: str = "playwright,fetch,travel,tavily,memory,time"
    mcp_tool_timeout_seconds: float = 45.0

    # A live browser costs roughly 1.3 GB across its process tree, and Aegra's
    # queue — Redis or otherwise — limits *runs*, not browsers. v1 to v4 launch
    # none at all, so a run limit either throttles cheap versions needlessly or
    # lets expensive ones pile up. This caps the thing that is actually scarce.
    # Runs past the cap wait for a slot rather than launching another Chrome.
    max_concurrent_browsers: int = 2
    browser_slot_timeout_seconds: float = 180.0

    playwright_mcp_url: str = "http://localhost:8931/mcp"
    playwright_mcp_headless: bool = True
    playwright_mcp_command: str = "npx"
    playwright_mcp_args: str = "-y @playwright/mcp@latest --isolated"

    filesystem_mcp_root: str = "./data/workspace"
    filesystem_mcp_command: str = "npx"
    filesystem_mcp_args: str = "-y @modelcontextprotocol/server-filesystem"

    fetch_mcp_command: str = "uvx"
    fetch_mcp_args: str = "mcp-server-fetch"

    # Cross-trip memory: home city, dietary needs, airlines, past destinations.
    # A JSON-backed knowledge graph, so it survives restarts and is inspectable.
    memory_mcp_command: str = "npx"
    memory_mcp_args: str = "-y @modelcontextprotocol/server-memory"
    memory_file_path: str = "./data/memory.json"

    # Timezone and date arithmetic. Travel planning is full of it and models get
    # it wrong reliably — IST offsets, arrival times across zones, what season a
    # month falls in at the destination.
    time_mcp_command: str = "uvx"
    time_mcp_args: str = "mcp-server-time --local-timezone Asia/Kolkata"

    # Tavily is a hosted MCP server: no subprocess, no npx, just an HTTPS
    # endpoint. The key is a query parameter on it, so it is stored on its own
    # and the URL is assembled at use — a full URL in config would end up in
    # logs and error messages the first time a connection failed.
    tavily_api_key: str = ""
    tavily_mcp_base: str = "https://mcp.tavily.com/mcp/"

    travel_mcp_command: str = "python"
    travel_mcp_args: str = "-m travel_mcp.server"

    # --- Storage / retention ---
    database_url: str = "postgresql://travel_planner:travel_planner@localhost:5432/travel_planner"
    # A trip is archived and its thread purged as soon as the plan is finalised.
    # Set false to keep threads around for debugging a run after the fact.
    purge_thread_on_complete: bool = True
    # Threads never completed are swept after this many days.
    abandoned_thread_ttl_days: int = 7

    # --- Logging -----------------------------------------------------------------
    log_level: str = "INFO"
    env_mode: Literal["LOCAL", "DEVELOPMENT", "PRODUCTION"] = "LOCAL"

    # --- Derived helpers -----------------------------------------------------------

    def model_id_for(self, tier: ModelTier) -> str:
        return {
            "high": self.bedrock_model_tier_high,
            "mid": self.bedrock_model_tier_mid,
            "low": self.bedrock_model_tier_low,
            "fallback": self.bedrock_model_fallback,
        }[tier]

    def max_tokens_for(self, tier: ModelTier) -> int:
        return {
            "high": self.bedrock_max_tokens_high,
            "mid": self.bedrock_max_tokens_mid,
            "low": self.bedrock_max_tokens_low,
            "fallback": self.bedrock_max_tokens_high,
        }[tier]

    @property
    def travel_mcp_arg_list(self) -> list[str]:
        return self.travel_mcp_args.split()

    @property
    def playwright_mcp_arg_list(self) -> list[str]:
        args = self.playwright_mcp_args.split()
        if self.playwright_mcp_headless and "--headless" not in args:
            args.append("--headless")
        return args

    @property
    def filesystem_mcp_arg_list(self) -> list[str]:
        return [*self.filesystem_mcp_args.split(), self.filesystem_mcp_root]

    @property
    def fetch_mcp_arg_list(self) -> list[str]:
        return self.fetch_mcp_args.split()

    @property
    def memory_mcp_arg_list(self) -> list[str]:
        return self.memory_mcp_args.split()

    @property
    def time_mcp_arg_list(self) -> list[str]:
        return self.time_mcp_args.split()

    @property
    def tavily_mcp_url(self) -> str | None:
        """The endpoint, with the key attached. None when unconfigured."""
        if not self.tavily_api_key.strip():
            return None
        return f"{self.tavily_mcp_base}?tavilyApiKey={self.tavily_api_key.strip()}"

    @property
    def enabled_mcp_servers(self) -> tuple[str, ...]:
        return tuple(s.strip() for s in self.mcp_enabled_servers.split(",") if s.strip())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings, built once.

    Cached so every node, tool and factory shares one validated object instead
    of re-reading `.env` on each call. Clear with `get_settings.cache_clear()`
    in tests that need to vary the environment.

    `.env` is loaded into `os.environ` first, not only into `Settings`: boto3
    resolves AWS credentials from the process environment, and without this
    step it would fall through to whatever provider `~/.aws` happens to hold.
    Under Aegra the server has already exported `.env`, so this is a no-op there.
    """
    load_dotenv(override=False)
    return Settings()
