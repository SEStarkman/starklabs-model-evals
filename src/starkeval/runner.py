import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, JsonValue

from starkeval.grading import GraderResult, grade_output
from starkeval.providers import Message, ModelRequest, Provider, resolve_provider
from starkeval.schema import EvalCase, EvalSuite

RunMode = Literal["parallel", "sequential"]
ResultStatus = Literal["passed", "failed", "error"]
ProviderResolver = Callable[[str], Provider]


class CaseResult(BaseModel):
    model: str
    case_id: str
    case_title: str
    repeat: int
    status: ResultStatus
    score: float | None
    raw_output: str | None
    error: str | None
    duration_ms: float
    settings: dict[str, JsonValue]
    provider_metadata: dict[str, JsonValue]
    grader_results: list[GraderResult]


class RunSummary(BaseModel):
    total: int
    passed: int
    failed: int
    errors: int
    average_score: float | None


class EvaluationRun(BaseModel):
    suite_name: str
    started_at: datetime
    completed_at: datetime
    mode: RunMode
    concurrency: int
    repeat: int
    models: list[str]
    results: list[CaseResult]
    summary: RunSummary
    by_model: dict[str, RunSummary]


def _summarize(results: list[CaseResult]) -> RunSummary:
    scores = [result.score for result in results if result.score is not None]
    return RunSummary(
        total=len(results),
        passed=sum(result.status == "passed" for result in results),
        failed=sum(result.status == "failed" for result in results),
        errors=sum(result.status == "error" for result in results),
        average_score=sum(scores) / len(scores) if scores else None,
    )


async def _run_case(
    model: str,
    case: EvalCase,
    repetition: int,
    settings: dict[str, JsonValue],
    provider: Provider,
) -> CaseResult:
    messages: list[Message] = []
    if case.system_prompt:
        messages.append(Message(role="system", content=case.system_prompt))
    messages.append(Message(role="user", content=case.prompt))
    request = ModelRequest(
        model=model,
        messages=tuple(messages),
        settings=dict(settings),
    )
    started = perf_counter()
    try:
        response = await provider.complete(request)
        grade = grade_output(response.output, case.graders)
        return CaseResult(
            model=model,
            case_id=case.id,
            case_title=case.title,
            repeat=repetition,
            status="passed" if grade.passed else "failed",
            score=grade.score,
            raw_output=response.output,
            error=None,
            duration_ms=(perf_counter() - started) * 1000,
            settings=dict(settings),
            provider_metadata=response.metadata,
            grader_results=grade.details,
        )
    except Exception as error:
        return CaseResult(
            model=model,
            case_id=case.id,
            case_title=case.title,
            repeat=repetition,
            status="error",
            score=None,
            raw_output=None,
            error=f"{type(error).__name__}: {error}",
            duration_ms=(perf_counter() - started) * 1000,
            settings=dict(settings),
            provider_metadata={},
            grader_results=[],
        )


async def run_suite(
    suite: EvalSuite,
    *,
    models: list[str],
    mode: RunMode,
    concurrency: int,
    repeat: int,
    provider_resolver: ProviderResolver = resolve_provider,
) -> EvaluationRun:
    if not models:
        raise ValueError("at least one model is required")
    if concurrency < 1:
        raise ValueError("concurrency must be positive")
    if repeat < 1:
        raise ValueError("repeat must be positive")

    started_at = datetime.now(UTC)
    providers = {model: provider_resolver(model) for model in models}
    jobs = [
        (model, case, repetition)
        for model in models
        for case in suite.cases
        for repetition in range(1, repeat + 1)
    ]

    results: list[CaseResult]
    if mode == "sequential":
        results = []
        for model, case, repetition in jobs:
            results.append(
                await _run_case(model, case, repetition, suite.settings, providers[model])
            )
    else:
        semaphore = asyncio.Semaphore(concurrency)

        async def run_bounded(model: str, case: EvalCase, repetition: int) -> CaseResult:
            async with semaphore:
                return await _run_case(
                    model,
                    case,
                    repetition,
                    suite.settings,
                    providers[model],
                )

        results = list(
            await asyncio.gather(
                *(run_bounded(model, case, repetition) for model, case, repetition in jobs)
            )
        )

    by_model = {
        model: _summarize([result for result in results if result.model == model])
        for model in models
    }
    return EvaluationRun(
        suite_name=suite.name,
        started_at=started_at,
        completed_at=datetime.now(UTC),
        mode=mode,
        concurrency=concurrency,
        repeat=repeat,
        models=models,
        results=results,
        summary=_summarize(results),
        by_model=by_model,
    )
