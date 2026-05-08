"""Remote RHEL worker execution over SSH/SFTP."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import io
from pathlib import Path
import posixpath
import shlex
import tarfile
import tempfile
import time
from typing import Any, Callable

from .build_orchestrator import BuildRequest, BuildResult
from .build_request_io import build_request_to_dict, with_remote_paths
from .builder_deployment import BuilderValidationError, RemoteWorkerConfig


class RemoteWorkerError(RuntimeError):
    """Raised when an SSH worker cannot complete a build."""


@dataclass(frozen=True)
class RemoteCommandResult:
    command: str
    returncode: int
    stdout: str = ""
    stderr: str = ""


class RemoteWorkerClient:
    def __init__(self, config: RemoteWorkerConfig):
        self.config = config

    def validate_entitlement(self, repo_ids: list[str]) -> None:
        with self._connect() as client:
            for command in (
                "command -v subscription-manager",
                "subscription-manager identity",
                "subscription-manager repos --list-enabled",
            ):
                result = self._exec(client, command)
                if result.returncode != 0:
                    raise BuilderValidationError(f"Remote worker entitlement validation failed: {result.stderr or result.stdout}")

            result = self._exec(client, "dnf repolist --enabled")
            if result.returncode != 0:
                raise BuilderValidationError(f"Remote worker dnf validation failed: {result.stderr or result.stdout}")
            enabled_text = f"{result.stdout}\n{result.stderr}"
            missing = [repo_id for repo_id in repo_ids if repo_id and repo_id not in enabled_text]
            if missing:
                raise BuilderValidationError(
                    "Remote worker is entitled, but these requested repo IDs are not enabled: " + ", ".join(missing)
                )

    def run_build(self, request: BuildRequest, *, log: Callable[[str], None] | None = None) -> BuildResult:
        remote_job = _remote_job_dir(self.config.remote_root, request.job_id or request.bundle_id)
        remote_archive = posixpath.join(remote_job, "input.tar.gz")
        remote_workspace = posixpath.join(remote_job, "workspace")
        remote_artifacts = posixpath.join(remote_job, "artifacts")
        remote_uploads = posixpath.join(remote_job, "input", "uploads")
        local_archive = _create_payload_archive(
            request,
            remote_workspace=remote_workspace,
            remote_artifact_dir=remote_artifacts,
            remote_upload_dir=remote_uploads,
        )

        try:
            with self._connect() as client:
                if log:
                    log(f"Dispatching build to remote worker {self.config.display_name}")
                self._exec_checked(client, f"mkdir -p {shlex.quote(remote_job)}")
                sftp = client.open_sftp()
                try:
                    _sftp_put(sftp, local_archive, remote_archive)
                finally:
                    sftp.close()

                command = (
                    f"cd {shlex.quote(self.config.app_path)} && "
                    f"python3 -m app.workers.remote_build "
                    f"--archive {shlex.quote(remote_archive)} "
                    f"--work-root {shlex.quote(remote_job)}"
                )
                result = self._exec(client, command, log=log)
                if result.returncode != 0:
                    raise RemoteWorkerError(result.stderr or result.stdout or f"remote command failed: {command}")

                return self._download_result(client, request, remote_job)
        finally:
            local_archive.unlink(missing_ok=True)

    def _download_result(self, client: Any, request: BuildRequest, remote_job: str) -> BuildResult:
        local_artifact_dir = Path(request.artifact_dir)
        local_manifest_dir = Path(request.workspace_dir) / "manifests"
        local_checksum_dir = Path(request.workspace_dir) / "checksums"
        for path in (local_artifact_dir, local_manifest_dir, local_checksum_dir):
            path.mkdir(parents=True, exist_ok=True)

        sftp = client.open_sftp()
        try:
            with sftp.open(posixpath.join(remote_job, "result.json"), "r") as handle:
                result_data = json.load(handle)

            iso_path = _download_declared_path(sftp, result_data.get("iso_path"), local_artifact_dir)
            manifest_path = _download_declared_path(sftp, result_data.get("manifest_path"), local_manifest_dir)
            checksum_path = _download_declared_path(sftp, result_data.get("checksum_path"), local_checksum_dir)
        finally:
            sftp.close()

        return BuildResult(
            status=str(result_data.get("status") or "completed"),
            iso_path=iso_path,
            manifest_path=manifest_path or local_manifest_dir / "bundle-manifest.json",
            checksum_path=checksum_path or local_checksum_dir / "SHA256SUMS",
            warnings=list(result_data.get("warnings") or []),
        )

    def _connect(self) -> Any:
        paramiko = _paramiko()
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        kwargs: dict[str, Any] = {
            "hostname": self.config.host,
            "username": self.config.username,
            "port": self.config.port,
            "timeout": 20,
        }
        if self.config.key_path:
            kwargs["key_filename"] = self.config.key_path
        try:
            client.connect(**kwargs)
        except Exception as exc:
            client.close()
            raise RemoteWorkerError(f"Could not connect to remote worker {self.config.display_name}: {exc}") from exc
        return client

    def _exec_checked(self, client: Any, command: str) -> RemoteCommandResult:
        result = self._exec(client, command)
        if result.returncode != 0:
            raise RemoteWorkerError(result.stderr or result.stdout or f"remote command failed: {command}")
        return result

    def _exec(self, client: Any, command: str, *, log: Callable[[str], None] | None = None) -> RemoteCommandResult:
        stdin, stdout, stderr = client.exec_command(command)
        stdin.close()
        channel = stdout.channel
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        while not channel.exit_status_ready():
            self._drain_channel(channel, stdout_chunks, stderr_chunks, log=log)
            time.sleep(0.25)
        self._drain_channel(channel, stdout_chunks, stderr_chunks, log=log)
        return RemoteCommandResult(
            command=command,
            returncode=channel.recv_exit_status(),
            stdout="".join(stdout_chunks),
            stderr="".join(stderr_chunks),
        )

    def _drain_channel(
        self,
        channel: Any,
        stdout_chunks: list[str],
        stderr_chunks: list[str],
        *,
        log: Callable[[str], None] | None = None,
    ) -> None:
        while channel.recv_ready():
            text = channel.recv(65536).decode("utf-8", errors="replace")
            stdout_chunks.append(text)
            if log:
                for line in text.rstrip().splitlines():
                    log(line)
        while channel.recv_stderr_ready():
            text = channel.recv_stderr(65536).decode("utf-8", errors="replace")
            stderr_chunks.append(text)
            if log:
                for line in text.rstrip().splitlines():
                    log(line)


def _create_payload_archive(
    request: BuildRequest,
    *,
    remote_workspace: str,
    remote_artifact_dir: str,
    remote_upload_dir: str,
) -> Path:
    remote_request = with_remote_paths(
        request,
        remote_workspace=remote_workspace,
        remote_artifact_dir=remote_artifact_dir,
        remote_upload_dir=remote_upload_dir,
    )
    handle = tempfile.NamedTemporaryFile(prefix="repoforge-remote-", suffix=".tar.gz", delete=False)
    archive_path = Path(handle.name)
    handle.close()
    with tarfile.open(archive_path, "w:gz") as archive:
        request_bytes = json.dumps(build_request_to_dict(remote_request), indent=2, sort_keys=True).encode("utf-8")
        info = tarfile.TarInfo("build-request.json")
        info.size = len(request_bytes)
        info.mtime = int(time.time())
        archive.addfile(info, io.BytesIO(request_bytes))
        for rpm in request.uploaded_rpms:
            storage_path = rpm.get("storage_path")
            if not storage_path:
                continue
            local_path = Path(str(storage_path))
            if local_path.exists():
                archive.add(local_path, arcname=f"uploads/{local_path.name}")
    return archive_path


def _sftp_put(sftp: Any, local_path: Path, remote_path: str) -> None:
    _sftp_mkdir_p(sftp, posixpath.dirname(remote_path))
    sftp.put(str(local_path), remote_path)


def _sftp_mkdir_p(sftp: Any, path: str) -> None:
    current = ""
    for part in path.split("/"):
        if not part:
            current = "/"
            continue
        current = posixpath.join(current, part)
        try:
            sftp.stat(current)
        except OSError:
            sftp.mkdir(current)


def _download_declared_path(sftp: Any, remote_path_value: Any, local_dir: Path) -> Path | None:
    if not remote_path_value:
        return None
    remote_path = str(remote_path_value)
    local_path = local_dir / posixpath.basename(remote_path)
    sftp.get(remote_path, str(local_path))
    return local_path


def _remote_job_dir(root: str, job_id: str) -> str:
    safe_id = "".join(char if char.isalnum() or char in "._-" else "-" for char in str(job_id)).strip("-") or "job"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return posixpath.join(root.rstrip("/") or "/var/lib/repoforge-worker", f"{safe_id}-{stamp}")


def _paramiko() -> Any:
    try:
        import paramiko  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RemoteWorkerError("paramiko is not installed; run python -m pip install -r requirements.txt") from exc
    return paramiko
