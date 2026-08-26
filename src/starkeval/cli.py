import asyncio
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from starkeval.reports import write_reports
from starkeval.runner import run_suite
from starkeval.schema import load_suite


class Mode(StrEnum):
    parallel = "parallel"
    sequential = "sequential"


app = typer.Typer(
    name="starkeval",
    help="Run declarative model-evaluation suites across one or more models.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Run declarative model-evaluation suites."""


@app.command("run")
def run_command(
    suite: Annotated[
        Path,
        typer.Option("--suite", exists=True, file_okay=True, dir_okay=False, readable=True),
    ],
    model: Annotated[
        list[str],
        typer.Option("--model", "-m", help="Provider/model ID; repeat for a model matrix."),
    ],
    mode: Annotated[Mode, typer.Option("--mode")] = Mode.parallel,
    concurrency: Annotated[int, typer.Option("--concurrency", min=1)] = 4,
    repeat: Annotated[int, typer.Option("--repeat", min=1)] = 1,
    output_dir: Annotated[Path, typer.Option("--output-dir")] = Path("results"),
) -> None:
    """Run every case in SUITE for every MODEL and persist JSON plus Markdown."""
    try:
        loaded_suite = load_suite(suite)
    except ValidationError as error:
        typer.echo("Invalid suite:", err=True)
        for detail in error.errors(include_input=False):
            location = ".".join(str(part) for part in detail["loc"])
            typer.echo(f"- {location}: {detail['msg']}", err=True)
        raise typer.Exit(code=2) from error

    evaluation = asyncio.run(
        run_suite(
            loaded_suite,
            models=model,
            mode=mode.value,
            concurrency=concurrency,
            repeat=repeat,
        )
    )
    paths = write_reports(evaluation, output_dir)
    typer.echo(
        f"Completed {evaluation.summary.total} evaluations: "
        f"{evaluation.summary.passed} passed, {evaluation.summary.failed} failed, "
        f"{evaluation.summary.errors} errors."
    )
    typer.echo(f"JSON: {paths.json}")
    typer.echo(f"Markdown: {paths.markdown}")
    if evaluation.summary.failed or evaluation.summary.errors:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
