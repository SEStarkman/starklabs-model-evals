from __future__ import annotations

import io
import subprocess
import tarfile

from starklabs_evals.sandbox import (
    SandboxLimits,
    build_container_spec,
    extract_artifacts,
    html_screenshot_command_spec,
    pygame_capture_capability,
    pygame_capture_command_spec,
    python_validation_capability,
    validate_python_single_file,
)


def test_container_spec_is_hardened_and_has_no_host_mounts(tmp_path) -> None:
    spec = build_container_spec(tmp_path / "workspace", SandboxLimits(timeout_seconds=2))

    assert spec.network == "none"
    assert spec.read_only_root is True
    assert "--cap-drop=ALL" in spec.command
    assert "--security-opt=no-new-privileges" in spec.command
    assert "--network=none" in spec.command
    assert "--pids-limit=64" in spec.command
    assert all("HOME" not in mount and ".ssh" not in mount for mount in spec.mounts)


def test_html_and_pygame_specs_are_container_hardened(tmp_path) -> None:
    html_spec = html_screenshot_command_spec(tmp_path / "workspace", "index.html")
    pygame_spec = pygame_capture_command_spec(tmp_path / "workspace", "game.py")

    for spec in (html_spec, pygame_spec):
        assert spec.network == "none"
        assert spec.read_only_root is True
        assert "--cap-drop=ALL" in spec.command
        assert "--security-opt=no-new-privileges" in spec.command
        assert "--network=none" in spec.command
        assert "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=64m" in spec.command
        assert all("/Users/" not in mount and "/home/" not in mount for mount in spec.mounts)

    assert "file:///work/index.html" in html_spec.command
    assert "python" in pygame_spec.command
    assert "game.py" in pygame_spec.command


def test_artifact_extraction_rejects_traversal_symlinks_and_oversize(tmp_path) -> None:
    safe = io.BytesIO()
    with tarfile.open(fileobj=safe, mode="w:gz") as archive:
        data = b"hello"
        info = tarfile.TarInfo("out/result.txt")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    safe.seek(0)
    extracted = extract_artifacts(
        safe.getvalue(),
        tmp_path,
        max_file_bytes=128,
        max_total_bytes=512,
    )
    assert extracted == [tmp_path / "out" / "result.txt"]

    unsafe = io.BytesIO()
    with tarfile.open(fileobj=unsafe, mode="w:gz") as archive:
        info = tarfile.TarInfo("../escape.txt")
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))
    unsafe.seek(0)
    try:
        extract_artifacts(unsafe.getvalue(), tmp_path, max_file_bytes=128, max_total_bytes=512)
    except ValueError as exc:
        assert "unsafe artifact path" in str(exc)
    else:  # pragma: no cover - assertion path
        raise AssertionError("expected traversal artifact to be rejected")

    link = io.BytesIO()
    with tarfile.open(fileobj=link, mode="w:gz") as archive:
        info = tarfile.TarInfo("link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        archive.addfile(info)
    link.seek(0)
    try:
        extract_artifacts(link.getvalue(), tmp_path, max_file_bytes=128, max_total_bytes=512)
    except ValueError as exc:
        assert "unsupported artifact type" in str(exc)
    else:  # pragma: no cover - assertion path
        raise AssertionError("expected symlink artifact to be rejected")


def test_python_validation_capability_reports_absent_runtime_truthfully() -> None:
    capability = python_validation_capability()
    assert capability.name == "python-single-file"
    assert isinstance(capability.available, bool)


def test_pygame_capability_does_not_use_host_import_as_evidence() -> None:
    capability = pygame_capture_capability()
    assert capability.name == "pygame-headless-capture"
    assert "host import" not in capability.detail.lower()


def test_python_timeout_force_removes_the_named_container(monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    monkeypatch.setattr("starklabs_evals.sandbox.shutil.which", lambda _: "/usr/bin/docker")

    def fake_run(
        command: list[str] | tuple[str, ...],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(command))
        if len(calls) == 1:
            raise subprocess.TimeoutExpired(command, timeout=1, output="partial", stderr="late")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr("starklabs_evals.sandbox.subprocess.run", fake_run)

    result = validate_python_single_file("while True: pass", SandboxLimits(timeout_seconds=1))

    assert result.timeout is True
    assert "--name=starklabs-eval-" in " ".join(calls[0])
    assert calls[1][:3] == ("docker", "rm", "-f")
