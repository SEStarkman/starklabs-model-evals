import asyncio

import pytest

from starkeval.providers import ModelRequest, ProviderResponse
from starkeval.runner import run_suite
from starkeval.schema import EvalCase, EvalSuite, GraderSpec


def make_suite() -> EvalSuite:
    return EvalSuite(
        name="test-suite",
        settings={"temperature": 0},
        cases=[
            EvalCase(
                id="alpha",
                title="Alpha",
                prompt="alpha prompt",
                graders=[GraderSpec(type="contains", value="response")],
            ),
            EvalCase(
                id="beta",
                title="Beta",
                prompt="beta prompt",
                graders=[GraderSpec(type="contains", value="response")],
            ),
        ],
    )


class RecordingProvider:
    def __init__(self, *, fail_prompt: str | None = None, delay: float = 0) -> None:
        self.requests: list[ModelRequest] = []
        self.fail_prompt = fail_prompt
        self.delay = delay
        self.active = 0
        self.max_active = 0

    async def complete(self, request: ModelRequest) -> ProviderResponse:
        self.requests.append(request)
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            if request.messages[-1].content == self.fail_prompt:
                raise RuntimeError("provider exploded")
            return ProviderResponse(output="response", metadata={"provider": "recording"})
        finally:
            self.active -= 1


@pytest.mark.asyncio
async def test_sequential_cases_use_fresh_independent_requests() -> None:
    provider = RecordingProvider()

    run = await run_suite(
        make_suite(),
        models=["test/model"],
        mode="sequential",
        concurrency=4,
        repeat=1,
        provider_resolver=lambda _model: provider,
    )

    assert [request.messages[-1].content for request in provider.requests] == [
        "alpha prompt",
        "beta prompt",
    ]
    assert provider.requests[0] is not provider.requests[1]
    assert provider.requests[0].messages == provider.requests[0].messages[-1:]
    assert provider.requests[1].messages == provider.requests[1].messages[-1:]
    assert [result.status for result in run.results] == ["passed", "passed"]
    assert [result.raw_output for result in run.results] == ["response", "response"]
    assert all(result.settings == {"temperature": 0} for result in run.results)
    assert all(result.duration_ms >= 0 for result in run.results)
    assert run.summary.total == 2
    assert run.summary.passed == 2


@pytest.mark.asyncio
async def test_parallel_mode_enforces_configured_concurrency_bound() -> None:
    suite = EvalSuite(
        name="parallel-suite",
        cases=[
            EvalCase(
                id=f"case-{index}",
                title=f"Case {index}",
                prompt=f"prompt {index}",
                graders=[GraderSpec(type="exact", value="response")],
            )
            for index in range(6)
        ],
    )
    provider = RecordingProvider(delay=0.01)

    run = await run_suite(
        suite,
        models=["test/model"],
        mode="parallel",
        concurrency=2,
        repeat=1,
        provider_resolver=lambda _model: provider,
    )

    assert provider.max_active == 2
    assert [result.case_id for result in run.results] == [f"case-{index}" for index in range(6)]


@pytest.mark.asyncio
async def test_run_expands_multi_model_case_repeat_matrix_in_deterministic_order() -> None:
    providers = {"test/a": RecordingProvider(), "test/b": RecordingProvider()}

    run = await run_suite(
        make_suite(),
        models=["test/a", "test/b"],
        mode="sequential",
        concurrency=1,
        repeat=2,
        provider_resolver=lambda model: providers[model],
    )

    assert [(result.model, result.case_id, result.repeat) for result in run.results] == [
        (model, case_id, repetition)
        for model in ["test/a", "test/b"]
        for case_id in ["alpha", "beta"]
        for repetition in [1, 2]
    ]
    assert run.summary.total == 8
    assert run.by_model["test/a"].total == 4
    assert run.by_model["test/b"].total == 4


@pytest.mark.asyncio
async def test_provider_failure_is_captured_without_aborting_batch() -> None:
    provider = RecordingProvider(fail_prompt="alpha prompt")

    run = await run_suite(
        make_suite(),
        models=["test/model"],
        mode="sequential",
        concurrency=1,
        repeat=1,
        provider_resolver=lambda _model: provider,
    )

    assert [result.status for result in run.results] == ["error", "passed"]
    assert run.results[0].error == "RuntimeError: provider exploded"
    assert run.results[0].raw_output is None
    assert run.results[1].raw_output == "response"
    assert run.summary.errors == 1
    assert run.summary.passed == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("models", "concurrency", "repeat", "message"),
    [
        ([], 1, 1, "at least one model"),
        (["test/model"], 0, 1, "concurrency must be positive"),
        (["test/model"], 1, 0, "repeat must be positive"),
    ],
)
async def test_run_rejects_invalid_batch_dimensions(
    models: list[str], concurrency: int, repeat: int, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        await run_suite(
            make_suite(),
            models=models,
            mode="sequential",
            concurrency=concurrency,
            repeat=repeat,
        )
