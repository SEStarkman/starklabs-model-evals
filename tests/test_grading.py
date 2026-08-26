import pytest

from starkeval.grading import grade_output
from starkeval.schema import GraderSpec


@pytest.mark.parametrize(
    ("grader", "output", "expected"),
    [
        (GraderSpec(type="exact", value="3"), " 3\n", True),
        (GraderSpec(type="contains", value="pot odds", ignore_case=True), "Use POT ODDS.", True),
        (GraderSpec(type="regex", value=r"raise|fold"), "I would raise here.", True),
        (GraderSpec(type="regex", value=r"^raise$"), "I would raise here.", False),
    ],
)
def test_deterministic_graders(grader: GraderSpec, output: str, expected: bool) -> None:
    result = grade_output(output, [grader])

    assert result.details[0].passed is expected


def test_grade_output_uses_weighted_score_and_requires_all_checks() -> None:
    result = grade_output(
        "Raise because the range is capped.",
        [
            GraderSpec(type="contains", value="raise", ignore_case=True, weight=3),
            GraderSpec(type="contains", value="pot odds", ignore_case=True, weight=1),
        ],
    )

    assert result.score == 0.75
    assert result.passed is False
