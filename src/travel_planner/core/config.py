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

    bedrock_model_tier_high: str = Field(description="Reasoning-heavy agents")
    bedrock_model_tier_mid: str = Field(description="Moderate agents")
    bedrock_model_tier_low: str = Field(description="Extraction-shaped agents")
    bedrock_model_fallback: str = Field(
        description="Per-agent fallback for unreliable structured output"
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
    playwright_mcp_url: str = "http://localhost:8931/mcp"
    playwright_mcp_headless: bool = True
    filesystem_mcp_root: str = "./data/workspace"
    travel_mcp_command: str = "python"
    travel_mcp_args: str = "-m travel_mcp.server"

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
    return Settings()  # type: ignore[call-arg]  # required fields come from the environment
