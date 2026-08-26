from __future__ import annotations

import json
import sqlite3
import subprocess

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from starklabs_evals.app import create_app
from starklabs_evals.keychain import InMemoryKeychain, MacOSSecurityKeychain


class FailingKeychain(InMemoryKeychain):
    def set(self, _account: str, value: str) -> None:
        msg = f"keychain unavailable while storing {value}"
        raise RuntimeError(msg)


class RecordingNativeKeychain:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def set(self, service: str, account: str, value: str) -> None:
        self.values[(service, account)] = value

    def get(self, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def delete(self, service: str, account: str) -> None:
        self.values.pop((service, account), None)


def authed(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_health_loopback_auth_and_cors(tmp_path) -> None:
    token = "test-token"
    app = create_app(db_path=tmp_path / "evals.sqlite", session_token=token)
    client = TestClient(app)

    assert client.get("/api/health").json()["bind_host"] == "127.0.0.1"
    assert client.get("/api/models").status_code == 401

    good = client.get(
        "/api/models",
        headers={"Origin": "http://127.0.0.1:5173", **authed(token)},
    )
    assert good.status_code == 200
    assert good.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"

    bad = client.options(
        "/api/models",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in bad.headers


def test_rejects_non_loopback_bind_without_dev_override(tmp_path) -> None:
    try:
        create_app(db_path=tmp_path / "evals.sqlite", bind_host="0.0.0.0")
    except ValueError as exc:
        assert "non-loopback" in str(exc)
    else:  # pragma: no cover - assertion path
        raise AssertionError("expected non-loopback bind to be rejected")


def test_bearer_is_exchanged_for_httponly_loopback_session_cookie(tmp_path) -> None:
    token = "launch-token-sentinel"
    client = TestClient(create_app(db_path=tmp_path / "evals.sqlite", session_token=token))

    session = client.get("/api/session", headers=authed(token))

    assert session.status_code == 200
    cookie = session.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert token not in cookie
    assert client.get("/api/models").status_code == 200


def test_model_credentials_never_leave_keychain_or_sqlite(tmp_path) -> None:
    token = "test-token"
    secret = "credential-value-for-test"
    db_path = tmp_path / "evals.sqlite"
    keychain = InMemoryKeychain()
    client = TestClient(create_app(db_path=db_path, keychain=keychain, session_token=token))

    response = client.post(
        "/api/models",
        headers=authed(token),
        json={
            "name": "Fake secure",
            "provider": "fake",
            "endpoint": "http://127.0.0.1:11434",
            "model_id": "fake-ok",
            "credential_label": "local-test",
            "credential_value": secret,
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["credential_present"] is True
    assert secret not in json.dumps(payload)
    assert keychain.get("model:1:local-test") == secret

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("select * from model_connections").fetchall()
    assert secret not in repr(rows)

    exported = client.get("/api/export", headers=authed(token)).json()
    assert secret not in json.dumps(exported)


def test_create_app_defaults_to_macos_keychain_for_production(tmp_path) -> None:
    token = "test-" + "token"
    app = create_app(db_path=tmp_path / "evals.sqlite", session_token=token)
    assert isinstance(app.state.keychain, MacOSSecurityKeychain)


def test_macos_keychain_uses_native_api_without_a_secret_bearing_subprocess(monkeypatch) -> None:
    backend = RecordingNativeKeychain()
    keychain = MacOSSecurityKeychain(backend=backend)

    def fail_subprocess(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Keychain access must not invoke a subprocess")

    monkeypatch.setattr(subprocess, "run", fail_subprocess)
    keychain.set("model:1:test", "credential-sentinel")

    assert keychain.get("model:1:test") == "credential-sentinel"
    keychain.delete("model:1:test")
    assert keychain.get("model:1:test") is None


def test_validation_errors_do_not_echo_credential_input(tmp_path) -> None:
    token = "test-token"
    secret = "credential-sentinel-" + ("x" * 5000)
    client = TestClient(create_app(db_path=tmp_path / "evals.sqlite", session_token=token))

    response = client.post(
        "/api/models",
        headers=authed(token),
        json={
            "name": "Hosted",
            "provider": "openai",
            "model_id": "gpt-test",
            "credential_value": secret,
        },
    )

    assert response.status_code == 422
    assert "credential-sentinel" not in response.text
    assert secret not in response.text


def test_credential_write_failure_rolls_back_model_and_hides_secret(tmp_path) -> None:
    token = "test-token"
    secret = "must-not-be-disclosed"
    db_path = tmp_path / "evals.sqlite"
    client = TestClient(
        create_app(db_path=db_path, keychain=FailingKeychain(), session_token=token),
        raise_server_exceptions=False,
    )

    response = client.post(
        "/api/models",
        headers=authed(token),
        json={
            "name": "Hosted",
            "provider": "openai",
            "endpoint": "https://api.openai.com/v1",
            "model_id": "gpt-test",
            "credential_label": "openai",
            "credential_value": secret,
        },
    )

    assert response.status_code == 500
    assert secret not in response.text
    with sqlite3.connect(db_path) as conn:
        count = conn.execute("select count(*) from model_connections").fetchone()[0]
    assert count == 0
