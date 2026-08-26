from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import urlparse

import httpx

LOCAL_RUNTIME_TYPES = {"ollama", "lmstudio", "llamacpp", "vllm"}
HOSTED_PROVIDER_TYPES = {"openai-compatible", "openai", "anthropic", "gemini"}


def assert_discovery_target_allowed(runtime: str, endpoint: str) -> None:
    parsed = urlparse(endpoint)
    if runtime not in LOCAL_RUNTIME_TYPES:
        msg = f"Discovery runtime blocked: {runtime}"
        raise ValueError(msg)
    if parsed.scheme != "http" or not parsed.hostname:
        msg = "Discovery endpoint blocked: only explicit HTTP loopback endpoints are allowed"
        raise ValueError(msg)
    host = parsed.hostname
    if host == "localhost":
        return
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        msg = "Discovery endpoint blocked: hostname must be localhost or loopback IP"
        raise ValueError(msg) from exc
    if not address.is_loopback:
        msg = "Discovery endpoint blocked by SSRF policy: loopback required"
        raise ValueError(msg)


def assert_model_endpoint_allowed(provider: str, endpoint: str | None) -> None:
    normalized = provider.lower()
    if normalized in LOCAL_RUNTIME_TYPES:
        if endpoint is None:
            msg = "Local runtime providers require an explicit HTTP loopback endpoint"
            raise ValueError(msg)
        assert_discovery_target_allowed(normalized, endpoint)
        return
    if normalized not in HOSTED_PROVIDER_TYPES:
        return
    if endpoint is None and normalized in {"openai", "anthropic", "gemini"}:
        return
    if endpoint is None:
        msg = "Hosted provider endpoint is required"
        raise ValueError(msg)
    parsed = urlparse(endpoint)
    if parsed.scheme != "https" or not parsed.hostname:
        msg = "Hosted provider endpoints require HTTPS public destinations"
        raise ValueError(msg)
    host = parsed.hostname.lower()
    if host in {"localhost", "metadata.google.internal"} or host.endswith(".local"):
        msg = "Hosted provider endpoint blocked by SSRF policy"
        raise ValueError(msg)
    try:
        address = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return
    if (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    ):
        msg = "Hosted provider endpoint blocked by SSRF policy"
        raise ValueError(msg)
    msg = "Hosted provider IP-literal endpoints are blocked by default"
    raise ValueError(msg)


def assert_resolved_host_public(
    endpoint: str,
    *,
    resolver: Callable[..., Sequence[tuple[Any, ...]]] = socket.getaddrinfo,
) -> None:
    parsed = urlparse(endpoint)
    if not parsed.hostname:
        msg = "Hosted provider endpoint has no hostname"
        raise ValueError(msg)
    addresses = resolver(
        parsed.hostname,
        parsed.port or 443,
        type=socket.SOCK_STREAM,
    )
    if not addresses:
        msg = "Hosted provider hostname did not resolve"
        raise ValueError(msg)
    for address_info in addresses:
        socket_address = address_info[4]
        address = ipaddress.ip_address(str(socket_address[0]))
        if not address.is_global:
            msg = "Hosted provider DNS resolution blocked by SSRF policy"
            raise ValueError(msg)


def discover_local_models(
    runtime: str,
    endpoint: str,
    *,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, object]:
    assert_discovery_target_allowed(runtime, endpoint)
    path = "/api/tags" if runtime == "ollama" else "/v1/models"
    try:
        with httpx.Client(
            timeout=httpx.Timeout(3.0, connect=1.0),
            follow_redirects=False,
            transport=transport,
        ) as client:
            response = client.get(f"{endpoint.rstrip('/')}{path}")
        models = _discovery_models(response, runtime)
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        return {
            "runtime": runtime,
            "endpoint": endpoint,
            "allowed": True,
            "reachable": False,
            "models": [],
            "error": {"code": "discovery_failed", "message": "Local runtime discovery failed"},
        }
    return {
        "runtime": runtime,
        "endpoint": endpoint,
        "allowed": True,
        "reachable": True,
        "models": models,
    }


def _discovery_models(response: httpx.Response, runtime: str) -> list[str]:
    if response.is_redirect or response.status_code >= 400:
        msg = "local runtime returned an error"
        raise ValueError(msg)
    if len(response.content) > 512 * 1024:
        msg = "local runtime response too large"
        raise ValueError(msg)
    payload = response.json()
    rows = payload.get("models", []) if runtime == "ollama" else payload.get("data", [])
    key = "name" if runtime == "ollama" else "id"
    return [str(row[key]) for row in rows if isinstance(row, dict) and key in row]


def safe_discovery_report(runtime: str, endpoint: str) -> dict[str, object]:
    return discover_local_models(runtime, endpoint)
