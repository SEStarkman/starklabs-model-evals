from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from starklabs_evals.app import create_app

TOKEN = "test-token"


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def test_import_reopen_run_matrix_partial_failure_and_rating(tmp_path) -> None:
    db_path = tmp_path / "evals.sqlite"
    app = create_app(db_path=db_path, session_token=TOKEN)
    client = TestClient(app)

    imported = client.post(
        "/api/import-pack",
        headers=auth(),
        json={
            "schema_version": 1,
            "pack_id": "public-smoke",
            "name": "Public smoke",
            "version": "1.0.0",
            "tests": [
                {
                    "stable_id": "count-r",
                    "title": "Count r",
                    "prompt": "How many r letters are in strawberry?",
                    "expected_output": "3",
                },
                {
                    "stable_id": "force-fail",
                    "title": "Force failure",
                    "prompt": "This prompt contains [FAIL].",
                    "expected_output": "Structured error",
                },
            ],
        },
    )
    assert imported.status_code == 201
    suite_id = imported.json()["id"]

    model_ok = client.post(
        "/api/models",
        headers=auth(),
        json={"name": "Fake OK", "provider": "fake", "model_id": "fake-ok"},
    ).json()["id"]
    model_fail = client.post(
        "/api/models",
        headers=auth(),
        json={"name": "Fake Fail", "provider": "fake", "model_id": "fake-fail"},
    ).json()["id"]

    run = client.post(
        "/api/runs",
        headers=auth(),
        json={
            "suite_id": suite_id,
            "model_ids": [model_ok, model_fail],
            "settings": {"temperature": 0},
        },
    )
    assert run.status_code == 201
    run_payload = client.post(f"/api/runs/{run.json()['id']}/wait", headers=auth()).json()
    assert run_payload["status"] == "completed"
    assert run_payload["fresh_requests"] == 4
    results = client.get(f"/api/runs/{run_payload['id']}/results", headers=auth()).json()["results"]
    assert len(results) == 4
    assert sum(1 for result in results if result["status"] == "failed") >= 1
    assert all(result["request_count"] == 1 for result in results)
    assert all("raw_output" in result or "error" in result for result in results)
    assert all(result["timing_ms"] >= 0 for result in results)
    assert all("artifacts" in result for result in results)

    first_success = next(result for result in results if result["status"] == "completed")
    assert first_success["artifacts"][0]["name"] == "raw-output.txt"
    rating = client.post(
        f"/api/results/{first_success['id']}/rating",
        headers=auth(),
        json={"winner_model_id": model_ok, "rating": 5, "notes": "Clear and deterministic"},
    )
    assert rating.status_code == 201

    reopened = TestClient(create_app(db_path=db_path, session_token=TOKEN))
    reopened_run = reopened.get(f"/api/runs/{run_payload['id']}", headers=auth()).json()
    assert reopened_run["id"] == run_payload["id"]
    reopened_rating = reopened.get(
        f"/api/results/{first_success['id']}/rating",
        headers=auth(),
    ).json()
    assert reopened_rating["notes"] == "Clear and deterministic"
    reopened_results = reopened.get(
        f"/api/runs/{run_payload['id']}/results",
        headers=auth(),
    ).json()["results"]
    reopened_success = next(
        result for result in reopened_results if result["id"] == first_success["id"]
    )
    assert reopened_success["rating"] == {
        "winner_model_id": model_ok,
        "rating": 5,
        "notes": "Clear and deterministic",
    }


def test_public_pack_contains_self_contained_poker_scenario() -> None:
    pack_path = Path("evals/public/1.0.0/pack.json")
    payload = json.loads(pack_path.read_text(encoding="utf-8"))
    prompt = payload["tests"][1]["prompt"]

    assert "AsJd" in prompt
    assert "Jh 8s 4s" in prompt
    assert "9.1bb into 9.1bb" in prompt
    assert "EVALS.md" not in prompt


def test_import_export_blocks_traversal_and_size(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "evals.sqlite", session_token=TOKEN))

    bad_path = client.post(
        "/api/import-pack",
        headers=auth(),
        json={
            "schema_version": 1,
            "pack_id": "../secret",
            "name": "bad",
            "version": "1.0.0",
            "tests": [],
        },
    )
    assert bad_path.status_code == 400

    too_big = client.post(
        "/api/import-pack",
        headers=auth(),
        json={
            "schema_version": 1,
            "pack_id": "big",
            "name": "big",
            "version": "1.0.0",
            "tests": [{"stable_id": "x", "title": "x", "prompt": "x" * 70_000}],
        },
    )
    assert too_big.status_code == 413
