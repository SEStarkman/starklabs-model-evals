from types import SimpleNamespace

import pytest

from starkeval.providers import (
    LiteLLMProvider,
    Message,
    MockProvider,
    ModelRequest,
    resolve_provider,
)


@pytest.mark.asyncio
async def test_mock_provider_is_deterministic_and_credential_free() -> None:
    provider = MockProvider()
    request = ModelRequest(
        model="mock/baseline",
        messages=(Message(role="user", content="How many r letters are in strawberry?"),),
        settings={"temperature": 0},
    )

    first = await provider.complete(request)
    second = await provider.complete(request)

    assert first.output == second.output == "3"
    assert first.metadata == {"provider": "mock", "fixture": "strawberry-count"}


def test_provider_resolution_keeps_mock_separate_from_hosted_models() -> None:
    assert isinstance(resolve_provider("mock/baseline"), MockProvider)
    assert type(resolve_provider("openai/gpt-4o-mini")).__name__ == "LiteLLMProvider"


@pytest.mark.asyncio
async def test_litellm_provider_forwards_request_and_normalizes_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_completion(**kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="adapter response"))],
            model="provider/model-version",
        )

    monkeypatch.setattr(
        "starkeval.providers.importlib.import_module",
        lambda module_name: (
            SimpleNamespace(acompletion=fake_completion) if module_name == "litellm" else None
        ),
    )
    request = ModelRequest(
        model="openai/example",
        messages=(
            Message(role="system", content="Be direct."),
            Message(role="user", content="Reply."),
        ),
        settings={"temperature": 0, "max_tokens": 25},
    )

    response = await LiteLLMProvider().complete(request)

    assert captured == {
        "model": "openai/example",
        "messages": [
            {"role": "system", "content": "Be direct."},
            {"role": "user", "content": "Reply."},
        ],
        "temperature": 0,
        "max_tokens": 25,
    }
    assert response.output == "adapter response"
    assert response.metadata == {
        "provider": "litellm",
        "response_model": "provider/model-version",
    }
