from __future__ import annotations

import logging
import queue
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .adapters import AdapterRequest, adapter_for
from .db import (
    add_result,
    connect,
    finish_run,
    get_model,
    get_suite,
    mark_run_running,
    recover_stale_runs,
    request_run_cancel,
)
from .discovery import HOSTED_PROVIDER_TYPES

if TYPE_CHECKING:
    import httpx

    from .keychain import Keychain

LOGGER = logging.getLogger("starklabs_evals")
MAX_QUEUED_RUNS = 32
RunWork = tuple[int, int, list[int], dict[str, Any]]


class BackgroundRunManager:
    def __init__(
        self,
        *,
        db_path: str | Path,
        keychain: Keychain,
        provider_transport: httpx.BaseTransport | None,
    ) -> None:
        self.db_path = db_path
        self.keychain = keychain
        self.provider_transport = provider_transport
        self._lock = threading.Lock()
        self._queue: queue.Queue[RunWork] = queue.Queue(maxsize=MAX_QUEUED_RUNS)
        self._events: dict[int, threading.Event] = {}
        self._canceling: set[int] = set()
        with connect(self.db_path) as conn:
            recover_stale_runs(conn)
        self._worker = threading.Thread(
            target=self._work_loop,
            daemon=True,
            name="starklabs-run-worker",
        )
        self._worker.start()

    def start(
        self,
        *,
        run_id: int,
        suite_id: int,
        model_ids: list[int],
        settings: dict[str, Any],
    ) -> None:
        event = threading.Event()
        with self._lock:
            self._events[run_id] = event
        try:
            self._queue.put_nowait((run_id, suite_id, model_ids, settings))
        except queue.Full:
            with connect(self.db_path) as conn:
                finish_run(conn, run_id, "failed")
            self._signal_done(run_id)

    def cancel(self, run_id: int) -> None:
        with connect(self.db_path) as conn:
            status = request_run_cancel(conn, run_id)
        if status == "canceling":
            with self._lock:
                self._canceling.add(run_id)
        if status == "canceled":
            self._signal_done(run_id)

    def wait(self, run_id: int, timeout_s: float = 10.0) -> None:
        with self._lock:
            event = self._events.get(run_id)
        if event is not None:
            event.wait(timeout=timeout_s)

    def _is_canceling(self, run_id: int) -> bool:
        with self._lock:
            return run_id in self._canceling

    def _signal_done(self, run_id: int) -> None:
        with self._lock:
            event = self._events.pop(run_id, None)
        if event is not None:
            event.set()

    def _work_loop(self) -> None:
        while True:
            run_id, suite_id, model_ids, settings = self._queue.get()
            try:
                self._execute(
                    run_id=run_id,
                    suite_id=suite_id,
                    model_ids=model_ids,
                    settings=settings,
                )
            except Exception as exc:
                LOGGER.warning("run worker failure %s: %s", run_id, type(exc).__name__)
            finally:
                self._queue.task_done()

    def _execute(
        self,
        *,
        run_id: int,
        suite_id: int,
        model_ids: list[int],
        settings: dict[str, Any],
    ) -> None:
        any_success = False
        canceled = False
        with connect(self.db_path) as conn:
            try:
                if self._is_canceling(run_id):
                    finish_run(conn, run_id, "canceled")
                    return
                if not mark_run_running(conn, run_id):
                    return
                suite_payload = get_suite(conn, suite_id)
                for test in suite_payload["tests"]:
                    test_success, canceled = self._execute_test(
                        conn,
                        run_id=run_id,
                        test=test,
                        model_ids=model_ids,
                        settings=settings,
                    )
                    any_success = test_success or any_success
                    if canceled:
                        break
                if canceled:
                    finish_run(conn, run_id, "canceled")
                else:
                    finish_run(conn, run_id, "completed" if any_success else "failed")
            except (KeyError, sqlite3.Error):
                LOGGER.warning("run worker database failure: %s", run_id)
                finish_run(conn, run_id, "failed")
            finally:
                with self._lock:
                    self._canceling.discard(run_id)
                self._signal_done(run_id)

    def _execute_test(
        self,
        conn: sqlite3.Connection,
        *,
        run_id: int,
        test: dict[str, Any],
        model_ids: list[int],
        settings: dict[str, Any],
    ) -> tuple[bool, bool]:
        any_success = False
        hosted_models: list[dict[str, Any]] = []
        for model_id in model_ids:
            if self._is_canceling(run_id):
                return any_success, True
            model = get_model(conn, model_id)
            if model["provider"] in HOSTED_PROVIDER_TYPES:
                hosted_models.append(model)
                continue
            adapter_result = self._complete_one(test, model, settings)
            any_success = (
                self._record_result(
                    conn,
                    run_id,
                    test,
                    model,
                    settings,
                    adapter_result,
                )
                or any_success
            )

        if hosted_models:
            with ThreadPoolExecutor(
                max_workers=min(4, len(hosted_models)),
                thread_name_prefix=f"starklabs-hosted-{run_id}",
            ) as executor:
                hosted_results = executor.map(
                    partial(self._complete_one, test, settings=settings),
                    hosted_models,
                )
                for model, adapter_result in zip(hosted_models, hosted_results, strict=True):
                    any_success = (
                        self._record_result(
                            conn,
                            run_id,
                            test,
                            model,
                            settings,
                            adapter_result,
                        )
                        or any_success
                    )
        return any_success, self._is_canceling(run_id)

    @staticmethod
    def _record_result(
        conn: sqlite3.Connection,
        run_id: int,
        test: dict[str, Any],
        model: dict[str, Any],
        settings: dict[str, Any],
        adapter_result: dict[str, Any],
    ) -> bool:
        result_id = add_result(
            conn,
            run_id=run_id,
            test_id=test["id"],
            model=model,
            status=adapter_result["status"],
            raw_output=adapter_result["raw_output"],
            error=adapter_result["error"],
            settings=settings,
            timing_ms=adapter_result["timing_ms"],
            request_count=adapter_result["request_count"],
        )
        if adapter_result["raw_output"]:
            conn.execute(
                """
                insert into artifacts (result_id, name, media_type, body)
                values (?, ?, ?, ?)
                """,
                (
                    result_id,
                    "raw-output.txt",
                    "text/plain",
                    adapter_result["raw_output"],
                ),
            )
            conn.commit()
        return str(adapter_result["status"]) == "completed"

    def _complete_one(
        self,
        test: dict[str, Any],
        model: dict[str, Any],
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            adapter = adapter_for(
                model["provider"],
                endpoint=model["endpoint"],
                credential_ref=model.get("credential_ref"),
                keychain=self.keychain,
                transport=self.provider_transport,
            )
            adapter_result = adapter.complete(
                AdapterRequest(
                    provider=model["provider"],
                    model_id=model["model_id"],
                    prompt=test["prompt"],
                    settings=settings,
                ),
            )
        except Exception as exc:
            LOGGER.warning("provider failure: %s", type(exc).__name__)
            return {
                "status": "failed",
                "raw_output": None,
                "error": {"code": "provider_exception", "message": type(exc).__name__},
                "timing_ms": 0,
                "request_count": 1,
            }
        else:
            return {
                "status": adapter_result.status,
                "raw_output": adapter_result.raw_output,
                "error": adapter_result.error,
                "timing_ms": adapter_result.timing_ms,
                "request_count": adapter_result.request_count,
            }
