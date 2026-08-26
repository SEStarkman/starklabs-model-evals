from __future__ import annotations

from fastapi.testclient import TestClient
from starklabs_evals.app import create_app
from starklabs_evals.sandbox import ValidationResult

TOKEN = "test-token"


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def test_executable_result_runs_only_after_explicit_request_and_records_evidence(
    tmp_path,
    monkeypatch,
) -> None:
    calls: list[str] = []

    def fake_validation(source: str) -> ValidationResult:
        calls.append(source)
        return ValidationResult("ok\n", "", 0, False)

    monkeypatch.setattr("starklabs_evals.app.validate_python_single_file", fake_validation)
    client = TestClient(create_app(db_path=tmp_path / "evals.sqlite", session_token=TOKEN))
    model_id = client.post(
        "/api/models",
        headers=auth(),
        json={"name": "Fake", "provider": "fake", "model_id": "fake-ok"},
    ).json()["id"]
    suite_id = client.post(
        "/api/suites",
        headers=auth(),
        json={
            "stable_id": "python-suite",
            "name": "Python",
            "tests": [
                {
                    "stable_id": "python",
                    "title": "Python",
                    "prompt": "print('ok')",
                    "expected_output_type": "code",
                    "executable": True,
                },
            ],
        },
    ).json()["id"]
    run = client.post(
        "/api/runs",
        headers=auth(),
        json={"suite_id": suite_id, "model_ids": [model_id], "settings": {}},
    ).json()
    client.post(f"/api/runs/{run['id']}/wait", headers=auth())
    result_id = client.get(f"/api/runs/{run['id']}/results", headers=auth()).json()["results"][0][
        "id"
    ]

    assert calls == []
    executed = client.post(
        f"/api/results/{result_id}/execute",
        headers=auth(),
        json={"category": "python-single-file"},
    )

    assert executed.status_code == 201
    assert executed.json()["command_category"] == "python-single-file-container"
    assert executed.json()["exit_code"] == 0
    assert len(calls) == 1
    history = client.get(f"/api/results/{result_id}/executions", headers=auth()).json()
    assert history["executions"][0]["stdout"] == "ok\n"
