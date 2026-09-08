"""Bedrock model factory and the structured-output resilience loop.

Two things live here because they are inseparable in practice: how a model is
built, and how a model that produces malformed structured output is recovered.

**Model construction.** `ChatBedrockConverse` over the Converse API, one cached
instance per tier. `max_tokens` is always set — Bedrock reserves the model
maximum against the account quota when it is unset, so a 200-token weather
lookup can throttle a 4k-token itinerary call. Retries use botocore's adaptive
mode, which backs off on throttling instead of hammering.

**Structured output.** `with_structured_output()` is tool-calling underneath,
and tool-calling reliability on typed schemas varies between model families far
more than plain-text quality does. `invoke_structured()` therefore treats a
parse failure as a recoverable event with three escalating responses:

1. **Repair** — re-prompt with the validator's own error text appended, so the
   model sees exactly which field was wrong. One repair recovers most
   near-misses at the cost of one extra call on the same cheap tier.
2. **Escalate** — after repairs are exhausted, retry on the next tier up. A
   Micro-tier agent that cannot hold a schema moves to Lite, then Pro, then the
   cross-family fallback. Every escalation is recorded so tier assignments can
   be tuned from evidence rather than guessed.
3. **Fail loudly** — `StructuredOutputError` carries every (model, error) pair
   tried. Nothing is silently substituted.
"""

import time
from collections.abc import Sequence
from functools import lru_cache
from typing import Any, cast

from botocore.config import Config as BotoConfig
from langchain_aws import ChatBedrockConverse
from langchain_core.messages import BaseMessage, HumanMessage
from pydantic import BaseModel

from travel_planner.core.config import ModelTier, Settings, get_settings
from travel_planner.core.exceptions import ModelInvocationError, StructuredOutputError
from travel_planner.core.logging import get_logger
from travel_planner.core.state import AgentRun

log = get_logger(__name__)

#: Escalation order. `fallback` is a different model family, reached only after
#: every Nova tier has failed the same schema.
_ESCALATION: dict[ModelTier, ModelTier | None] = {
    "low": "mid",
    "mid": "high",
    "high": "fallback",
    "fallback": None,
}

_REPAIR_TEMPLATE = (
    "Your previous response did not match the required output schema.\n"
    "Validation error:\n{error}\n\n"
    "Respond again with a single object that matches the schema exactly. "
    "Do not add fields, omit required fields, or change field types."
)


# ---------------------------------------------------------------------------
# Model construction
# ---------------------------------------------------------------------------


@lru_cache(maxsize=8)
def make_model(tier: ModelTier, temperature: float | None = None) -> ChatBedrockConverse:
    """Build (and cache) the Converse model for a tier.

    Cached per (tier, temperature) because constructing the underlying boto3
    client is comparatively expensive and every node in every graph would
    otherwise pay it on each invocation.
    """
    settings = get_settings()
    return _build_model(settings, tier, temperature)


def _build_model(
    settings: Settings, tier: ModelTier, temperature: float | None
) -> ChatBedrockConverse:
    boto_config = BotoConfig(
        region_name=settings.aws_region,
        read_timeout=settings.bedrock_read_timeout,
        retries={"max_attempts": settings.bedrock_max_retries, "mode": settings.bedrock_retry_mode},
    )
    kwargs: dict = {
        "model": settings.model_id_for(tier),
        "region_name": settings.aws_region,
        "max_tokens": settings.max_tokens_for(tier),
        "temperature": settings.bedrock_temperature if temperature is None else temperature,
        "config": boto_config,
    }
    if settings.aws_profile:
        kwargs["credentials_profile_name"] = settings.aws_profile
    return ChatBedrockConverse(**kwargs)


# ---------------------------------------------------------------------------
# Structured output with repair and escalation
# ---------------------------------------------------------------------------


class StructuredResult[SchemaT: BaseModel]:
    """A parsed result plus the telemetry describing how it was obtained."""

    __slots__ = ("run", "value")

    def __init__(self, value: SchemaT, run: AgentRun) -> None:
        self.value = value
        self.run = run


def invoke_structured[SchemaT: BaseModel](
    schema: type[SchemaT],
    messages: Sequence[BaseMessage],
    *,
    tier: ModelTier,
    agent: str,
    settings: Settings | None = None,
) -> StructuredResult[SchemaT]:
    """Invoke a model and return output validated against `schema`.

    Applies the repair and escalation loop described in the module docstring.
    The returned `AgentRun` records which model finally succeeded, how many
    repairs it took, and whether the tier was raised — the frontend's run
    timeline and the tier-tuning evidence both come from this record.

    Raises:
        StructuredOutputError: every tier and repair attempt failed to parse.
        ModelInvocationError: Bedrock itself failed after the retry policy.
    """
    settings = settings or get_settings()
    attempts: list[tuple[str, str]] = []
    current: ModelTier | None = tier
    escalated = False
    started = time.perf_counter()

    while current is not None:
        model_id = settings.model_id_for(current)
        structured = make_model(current).with_structured_output(schema, include_raw=True)
        convo: list[BaseMessage] = list(messages)
        repairs = 0

        while True:
            try:
                # `include_raw=True` above is what makes this a dict of
                # raw/parsed/parsing_error; without it LangChain returns the
                # parsed model directly, and the signature's union covers both
                # modes. Narrowing to the one actually asked for.
                out = cast(dict[str, Any], structured.invoke(convo))
            except Exception as exc:  # boto/botocore/langchain transport errors
                log.error(
                    "model_invocation_failed",
                    agent=agent,
                    model_id=model_id,
                    error=type(exc).__name__,
                )
                raise ModelInvocationError(model_id, exc) from exc

            parsed = out.get("parsed")
            raw = out.get("raw")
            error = out.get("parsing_error")

            if parsed is not None and error is None:
                usage = getattr(raw, "usage_metadata", None) or {}
                run = AgentRun(
                    agent=agent,
                    model_id=model_id,
                    tier=current,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    input_tokens=int(usage.get("input_tokens", 0)),
                    output_tokens=int(usage.get("output_tokens", 0)),
                    repairs=repairs,
                    escalated=escalated,
                )
                if repairs or escalated:
                    log.warning(
                        "structured_output_recovered",
                        agent=agent,
                        model_id=model_id,
                        repairs=repairs,
                        escalated=escalated,
                    )
                return StructuredResult(parsed, run)

            # --- parse failure: repair or give up on this tier ---
            err_text = str(error) if error else "model returned no structured output"
            attempts.append((model_id, err_text[:300]))
            if repairs >= settings.structured_output_max_repairs:
                log.warning(
                    "structured_output_tier_exhausted",
                    agent=agent,
                    model_id=model_id,
                    repairs=repairs,
                )
                break
            repairs += 1
            log.info("structured_output_repair", agent=agent, model_id=model_id, attempt=repairs)
            if raw is not None:
                convo.append(raw)
            convo.append(HumanMessage(content=_REPAIR_TEMPLATE.format(error=err_text)))

        if not settings.structured_output_escalate_tier:
            break
        current = _ESCALATION[current]
        escalated = True

    raise StructuredOutputError(schema.__name__, attempts)
