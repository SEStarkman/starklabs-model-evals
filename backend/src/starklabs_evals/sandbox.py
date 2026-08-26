from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
import tarfile
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

SUPPORTED_ARTIFACT_SUFFIXES = {".txt", ".md", ".json", ".html", ".css", ".js", ".py", ".log"}


@dataclass(frozen=True)
class SandboxLimits:
    cpu_count: int = 1
    memory_mb: int = 256
    pids: int = 64
    timeout_seconds: int = 10


@dataclass(frozen=True)
class ContainerSpec:
    engine: str
    container_name: str
    image: str
    network: str
    read_only_root: bool
    mounts: tuple[str, ...]
    command: tuple[str, ...]
    timeout_seconds: int


@dataclass(frozen=True)
class Capability:
    name: str
    available: bool
    detail: str


@dataclass(frozen=True)
class ValidationResult:
    stdout: str
    stderr: str
    exit_code: int | None
    timeout: bool
    unavailable_reason: str | None = None


def build_container_spec(workspace: Path, limits: SandboxLimits | None = None) -> ContainerSpec:
    limits = limits or SandboxLimits()
    workspace = workspace.resolve()
    container_name = f"starklabs-eval-{hashlib.sha256(str(workspace).encode()).hexdigest()[:12]}"
    tmp_mount = f"{workspace}:/work:rw"
    command = (
        "docker",
        "run",
        "--rm",
        f"--name={container_name}",
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        f"--cpus={limits.cpu_count}",
        f"--memory={limits.memory_mb}m",
        f"--pids-limit={limits.pids}",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m",
        "-v",
        tmp_mount,
        "-w",
        "/work",
        "python:3.12-alpine",
        "python",
        "candidate.py",
    )
    return ContainerSpec(
        engine="docker",
        container_name=container_name,
        image="python:3.12-alpine",
        network="none",
        read_only_root=True,
        mounts=(tmp_mount,),
        command=command,
        timeout_seconds=limits.timeout_seconds,
    )


def container_engine_capability() -> Capability:
    engine = shutil.which("docker") or shutil.which("podman")
    if engine:
        return Capability("container-engine", True, f"container engine available at {engine}")
    return Capability("container-engine", False, "Docker/Podman is unavailable on PATH")


def html_screenshot_command_spec(workspace: Path, html_file: str) -> ContainerSpec:
    spec = build_container_spec(workspace)
    command = (
        *spec.command[: spec.command.index("python:3.12-alpine")],
        "mcr.microsoft.com/playwright:v1.49.1-jammy",
        "npx",
        "playwright",
        "screenshot",
        f"file:///work/{html_file}",
        "/work/artifacts/screenshot.png",
    )
    return ContainerSpec(
        engine=spec.engine,
        container_name=spec.container_name,
        image="mcr.microsoft.com/playwright:v1.49.1-jammy",
        network=spec.network,
        read_only_root=spec.read_only_root,
        mounts=spec.mounts,
        command=command,
        timeout_seconds=spec.timeout_seconds,
    )


def pygame_capture_command_spec(workspace: Path, python_file: str) -> ContainerSpec:
    spec = build_container_spec(workspace)
    command = (
        *spec.command[: spec.command.index("python:3.12-alpine")],
        "-e",
        "SDL_VIDEODRIVER=dummy",
        "python:3.12-slim",
        "python",
        python_file,
    )
    return ContainerSpec(
        engine=spec.engine,
        container_name=spec.container_name,
        image="python:3.12-slim",
        network=spec.network,
        read_only_root=spec.read_only_root,
        mounts=spec.mounts,
        command=command,
        timeout_seconds=spec.timeout_seconds,
    )


def validate_python_single_file(
    source: str,
    limits: SandboxLimits | None = None,
) -> ValidationResult:
    capability = container_engine_capability()
    if not capability.available:
        return ValidationResult("", "", None, False, capability.detail)
    limits = limits or SandboxLimits()
    engine = "docker" if shutil.which("docker") else "podman"
    with tempfile.TemporaryDirectory(prefix="starklabs-eval-") as tmp:
        workspace = Path(tmp)
        (workspace / "candidate.py").write_text(source, encoding="utf-8")
        spec = build_container_spec(workspace, limits)
        command = (engine, *spec.command[1:])
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=limits.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            with suppress(OSError, subprocess.TimeoutExpired):
                subprocess.run(
                    [engine, "rm", "-f", spec.container_name],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else exc.stdout
            stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else exc.stderr
            return ValidationResult(
                stdout or "",
                stderr or "",
                None,
                True,
                None,
            )
        return ValidationResult(
            result.stdout,
            result.stderr,
            result.returncode,
            False,
            None,
        )


def _validate_artifact_name(name: str) -> Path:
    posix = PurePosixPath(name)
    if posix.is_absolute() or ".." in posix.parts or not posix.name:
        msg = f"unsafe artifact path: {name}"
        raise ValueError(msg)
    suffix = posix.suffix.lower()
    if suffix not in SUPPORTED_ARTIFACT_SUFFIXES:
        msg = f"unsupported artifact format: {name}"
        raise ValueError(msg)
    return Path(*posix.parts)


def extract_artifacts(
    archive_bytes: bytes,
    destination: Path,
    *,
    max_file_bytes: int,
    max_total_bytes: int,
) -> list[Path]:
    if len(archive_bytes) > max_total_bytes:
        msg = "artifact archive too large"
        raise ValueError(msg)
    destination.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    total = 0
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                msg = f"unsupported artifact type: {member.name}"
                raise ValueError(msg)
            if member.size > max_file_bytes:
                msg = f"artifact too large: {member.name}"
                raise ValueError(msg)
            total += member.size
            if total > max_total_bytes:
                msg = "artifact payload too large"
                raise ValueError(msg)
            relative = _validate_artifact_name(member.name)
            target = (destination / relative).resolve()
            if not target.is_relative_to(destination.resolve()):
                msg = f"unsafe artifact path: {member.name}"
                raise ValueError(msg)
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                msg = f"artifact missing body: {member.name}"
                raise ValueError(msg)
            target.write_bytes(source.read())
            extracted.append(target)
    return extracted


def python_validation_capability() -> Capability:
    engine = container_engine_capability()
    if engine.available:
        return Capability("python-single-file", True, "Python validation runs inside container")
    return Capability("python-single-file", False, engine.detail)


def html_screenshot_capability() -> Capability:
    engine = container_engine_capability()
    if engine.available:
        return Capability("html-screenshot", True, "HTML screenshots run inside container")
    return Capability("html-screenshot", False, engine.detail)


def pygame_capture_capability() -> Capability:
    engine = container_engine_capability()
    if not engine.available:
        return Capability("pygame-headless-capture", False, engine.detail)
    return Capability(
        "pygame-headless-capture",
        False,
        "pygame capture requires a configured isolated container image with pygame installed",
    )
