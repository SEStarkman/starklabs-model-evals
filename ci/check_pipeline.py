#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DIGEST_PATTERN = re.compile(r"version:\s*\{\s*digest:\s*['\"]?sha256:[0-9a-f]{64}['\"]?\s*\}")
TAG_PATTERN = re.compile(r"\btag:\s*([^,}\s]+)")
CURL_PIPE_PATTERN = re.compile(r"\bcurl\b[^\n|]*\|\s*(?:ba)?sh\b")
DEPLOY_PATTERN = re.compile(
    r"\bterraform\s+(?:apply|destroy)\b|\bgcloud\b[^\n]*(?:deploy|apply|builds\s+submit)\b",
)


def pipeline_files(root: Path) -> list[Path]:
    ci_root = root / "ci"
    return sorted(
        path
        for path in ci_root.rglob("*")
        if path.is_file() and path.suffix in {".yml", ".yaml", ".sh"}
    )


def find_violations(root: Path) -> list[str]:  # noqa: PLR0912
    violations: list[str] = []
    workflows = root / ".github" / "workflows"
    if workflows.exists() and any(workflows.glob("*.y*ml")):
        violations.append("GitHub Actions are not allowed; use the Concourse pipeline")

    for path in pipeline_files(root):
        relative = path.relative_to(root)
        text = path.read_text(encoding="utf-8")
        if "image_resource:" in text:
            if DIGEST_PATTERN.search(text) is None:
                violations.append(f"{relative}: task image requires an immutable digest")
            for raw_tag in TAG_PATTERN.findall(text):
                tag = raw_tag.strip("'\"")
                if tag in {"latest", "main", "master"} or re.fullmatch(r"v?\d+", tag):
                    violations.append(f"{relative}: mutable image tag is forbidden: {tag}")
        if CURL_PIPE_PATTERN.search(text):
            violations.append(f"{relative}: curl-pipe installer is forbidden")
        if DEPLOY_PATTERN.search(text):
            violations.append(f"{relative}: Terraform/GCP deployment commands are forbidden")

        for line_number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if ("uv sync" in stripped or "uv run" in stripped) and "--frozen" not in stripped:
                violations.append(
                    f"{relative}:{line_number}: unfrozen uv command is forbidden",
                )
            if "uv pip install" in stripped or re.search(r"(^|\s)pip(?:3)?\s+install\b", stripped):
                violations.append(
                    f"{relative}:{line_number}: unfrozen uv command is forbidden",
                )
            if re.search(r"(^|\s)npm\s+install\b", stripped):
                violations.append(
                    f"{relative}:{line_number}: unfrozen npm command is forbidden",
                )
            if "npm ci" in stripped and "--ignore-scripts" not in stripped:
                violations.append(
                    f"{relative}:{line_number}: npm ci must disable unnecessary lifecycle scripts",
                )
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate local Concourse supply-chain policy")
    parser.add_argument("--root", type=Path, default=Path())
    args = parser.parse_args()

    violations = find_violations(args.root.resolve())
    if violations:
        for violation in violations:
            print(violation, file=sys.stderr)
        return 1
    print("Concourse supply-chain policy: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
