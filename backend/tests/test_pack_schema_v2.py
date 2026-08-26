from __future__ import annotations

import sqlite3

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient
from starklabs_evals.app import create_app
from starklabs_evals.db import SCHEMA_VERSION, connect

TOKEN = "test-token"


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def test_schema_v2_import_export_reopen_preserves_optional_contract(tmp_path) -> None:
    db_path = tmp_path / "evals.sqlite"
    client = TestClient(create_app(db_path=db_path, session_token=TOKEN))
    pack = {
        "schema_version": 2,
        "pack_id": "v2-pack",
        "name": "V2 Pack",
        "version": "2.0.0",
        "tests": [
            {
                "stable_id": "html-ref",
                "title": "Render hostile reference safely",
                "prompt": "Render this as plain text.",
                "reference_text": "<script>alert('x')</script>",
                "reference_files": [
                    {
                        "name": "hostile <name>.txt",
                        "media_type": "text/plain",
                        "content": "<b>not html</b>",
                    },
                ],
                "expected_output": "Plain text",
                "expected_output_type": "html",
                "private_rubric": "Do not disclose this in public fixtures.",
                "execution_settings": {"requires_sandbox": False, "timeout_s": 7},
                "executable": False,
            },
        ],
    }

    response = client.post("/api/import-pack", headers=auth(), json=pack)

    assert response.status_code == 201
    suite_id = response.json()["id"]
    exported = client.get(f"/api/suites/{suite_id}/export", headers=auth()).json()
    assert exported == pack

    reopened = TestClient(create_app(db_path=db_path, session_token=TOKEN))
    reopened_export = reopened.get(f"/api/suites/{suite_id}/export", headers=auth()).json()
    assert reopened_export == pack
    with sqlite3.connect(db_path) as raw:
        assert raw.execute("pragma user_version").fetchone()[0] == SCHEMA_VERSION


@pytest.mark.parametrize(
    "reference_files",
    [
        [{"name": "../secret.txt", "content": "x"}],
        [{"name": "/absolute/secret.txt", "content": "x"}],
        [{"name": "nested/file.txt", "content": "x"}],
        [{"name": "same.txt", "content": "x"}, {"name": "same.txt", "content": "y"}],
        [{"name": "link -> /etc/passwd", "content": "x"}],
        [{"name": "huge.txt", "content": "x" * 70_000}],
    ],
)
def test_schema_v2_rejects_arbitrary_paths_duplicates_and_oversize(
    tmp_path,
    reference_files: list[dict[str, str]],
) -> None:
    client = TestClient(create_app(db_path=tmp_path / "evals.sqlite", session_token=TOKEN))

    response = client.post(
        "/api/import-pack",
        headers=auth(),
        json={
            "schema_version": 2,
            "pack_id": "bad-files",
            "name": "Bad Files",
            "version": "2.0.0",
            "tests": [
                {
                    "stable_id": "bad",
                    "title": "Bad",
                    "prompt": "Bad",
                    "reference_files": reference_files,
                },
            ],
        },
    )

    assert response.status_code in {400, 413}


def test_schema_v1_pack_import_uses_current_db_and_v2_pack_defaults(tmp_path) -> None:
    conn = connect(tmp_path / "evals.sqlite")
    assert SCHEMA_VERSION == 3
    assert conn.execute("pragma user_version").fetchone()[0] == 3
    conn.close()

    client = TestClient(create_app(db_path=tmp_path / "evals.sqlite", session_token=TOKEN))
    response = client.post(
        "/api/import-pack",
        headers=auth(),
        json={
            "schema_version": 1,
            "pack_id": "v1-pack",
            "name": "V1",
            "version": "1.0.0",
            "tests": [{"stable_id": "basic", "title": "Basic", "prompt": "Say hi"}],
        },
    )

    assert response.status_code == 201
    exported = client.get(f"/api/suites/{response.json()['id']}/export", headers=auth()).json()
    assert exported["schema_version"] == 2
    assert exported["tests"][0]["expected_output_type"] == "text"
    assert exported["tests"][0]["reference_files"] == []
