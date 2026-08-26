import re
from typing import Literal

from pydantic import BaseModel

from starkeval.schema import GraderSpec


class GraderResult(BaseModel):
    type: Literal["exact", "contains", "regex"]
    expected: str
    passed: bool
    weight: float


class GradeResult(BaseModel):
    passed: bool
    score: float
    details: list[GraderResult]


def _matches(output: str, grader: GraderSpec) -> bool:
    candidate = output.strip()
    expected = grader.value
    flags = re.IGNORECASE if grader.ignore_case else 0
    if grader.type == "exact":
        if grader.ignore_case:
            return candidate.casefold() == expected.strip().casefold()
        return candidate == expected.strip()
    if grader.type == "contains":
        if grader.ignore_case:
            return expected.casefold() in candidate.casefold()
        return expected in candidate
    return re.search(expected, candidate, flags=flags) is not None


def grade_output(output: str, graders: list[GraderSpec]) -> GradeResult:
    details = [
        GraderResult(
            type=grader.type,
            expected=grader.value,
            passed=_matches(output, grader),
            weight=grader.weight,
        )
        for grader in graders
    ]
    total_weight = sum(detail.weight for detail in details)
    passed_weight = sum(detail.weight for detail in details if detail.passed)
    return GradeResult(
        passed=all(detail.passed for detail in details),
        score=passed_weight / total_weight,
        details=details,
    )
