import json
import re
from dataclasses import dataclass
from pathlib import Path

from starkeval.runner import CaseResult, EvaluationRun, RunSummary


@dataclass(frozen=True)
class ReportPaths:
    json: Path
    markdown: Path


def _safe_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-") or "evaluation"


def _score(score: float | None) -> str:
    return "n/a" if score is None else f"{score:.1%}"


def _safe_code_fence(content: str) -> str:
    longest_run = max((len(match.group()) for match in re.finditer(r"`+", content)), default=0)
    return "`" * max(3, longest_run + 1)


def _summary_row(model: str, summary: RunSummary) -> str:
    return (
        f"| {model} | {summary.passed} | {summary.failed} | {summary.errors} | "
        f"{_score(summary.average_score)} |"
    )


def _result_section(result: CaseResult) -> list[str]:
    status_icon = {"passed": "PASS", "failed": "FAIL", "error": "ERROR"}[result.status]
    lines = [
        f"### {result.case_title} — {result.model} — sample {result.repeat}",
        "",
        f"**{status_icon}** · score {_score(result.score)} · {result.duration_ms:.1f} ms",
        "",
    ]
    if result.error:
        lines.extend([f"**Error:** `{result.error}`", ""])
    if result.raw_output is not None:
        fence = _safe_code_fence(result.raw_output)
        lines.extend(["**Raw output**", "", f"{fence}text", result.raw_output, fence, ""])
    if result.grader_results:
        lines.extend(
            [
                "**Checks**",
                "",
                "| Type | Expected | Result | Weight |",
                "|---|---|---:|---:|",
            ]
        )
        for grader in result.grader_results:
            expected = grader.expected.replace("|", "\\|").replace("\n", " ")
            outcome = "pass" if grader.passed else "fail"
            lines.append(f"| {grader.type} | `{expected}` | {outcome} | {grader.weight:g} |")
        lines.append("")
    return lines


def render_markdown(run: EvaluationRun) -> str:
    lines = [
        f"# Evaluation: {run.suite_name}",
        "",
        f"Started: `{run.started_at.isoformat()}`  ",
        f"Mode: `{run.mode}` · concurrency: `{run.concurrency}` · repeats: `{run.repeat}`",
        "",
        "## At a glance",
        "",
        f"- **{run.summary.passed}/{run.summary.total} passed**",
        f"- **{run.summary.failed} failed · {run.summary.errors} errors**",
        f"- **Average score: {_score(run.summary.average_score)}**",
        "",
        "| Model | Passed | Failed | Errors | Average score |",
        "|---|---:|---:|---:|---:|",
    ]
    lines.extend(_summary_row(model, run.by_model[model]) for model in run.models)
    lines.extend(["", "## Case results", ""])
    for result in run.results:
        lines.extend(_result_section(result))
    return "\n".join(lines).rstrip() + "\n"


def write_reports(run: EvaluationRun, output_dir: Path) -> ReportPaths:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = run.started_at.strftime("%Y%m%dT%H%M%S.%fZ")
    stem = f"{_safe_name(run.suite_name)}_{timestamp}"
    json_path = output_dir / f"{stem}.json"
    markdown_path = output_dir / f"{stem}.md"
    json_path.write_text(
        json.dumps(run.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(run), encoding="utf-8")
    return ReportPaths(json=json_path, markdown=markdown_path)
