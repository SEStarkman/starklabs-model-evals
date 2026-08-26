from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def test_macos_app_builder_requires_prebuilt_web_when_skipping_build(tmp_path) -> None:
    repo_root = tmp_path / "repo-missing-dist"
    subprocess.run(["cp", "-R", ".", str(repo_root)], check=True)
    subprocess.run(["rm", "-rf", str(repo_root / "web" / "dist")], check=True)
    script = Path("packaging/macos/build_app.py")
    result = subprocess.run(
        [
            "python3",
            str(script),
            "--repo-root",
            str(repo_root),
            "--output",
            str(tmp_path),
            "--skip-web-build",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "web/dist/index.html" in result.stderr


def test_macos_app_builder_creates_unsigned_launcher_from_existing_dist(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    subprocess.run(["cp", "-R", ".", str(repo_root)], check=True)
    source_dist = Path("web/dist")
    if not (source_dist / "index.html").exists():
        pytest.skip("package test requires the real web build")
    dist = repo_root / "web" / "dist"
    shutil.rmtree(dist, ignore_errors=True)
    shutil.copytree(source_dist, dist)
    (repo_root / "secret.sqlite").write_text("secret", encoding="utf-8")
    (repo_root / "dist").mkdir(exist_ok=True)
    (repo_root / "dist" / "wheel-with-local-path.whl").write_text("artifact", encoding="utf-8")
    (repo_root / ".uv-cache").mkdir(exist_ok=True)
    (repo_root / ".uv-cache" / "cached-secret").write_text("secret", encoding="utf-8")
    (repo_root / "backend" / "src" / "generated.egg-info").mkdir(parents=True)
    (repo_root / "backend" / "src" / "generated.egg-info" / "PKG-INFO").write_text(
        "generated",
        encoding="utf-8",
    )
    (repo_root / "web" / "test-results").mkdir(exist_ok=True)
    (repo_root / "web" / "test-results" / "result.json").write_text("{}", encoding="utf-8")

    script = Path("packaging/macos/build_app.py")
    result = subprocess.run(
        [
            "python3",
            str(script),
            "--repo-root",
            str(repo_root),
            "--output",
            str(tmp_path),
            "--skip-web-build",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    app_path = tmp_path / "Starklabs Model Evals.app"
    assert app_path.exists()
    assert (app_path / "Contents" / "Info.plist").exists()
    launcher = app_path / "Contents" / "MacOS" / "starklabs-model-evals"
    assert launcher.exists()
    assert launcher.stat().st_mode & 0o111
    assert "unsigned" in result.stdout.lower()
    packaged_repo = app_path / "Contents" / "Resources" / "repo"
    assert (packaged_repo / "web" / "dist" / "index.html").exists()
    assert any((packaged_repo / "web" / "dist" / "assets").iterdir())
    assert not (packaged_repo / "dist").exists()
    assert not (packaged_repo / "secret.sqlite").exists()
    assert not (packaged_repo / ".uv-cache").exists()
    assert not (packaged_repo / "backend" / "src" / "generated.egg-info").exists()
    assert not (packaged_repo / "web" / "test-results").exists()
    launcher_text = launcher.read_text(encoding="utf-8")
    assert "STARKLABS_EVALS_SMOKE" in launcher_text
    assert "PYTHONDONTWRITEBYTECODE=1" in launcher_text
    assert 'UV_PROJECT_ENVIRONMENT="$DATA_DIR/runtime-venv"' in launcher_text
    assert "uv sync --frozen --no-dev" in launcher_text
    assert '"$UV_PROJECT_ENVIRONMENT/bin/python" -m starklabs_evals.server' in launcher_text
    assert 'PORT="$(python3 -c' in launcher_text
    assert '--port "$PORT"' in launcher_text
    assert '/usr/sbin/lsof -nP -a -p "$PID" -iTCP:"$PORT" -sTCP:LISTEN' in launcher_text
    assert "--port 8765" not in launcher_text


def test_macos_app_builder_rejects_symlinks_in_runtime_sources(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    shutil.copytree(Path.cwd(), repo_root, ignore=shutil.ignore_patterns("node_modules", ".venv"))
    source_dist = Path("web/dist")
    if not (source_dist / "index.html").exists():
        pytest.skip("package test requires the real web build")
    dist = repo_root / "web" / "dist"
    shutil.rmtree(dist, ignore_errors=True)
    shutil.copytree(source_dist, dist)
    private_file = tmp_path / "private.txt"
    private_file.write_text("must not be packaged", encoding="utf-8")
    (repo_root / "backend" / "src" / "private-link").symlink_to(private_file)

    result = subprocess.run(
        [
            "python3",
            "packaging/macos/build_app.py",
            "--repo-root",
            str(repo_root),
            "--output",
            str(tmp_path / "output"),
            "--skip-web-build",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "symbolic link" in result.stderr.lower()
