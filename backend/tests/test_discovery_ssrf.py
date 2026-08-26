from __future__ import annotations

import httpx
import pytest
from starklabs_evals.discovery import (
    assert_discovery_target_allowed,
    assert_resolved_host_public,
    discover_local_models,
)


def test_ssrf_blocks_metadata_and_private_network_targets() -> None:
    blocked = [
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.0.5:8000",
        "http://192.168.1.5:8000",
        "http://172.16.1.5:8000",
        "http://example.com",
    ]
    for endpoint in blocked:
        try:
            assert_discovery_target_allowed("ollama", endpoint)
        except ValueError as exc:
            assert "blocked" in str(exc)
        else:  # pragma: no cover - assertion path
            raise AssertionError(f"expected {endpoint} to be blocked")


def test_ssrf_allows_explicit_loopback_runtime_types() -> None:
    assert_discovery_target_allowed("ollama", "http://127.0.0.1:11434")
    assert_discovery_target_allowed("lmstudio", "http://localhost:1234")
    assert_discovery_target_allowed("llamacpp", "http://[::1]:8080")


def test_hosted_dns_resolution_rejects_private_and_metadata_addresses() -> None:
    def private_resolver(
        *_args: object,
        **_kwargs: object,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [(2, 1, 6, "", ("169.254.169.254", 443))]

    with pytest.raises(ValueError, match="SSRF"):
        assert_resolved_host_public("https://models.example.test/v1", resolver=private_resolver)


def test_hosted_dns_resolution_accepts_only_public_addresses() -> None:
    def public_resolver(
        *_args: object,
        **_kwargs: object,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [(2, 1, 6, "", ("93.184.216.34", 443))]

    assert_resolved_host_public("https://models.example.test/v1", resolver=public_resolver)


def test_local_discovery_calls_only_the_validated_loopback_surface() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://127.0.0.1:11434/api/tags"
        return httpx.Response(200, json={"models": [{"name": "llama3:latest"}]})

    report = discover_local_models(
        "ollama",
        "http://127.0.0.1:11434",
        transport=httpx.MockTransport(handler),
    )

    assert report["reachable"] is True
    assert report["models"] == ["llama3:latest"]
