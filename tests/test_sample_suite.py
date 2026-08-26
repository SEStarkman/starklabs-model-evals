from pathlib import Path

import pytest

from starkeval.runner import run_suite
from starkeval.schema import load_suite


def test_core_sample_suite_has_smoke_and_substantive_poker_cases() -> None:
    suite = load_suite(Path("suites/core.yaml"))

    assert [case.id for case in suite.cases] == ["strawberry-count", "poker-river-analysis"]
    strawberry, poker = suite.cases
    assert "smoke" in strawberry.description.casefold()
    assert len(poker.prompt) > 300
    assert {grader.type for grader in poker.graders} == {"contains", "regex"}
    assert len(poker.graders) >= 5


@pytest.mark.asyncio
async def test_mock_provider_passes_every_core_case_without_credentials() -> None:
    suite = load_suite(Path("suites/core.yaml"))

    run = await run_suite(
        suite,
        models=["mock/baseline"],
        mode="parallel",
        concurrency=2,
        repeat=1,
    )

    assert [(result.case_id, result.status) for result in run.results] == [
        ("strawberry-count", "passed"),
        ("poker-river-analysis", "passed"),
    ]
