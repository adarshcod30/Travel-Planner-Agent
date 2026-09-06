"""The structured-output repair and escalation loop, without Bedrock.

`make_model` is replaced in the `bedrock` module namespace with a fake whose
`with_structured_output()` returns a runner that pops scripted results, so each
test controls exactly what "the model" answers on every call and can assert the
full sequence of (tier, messages) the loop produced.

`make_model` is `lru_cache`d in production; patching the module attribute
sidesteps the cache entirely, so no test depends on what an earlier one built.
"""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from travel_planner.core import bedrock as bedrock_mod
from travel_planner.core.bedrock import StructuredResult, invoke_structured
from travel_planner.core.config import Settings
from travel_planner.core.exceptions import ModelInvocationError, StructuredOutputError
from travel_planner.core.state import AgentRun


class Answer(BaseModel):
    city: str
    days: int


MESSAGES = [SystemMessage(content="You resolve destinations."), HumanMessage(content="Kyoto, 4")]

ERROR_TEXT = "1 validation error for Answer\ndays\n  Input should be a valid integer"


# --- scripted fake --------------------------------------------------------------------


def _ok(value: Answer, *, input_tokens: int = 0, output_tokens: int = 0) -> dict:
    raw = AIMessage(
        content="",
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    )
    return {"parsed": value, "raw": raw, "parsing_error": None}


def _bad(error_text: str = ERROR_TEXT, *, raw: AIMessage | None = None) -> dict:
    if raw is None:
        raw = AIMessage(content='{"city": "Kyoto", "days": "four"}')
    return {"parsed": None, "raw": raw, "parsing_error": ValueError(error_text)}


class _FakeRunner:
    """Stands in for `model.with_structured_output(...)`."""

    def __init__(self, tier: str, script: list, calls: list) -> None:
        self._tier = tier
        self._script = script
        self._calls = calls

    def invoke(self, messages):
        # Snapshot: the loop mutates its conversation list between calls.
        self._calls.append((self._tier, list(messages)))
        if not self._script:
            raise AssertionError(f"tier {self._tier!r} invoked more times than scripted")
        result = self._script.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


class _FakeModel:
    """Stands in for the `ChatBedrockConverse` instance `make_model` returns."""

    def __init__(self, tier: str, script: list, calls: list, wso_calls: list) -> None:
        self._tier = tier
        self._script = script
        self._calls = calls
        self._wso_calls = wso_calls

    def with_structured_output(self, schema, include_raw: bool = False):
        self._wso_calls.append((self._tier, schema, include_raw))
        return _FakeRunner(self._tier, self._script, self._calls)


class FakeBedrock:
    """Owns the per-tier scripts and the call log for one test."""

    def __init__(self, scripts: dict[str, list]) -> None:
        self.scripts = {tier: list(script) for tier, script in scripts.items()}
        self.calls: list[tuple[str, list]] = []
        self.wso_calls: list[tuple[str, type, bool]] = []

    def make_model(self, tier, temperature=None):
        if tier not in self.scripts:
            raise AssertionError(f"tier {tier!r} was not scripted for this test")
        return _FakeModel(tier, self.scripts[tier], self.calls, self.wso_calls)

    @property
    def tiers_called(self) -> list[str]:
        return [tier for tier, _ in self.calls]

    def assert_scripts_consumed(self) -> None:
        leftover = {tier: len(script) for tier, script in self.scripts.items() if script}
        assert not leftover, f"unconsumed scripted results: {leftover}"


def _settings(**overrides) -> Settings:
    values = {
        "bedrock_model_tier_high": "m-high",
        "bedrock_model_tier_mid": "m-mid",
        "bedrock_model_tier_low": "m-low",
        "bedrock_model_fallback": "m-fb",
        "structured_output_max_repairs": 1,
        "structured_output_escalate_tier": True,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def settings(monkeypatch) -> Settings:
    """Sentinel model ids, and `get_settings` patched so the default path sees them too."""
    built = _settings()
    monkeypatch.setattr(bedrock_mod, "get_settings", lambda: built)
    return built


def _install(monkeypatch, scripts: dict[str, list]) -> FakeBedrock:
    fake = FakeBedrock(scripts)
    monkeypatch.setattr(bedrock_mod, "make_model", fake.make_model)
    return fake


# --- (a) success on the first call ----------------------------------------------------


def test_success_first_call(monkeypatch, settings):
    answer = Answer(city="Kyoto", days=4)
    fake = _install(monkeypatch, {"low": [_ok(answer, input_tokens=42, output_tokens=17)]})

    result = invoke_structured(Answer, MESSAGES, tier="low", agent="destination", settings=settings)

    assert isinstance(result, StructuredResult)
    assert result.value is answer
    run = result.run
    assert isinstance(run, AgentRun)
    assert run.agent == "destination"
    assert run.model_id == "m-low"
    assert run.tier == "low"
    assert run.repairs == 0
    assert run.escalated is False
    assert run.input_tokens == 42
    assert run.output_tokens == 17
    assert run.duration_ms >= 0

    assert fake.tiers_called == ["low"]
    assert fake.calls[0][1] == MESSAGES
    assert fake.wso_calls == [("low", Answer, True)]
    fake.assert_scripts_consumed()


def test_default_settings_come_from_get_settings(monkeypatch, settings):
    """Omitting `settings=` must resolve model ids through the (patched) `get_settings`."""
    fake = _install(monkeypatch, {"mid": [_ok(Answer(city="Lisbon", days=3))]})

    result = invoke_structured(Answer, MESSAGES, tier="mid", agent="hotel")

    assert result.run.model_id == "m-mid"
    assert fake.tiers_called == ["mid"]


def test_missing_usage_metadata_defaults_to_zero(monkeypatch, settings):
    raw = AIMessage(content="")  # no usage_metadata at all
    fake = _install(
        monkeypatch,
        {"low": [{"parsed": Answer(city="Oslo", days=2), "raw": raw, "parsing_error": None}]},
    )

    result = invoke_structured(Answer, MESSAGES, tier="low", agent="weather", settings=settings)

    assert result.run.input_tokens == 0
    assert result.run.output_tokens == 0
    fake.assert_scripts_consumed()


# --- (b) one repair on the same tier --------------------------------------------------


def test_one_parse_failure_then_success_is_a_repair(monkeypatch, settings):
    bad_raw = AIMessage(content='{"city": "Kyoto", "days": "four"}')
    answer = Answer(city="Kyoto", days=4)
    fake = _install(monkeypatch, {"low": [_bad(raw=bad_raw), _ok(answer)]})

    result = invoke_structured(Answer, MESSAGES, tier="low", agent="destination", settings=settings)

    assert result.value is answer
    assert result.run.repairs == 1
    assert result.run.escalated is False
    assert result.run.model_id == "m-low"
    assert fake.tiers_called == ["low", "low"]

    first_messages = fake.calls[0][1]
    second_messages = fake.calls[1][1]
    assert first_messages == MESSAGES

    # Repair turn: original conversation, the model's bad reply, then the repair prompt.
    assert second_messages[: len(MESSAGES)] == MESSAGES
    assert second_messages[-2] is bad_raw
    repair = second_messages[-1]
    assert isinstance(repair, HumanMessage)
    assert ERROR_TEXT in repair.content
    assert "did not match the required output schema" in repair.content
    assert len(second_messages) == len(MESSAGES) + 2
    fake.assert_scripts_consumed()


def test_repair_without_raw_message_appends_only_the_prompt(monkeypatch, settings):
    """A `None` raw reply must not be appended; the fallback error text is used."""
    empty = {"parsed": None, "raw": None, "parsing_error": None}
    answer = Answer(city="Kyoto", days=4)
    fake = _install(monkeypatch, {"low": [empty, _ok(answer)]})

    result = invoke_structured(Answer, MESSAGES, tier="low", agent="destination", settings=settings)

    assert result.run.repairs == 1
    second_messages = fake.calls[1][1]
    assert len(second_messages) == len(MESSAGES) + 1
    assert all(message is not None for message in second_messages)
    assert "model returned no structured output" in second_messages[-1].content


def test_max_repairs_two_allows_two_repairs_on_one_tier(monkeypatch, settings):
    settings = _settings(structured_output_max_repairs=2)
    answer = Answer(city="Kyoto", days=4)
    fake = _install(monkeypatch, {"low": [_bad(), _bad(), _ok(answer)]})

    result = invoke_structured(Answer, MESSAGES, tier="low", agent="destination", settings=settings)

    assert result.run.repairs == 2
    assert result.run.escalated is False
    assert fake.tiers_called == ["low", "low", "low"]
    # Each repair turn grows the conversation by two: bad reply + repair prompt.
    assert len(fake.calls[2][1]) == len(MESSAGES) + 4
    fake.assert_scripts_consumed()


# --- (c) escalation to the next tier ---------------------------------------------------


def test_low_exhausted_then_mid_succeeds_escalates(monkeypatch, settings):
    answer = Answer(city="Kyoto", days=4)
    fake = _install(monkeypatch, {"low": [_bad(), _bad()], "mid": [_ok(answer)]})

    result = invoke_structured(Answer, MESSAGES, tier="low", agent="destination", settings=settings)

    assert result.value is answer
    assert result.run.escalated is True
    assert result.run.model_id == "m-mid"
    assert result.run.tier == "mid"
    # Repairs count is per tier: the successful tier needed none.
    assert result.run.repairs == 0
    assert fake.tiers_called == ["low", "low", "mid"]
    # The escalated tier starts from the original conversation, not the repair history.
    assert fake.calls[2][1] == MESSAGES
    fake.assert_scripts_consumed()


def test_escalation_walks_low_mid_high_fallback(monkeypatch, settings):
    answer = Answer(city="Kyoto", days=4)
    fake = _install(
        monkeypatch,
        {
            "low": [_bad(), _bad()],
            "mid": [_bad(), _bad()],
            "high": [_bad(), _bad()],
            "fallback": [_ok(answer)],
        },
    )

    result = invoke_structured(Answer, MESSAGES, tier="low", agent="itinerary", settings=settings)

    assert result.run.model_id == "m-fb"
    assert result.run.tier == "fallback"
    assert result.run.escalated is True
    assert fake.tiers_called == ["low", "low", "mid", "mid", "high", "high", "fallback"]
    fake.assert_scripts_consumed()


def test_escalation_starts_from_the_requested_tier(monkeypatch, settings):
    """A `high` agent never falls back to a cheaper tier; it goes straight to fallback."""
    answer = Answer(city="Kyoto", days=4)
    fake = _install(monkeypatch, {"high": [_bad(), _bad()], "fallback": [_ok(answer)]})

    result = invoke_structured(Answer, MESSAGES, tier="high", agent="itinerary", settings=settings)

    assert result.run.model_id == "m-fb"
    assert fake.tiers_called == ["high", "high", "fallback"]


# --- (d) every tier fails ---------------------------------------------------------------


def test_every_tier_fails_raises_with_all_attempts(monkeypatch, settings):
    fake = _install(
        monkeypatch,
        {
            "low": [_bad("low-err-1"), _bad("low-err-2")],
            "mid": [_bad("mid-err-1"), _bad("mid-err-2")],
            "high": [_bad("high-err-1"), _bad("high-err-2")],
            "fallback": [_bad("fb-err-1"), _bad("fb-err-2")],
        },
    )

    with pytest.raises(StructuredOutputError) as excinfo:
        invoke_structured(Answer, MESSAGES, tier="low", agent="destination", settings=settings)

    exc = excinfo.value
    assert exc.schema_name == "Answer"
    assert [model for model, _ in exc.attempts] == [
        "m-low",
        "m-low",
        "m-mid",
        "m-mid",
        "m-high",
        "m-high",
        "m-fb",
        "m-fb",
    ]
    assert [error for _, error in exc.attempts] == [
        "low-err-1",
        "low-err-2",
        "mid-err-1",
        "mid-err-2",
        "high-err-1",
        "high-err-2",
        "fb-err-1",
        "fb-err-2",
    ]
    assert "Answer" in str(exc)
    assert "8 attempt(s)" in str(exc)
    fake.assert_scripts_consumed()


def test_every_tier_fails_with_no_repairs_lists_each_model_once(monkeypatch, settings):
    settings = _settings(structured_output_max_repairs=0)
    fake = _install(
        monkeypatch,
        {"low": [_bad()], "mid": [_bad()], "high": [_bad()], "fallback": [_bad()]},
    )

    with pytest.raises(StructuredOutputError) as excinfo:
        invoke_structured(Answer, MESSAGES, tier="low", agent="destination", settings=settings)

    assert [model for model, _ in excinfo.value.attempts] == ["m-low", "m-mid", "m-high", "m-fb"]
    assert fake.tiers_called == ["low", "mid", "high", "fallback"]
    fake.assert_scripts_consumed()


def test_attempt_error_text_is_truncated(monkeypatch, settings):
    settings = _settings(structured_output_max_repairs=0, structured_output_escalate_tier=False)
    _install(monkeypatch, {"low": [_bad("x" * 1000)]})

    with pytest.raises(StructuredOutputError) as excinfo:
        invoke_structured(Answer, MESSAGES, tier="low", agent="destination", settings=settings)

    ((_, error_text),) = excinfo.value.attempts
    assert len(error_text) == 300


# --- (e) escalation disabled -------------------------------------------------------------


def test_escalation_disabled_fails_after_low_only(monkeypatch, settings):
    settings = _settings(structured_output_escalate_tier=False)
    # `mid` is scripted so that an unexpected escalation would consume it (and fail below).
    fake = _install(monkeypatch, {"low": [_bad(), _bad()], "mid": [_ok(Answer(city="x", days=1))]})

    with pytest.raises(StructuredOutputError) as excinfo:
        invoke_structured(Answer, MESSAGES, tier="low", agent="destination", settings=settings)

    assert [model for model, _ in excinfo.value.attempts] == ["m-low", "m-low"]
    assert fake.tiers_called == ["low", "low"]
    assert fake.scripts["mid"], "mid must not have been invoked when escalation is disabled"


def test_escalation_disabled_still_repairs_on_the_same_tier(monkeypatch, settings):
    settings = _settings(structured_output_escalate_tier=False)
    answer = Answer(city="Kyoto", days=4)
    fake = _install(monkeypatch, {"low": [_bad(), _ok(answer)]})

    result = invoke_structured(Answer, MESSAGES, tier="low", agent="destination", settings=settings)

    assert result.run.repairs == 1
    assert result.run.escalated is False
    assert fake.tiers_called == ["low", "low"]


# --- (f) transport failure ----------------------------------------------------------------


def test_runner_exception_becomes_model_invocation_error(monkeypatch, settings):
    boom = RuntimeError("connection reset")
    fake = _install(monkeypatch, {"low": [boom], "mid": [_ok(Answer(city="x", days=1))]})

    with pytest.raises(ModelInvocationError) as excinfo:
        invoke_structured(Answer, MESSAGES, tier="low", agent="destination", settings=settings)

    exc = excinfo.value
    assert exc.model_id == "m-low"
    assert exc.cause is boom
    assert exc.__cause__ is boom
    assert "RuntimeError" in str(exc)
    assert "connection reset" in str(exc)
    # Transport errors are not parse failures: no repair, no escalation.
    assert fake.tiers_called == ["low"]
    assert fake.scripts["mid"], "mid must not be tried after a transport error"


def test_runner_exception_after_a_repair_reports_the_same_model(monkeypatch, settings):
    boom = RuntimeError("throttled")
    fake = _install(monkeypatch, {"low": [_bad(), boom]})

    with pytest.raises(ModelInvocationError) as excinfo:
        invoke_structured(Answer, MESSAGES, tier="low", agent="destination", settings=settings)

    assert excinfo.value.model_id == "m-low"
    assert fake.tiers_called == ["low", "low"]


def test_runner_exception_on_escalated_tier_reports_that_model(monkeypatch, settings):
    boom = RuntimeError("throttled")
    fake = _install(monkeypatch, {"low": [_bad(), _bad()], "mid": [boom]})

    with pytest.raises(ModelInvocationError) as excinfo:
        invoke_structured(Answer, MESSAGES, tier="low", agent="destination", settings=settings)

    assert excinfo.value.model_id == "m-mid"
    assert fake.tiers_called == ["low", "low", "mid"]
