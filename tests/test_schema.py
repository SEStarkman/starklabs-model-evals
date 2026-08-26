from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from starkeval.schema import load_suite


def test_load_suite_parses_reviewable_yaml(tmp_path: Path) -> None:
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(
        """
name: core
settings:
  temperature: 0
  max_tokens: 200
cases:
  - id: strawberry-count
    title: Strawberry counting smoke check
    prompt: How many letter r characters are in strawberry?
    graders:
      - type: exact
        value: "3"
""".strip()
    )

    suite = load_suite(suite_path)

    assert suite.name == "core"
    assert suite.cases[0].id == "strawberry-count"
    assert suite.cases[0].graders[0].type == "exact"
    assert suite.settings == {"temperature": 0, "max_tokens": 200}


def test_load_suite_rejects_duplicate_case_ids(tmp_path: Path) -> None:
    suite_path = tmp_path / "duplicate.yaml"
    suite_path.write_text(
        """
name: duplicate
cases:
  - id: repeated
    title: First
    prompt: First prompt
    graders: [{type: contains, value: first}]
  - id: repeated
    title: Second
    prompt: Second prompt
    graders: [{type: contains, value: second}]
""".strip()
    )

    with pytest.raises(ValidationError, match="case ids must be unique"):
        load_suite(suite_path)


def test_load_suite_rejects_secret_like_settings(tmp_path: Path) -> None:
    suite_path = tmp_path / "secret.yaml"
    suite_path.write_text(
        """
name: unsafe
settings:
  api_key: should-never-be-here
cases:
  - id: case
    title: Case
    prompt: Prompt
    graders: [{type: exact, value: output}]
""".strip()
    )

    with pytest.raises(ValidationError, match="credentials must come from the environment"):
        load_suite(suite_path)


@pytest.mark.parametrize(
    ("settings", "unsafe_path"),
    [
        ({"apiKey": "never-print-this"}, "settings.apiKey"),
        ({"api-key": "never-print-this"}, "settings.api-key"),
        ({"access_token": "never-print-this"}, "settings.access_token"),
        ({"bearerToken": "never-print-this"}, "settings.bearerToken"),
        ({"authorization": "never-print-this"}, "settings.authorization"),
        ({"client_secret": "never-print-this"}, "settings.client_secret"),
        ({"private_key": "never-print-this"}, "settings.private_key"),
        ({"webhook_url": "never-print-this"}, "settings.webhook_url"),
        (
            {"providers": [{"options": {"Api-Key": "never-print-this"}}]},
            "settings.providers[0].options.Api-Key",
        ),
    ],
)
def test_load_suite_rejects_nested_credential_aliases_without_exposing_values(
    tmp_path: Path, settings: dict[str, object], unsafe_path: str
) -> None:
    suite_path = tmp_path / "unsafe.yaml"
    suite_path.write_text(
        yaml.safe_dump(
            {
                "name": "unsafe",
                "settings": settings,
                "cases": [
                    {
                        "id": "case",
                        "title": "Case",
                        "prompt": "Prompt",
                        "graders": [{"type": "exact", "value": "output"}],
                    }
                ],
            }
        )
    )

    with pytest.raises(ValidationError) as exc_info:
        load_suite(suite_path)

    message = str(exc_info.value)
    assert unsafe_path in message
    assert "never-print-this" not in message


def test_load_suite_rejects_invalid_regex_grader_patterns(tmp_path: Path) -> None:
    suite_path = tmp_path / "invalid-regex.yaml"
    suite_path.write_text(
        """
name: invalid-regex
cases:
  - id: case
    title: Case
    prompt: Prompt
    graders:
      - type: regex
        value: "[unterminated"
""".strip()
    )

    with pytest.raises(ValidationError, match="invalid regex grader pattern"):
        load_suite(suite_path)
