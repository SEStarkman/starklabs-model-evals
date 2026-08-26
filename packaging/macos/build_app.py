from __future__ import annotations

import argparse
import plistlib
import shutil
import subprocess
from pathlib import Path

APP_NAME = "Starklabs Model Evals.app"


def reject_symlinks(source: Path) -> None:
    for path in (source, *source.rglob("*")):
        if path.is_symlink():
            msg = f"Refusing to package symbolic link: {path}"
            raise ValueError(msg)


def copy_tree(source: Path, destination: Path) -> None:
    reject_symlinks(source)
    if destination.exists():
        shutil.rmtree(destination)
    root = source.resolve()

    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored = set(
            shutil.ignore_patterns(
                ".git",
                ".venv",
                ".uv-cache",
                "node_modules",
                ".mypy_cache",
                ".pytest_cache",
                ".ruff_cache",
                "__pycache__",
                "*.py[cod]",
                "*.egg-info",
                "test-results",
                "build",
                "*.sqlite",
                "*.log",
            )(directory, names),
        )
        current = Path(directory).resolve()
        if current == root and "dist" in names:
            ignored.add("dist")
        return ignored

    shutil.copytree(
        source,
        destination,
        ignore=ignore,
        symlinks=False,
    )


def copy_runtime_tree(repo_root: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    for filename in ("pyproject.toml", "uv.lock", "README.md"):
        source = repo_root / filename
        reject_symlinks(source)
        shutil.copy2(source, destination / filename)
    copy_tree(repo_root / "backend" / "src", destination / "backend" / "src")
    copy_tree(repo_root / "web" / "dist", destination / "web" / "dist")


def write_launcher(path: Path) -> None:
    path.write_text(
        """#!/bin/zsh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO_DIR="$APP_DIR/Resources/repo"
DATA_DIR="$HOME/Library/Application Support/Starklabs Model Evals"
mkdir -p "$DATA_DIR"

TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
PORT="$(python3 -c 'import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()')"
export STARKLABS_SESSION_TOKEN="$TOKEN"
export PYTHONDONTWRITEBYTECODE=1
export UV_CACHE_DIR="${TMPDIR:-/tmp}/starklabs-model-evals-uv-cache"
export UV_PROJECT_ENVIRONMENT="$DATA_DIR/runtime-venv"

cd "$REPO_DIR"
uv sync --frozen --no-dev
"$UV_PROJECT_ENVIRONMENT/bin/python" -m starklabs_evals.server \
  --db "$DATA_DIR/evals.sqlite" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --web-dist "$REPO_DIR/web/dist" &
PID="$!"
trap 'kill "$PID" 2>/dev/null || true' EXIT INT TERM

for _ in {1..80}; do
  if /usr/bin/curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
    if ! /usr/sbin/lsof -nP -a -p "$PID" -iTCP:"$PORT" -sTCP:LISTEN >/dev/null; then
      echo "Backend listener is not owned by launcher process $PID" >&2
      exit 1
    fi
    if [[ "${STARKLABS_EVALS_SMOKE:-0}" == "1" ]]; then
      HEADER_NAME="Authorization"
      /usr/bin/printf 'header = "%s: Bearer %s"\n' "$HEADER_NAME" "$TOKEN" | \
        /usr/bin/curl --config - -fsS "http://127.0.0.1:$PORT/api/session" >/dev/null
      kill "$PID" 2>/dev/null || true
      wait "$PID" 2>/dev/null || true
      exit 0
    fi
    /usr/bin/open "http://127.0.0.1:$PORT/#token=$TOKEN"
    wait "$PID"
    exit $?
  fi
  sleep 0.25
done

echo "Backend did not become ready on 127.0.0.1:$PORT" >&2
exit 1
""",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | 0o755)


def write_plist(path: Path) -> None:
    payload = {
        "CFBundleDisplayName": "Starklabs Model Evals",
        "CFBundleExecutable": "starklabs-model-evals",
        "CFBundleIdentifier": "local.starklabs.model-evals",
        "CFBundleName": "Starklabs Model Evals",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
    }
    path.write_bytes(plistlib.dumps(payload, sort_keys=True))


def build_web(repo_root: Path) -> None:
    subprocess.run(
        ["npm", "ci", "--prefix", "web", "--ignore-scripts"],
        cwd=repo_root,
        check=True,
    )
    subprocess.run(["npm", "run", "build", "--prefix", "web"], cwd=repo_root, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", default="packaging/macos/build")
    parser.add_argument("--skip-web-build", action="store_true")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    output = Path(args.output).resolve()
    app_path = output / APP_NAME
    contents = app_path / "Contents"
    macos = contents / "MacOS"
    resources = contents / "Resources"

    if not args.skip_web_build:
        build_web(repo_root)
    dist_index = repo_root / "web" / "dist" / "index.html"
    if not dist_index.exists():
        msg = f"Missing built web at {dist_index}"
        raise SystemExit(msg)

    if app_path.exists():
        shutil.rmtree(app_path)
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)
    copy_runtime_tree(repo_root, resources / "repo")
    write_plist(contents / "Info.plist")
    write_launcher(macos / "starklabs-model-evals")

    print(f"Built unsigned, not notarized app at {app_path}")


if __name__ == "__main__":
    main()
