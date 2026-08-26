from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 3


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        create table if not exists model_connections (
          id integer primary key,
          name text not null,
          provider text not null,
          endpoint text,
          model_id text not null,
          credential_ref text,
          created_at text not null default current_timestamp
        );
        create table if not exists suites (
          id integer primary key,
          stable_id text not null,
          name text not null,
          version text not null,
          created_at text not null default current_timestamp
        );
        create table if not exists tests (
          id integer primary key,
          suite_id integer not null references suites(id) on delete cascade,
          stable_id text not null,
          title text not null,
          prompt text not null,
          expected_output text,
          reference_text text,
          reference_files_json text not null default '[]',
          expected_output_type text not null default 'text',
          private_rubric text,
          execution_settings_json text not null default '{}',
          executable integer not null default 0,
          position integer not null
        );
        create table if not exists runs (
          id integer primary key,
          suite_id integer not null references suites(id),
          status text not null,
          settings_json text not null,
          total_requests integer not null default 0,
          started_at text not null default current_timestamp,
          finished_at text
        );
        create table if not exists results (
          id integer primary key,
          run_id integer not null references runs(id) on delete cascade,
          test_id integer not null references tests(id),
          model_id integer not null references model_connections(id),
          provider text not null,
          provider_model_id text not null,
          status text not null,
          raw_output text,
          error_json text,
          settings_json text not null,
          timing_ms integer not null,
          request_count integer not null
        );
        create table if not exists artifacts (
          id integer primary key,
          result_id integer not null references results(id) on delete cascade,
          name text not null,
          media_type text not null,
          body text not null
        );
        create table if not exists ratings (
          result_id integer primary key references results(id) on delete cascade,
          winner_model_id integer references model_connections(id),
          rating integer not null,
          notes text not null,
          updated_at text not null default current_timestamp
        );
        create table if not exists artifact_executions (
          id integer primary key,
          result_id integer not null references results(id) on delete cascade,
          command_category text not null,
          status text not null,
          exit_code integer,
          timed_out integer not null,
          stdout text not null,
          stderr text not null,
          capability_gap text,
          created_at text not null default current_timestamp
        );
        """,
    )
    existing_columns = {
        str(row["name"]) for row in conn.execute("pragma table_info(tests)").fetchall()
    }
    migrations = {
        "reference_text": "alter table tests add column reference_text text",
        "reference_files_json": (
            "alter table tests add column reference_files_json text not null default '[]'"
        ),
        "expected_output_type": (
            "alter table tests add column expected_output_type text not null default 'text'"
        ),
        "private_rubric": "alter table tests add column private_rubric text",
        "execution_settings_json": (
            "alter table tests add column execution_settings_json text not null default '{}'"
        ),
        "executable": "alter table tests add column executable integer not null default 0",
    }
    for column_name, statement in migrations.items():
        if column_name not in existing_columns:
            conn.execute(statement)
    run_columns = {str(row["name"]) for row in conn.execute("pragma table_info(runs)").fetchall()}
    if "total_requests" not in run_columns:
        conn.execute("alter table runs add column total_requests integer not null default 0")
    conn.execute(f"pragma user_version = {SCHEMA_VERSION}")
    conn.commit()


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in tuple(row.keys())}


def create_model(
    conn: sqlite3.Connection,
    *,
    name: str,
    provider: str,
    endpoint: str | None,
    model_id: str,
    credential_ref: str | None,
) -> dict[str, Any]:
    cursor = conn.execute(
        """
        insert into model_connections (name, provider, endpoint, model_id, credential_ref)
        values (?, ?, ?, ?, ?)
        """,
        (name, provider, endpoint, model_id, credential_ref),
    )
    conn.commit()
    inserted_model_id = cursor.lastrowid
    if inserted_model_id is None:
        msg = "model insert failed"
        raise RuntimeError(msg)
    return get_model(conn, int(inserted_model_id))


def public_model(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    return {
        "id": data["id"],
        "name": data["name"],
        "provider": data["provider"],
        "endpoint": data["endpoint"],
        "model_id": data["model_id"],
        "credential_present": data.get("credential_ref") is not None,
        "created_at": data.get("created_at"),
    }


def get_model(conn: sqlite3.Connection, model_db_id: int) -> dict[str, Any]:
    row = conn.execute("select * from model_connections where id = ?", (model_db_id,)).fetchone()
    if row is None:
        msg = "model not found"
        raise KeyError(msg)
    return row_to_dict(row)


def list_models(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        public_model(row) for row in conn.execute("select * from model_connections order by id")
    ]


def create_suite(
    conn: sqlite3.Connection,
    *,
    stable_id: str,
    name: str,
    version: str,
    tests: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    cursor = conn.execute(
        "insert into suites (stable_id, name, version) values (?, ?, ?)",
        (stable_id, name, version),
    )
    raw_suite_id = cursor.lastrowid
    if raw_suite_id is None:
        msg = "suite insert failed"
        raise RuntimeError(msg)
    suite_id = int(raw_suite_id)
    for position, test in enumerate(tests, start=1):
        conn.execute(
            """
            insert into tests (
              suite_id, stable_id, title, prompt, expected_output, reference_text,
              reference_files_json, expected_output_type, private_rubric,
              execution_settings_json, executable, position
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                suite_id,
                test["stable_id"],
                test["title"],
                test["prompt"],
                test.get("expected_output"),
                test.get("reference_text"),
                json.dumps(test.get("reference_files", []), sort_keys=True),
                test.get("expected_output_type", "text"),
                test.get("private_rubric"),
                json.dumps(test.get("execution_settings", {}), sort_keys=True),
                1 if test.get("executable", False) else 0,
                position,
            ),
        )
    conn.commit()
    return get_suite(conn, suite_id)


def get_suite(conn: sqlite3.Connection, suite_id: int) -> dict[str, Any]:
    suite = conn.execute("select * from suites where id = ?", (suite_id,)).fetchone()
    if suite is None:
        msg = "suite not found"
        raise KeyError(msg)
    tests = [
        test_row_to_dict(row)
        for row in conn.execute(
            "select * from tests where suite_id = ? order by position",
            (suite_id,),
        )
    ]
    payload = row_to_dict(suite)
    payload["tests"] = tests
    return payload


def test_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = row_to_dict(row)
    data["reference_files"] = json.loads(data.pop("reference_files_json"))
    data["execution_settings"] = json.loads(data.pop("execution_settings_json"))
    data["executable"] = bool(data["executable"])
    return data


def list_suites(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        get_suite(conn, int(row["id"]))
        for row in conn.execute("select id from suites order by created_at desc, id desc")
    ]


def create_run(
    conn: sqlite3.Connection,
    *,
    suite_id: int,
    settings: dict[str, Any],
    total_requests: int,
) -> int:
    cursor = conn.execute(
        "insert into runs (suite_id, status, settings_json, total_requests) values (?, ?, ?, ?)",
        (suite_id, "queued", json.dumps(settings, sort_keys=True), total_requests),
    )
    conn.commit()
    run_id = cursor.lastrowid
    if run_id is None:
        msg = "run insert failed"
        raise RuntimeError(msg)
    return int(run_id)


def finish_run(conn: sqlite3.Connection, run_id: int, status: str) -> None:
    conn.execute(
        "update runs set status = ?, finished_at = current_timestamp where id = ?",
        (status, run_id),
    )
    conn.commit()


def mark_run_running(conn: sqlite3.Connection, run_id: int) -> bool:
    cursor = conn.execute(
        "update runs set status = 'running' where id = ? and status = 'queued'",
        (run_id,),
    )
    conn.commit()
    return cursor.rowcount == 1


def request_run_cancel(conn: sqlite3.Connection, run_id: int) -> str:
    row = conn.execute("select status from runs where id = ?", (run_id,)).fetchone()
    if row is None:
        msg = "run not found"
        raise KeyError(msg)
    current = str(row["status"])
    if current == "queued":
        finish_run(conn, run_id, "canceled")
        return "canceled"
    if current == "running":
        conn.execute("update runs set status = 'canceling' where id = ?", (run_id,))
        conn.commit()
        return "canceling"
    return current


def recover_stale_runs(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        update runs
        set status = case when status = 'canceling' then 'canceled' else 'failed' end,
            finished_at = current_timestamp
        where status in ('queued', 'running', 'canceling')
        """,
    )
    conn.commit()


def add_result(
    conn: sqlite3.Connection,
    *,
    run_id: int,
    test_id: int,
    model: dict[str, Any],
    status: str,
    raw_output: str | None,
    error: dict[str, str] | None,
    settings: dict[str, Any],
    timing_ms: int,
    request_count: int,
) -> int:
    cursor = conn.execute(
        """
        insert into results (
          run_id, test_id, model_id, provider, provider_model_id, status, raw_output,
          error_json, settings_json, timing_ms, request_count
        ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            test_id,
            model["id"],
            model["provider"],
            model["model_id"],
            status,
            raw_output,
            json.dumps(error, sort_keys=True) if error else None,
            json.dumps(settings, sort_keys=True),
            timing_ms,
            request_count,
        ),
    )
    conn.commit()
    result_id = cursor.lastrowid
    if result_id is None:
        msg = "result insert failed"
        raise RuntimeError(msg)
    return int(result_id)


def get_run(conn: sqlite3.Connection, run_id: int) -> dict[str, Any]:
    row = conn.execute("select * from runs where id = ?", (run_id,)).fetchone()
    if row is None:
        msg = "run not found"
        raise KeyError(msg)
    data = row_to_dict(row)
    data["settings"] = json.loads(data.pop("settings_json"))
    data["fresh_requests"] = conn.execute(
        "select coalesce(sum(request_count), 0) from results where run_id = ?",
        (run_id,),
    ).fetchone()[0]
    data["completed_requests"] = conn.execute(
        "select count(*) from results where run_id = ?",
        (run_id,),
    ).fetchone()[0]
    return data


def list_runs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        get_run(conn, int(row["id"]))
        for row in conn.execute("select id from runs order by started_at desc, id desc")
    ]


def list_results(conn: sqlite3.Connection, run_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        select
          r.*, t.title as test_title, t.stable_id as test_stable_id,
          t.prompt as source_prompt, t.reference_text as source_reference_text,
          t.expected_output_type as expected_output_type, t.executable as executable,
          m.name as model_name, rat.winner_model_id as rating_winner_model_id,
          rat.rating as saved_rating, rat.notes as rating_notes
        from results r
        join tests t on t.id = r.test_id
        join model_connections m on m.id = r.model_id
        left join ratings rat on rat.result_id = r.id
        where r.run_id = ?
        order by t.position, r.id
        """,
        (run_id,),
    ).fetchall()
    results = []
    for row in rows:
        data = row_to_dict(row)
        data["error"] = json.loads(data.pop("error_json")) if data["error_json"] else None
        data["settings"] = json.loads(data.pop("settings_json"))
        saved_rating = data.pop("saved_rating")
        rating_winner_model_id = data.pop("rating_winner_model_id")
        rating_notes = data.pop("rating_notes")
        data["rating"] = (
            {
                "winner_model_id": rating_winner_model_id,
                "rating": saved_rating,
                "notes": rating_notes,
            }
            if saved_rating is not None
            else None
        )
        data["artifacts"] = [
            row_to_dict(artifact)
            for artifact in conn.execute(
                "select id, name, media_type from artifacts where result_id = ? order by id",
                (data["id"],),
            )
        ]
        results.append(data)
    return results


def save_rating(
    conn: sqlite3.Connection,
    *,
    result_id: int,
    winner_model_id: int | None,
    rating: int,
    notes: str,
) -> dict[str, Any]:
    conn.execute(
        """
        insert into ratings (result_id, winner_model_id, rating, notes, updated_at)
        values (?, ?, ?, ?, current_timestamp)
        on conflict(result_id) do update set
          winner_model_id = excluded.winner_model_id,
          rating = excluded.rating,
          notes = excluded.notes,
          updated_at = current_timestamp
        """,
        (result_id, winner_model_id, rating, notes),
    )
    conn.commit()
    return get_rating(conn, result_id)


def get_rating(conn: sqlite3.Connection, result_id: int) -> dict[str, Any]:
    row = conn.execute("select * from ratings where result_id = ?", (result_id,)).fetchone()
    if row is None:
        msg = "rating not found"
        raise KeyError(msg)
    return row_to_dict(row)


def record_artifact_execution(
    conn: sqlite3.Connection,
    *,
    result_id: int,
    command_category: str,
    status: str,
    exit_code: int | None,
    timed_out: bool,
    stdout: str,
    stderr: str,
    capability_gap: str | None,
) -> dict[str, Any]:
    cursor = conn.execute(
        """
        insert into artifact_executions (
          result_id, command_category, status, exit_code, timed_out,
          stdout, stderr, capability_gap
        ) values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            result_id,
            command_category,
            status,
            exit_code,
            int(timed_out),
            stdout[:65536],
            stderr[:65536],
            capability_gap,
        ),
    )
    conn.commit()
    row = conn.execute(
        "select * from artifact_executions where id = ?",
        (cursor.lastrowid,),
    ).fetchone()
    if row is None:
        msg = "artifact execution not found"
        raise KeyError(msg)
    return row_to_dict(row)


def list_artifact_executions(
    conn: sqlite3.Connection,
    result_id: int,
) -> list[dict[str, Any]]:
    return [
        row_to_dict(row)
        for row in conn.execute(
            "select * from artifact_executions where result_id = ? order by id desc",
            (result_id,),
        )
    ]
