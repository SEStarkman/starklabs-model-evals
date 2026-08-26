from __future__ import annotations

import pytest
from starklabs_evals.server import session_token_from_env


def test_direct_server_requires_session_token_env_without_printing(monkeypatch, capsys) -> None:
    monkeypatch.delenv("STARKLABS_SESSION_TOKEN", raising=False)

    with pytest.raises(SystemExit):
        session_token_from_env()

    captured = capsys.readouterr()
    assert "STARKLABS_SESSION_TOKEN=" not in captured.out
    assert "STARKLABS_SESSION_TOKEN=" not in captured.err


def test_direct_server_reads_session_token_without_logging_value(monkeypatch, capsys) -> None:
    monkeypatch.setenv("STARKLABS_SESSION_TOKEN", "secret-session-token")

    assert session_token_from_env() == "secret-session-token"
    captured = capsys.readouterr()
    assert "secret-session-token" not in captured.out
    assert "secret-session-token" not in captured.err
