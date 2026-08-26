from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

import httpx

from .discovery import (
    HOSTED_PROVIDER_TYPES,
    LOCAL_RUNTIME_TYPES,
    assert_model_endpoint_allowed,
    assert_resolved_host_public,
)

if TYPE_CHECKING:
    from .keychain import Keychain


@dataclass(frozen=True)
class AdapterRequest:
    provider: str
    model_id: str
    prompt: str
    settings: dict[str, object]


@dataclass(frozen=True)
class AdapterResult:
    status: str
    raw_output: str | None
    error: dict[str, str] | None
    timing_ms: int
    request_count: int = 1


class ProviderAdapter(Protocol):
    def complete(self, request: AdapterRequest) -> AdapterResult: ...


class FakeAdapter:
    def complete(self, request: AdapterRequest) -> AdapterResult:
        start = time.perf_counter()
        delay_ms = request.settings.get("delay_ms")
        if isinstance(delay_ms, int | float) and delay_ms > 0:
            time.sleep(min(float(delay_ms), 1_000) / 1_000)
        if "fail" in request.model_id.lower() or "[FAIL]" in request.prompt:
            return AdapterResult(
                status="failed",
                raw_output=None,
                error={"code": "fake_provider_failure", "message": "Deterministic fake failure"},
                timing_ms=int((time.perf_counter() - start) * 1000),
            )
        digest = hashlib.sha256(
            f"{request.model_id}\n{request.prompt}\n{request.settings}".encode(),
        ).hexdigest()[:12]
        output = f"[fake:{request.model_id}:{digest}] {request.prompt[:240]}"
        return AdapterResult(
            status="completed",
            raw_output=output,
            error=None,
            timing_ms=int((time.perf_counter() - start) * 1000),
        )


class ConfigOnlyHostedAdapter:
    def complete(self, request: AdapterRequest) -> AdapterResult:
        start = time.perf_counter()
        return AdapterResult(
            status="failed",
            raw_output=None,
            error={
                "code": "hosted_provider_disabled",
                "message": (
                    f"{request.provider} is configurable but real provider calls are disabled"
                ),
            },
            timing_ms=int((time.perf_counter() - start) * 1000),
        )


HOSTED_DEFAULT_ENDPOINTS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
}
SUPPORTED_SETTINGS = {"temperature", "top_p", "max_tokens", "seed", "stop"}
MAX_RESPONSE_BYTES = 512 * 1024


def _allowed_settings(settings: dict[str, object]) -> dict[str, object]:
    return {key: settings[key] for key in settings if key in SUPPORTED_SETTINGS}


def _safe_failure(code: str, message: str, start: float) -> AdapterResult:
    return AdapterResult(
        status="failed",
        raw_output=None,
        error={"code": code, "message": message},
        timing_ms=int((time.perf_counter() - start) * 1000),
    )


class SafeHttpAdapter:
    def __init__(
        self,
        *,
        provider: str,
        endpoint: str,
        credential_ref: str | None,
        keychain: Keychain | None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        assert_model_endpoint_allowed(provider, endpoint)
        self.provider = provider.lower()
        self.endpoint = endpoint.rstrip("/")
        self.credential_ref = credential_ref
        self.keychain = keychain
        self.transport = transport

    def complete(self, request: AdapterRequest) -> AdapterResult:
        start = time.perf_counter()
        secret = self._credential()
        try:
            if self.provider in HOSTED_PROVIDER_TYPES and self.transport is None:
                assert_resolved_host_public(self.endpoint)
            with httpx.Client(
                timeout=httpx.Timeout(10.0, connect=3.0, read=10.0, write=10.0, pool=3.0),
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                response = client.post(
                    self._url(request.model_id),
                    headers=self._headers(secret),
                    json=self._body(request),
                )
                if response.is_redirect:
                    return _safe_failure(
                        "provider_redirect_blocked",
                        "provider redirect blocked",
                        start,
                    )
                if len(response.content) > MAX_RESPONSE_BYTES:
                    return _safe_failure(
                        "provider_response_too_large",
                        "provider response too large",
                        start,
                    )
                if response.status_code >= 400:
                    return _safe_failure("provider_http_error", "provider returned an error", start)
                return AdapterResult(
                    status="completed",
                    raw_output=self._extract_output(response),
                    error=None,
                    timing_ms=int((time.perf_counter() - start) * 1000),
                    request_count=1,
                )
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return _safe_failure("provider_error", "provider request failed", start)

    def _credential(self) -> str | None:
        if not self.credential_ref or not self.keychain:
            return None
        return self.keychain.get(self.credential_ref)

    def _headers(self, secret: str | None) -> dict[str, str]:
        headers = {"content-type": "application/json"}
        if self.provider in {"openai", "openai-compatible"} and secret:
            headers["authorization"] = f"Bearer {secret}"
        if self.provider == "anthropic":
            headers["anthropic-version"] = "2023-06-01"
            if secret:
                headers["x-api-key"] = secret
        if self.provider == "gemini" and secret:
            headers["x-goog-api-key"] = secret
        return headers

    def _url(self, model_id: str) -> str:
        if self.provider in {"openai", "openai-compatible"}:
            return f"{self.endpoint}/chat/completions"
        if self.provider == "ollama":
            return f"{self.endpoint}/api/generate"
        if self.provider == "anthropic":
            return f"{self.endpoint}/messages"
        if self.provider == "gemini":
            return f"{self.endpoint}/models/{model_id}:generateContent"
        return f"{self.endpoint}/chat/completions"

    def _body(self, request: AdapterRequest) -> dict[str, Any]:
        settings = _allowed_settings(request.settings)
        if self.provider in {"openai", "openai-compatible"}:
            return {
                "model": request.model_id,
                "messages": [{"role": "user", "content": request.prompt}],
                **settings,
            }
        if self.provider == "anthropic":
            return {
                "model": request.model_id,
                "messages": [{"role": "user", "content": request.prompt}],
                "max_tokens": settings.pop("max_tokens", 1024),
                **settings,
            }
        if self.provider == "gemini":
            return {
                "contents": [{"parts": [{"text": request.prompt}]}],
                "generationConfig": settings,
            }
        if self.provider == "ollama":
            return {
                "model": request.model_id,
                "prompt": request.prompt,
                "stream": False,
                "options": settings,
            }
        return {"model": request.model_id, "prompt": request.prompt, **settings}

    def _extract_output(self, response: httpx.Response) -> str:
        payload = response.json()
        if self.provider in {"openai", "openai-compatible"}:
            content = payload["choices"][0]["message"]["content"]
            return str(content)
        if self.provider == "anthropic":
            content = payload["content"][0]["text"]
            return str(content)
        if self.provider == "gemini":
            content = payload["candidates"][0]["content"]["parts"][0]["text"]
            return str(content)
        if self.provider == "ollama":
            return str(payload["response"])
        return str(payload)


def adapter_for(
    provider: str,
    *,
    endpoint: str | None = None,
    credential_ref: str | None = None,
    keychain: Keychain | None = None,
    transport: httpx.BaseTransport | None = None,
) -> ProviderAdapter:
    normalized = provider.lower()
    if normalized == "fake":
        return FakeAdapter()
    if normalized in HOSTED_PROVIDER_TYPES and transport is None:
        return ConfigOnlyHostedAdapter()
    if normalized in {"openai-compatible", "openai", "anthropic", "gemini"} | LOCAL_RUNTIME_TYPES:
        resolved_endpoint = endpoint or HOSTED_DEFAULT_ENDPOINTS.get(normalized)
        if resolved_endpoint is None:
            msg = f"Endpoint is required for provider: {provider}"
            raise ValueError(msg)
        return SafeHttpAdapter(
            provider=normalized,
            endpoint=resolved_endpoint,
            credential_ref=credential_ref,
            keychain=keychain,
            transport=transport,
        )
    msg = f"Unsupported provider: {provider}"
    raise ValueError(msg)
