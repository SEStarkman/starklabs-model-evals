import json
from pathlib import Path

import pytest

from starkeval.providers import ModelRequest, ProviderResponse
from starkeval.reports import render_markdown, write_reports
from starkeval.runner import run_suite
from starkeval.schema import EvalCase, EvalSuite, GraderSpec


class RawOutputProvider:
    async def complete(self, request: ModelRequest) -> ProviderResponse:
        del request
        return ProviderResponse(
            output="before\n```\n## untrusted heading\n```\nafter",
            metadata={"provider": "raw-output"},
        )


@pytest.mark.asyncio
async def test_write_reports_persists_complete_json_and_readable_markdown(tmp_path: Path) -> None:
    suite = EvalSuite(
        name="report-suite",
        settings={"temperature": 0},
        cases=[
            EvalCase(
                id="strawberry-count",
                title="Strawberry smoke",
                prompt="How many r letters are in strawberry?",
                graders=[GraderSpec(type="exact", value="3")],
            ),
            EvalCase(
                id="poker-analysis",
                title="Poker analysis",
                prompt="Return the default fixture.",
                graders=[GraderSpec(type="exact", value="mock response")],
            ),
        ],
    )
    run = await run_suite(
        suite,
        models=["mock/baseline"],
        mode="sequential",
        concurrency=1,
        repeat=1,
    )

    paths = write_reports(run, tmp_path)

    assert paths.json.exists()
    assert paths.markdown.exists()
    assert paths.json.stem.startswith("report-suite_")
    payload = json.loads(paths.json.read_text())
    assert payload["suite_name"] == "report-suite"
    assert payload["summary"] == {
        "total": 2,
        "passed": 2,
        "failed": 0,
        "errors": 0,
        "average_score": 1.0,
    }
    assert {result["case_id"] for result in payload["results"]} == {
        "strawberry-count",
        "poker-analysis",
    }
    assert all("raw_output" in result for result in payload["results"])
    assert all("duration_ms" in result for result in payload["results"])
    assert all("error" in result for result in payload["results"])
    assert all("settings" in result for result in payload["results"])
    markdown = paths.markdown.read_text()
    assert "# Evaluation: report-suite" in markdown
    assert "## At a glance" in markdown
    assert "| Model | Passed | Failed | Errors | Average score |" in markdown
    assert "## Case results" in markdown
    assert "### Poker analysis — mock/baseline — sample 1" in markdown


@pytest.mark.asyncio
async def test_markdown_report_uses_a_safe_fence_for_untrusted_model_output() -> None:
    suite = EvalSuite(
        name="untrusted-output",
        cases=[
            EvalCase(
                id="case",
                title="Case",
                prompt="Prompt",
                graders=[GraderSpec(type="contains", value="before")],
            )
        ],
    )
    run = await run_suite(
        suite,
        models=["test/model"],
        mode="sequential",
        concurrency=1,
        repeat=1,
        provider_resolver=lambda _model: RawOutputProvider(),
    )

    markdown = render_markdown(run)

    assert "````text\nbefore\n```\n## untrusted heading\n```\nafter\n````" in markdown
