from __future__ import annotations

import threading
import time

import httpx
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from starklabs_evals.app import create_app
from starklabs_evals.db import add_result, connect, create_run, get_model, get_suite

TOKEN = "test-token"


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def _suite(client: TestClient, count: int) -> int:
    response = client.post(
        "/api/suites",
        headers=auth(),
        json={
            "stable_id": "background-suite",
            "name": "Background Suite",
            "tests": [
                {"stable_id": f"t-{index}", "title": f"T {index}", "prompt": "slow prompt"}
                for index in range(count)
            ],
        },
    )
    assert response.status_code == 201
    return int(response.json()["id"])


def _model(client: TestClient) -> int:
    response = client.post(
        "/api/models",
        headers=auth(),
        json={"name": "Fake Slow", "provider": "fake", "model_id": "fake-slow"},
    )
    assert response.status_code == 201
    return int(response.json()["id"])


def test_run_progress_wait_and_reopen_history(tmp_path) -> None:
    db_path = tmp_path / "evals.sqlite"
    client = TestClient(create_app(db_path=db_path, session_token=TOKEN))
    suite_id = _suite(client, 2)
    model_id = _model(client)

    started = client.post(
        "/api/runs",
        headers=auth(),
        json={"suite_id": suite_id, "model_ids": [model_id], "settings": {"delay_ms": 20}},
    )

    assert started.status_code == 201
    assert started.json()["status"] in {"queued", "running", "completed"}
    waited = client.post(f"/api/runs/{started.json()['id']}/wait", headers=auth()).json()
    assert waited["status"] == "completed"
    assert waited["fresh_requests"] == 2
    assert waited["completed_requests"] == 2
    assert waited["total_requests"] == 2

    reopened = TestClient(create_app(db_path=db_path, session_token=TOKEN))
    history = reopened.get(f"/api/runs/{started.json()['id']}", headers=auth()).json()
    assert history["status"] == "completed"
    assert history["completed_requests"] == 2


def test_cancel_stops_background_run_before_full_matrix(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "evals.sqlite", session_token=TOKEN))
    suite_id = _suite(client, 8)
    model_id = _model(client)
    started = client.post(
        "/api/runs",
        headers=auth(),
        json={"suite_id": suite_id, "model_ids": [model_id], "settings": {"delay_ms": 40}},
    ).json()

    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        current = client.get(f"/api/runs/{started['id']}", headers=auth()).json()
        if current["completed_requests"] >= 1:
            break
        time.sleep(0.01)

    canceled = client.post(f"/api/runs/{started['id']}/cancel", headers=auth()).json()
    waited = client.post(f"/api/runs/{started['id']}/wait", headers=auth()).json()

    assert canceled["status"] in {"canceling", "canceled"}
    assert waited["status"] == "canceled"
    assert waited["completed_requests"] < waited["total_requests"]
    results = client.get(f"/api/runs/{started['id']}/results", headers=auth()).json()["results"]
    assert len(results) == waited["completed_requests"]
    assert all(result["request_count"] == 1 for result in results)


def test_start_run_rejects_missing_models_without_orphan_run(tmp_path) -> None:
    client = TestClient(create_app(db_path=tmp_path / "evals.sqlite", session_token=TOKEN))
    suite_id = _suite(client, 1)

    response = client.post(
        "/api/runs",
        headers=auth(),
        json={"suite_id": suite_id, "model_ids": [999], "settings": {}},
    )

    assert response.status_code == 400
    assert client.get("/api/runs", headers=auth()).json()["runs"] == []


def test_hosted_matrix_uses_bounded_concurrency(tmp_path) -> None:
    lock = threading.Lock()
    active = 0
    maximum_active = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.03)
        with lock:
            active -= 1
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = TestClient(
        create_app(
            db_path=tmp_path / "evals.sqlite",
            session_token=TOKEN,
            provider_transport=httpx.MockTransport(handler),
        ),
    )
    suite_id = _suite(client, 1)
    model_ids = []
    for index in range(6):
        response = client.post(
            "/api/models",
            headers=auth(),
            json={
                "name": f"Hosted {index}",
                "provider": "openai-compatible",
                "model_id": f"model-{index}",
                "endpoint": "https://api.example.test/v1",
            },
        )
        assert response.status_code == 201
        model_ids.append(response.json()["id"])

    started = client.post(
        "/api/runs",
        headers=auth(),
        json={"suite_id": suite_id, "model_ids": model_ids, "settings": {}},
    ).json()
    waited = client.post(f"/api/runs/{started['id']}/wait", headers=auth()).json()

    assert waited["status"] == "completed"
    assert 2 <= maximum_active <= 4


def test_global_run_cap_queues_second_run(tmp_path) -> None:
    release = threading.Event()
    started_request = threading.Event()
    lock = threading.Lock()
    active = 0
    maximum_active = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
        started_request.set()
        assert release.wait(timeout=2)
        with lock:
            active -= 1
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = TestClient(
        create_app(
            db_path=tmp_path / "evals.sqlite",
            session_token=TOKEN,
            provider_transport=httpx.MockTransport(handler),
        ),
    )
    suite_id = _suite(client, 1)
    model_id = client.post(
        "/api/models",
        headers=auth(),
        json={
            "name": "Hosted",
            "provider": "openai-compatible",
            "model_id": "model",
            "endpoint": "https://api.example.test/v1",
        },
    ).json()["id"]

    first = client.post(
        "/api/runs",
        headers=auth(),
        json={"suite_id": suite_id, "model_ids": [model_id], "settings": {}},
    ).json()
    assert started_request.wait(timeout=2)
    second = client.post(
        "/api/runs",
        headers=auth(),
        json={"suite_id": suite_id, "model_ids": [model_id], "settings": {}},
    ).json()
    second_while_first_active = client.get(
        f"/api/runs/{second['id']}",
        headers=auth(),
    ).json()
    release.set()

    first_done = client.post(f"/api/runs/{first['id']}/wait", headers=auth()).json()
    second_done = client.post(f"/api/runs/{second['id']}/wait", headers=auth()).json()

    assert second_while_first_active["status"] == "queued"
    assert first_done["status"] == "completed"
    assert second_done["status"] == "completed"
    assert maximum_active == 1


def test_cancel_queued_run_never_calls_provider(tmp_path) -> None:
    release = threading.Event()
    started_request = threading.Event()
    request_count = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        started_request.set()
        assert release.wait(timeout=2)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    client = TestClient(
        create_app(
            db_path=tmp_path / "evals.sqlite",
            session_token=TOKEN,
            provider_transport=httpx.MockTransport(handler),
        ),
    )
    suite_id = _suite(client, 1)
    model_id = client.post(
        "/api/models",
        headers=auth(),
        json={
            "name": "Hosted",
            "provider": "openai-compatible",
            "model_id": "model",
            "endpoint": "https://api.example.test/v1",
        },
    ).json()["id"]
    first = client.post(
        "/api/runs",
        headers=auth(),
        json={"suite_id": suite_id, "model_ids": [model_id], "settings": {}},
    ).json()
    assert started_request.wait(timeout=2)
    queued = client.post(
        "/api/runs",
        headers=auth(),
        json={"suite_id": suite_id, "model_ids": [model_id], "settings": {}},
    ).json()

    canceled = client.post(f"/api/runs/{queued['id']}/cancel", headers=auth()).json()
    release.set()
    client.post(f"/api/runs/{first['id']}/wait", headers=auth())
    canceled_done = client.post(f"/api/runs/{queued['id']}/wait", headers=auth()).json()

    assert canceled["status"] == "canceled"
    assert canceled_done["status"] == "canceled"
    assert canceled_done["completed_requests"] == 0
    assert request_count == 1


def test_reopen_recovers_stale_runs_without_replaying_requests(tmp_path) -> None:
    db_path = tmp_path / "evals.sqlite"
    setup_client = TestClient(create_app(db_path=db_path, session_token=TOKEN))
    suite_id = _suite(setup_client, 1)
    model_id = _model(setup_client)

    with connect(db_path) as conn:
        suite = get_suite(conn, suite_id)
        model = get_model(conn, model_id)
        queued_id = create_run(conn, suite_id=suite_id, settings={}, total_requests=1)
        running_id = create_run(conn, suite_id=suite_id, settings={}, total_requests=1)
        canceling_id = create_run(conn, suite_id=suite_id, settings={}, total_requests=1)
        conn.execute("update runs set status = 'running' where id = ?", (running_id,))
        conn.execute("update runs set status = 'canceling' where id = ?", (canceling_id,))
        conn.commit()
        add_result(
            conn,
            run_id=running_id,
            test_id=suite["tests"][0]["id"],
            model=model,
            status="completed",
            raw_output="preserved",
            error=None,
            settings={},
            timing_ms=1,
            request_count=1,
        )

    provider_requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal provider_requests
        provider_requests += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": "duplicate"}}]})

    reopened = TestClient(
        create_app(
            db_path=db_path,
            session_token=TOKEN,
            provider_transport=httpx.MockTransport(handler),
        ),
    )
    queued = reopened.get(f"/api/runs/{queued_id}", headers=auth()).json()
    running = reopened.get(f"/api/runs/{running_id}", headers=auth()).json()
    canceling = reopened.get(f"/api/runs/{canceling_id}", headers=auth()).json()
    preserved = reopened.get(f"/api/runs/{running_id}/results", headers=auth()).json()["results"]

    assert queued["status"] == "failed"
    assert running["status"] == "failed"
    assert running["completed_requests"] == 1
    assert running["fresh_requests"] == 1
    assert canceling["status"] == "canceled"
    assert [result["raw_output"] for result in preserved] == ["preserved"]
    assert provider_requests == 0
