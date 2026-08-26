from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .db import (
    connect,
    create_model,
    create_run,
    create_suite,
    get_model,
    get_rating,
    get_run,
    get_suite,
    list_artifact_executions,
    list_models,
    list_results,
    list_runs,
    list_suites,
    public_model,
    record_artifact_execution,
    save_rating,
)
from .discovery import assert_model_endpoint_allowed, safe_discovery_report
from .keychain import Keychain, MacOSSecurityKeychain
from .packs import export_payload, validate_pack
from .runs import BackgroundRunManager
from .sandbox import (
    container_engine_capability,
    html_screenshot_capability,
    pygame_capture_capability,
    python_validation_capability,
    validate_python_single_file,
)
from .settings import AppSettings

BROWSER_SESSION_COOKIE = "starklabs_browser_session"

if TYPE_CHECKING:
    import httpx


class ModelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider: str = Field(min_length=1, max_length=60)
    endpoint: str | None = Field(default=None, max_length=300)
    model_id: str = Field(min_length=1, max_length=160)
    credential_label: str | None = Field(default=None, max_length=120)
    credential_value: str | None = Field(default=None, max_length=4096)


class TestCreate(BaseModel):
    stable_id: str
    title: str
    prompt: str
    expected_output: str | None = None
    reference_text: str | None = None
    reference_files: list[dict[str, str]] = Field(default_factory=list)
    expected_output_type: str = "text"
    private_rubric: str | None = None
    execution_settings: dict[str, Any] = Field(default_factory=dict)
    executable: bool = False


class SuiteCreate(BaseModel):
    stable_id: str = "local-suite"
    name: str
    version: str = "0.1.0"
    tests: list[TestCreate]


class RunCreate(BaseModel):
    suite_id: int
    model_ids: list[int] = Field(min_length=1, max_length=20)
    settings: dict[str, Any] = Field(default_factory=dict)


class RatingCreate(BaseModel):
    winner_model_id: int | None = None
    rating: int = Field(ge=1, le=5)
    notes: str = Field(default="", max_length=4000)


class ArtifactExecute(BaseModel):
    category: str = Field(pattern="^python-single-file$")


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, OverflowError):
        return HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=str(exc))
    if isinstance(exc, (KeyError, ValueError)):
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="internal error")


def create_app(
    *,
    db_path: str | Path,
    bind_host: str = "127.0.0.1",
    allow_non_loopback: bool = False,
    session_token: str | None = None,
    keychain: Keychain | None = None,
    web_dist: str | Path | None = None,
    provider_transport: httpx.BaseTransport | None = None,
) -> FastAPI:
    settings = AppSettings(
        db_path=str(db_path),
        bind_host=bind_host,
        allow_non_loopback=allow_non_loopback,
        session_token=session_token or AppSettings(db_path=str(db_path)).session_token,
    )
    settings.validate()
    keychain = keychain or MacOSSecurityKeychain()
    app = FastAPI(title="Starklabs Model Evals", version=__version__)
    app.state.settings = settings
    app.state.keychain = keychain
    app.state.browser_session = None
    app.state.run_manager = BackgroundRunManager(
        db_path=settings.db_path,
        keychain=keychain,
        provider_transport=provider_transport,
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        safe_errors = [
            {
                "type": error.get("type", "validation_error"),
                "loc": error.get("loc", ()),
                "msg": error.get("msg", "Invalid request"),
            }
            for error in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": safe_errors})

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    def require_auth(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> None:
        expected = f"Bearer {settings.session_token}"
        bearer_ok = secrets.compare_digest(authorization or "", expected)
        browser_session = app.state.browser_session
        cookie = request.cookies.get(BROWSER_SESSION_COOKIE)
        cookie_ok = (
            isinstance(browser_session, str)
            and isinstance(cookie, str)
            and secrets.compare_digest(cookie, browser_session)
        )
        if not bearer_ok and not cookie_ok:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")

    def db_conn() -> Iterator[sqlite3.Connection]:
        conn = connect(settings.db_path)
        try:
            yield conn
        finally:
            conn.close()

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {
            "ok": True,
            "version": __version__,
            "bind_host": settings.bind_host,
            "cors_origins": settings.cors_origins,
        }

    @app.get("/api/session")
    def session(response: Response, _: None = Depends(require_auth)) -> dict[str, object]:
        browser_session = secrets.token_urlsafe(32)
        app.state.browser_session = browser_session
        response.set_cookie(
            BROWSER_SESSION_COOKIE,
            browser_session,
            httponly=True,
            samesite="strict",
            path="/",
        )
        return {"ok": True}

    @app.get("/api/models")
    def models(
        _: None = Depends(require_auth),
        conn: sqlite3.Connection = Depends(db_conn),
    ) -> dict[str, object]:
        return {"models": list_models(conn)}

    @app.post("/api/models", status_code=201)
    def add_model(
        payload: ModelCreate,
        _: None = Depends(require_auth),
        conn: sqlite3.Connection = Depends(db_conn),
    ) -> dict[str, object]:
        try:
            assert_model_endpoint_allowed(payload.provider, payload.endpoint)
        except ValueError as exc:
            raise _http_error(exc) from exc
        model = create_model(
            conn,
            name=payload.name,
            provider=payload.provider,
            endpoint=payload.endpoint,
            model_id=payload.model_id,
            credential_ref=None,
        )
        if payload.credential_value:
            label = payload.credential_label or payload.provider
            credential_ref = f"model:{model['id']}:{label}"
            try:
                keychain.set(credential_ref, payload.credential_value)
                conn.execute(
                    "update model_connections set credential_ref = ? where id = ?",
                    (credential_ref, model["id"]),
                )
                conn.commit()
                model["credential_ref"] = credential_ref
            except Exception as exc:
                keychain.delete(credential_ref)
                conn.execute("delete from model_connections where id = ?", (model["id"],))
                conn.commit()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="credential storage failed",
                ) from exc
        return public_model(model)

    @app.post("/api/models/{model_id}/test")
    def test_model(
        model_id: int,
        _: None = Depends(require_auth),
        conn: sqlite3.Connection = Depends(db_conn),
    ) -> dict[str, object]:
        model = get_model(conn, model_id)
        from .adapters import AdapterRequest, adapter_for

        adapter = adapter_for(
            model["provider"],
            endpoint=model["endpoint"],
            credential_ref=model.get("credential_ref"),
            keychain=keychain,
            transport=provider_transport,
        )
        result = adapter.complete(
            AdapterRequest(
                provider=model["provider"],
                model_id=model["model_id"],
                prompt="Return a deterministic connectivity check.",
                settings={},
            ),
        )
        return result.__dict__

    @app.get("/api/models/discover")
    def discover(
        runtime: str,
        endpoint: str,
        _: None = Depends(require_auth),
    ) -> dict[str, object]:
        try:
            return safe_discovery_report(runtime, endpoint)
        except ValueError as exc:
            raise _http_error(exc) from exc

    @app.get("/api/suites")
    def suites(
        _: None = Depends(require_auth),
        conn: sqlite3.Connection = Depends(db_conn),
    ) -> dict[str, object]:
        return {"suites": list_suites(conn)}

    @app.get("/api/suites/{suite_id}")
    def suite(
        suite_id: int,
        _: None = Depends(require_auth),
        conn: sqlite3.Connection = Depends(db_conn),
    ) -> dict[str, object]:
        try:
            return get_suite(conn, suite_id)
        except KeyError as exc:
            raise _http_error(exc) from exc

    @app.post("/api/suites", status_code=201)
    def add_suite(
        payload: SuiteCreate,
        _: None = Depends(require_auth),
        conn: sqlite3.Connection = Depends(db_conn),
    ) -> dict[str, object]:
        try:
            normalized = validate_pack(
                {
                    "schema_version": 1,
                    "pack_id": payload.stable_id,
                    "name": payload.name,
                    "version": payload.version,
                    "tests": [test.model_dump() for test in payload.tests],
                },
                max_bytes=settings.max_pack_bytes,
            )
            return create_suite(conn, **normalized)
        except (ValueError, OverflowError) as exc:
            raise _http_error(exc) from exc

    @app.post("/api/import-pack", status_code=201)
    def import_pack(
        payload: dict[str, Any],
        _: None = Depends(require_auth),
        conn: sqlite3.Connection = Depends(db_conn),
    ) -> dict[str, object]:
        try:
            normalized = validate_pack(payload, max_bytes=settings.max_pack_bytes)
            return create_suite(conn, **normalized)
        except (ValueError, OverflowError) as exc:
            raise _http_error(exc) from exc

    @app.get("/api/export")
    def export_all(
        _: None = Depends(require_auth),
        conn: sqlite3.Connection = Depends(db_conn),
    ) -> dict[str, object]:
        return {
            "schema_version": 2,
            "suites": [export_payload(suite) for suite in list_suites(conn)],
        }

    @app.get("/api/suites/{suite_id}/export")
    def export_suite(
        suite_id: int,
        _: None = Depends(require_auth),
        conn: sqlite3.Connection = Depends(db_conn),
    ) -> dict[str, object]:
        try:
            return export_payload(get_suite(conn, suite_id))
        except KeyError as exc:
            raise _http_error(exc) from exc

    @app.post("/api/runs", status_code=201)
    def start_run(
        payload: RunCreate,
        _: None = Depends(require_auth),
        conn: sqlite3.Connection = Depends(db_conn),
    ) -> dict[str, object]:
        try:
            suite_payload = get_suite(conn, payload.suite_id)
            for model_id in payload.model_ids:
                get_model(conn, model_id)
        except KeyError as exc:
            raise _http_error(exc) from exc
        total_requests = len(suite_payload["tests"]) * len(payload.model_ids)
        run_id = create_run(
            conn,
            suite_id=payload.suite_id,
            settings=payload.settings,
            total_requests=total_requests,
        )
        app.state.run_manager.start(
            run_id=run_id,
            suite_id=payload.suite_id,
            model_ids=payload.model_ids,
            settings=payload.settings,
        )
        return get_run(conn, run_id)

    @app.post("/api/runs/{run_id}/cancel")
    def cancel_run(
        run_id: int,
        _: None = Depends(require_auth),
        conn: sqlite3.Connection = Depends(db_conn),
    ) -> dict[str, object]:
        app.state.run_manager.cancel(run_id)
        return get_run(conn, run_id)

    @app.post("/api/runs/{run_id}/wait")
    def wait_run(
        run_id: int,
        _: None = Depends(require_auth),
        conn: sqlite3.Connection = Depends(db_conn),
    ) -> dict[str, object]:
        app.state.run_manager.wait(run_id)
        return get_run(conn, run_id)

    @app.get("/api/runs")
    def runs(
        _: None = Depends(require_auth),
        conn: sqlite3.Connection = Depends(db_conn),
    ) -> dict[str, object]:
        return {"runs": list_runs(conn)}

    @app.get("/api/runs/{run_id}")
    def run(
        run_id: int,
        _: None = Depends(require_auth),
        conn: sqlite3.Connection = Depends(db_conn),
    ) -> dict[str, object]:
        return get_run(conn, run_id)

    @app.get("/api/runs/{run_id}/results")
    def results(
        run_id: int,
        _: None = Depends(require_auth),
        conn: sqlite3.Connection = Depends(db_conn),
    ) -> dict[str, object]:
        return {"results": list_results(conn, run_id)}

    @app.get("/api/artifacts/{artifact_id}")
    def artifact(
        artifact_id: int,
        _: None = Depends(require_auth),
        conn: sqlite3.Connection = Depends(db_conn),
    ) -> Response:
        row = conn.execute(
            "select media_type, body from artifacts where id = ?",
            (artifact_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="artifact not found")
        return Response(content=row["body"], media_type=row["media_type"])

    @app.post("/api/results/{result_id}/execute", status_code=201)
    def execute_result(
        result_id: int,
        payload: ArtifactExecute,
        _: None = Depends(require_auth),
        conn: sqlite3.Connection = Depends(db_conn),
    ) -> dict[str, object]:
        row = conn.execute(
            """
            select r.raw_output, t.executable
            from results r join tests t on t.id = r.test_id
            where r.id = ?
            """,
            (result_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="result not found")
        if not bool(row["executable"]):
            raise HTTPException(status_code=409, detail="test is not marked executable")
        source = str(row["raw_output"] or "")
        if not source:
            raise HTTPException(status_code=400, detail="result has no source output")
        if len(source.encode()) > 256 * 1024:
            raise HTTPException(status_code=413, detail="source output too large")
        if payload.category != "python-single-file":  # pragma: no cover - pydantic enforces
            raise HTTPException(status_code=400, detail="unsupported execution category")
        outcome = validate_python_single_file(source)
        execution_status = (
            "unavailable"
            if outcome.unavailable_reason
            else "timeout"
            if outcome.timeout
            else "completed"
            if outcome.exit_code == 0
            else "failed"
        )
        return record_artifact_execution(
            conn,
            result_id=result_id,
            command_category="python-single-file-container",
            status=execution_status,
            exit_code=outcome.exit_code,
            timed_out=outcome.timeout,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
            capability_gap=outcome.unavailable_reason,
        )

    @app.get("/api/results/{result_id}/executions")
    def result_executions(
        result_id: int,
        _: None = Depends(require_auth),
        conn: sqlite3.Connection = Depends(db_conn),
    ) -> dict[str, object]:
        if conn.execute("select 1 from results where id = ?", (result_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="result not found")
        return {"executions": list_artifact_executions(conn, result_id)}

    @app.post("/api/results/{result_id}/rating", status_code=201)
    def rate(
        result_id: int,
        payload: RatingCreate,
        _: None = Depends(require_auth),
        conn: sqlite3.Connection = Depends(db_conn),
    ) -> dict[str, object]:
        return save_rating(
            conn,
            result_id=result_id,
            winner_model_id=payload.winner_model_id,
            rating=payload.rating,
            notes=payload.notes,
        )

    @app.get("/api/results/{result_id}/rating")
    def rating(
        result_id: int,
        _: None = Depends(require_auth),
        conn: sqlite3.Connection = Depends(db_conn),
    ) -> dict[str, object]:
        return get_rating(conn, result_id)

    @app.get("/api/capabilities")
    def capabilities(_: None = Depends(require_auth)) -> dict[str, object]:
        return {
            "capabilities": [
                container_engine_capability().__dict__,
                python_validation_capability().__dict__,
                html_screenshot_capability().__dict__,
                pygame_capture_capability().__dict__,
            ],
        }

    if web_dist and Path(web_dist).exists():
        app.mount("/", StaticFiles(directory=str(web_dist), html=True), name="web")

    return app
