"""The only module that calls the model (ADR 0002).

It reads the model id, effort, `max_tokens`, the spend cap and the price table from
`model.yaml`; counts tokens and cost on every call; and runs in one of three modes:

- `live`: calls Claude through `langchain-anthropic`;
- `record`: the same, and saves every exchange under the review's fixture directory;
- `replay`: serves recorded exchanges back with no network and no key, and fails on a request
  that was never recorded.

Claude API rules it keeps: thinking is adaptive and never given a budget or turned off; the
effort is always sent; no `temperature`, no forced `tool_choice`; messages are passed and
returned unchanged, so assistant turns (thinking blocks included) go back exactly as received;
the stop reason is checked before the content, and a refusal comes back as a `Refused` value
rather than as content.

Structured output is requested in the API's own format (`output_config.format`, the schema
converted by the SDK's `transform_schema`), never through a forced tool call. Validating the
answer against the schema is the caller's job.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from anthropic import transform_schema
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, message_to_dict, messages_from_dict
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from reviewer.fixtures import FixtureStore, Mode
from reviewer.settings import Settings

Effort = Literal["low", "medium", "high", "xhigh", "max"]


class Price(BaseModel):
    """US dollars per million tokens."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input: float = Field(ge=0)
    output: float = Field(ge=0)
    cache_read: float = Field(ge=0)
    cache_write: float = Field(ge=0)


class ModelConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    model: str = Field(min_length=1)
    effort: Effort
    max_tokens: int = Field(ge=1024, le=32000)
    spend_cap_usd: float = Field(gt=0)
    prices_usd_per_million: dict[str, Price]

    @model_validator(mode="after")
    def _model_has_a_price(self) -> Self:
        if self.model not in self.prices_usd_per_million:
            raise ValueError(f"no price for model {self.model!r} in prices_usd_per_million")
        return self


class ModelConfigError(ValueError):
    """`model.yaml` is missing, is not YAML, or does not match the schema."""


def load_model_config(path: Path | None = None) -> ModelConfig:
    """Load and validate `path`, or the `model.yaml` shipped in the package."""
    source = path if path is not None else files("reviewer") / "model.yaml"
    try:
        data = yaml.safe_load(source.read_text(encoding="utf-8"))
        return ModelConfig.model_validate(data)
    except OSError as error:
        raise ModelConfigError(f"cannot read {source}: {error}") from error
    except yaml.YAMLError as error:
        raise ModelConfigError(f"{source} is not valid YAML: {error}") from error
    except ValidationError as error:
        raise ModelConfigError(
            f"{source} does not match the model configuration:\n{error}"
        ) from error


@dataclass(frozen=True)
class Usage:
    """Tokens of one call, as the API reports them. `input_tokens` excludes cache reads."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def cost_usd(self, price: Price) -> float:
        return (
            self.input_tokens * price.input
            + self.output_tokens * price.output
            + self.cache_read_tokens * price.cache_read
            + self.cache_write_tokens * price.cache_write
        ) / 1_000_000

    @classmethod
    def of(cls, message: AIMessage) -> "Usage":
        raw = message.response_metadata.get("usage")
        if isinstance(raw, dict):
            return cls(
                input_tokens=raw.get("input_tokens") or 0,
                output_tokens=raw.get("output_tokens") or 0,
                cache_read_tokens=raw.get("cache_read_input_tokens") or 0,
                cache_write_tokens=raw.get("cache_creation_input_tokens") or 0,
            )
        # Not an Anthropic response (a test model): fall back to LangChain's summary.
        summary = message.usage_metadata or {}
        details = summary.get("input_token_details") or {}
        cache_read = details.get("cache_read") or 0
        cache_write = details.get("cache_creation") or 0
        return cls(
            input_tokens=(summary.get("input_tokens") or 0) - cache_read - cache_write,
            output_tokens=summary.get("output_tokens") or 0,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        )


@dataclass
class Spend:
    """What one review has used so far."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0

    def add(self, usage: Usage, cost_usd: float) -> None:
        self.calls += 1
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cache_read_tokens += usage.cache_read_tokens
        self.cache_write_tokens += usage.cache_write_tokens
        self.cost_usd += cost_usd


class SpendCapReached(RuntimeError):
    """The review has spent its cap; the caller ends with what it has."""


@dataclass(frozen=True)
class Reply:
    """A response that was not refused. `message` goes back into the history unchanged."""

    message: AIMessage
    stop_reason: str | None
    usage: Usage
    cost_usd: float

    @property
    def text(self) -> str:
        """The text blocks of the answer, joined; thinking and tool calls left out."""
        content = self.message.content
        if isinstance(content, str):
            return content
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )


@dataclass(frozen=True)
class Refused:
    """The model declined (`stop_reason` is `refusal`). Its content is not to be used."""

    category: str | None
    explanation: str | None
    message: AIMessage = field(repr=False)
    usage: Usage = Usage()
    cost_usd: float = 0.0


def canonical_message(message: BaseMessage) -> dict[str, Any]:
    """What the model sees of a message; ids and metadata are left out."""
    canonical: dict[str, Any] = {"type": message.type, "content": message.content}
    if isinstance(message, AIMessage) and message.tool_calls:
        canonical["tool_calls"] = [
            {"id": call["id"], "name": call["name"], "args": call["args"]}
            for call in message.tool_calls
        ]
    tool_call_id = getattr(message, "tool_call_id", None)
    if tool_call_id is not None:
        canonical["tool_call_id"] = tool_call_id
    return canonical


class ModelClient:
    """Calls the model for one review, counting spend against the cap."""

    def __init__(
        self,
        config: ModelConfig,
        mode: Mode = Mode.LIVE,
        *,
        fixtures: Path | None = None,
        chat_model: BaseChatModel | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.config = config
        self.mode = mode
        self.spend = Spend()
        self._store: FixtureStore | None = None
        self._chat_model: BaseChatModel | None = None
        if mode is not Mode.LIVE:
            if fixtures is None:
                raise ValueError(f"{mode.value} mode needs a fixture directory")
            self._store = FixtureStore(fixtures, "model", mode)
        if mode is not Mode.REPLAY:
            self._chat_model = chat_model or _anthropic_chat_model(
                config, settings or Settings.load()
            )

    def invoke(
        self,
        messages: Sequence[BaseMessage],
        *,
        tools: Sequence[Any] = (),
        output_schema: type[BaseModel] | None = None,
    ) -> Reply | Refused:
        """One model call. Raises `SpendCapReached` before calling once the cap is reached."""
        if self.spend.cost_usd >= self.config.spend_cap_usd:
            raise SpendCapReached(
                f"spent ${self.spend.cost_usd:.4f} of a ${self.config.spend_cap_usd:.2f} cap"
            )
        output_format = (
            {"type": "json_schema", "schema": transform_schema(output_schema)}
            if output_schema is not None
            else None
        )
        request = self._canonical_request(messages, tools, output_format)

        if self._store is not None and self.mode is Mode.REPLAY:
            [message] = messages_from_dict([self._store.load(request)])
            assert isinstance(message, AIMessage)  # noqa: S101 (a recording holds an AI message)
        else:
            assert self._chat_model is not None  # noqa: S101 (set for live and record)
            runnable: Any = self._chat_model
            if tools:
                runnable = runnable.bind_tools(list(tools))
            if output_format is not None:
                runnable = runnable.bind(output_config={"format": output_format})
            message = runnable.invoke(list(messages))
            if not isinstance(message, AIMessage):
                raise TypeError(f"the chat model returned {type(message).__name__}")
            if self._store is not None:
                self._store.save(request, message_to_dict(message))

        usage = Usage.of(message)
        cost = usage.cost_usd(self._price_of(message))
        self.spend.add(usage, cost)

        stop_reason = message.response_metadata.get("stop_reason")
        if stop_reason == "refusal":
            details = message.response_metadata.get("stop_details") or {}
            return Refused(
                category=details.get("category"),
                explanation=details.get("explanation"),
                message=message,
                usage=usage,
                cost_usd=cost,
            )
        return Reply(message=message, stop_reason=stop_reason, usage=usage, cost_usd=cost)

    def _canonical_request(
        self,
        messages: Sequence[BaseMessage],
        tools: Sequence[Any],
        output_format: dict[str, Any] | None,
    ) -> dict[str, Any]:
        return {
            "model": self.config.model,
            "effort": self.config.effort,
            "max_tokens": self.config.max_tokens,
            "messages": [canonical_message(m) for m in messages],
            "tools": [convert_to_openai_tool(tool) for tool in tools],
            "output_format": output_format,
        }

    def _price_of(self, message: AIMessage) -> Price:
        served_by = message.response_metadata.get("model") or self.config.model
        price = self.config.prices_usd_per_million.get(served_by)
        if price is None:
            raise ModelConfigError(f"the response came from {served_by!r}, which has no price")
        return price


def _anthropic_chat_model(config: ModelConfig, settings: Settings) -> BaseChatModel:
    from langchain_anthropic import ChatAnthropic

    return ChatAnthropic(
        model=config.model,
        api_key=settings.require_anthropic_key(),
        max_tokens=config.max_tokens,
        thinking={"type": "adaptive"},
        output_config={"effort": config.effort},
    )
