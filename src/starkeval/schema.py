import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

_CREDENTIAL_KEY_MARKERS = {
    "apikey",
    "apitoken",
    "accesstoken",
    "authtoken",
    "bearertoken",
    "clientsecret",
    "idtoken",
    "privatekey",
    "refreshtoken",
    "webhookurl",
}
_CREDENTIAL_KEY_PARTS = {
    "authorization",
    "credential",
    "credentials",
    "passwd",
    "password",
    "secret",
    "token",
}


def _is_credential_key(key: str) -> bool:
    separated = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    parts = set(re.findall(r"[a-z0-9]+", separated.casefold()))
    normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
    return bool(parts & _CREDENTIAL_KEY_PARTS) or any(
        marker in normalized for marker in _CREDENTIAL_KEY_MARKERS
    )


def _find_unsafe_setting(value: object, path: str = "settings") -> str | None:
    if isinstance(value, dict):
        for key, nested_value in value.items():
            nested_path = f"{path}.{key}"
            if _is_credential_key(key):
                return nested_path
            unsafe_path = _find_unsafe_setting(nested_value, nested_path)
            if unsafe_path is not None:
                return unsafe_path
    elif isinstance(value, list):
        for index, nested_value in enumerate(value):
            unsafe_path = _find_unsafe_setting(nested_value, f"{path}[{index}]")
            if unsafe_path is not None:
                return unsafe_path
    return None


class GraderSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["exact", "contains", "regex"]
    value: str = Field(min_length=1)
    ignore_case: bool = False
    weight: float = Field(default=1.0, gt=0)

    @model_validator(mode="after")
    def validate_regex(self) -> "GraderSpec":
        if self.type == "regex":
            try:
                re.compile(self.value)
            except re.error as error:
                raise ValueError(f"invalid regex grader pattern: {error.msg}") from error
        return self


class EvalCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    title: str = Field(min_length=1)
    description: str | None = None
    system_prompt: str | None = None
    prompt: str = Field(min_length=1)
    graders: list[GraderSpec] = Field(min_length=1)


class EvalSuite(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    name: str = Field(min_length=1)
    description: str | None = None
    settings: dict[str, JsonValue] = Field(default_factory=dict)
    cases: list[EvalCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_suite(self) -> "EvalSuite":
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("case ids must be unique")
        unsafe_path = _find_unsafe_setting(self.settings)
        if unsafe_path is not None:
            raise ValueError(
                "credentials must come from the environment, not suite settings; "
                f"unsafe setting: {unsafe_path}"
            )
        return self


def load_suite(path: Path) -> EvalSuite:
    with path.open(encoding="utf-8") as suite_file:
        raw_suite = yaml.safe_load(suite_file)
    return EvalSuite.model_validate(raw_suite)
