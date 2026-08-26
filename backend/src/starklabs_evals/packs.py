from __future__ import annotations

import json
import re
from typing import Any

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
MAX_FIELD_BYTES = 64 * 1024
MAX_TESTS = 100
EXPECTED_OUTPUT_TYPES = {"text", "json", "html", "code"}


def validate_safe_id(value: str, field_name: str) -> None:
    if not SAFE_ID.fullmatch(value):
        msg = f"unsafe {field_name}"
        raise ValueError(msg)


def validate_reference_file(file_payload: dict[str, Any], seen_names: set[str]) -> dict[str, str]:
    name = str(file_payload.get("name", ""))
    if (
        not name
        or name in {".", ".."}
        or "/" in name
        or "\\" in name
        or ".." in name
        or "->" in name
        or re.match(r"^[A-Za-z]:", name)
    ):
        msg = "unsafe reference filename"
        raise ValueError(msg)
    if name in seen_names:
        msg = "duplicate reference filename"
        raise ValueError(msg)
    seen_names.add(name)
    content = str(file_payload.get("content", ""))
    if len(content.encode()) > MAX_FIELD_BYTES:
        msg = "reference file too large"
        raise OverflowError(msg)
    media_type = str(file_payload.get("media_type", "text/plain"))[:120] or "text/plain"
    return {"name": name, "media_type": media_type, "content": content}


def validate_reference_files(reference_files_payload: object) -> list[dict[str, str]]:
    if not isinstance(reference_files_payload, list):
        msg = "invalid reference_files"
        raise ValueError(msg)
    seen_files: set[str] = set()
    reference_files = [
        validate_reference_file(file_payload, seen_files)
        for file_payload in reference_files_payload
        if isinstance(file_payload, dict)
    ]
    if len(reference_files) != len(reference_files_payload):
        msg = "invalid reference file entry"
        raise ValueError(msg)
    return reference_files


def validate_optional_text(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text.encode()) > MAX_FIELD_BYTES:
        msg = f"{field_name} too large"
        raise OverflowError(msg)
    return text


def normalize_test(test: dict[str, Any], *, index: int, seen: set[str]) -> dict[str, Any]:
    stable_id = str(test.get("stable_id", f"test-{index}"))
    validate_safe_id(stable_id, "test stable_id")
    if stable_id in seen:
        msg = "duplicate test stable_id"
        raise ValueError(msg)
    seen.add(stable_id)
    title = str(test.get("title", "")).strip()
    prompt = str(test.get("prompt", ""))
    if not title or not prompt:
        msg = "test title and prompt are required"
        raise ValueError(msg)
    if len(prompt.encode()) > MAX_FIELD_BYTES:
        msg = "test prompt too large"
        raise OverflowError(msg)
    expected_output_type = str(test.get("expected_output_type", "text"))
    if expected_output_type not in EXPECTED_OUTPUT_TYPES:
        msg = "invalid expected_output_type"
        raise ValueError(msg)
    execution_settings = test.get("execution_settings", {})
    if not isinstance(execution_settings, dict):
        msg = "invalid execution_settings"
        raise ValueError(msg)
    if len(json.dumps(execution_settings, sort_keys=True).encode()) > MAX_FIELD_BYTES:
        msg = "execution settings too large"
        raise OverflowError(msg)
    expected = test.get("expected_output")
    return {
        "stable_id": stable_id,
        "title": title[:200],
        "prompt": prompt,
        "expected_output": str(expected) if expected is not None else None,
        "reference_text": validate_optional_text(test.get("reference_text"), "reference text"),
        "reference_files": validate_reference_files(test.get("reference_files", [])),
        "expected_output_type": expected_output_type,
        "private_rubric": validate_optional_text(test.get("private_rubric"), "private rubric"),
        "execution_settings": execution_settings,
        "executable": bool(test.get("executable", False)),
    }


def validate_pack(payload: dict[str, Any], *, max_bytes: int = MAX_FIELD_BYTES) -> dict[str, Any]:
    encoded = json.dumps(payload, ensure_ascii=False).encode()
    if len(encoded) > max_bytes:
        msg = "eval pack too large"
        raise OverflowError(msg)
    schema_version = payload.get("schema_version")
    if schema_version not in {1, 2}:
        msg = "unsupported eval pack schema_version"
        raise ValueError(msg)
    pack_id = str(payload.get("pack_id", ""))
    version = str(payload.get("version", ""))
    validate_safe_id(pack_id, "pack_id")
    validate_safe_id(version, "version")
    tests = payload.get("tests")
    if not isinstance(tests, list) or len(tests) > MAX_TESTS:
        msg = "invalid tests"
        raise ValueError(msg)
    normalized_tests: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, test in enumerate(tests, start=1):
        if not isinstance(test, dict):
            msg = "invalid test entry"
            raise ValueError(msg)
        normalized_tests.append(normalize_test(test, index=index, seen=seen))
    return {
        "stable_id": pack_id,
        "name": str(payload.get("name", pack_id)).strip()[:200] or pack_id,
        "version": version,
        "tests": normalized_tests,
    }


def export_payload(suite: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "pack_id": suite["stable_id"],
        "name": suite["name"],
        "version": suite["version"],
        "tests": [
            {
                "stable_id": test["stable_id"],
                "title": test["title"],
                "prompt": test["prompt"],
                "expected_output": test["expected_output"],
                "reference_text": test.get("reference_text"),
                "reference_files": test.get("reference_files", []),
                "expected_output_type": test.get("expected_output_type", "text"),
                "private_rubric": test.get("private_rubric"),
                "execution_settings": test.get("execution_settings", {}),
                "executable": test.get("executable", False),
            }
            for test in suite["tests"]
        ],
    }
