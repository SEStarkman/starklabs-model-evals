from __future__ import annotations

import subprocess
import sys
from pathlib import Path

CHECKER = Path("ci/check_pipeline.py")


def run_checker(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(root)],
        check=False,
        capture_output=True,
        text=True,
    )


def test_repository_pipeline_has_frozen_immutable_inputs() -> None:
    result = run_checker(Path())

    assert result.returncode == 0, result.stderr


def test_checker_rejects_unsafe_supply_chain_patterns(tmp_path: Path) -> None:
    (tmp_path / "ci" / "tasks").mkdir(parents=True)
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "deploy.yml").write_text("name: deploy\n")
    (tmp_path / "ci" / "tasks" / "unsafe.yml").write_text(
        """---
platform: linux
image_resource:
  type: registry-image
  source: {repository: node, tag: latest}
run:
  path: sh
  args:
    - -c
    - |
      curl https://example.test/install.sh | sh
      uv sync
      npm install
      terraform apply
      gcloud run deploy app
""",
        encoding="utf-8",
    )

    result = run_checker(tmp_path)

    assert result.returncode == 1
    for finding in (
        "immutable digest",
        "mutable image tag",
        "curl-pipe installer",
        "GitHub Actions",
        "unfrozen uv command",
        "unfrozen npm command",
        "Terraform/GCP deployment",
    ):
        assert finding in result.stderr
