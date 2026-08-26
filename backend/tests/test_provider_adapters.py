from __future__ import annotations

import json

import httpx
import pytest
from starklabs_evals.adapters import AdapterRequest, adapter_for
from starklabs_evals.discovery import assert_model_endpoint_allowed
from starklabs_evals.keychain import InMemoryKeychain


def test_hosted_endpoint_policy_blocks_loopback_metadata_and_ip_literals() -> None:
    blocked = [
        ("openai", "https://127.0.0.1/v1"),
        ("openai", "https://localhost/v1"),
        ("openai", "https://169.254.169.254/latest/meta-data"),
        ("openai-compatible", "http://api.example.test/v1"),
        ("anthropic", "https://10.0.0.5/v1"),
    ]
    for provider, endpoint in blocked:
        with pytest.raises(ValueError, match="blocked|HTTPS"):
            assert_model_endpoint_allowed(provider, endpoint)


def test_local_runtime_endpoint_policy_requires_http_loopback() -> None:
    assert_model_endpoint_allowed("ollama", "http://127.0.0.1:11434")
    assert_model_endpoint_allowed("lmstudio", "http://localhost:1234")
    with pytest.raises(ValueError, match="loopback"):
        assert_model_endpoint_allowed("ollama", "http://192.168.1.10:11434")
    with pytest.raises(ValueError, match="HTTP loopback"):
        assert_model_endpoint_allowed("ollama", "https://127.0.0.1:11434")


def test_hosted_adapter_without_injected_transport_is_config_only() -> None:
    adapter = adapter_for(
        "openai",
        credential_ref="model:1:test",
        keychain=InMemoryKeychain({"model:1:test": "must-not-be-read"}),
    )

    result = adapter.complete(
        AdapterRequest(provider="openai", model_id="gpt-test", prompt="hello", settings={}),
    )

    assert result.status == "failed"
    assert result.error == {
        "code": "hosted_provider_disabled",
        "message": "openai is configurable but real provider calls are disabled",
    }


def test_openai_compatible_adapter_uses_exact_model_settings_and_credential() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        payload = json.loads(request.content)
        assert payload == {
            "model": "local-model",
            "messages": [{"role": "user", "content": "hello"}],
            "temperature": 0,
            "top_p": 0.9,
        }
        assert request.headers["authorization"] == "Bearer secret-token"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "world"}}]},
        )

    keychain = InMemoryKeychain({"model:1:test": "secret-token"})
    adapter = adapter_for(
        "openai-compatible",
        endpoint="https://api.example.test/v1",
        credential_ref="model:1:test",
        keychain=keychain,
        transport=httpx.MockTransport(handler),
    )

    result = adapter.complete(
        AdapterRequest(
            provider="openai-compatible",
            model_id="local-model",
            prompt="hello",
            settings={"temperature": 0, "top_p": 0.9},
        ),
    )

    assert result.status == "completed"
    assert result.raw_output == "world"
    assert result.request_count == 1
    assert seen[0].url == "https://api.example.test/v1/chat/completions"


def test_adapter_errors_do_not_disclose_secret_or_response_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="secret-token leaked body")

    keychain = InMemoryKeychain({"model:1:test": "secret-token"})
    adapter = adapter_for(
        "openai",
        credential_ref="model:1:test",
        keychain=keychain,
        transport=httpx.MockTransport(handler),
    )

    result = adapter.complete(
        AdapterRequest(provider="openai", model_id="gpt-test", prompt="hello", settings={}),
    )

    serialized = json.dumps(result.__dict__)
    assert result.status == "failed"
    assert "secret-token" not in serialized
    assert "leaked body" not in serialized


def test_ollama_adapter_uses_loopback_endpoint_with_mock_transport_only() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url == "http://127.0.0.1:11434/api/generate"
        assert json.loads(request.content) == {
            "model": "llama-local",
            "prompt": "hello",
            "stream": False,
            "options": {"temperature": 0},
        }
        return httpx.Response(200, json={"response": "local world"})

    adapter = adapter_for(
        "ollama",
        endpoint="http://127.0.0.1:11434",
        transport=httpx.MockTransport(handler),
    )

    result = adapter.complete(
        AdapterRequest(
            provider="ollama",
            model_id="llama-local",
            prompt="hello",
            settings={"temperature": 0},
        ),
    )

    assert result.status == "completed"
    assert result.raw_output == "local world"
    assert len(seen) == 1
