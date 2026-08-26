import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from starkeval.cli import app


@pytest.mark.parametrize("mode", ["parallel", "sequential"])
def test_cli_runs_complete_suite_in_one_command(tmp_path: Path, mode: str) -> None:
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(
        """
name: cli-smoke
cases:
  - id: strawberry-count
    title: Strawberry smoke
    prompt: How many r letters are in strawberry?
    graders:
      - type: exact
        value: "3"
""".strip()
    )
    output_dir = tmp_path / "results"

    result = CliRunner().invoke(
        app,
        [
            "run",
            "--suite",
            str(suite_path),
            "--model",
            "mock/baseline",
            "--mode",
            mode,
            "--concurrency",
            "2",
            "--output-dir",
            str(output_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Completed 1 evaluations: 1 passed, 0 failed, 0 errors." in result.output
    json_paths = list(output_dir.glob("*.json"))
    markdown_paths = list(output_dir.glob("*.md"))
    assert len(json_paths) == 1
    assert len(markdown_paths) == 1
    payload = json.loads(json_paths[0].read_text())
    assert payload["mode"] == mode
    assert [case["case_id"] for case in payload["results"]] == ["strawberry-count"]
