import importlib
from collections.abc import Awaitable, Callable
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, JsonValue


class Message(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Literal["system", "user", "assistant"]
    content: str


class ModelRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    model: str
    messages: tuple[Message, ...]
    settings: dict[str, JsonValue]


class ProviderResponse(BaseModel):
    output: str
    metadata: dict[str, JsonValue]


class Provider(Protocol):
    async def complete(self, request: ModelRequest) -> ProviderResponse: ...


class MockProvider:
    async def complete(self, request: ModelRequest) -> ProviderResponse:
        prompt = request.messages[-1].content.casefold()
        if "strawberry" in prompt:
            return ProviderResponse(
                output="3",
                metadata={"provider": "mock", "fixture": "strawberry-count"},
            )
        if "poker" in prompt or "hold'em" in prompt:
            output = (
                "Fold. Calling 9.1bb to contest a 27.3bb final pot requires 33.3% equity. "
                "The button's value range includes Kx, two pair, and slow-played sets. "
                "Missed spade draws are the main bluff candidates, but Hero's As blocks "
                "natural ace-high spade bluffs. Without a read showing enough other bluffs, "
                "the bluff frequency is below the price required to call."
            )
            return ProviderResponse(
                output=output,
                metadata={"provider": "mock", "fixture": "poker-analysis"},
            )
        return ProviderResponse(
            output="mock response",
            metadata={"provider": "mock", "fixture": "default"},
        )


class LiteLLMProvider:
    async def complete(self, request: ModelRequest) -> ProviderResponse:
        try:
            module = importlib.import_module("litellm")
        except ModuleNotFoundError as error:
            raise RuntimeError(
                "Hosted/local model support requires: uv sync --extra providers"
            ) from error

        completion = module.acompletion
        call: Callable[..., Awaitable[object]] = completion
        response = await call(
            model=request.model,
            messages=[message.model_dump() for message in request.messages],
            **request.settings,
        )
        choices = getattr(response, "choices", None)
        if not choices:
            raise RuntimeError("LiteLLM returned no choices")
        output = getattr(choices[0].message, "content", None)
        if not isinstance(output, str):
            raise RuntimeError("LiteLLM returned a non-text response")
        response_model = getattr(response, "model", request.model)
        return ProviderResponse(
            output=output,
            metadata={"provider": "litellm", "response_model": str(response_model)},
        )


def resolve_provider(model: str) -> Provider:
    if model.startswith("mock/"):
        return MockProvider()
    return LiteLLMProvider()
