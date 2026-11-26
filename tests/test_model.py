import json
from pathlib import Path
from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import tool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, Field

from reviewer.fixtures import FixtureError, Mode, ReplayMissError
from reviewer.model import (
    ModelClient,
    ModelConfig,
    ModelConfigError,
    Refused,
    Reply,
    SpendCapReached,
    Usage,
    _anthropic_chat_model,
    load_model_config,
)
from reviewer.settings import MissingCredentialError, Settings

MODEL = "claude-opus-5-5"


class ScriptedChatModel(BaseChatModel):
    """Answers with the given messages in order and remembers what it was sent."""

    replies: list[AIMessage]
    calls: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.calls.append({"messages": list(messages), **kwargs})
        reply = self.replies[len(self.calls) - 1]
        return ChatResult(generations=[ChatGeneration(message=reply)])

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self.bind(tools=[convert_to_openai_tool(t) for t in tools], **kwargs)


def config(**overrides: Any) -> ModelConfig:
    fields: dict[str, Any] = {
        "model": MODEL,
        "effort": "high",
        "max_tokens": 16000,
        "spend_cap_usd": 1.0,
        "prices_usd_per_million": {
            MODEL: {"input": 4.0, "output": 20.0, "cache_read": 0.2, "cache_write": 5.0}
        },
    }
    fields.update(overrides)
    return ModelConfig.model_validate(fields)


def answer(
    content: Any = "done",
    *,
    stop_reason: str = "end_turn",
    input_tokens: int = 1000,
    output_tokens: int = 100,
    cache_read: int = 0,
    tool_calls: list[dict[str, Any]] | None = None,
    **metadata: Any,
) -> AIMessage:
    return AIMessage(
        content=content,
        tool_calls=tool_calls or [],
        response_metadata={
            "model": MODEL,
            "stop_reason": stop_reason,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": 0,
            },
            **metadata,
        },
    )


@tool
def read_file(path: str) -> str:
    """Read a file of the repository."""
    return path


THINKING_AND_TOOL = [
    {"type": "thinking", "thinking": "", "signature": "sig-abc"},
    {"type": "text", "text": "Reading the workflow."},
    {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "ci.yml"}},
]


def conversation() -> list[BaseMessage]:
    return [SystemMessage("You review repositories."), HumanMessage("Review octocat/hello-world.")]


@pytest.fixture
def no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


def test_record_then_replay_returns_the_same_messages(tmp_path: Path, no_key: None) -> None:
    first = answer(
        THINKING_AND_TOOL,
        stop_reason="tool_use",
        tool_calls=[{"id": "toolu_1", "name": "read_file", "args": {"path": "ci.yml"}}],
    )
    second = answer('{"findings": []}')
    recorder = ModelClient(
        config(),
        Mode.RECORD,
        fixtures=tmp_path,
        chat_model=ScriptedChatModel(replies=[first, second]),
    )

    history = conversation()
    recorded_first = recorder.invoke(history, tools=[read_file])
    assert isinstance(recorded_first, Reply)
    history += [recorded_first.message, ToolMessage("on: [push]", tool_call_id="toolu_1")]
    recorded_second = recorder.invoke(history, tools=[read_file])

    replayer = ModelClient(config(), Mode.REPLAY, fixtures=tmp_path)
    history = conversation()
    replayed_first = replayer.invoke(history, tools=[read_file])
    assert isinstance(replayed_first, Reply)
    history += [replayed_first.message, ToolMessage("on: [push]", tool_call_id="toolu_1")]
    replayed_second = replayer.invoke(history, tools=[read_file])

    assert isinstance(recorded_second, Reply) and isinstance(replayed_second, Reply)
    assert replayed_first.message.content == THINKING_AND_TOOL
    assert replayed_first.message.tool_calls == recorded_first.message.tool_calls
    assert replayed_first.stop_reason == "tool_use"
    assert replayed_second.text == '{"findings": []}'
    assert replayer.spend == recorder.spend
    assert len(list((tmp_path / "model").iterdir())) == 2


def test_assistant_messages_and_the_history_pass_through_unchanged(tmp_path: Path) -> None:
    reply = answer(THINKING_AND_TOOL, stop_reason="tool_use")
    chat_model = ScriptedChatModel(replies=[reply])
    history = conversation()
    before = [m.model_copy(deep=True) for m in history]

    result = ModelClient(config(), chat_model=chat_model).invoke(history)

    assert isinstance(result, Reply)
    assert result.message.content == THINKING_AND_TOOL
    assert history == before
    assert chat_model.calls[0]["messages"] == before


def test_a_request_that_was_never_recorded_fails_loudly(tmp_path: Path) -> None:
    ModelClient(
        config(), Mode.RECORD, fixtures=tmp_path, chat_model=ScriptedChatModel(replies=[answer()])
    ).invoke(conversation())
    replayer = ModelClient(config(), Mode.REPLAY, fixtures=tmp_path)

    with pytest.raises(ReplayMissError, match="re-recording"):
        replayer.invoke([HumanMessage("Review someone/else.")])


@pytest.mark.parametrize(
    "changed",
    [{"model": "claude-opus-5"}, {"effort": "medium"}, {"max_tokens": 8000}],
)
def test_changing_a_model_setting_invalidates_the_recording(
    tmp_path: Path, changed: dict[str, Any]
) -> None:
    ModelClient(
        config(), Mode.RECORD, fixtures=tmp_path, chat_model=ScriptedChatModel(replies=[answer()])
    ).invoke(conversation())
    prices = config().prices_usd_per_million | {
        "claude-opus-5": config().prices_usd_per_million[MODEL]
    }

    replayer = ModelClient(
        config(prices_usd_per_million=prices, **changed), Mode.REPLAY, fixtures=tmp_path
    )
    with pytest.raises(ReplayMissError):
        replayer.invoke(conversation())


def test_an_identical_request_made_twice_replays_both_answers_in_order(tmp_path: Path) -> None:
    replies = [answer("first"), answer("second")]
    recorder = ModelClient(
        config(), Mode.RECORD, fixtures=tmp_path, chat_model=ScriptedChatModel(replies=replies)
    )
    recorder.invoke(conversation())
    recorder.invoke(conversation())

    replayer = ModelClient(config(), Mode.REPLAY, fixtures=tmp_path)
    texts = [replayer.invoke(conversation()), replayer.invoke(conversation())]

    assert [r.text for r in texts if isinstance(r, Reply)] == ["first", "second"]
    with pytest.raises(ReplayMissError):
        replayer.invoke(conversation())


def test_replay_needs_no_key_and_live_mode_does(tmp_path: Path, no_key: None) -> None:
    (tmp_path / "model").mkdir()
    ModelClient(config(), Mode.REPLAY, fixtures=tmp_path)

    with pytest.raises(MissingCredentialError, match="ANTHROPIC_API_KEY"):
        ModelClient(config(), Mode.LIVE, settings=Settings.load(env_file=None))


def test_record_refuses_a_directory_that_already_holds_recordings(tmp_path: Path) -> None:
    (tmp_path / "model").mkdir()
    (tmp_path / "model" / "old-0.json").write_text("{}", encoding="utf-8")

    with pytest.raises(FixtureError, match="already holds recordings"):
        ModelClient(
            config(), Mode.RECORD, fixtures=tmp_path, chat_model=ScriptedChatModel(replies=[])
        )


def test_replay_without_recordings_and_record_without_a_directory_are_rejected(
    tmp_path: Path,
) -> None:
    with pytest.raises(FixtureError, match="does not exist"):
        ModelClient(config(), Mode.REPLAY, fixtures=tmp_path / "absent")
    with pytest.raises(ValueError, match="fixture directory"):
        ModelClient(config(), Mode.RECORD, chat_model=ScriptedChatModel(replies=[]))


def test_the_spend_counter_adds_up_tokens_and_cost() -> None:
    replies = [
        answer(input_tokens=10_000, output_tokens=2_000),
        answer(input_tokens=1_000, output_tokens=500, cache_read=20_000),
    ]
    client = ModelClient(config(), chat_model=ScriptedChatModel(replies=replies))

    first = client.invoke(conversation())
    client.invoke(conversation())

    # First: 10k in at $4/M + 2k out at $20/M = 0.04 + 0.04.
    # Second: 1k in, 500 out, 20k cached at $0.2/M = 0.004 + 0.01 + 0.004.
    assert isinstance(first, Reply)
    assert first.cost_usd == pytest.approx(0.08)
    assert client.spend.calls == 2
    assert client.spend.input_tokens == 11_000
    assert client.spend.output_tokens == 2_500
    assert client.spend.cache_read_tokens == 20_000
    assert client.spend.cost_usd == pytest.approx(0.098)


def test_the_spend_cap_stops_the_next_call() -> None:
    replies = [answer(input_tokens=100_000, output_tokens=10_000), answer()]
    chat_model = ScriptedChatModel(replies=replies)
    client = ModelClient(config(spend_cap_usd=0.5), chat_model=chat_model)

    client.invoke(conversation())  # $0.60: overshoots, but the call was allowed
    with pytest.raises(SpendCapReached, match=r"\$0\.6000 of a \$0\.50 cap"):
        client.invoke(conversation())
    assert len(chat_model.calls) == 1


def test_a_refusal_comes_back_as_a_value_and_still_counts(tmp_path: Path) -> None:
    refusal = answer(
        [],
        stop_reason="refusal",
        stop_details={"type": "refusal", "category": "cyber", "explanation": "Declined."},
    )
    recorder = ModelClient(
        config(), Mode.RECORD, fixtures=tmp_path, chat_model=ScriptedChatModel(replies=[refusal])
    )

    recorded = recorder.invoke(conversation())
    replayed = ModelClient(config(), Mode.REPLAY, fixtures=tmp_path).invoke(conversation())

    for result in (recorded, replayed):
        assert isinstance(result, Refused)
        assert result.category == "cyber"
        assert result.explanation == "Declined."
        assert result.cost_usd > 0
    assert recorder.spend.calls == 1


def test_usage_falls_back_to_langchain_counts_without_anthropic_metadata() -> None:
    message = AIMessage(
        content="x",
        usage_metadata={
            "input_tokens": 1300,
            "output_tokens": 50,
            "total_tokens": 1350,
            "input_token_details": {"cache_read": 300},
        },
    )

    assert Usage.of(message) == Usage(input_tokens=1000, output_tokens=50, cache_read_tokens=300)


def test_a_response_from_an_unpriced_model_is_an_error() -> None:
    client = ModelClient(
        config(), chat_model=ScriptedChatModel(replies=[answer(model="claude-unknown")])
    )

    with pytest.raises(ModelConfigError, match="claude-unknown"):
        client.invoke(conversation())


class Verdict(BaseModel):
    result: str
    reason: str


def test_the_anthropic_request_keeps_the_claude_api_rules() -> None:
    """Pins what the installed langchain-anthropic sends: re-check on every bump."""
    settings = Settings(anthropic_api_key="sk-test-not-a-real-key")  # type: ignore[arg-type]
    chat_model = _anthropic_chat_model(config(), settings)
    binding = chat_model.bind_tools([read_file]).bind(
        output_config={"format": {"type": "json_schema", "schema": {"type": "object"}}}
    )

    payload = chat_model._get_request_payload(  # type: ignore[attr-defined]
        conversation(), **binding.kwargs
    )

    assert payload["model"] == MODEL
    assert payload["max_tokens"] == 16000
    assert payload["thinking"] == {"type": "adaptive"}
    assert payload["output_config"]["effort"] == "high"
    assert payload["output_config"]["format"]["type"] == "json_schema"
    assert [t["name"] for t in payload["tools"]] == ["read_file"]
    for rejected in ("temperature", "top_p", "top_k", "tool_choice", "betas"):
        assert rejected not in payload, rejected
    assert "budget_tokens" not in json.dumps(payload)


def test_structured_output_is_sent_in_the_api_format_and_recorded(tmp_path: Path) -> None:
    chat_model = ScriptedChatModel(replies=[answer('{"result": "pass", "reason": "ok"}')])
    client = ModelClient(config(), Mode.RECORD, fixtures=tmp_path, chat_model=chat_model)

    reply = client.invoke(conversation(), output_schema=Verdict)

    sent = chat_model.calls[0]["output_config"]["format"]
    assert sent["type"] == "json_schema"
    assert sent["schema"]["additionalProperties"] is False
    assert sorted(sent["schema"]["required"]) == ["reason", "result"]
    assert isinstance(reply, Reply)
    assert Verdict.model_validate_json(reply.text).result == "pass"
    [recording] = (tmp_path / "model").iterdir()
    assert json.loads(recording.read_text(encoding="utf-8"))["request"]["output_format"] == sent


def test_the_packaged_configuration_loads() -> None:
    packaged = load_model_config()

    assert packaged.model == MODEL
    assert packaged.effort == "high"
    assert packaged.spend_cap_usd > 0
    assert MODEL in packaged.prices_usd_per_million


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"model": "claude-opus-5"}, "no price"),
        ({"effort": "extreme"}, "effort"),
        ({"thinking_budget": 4000}, "thinking_budget"),
        ({"temperature": 0}, "temperature"),
        ({"spend_cap_usd": 0}, "spend_cap_usd"),
    ],
)
def test_a_malformed_configuration_is_rejected(
    tmp_path: Path, change: dict[str, Any], message: str
) -> None:
    data = config().model_dump() | change
    path = tmp_path / "model.yaml"
    path.write_text(json.dumps(data), encoding="utf-8")  # JSON is YAML

    with pytest.raises(ModelConfigError, match=message):
        load_model_config(path)
