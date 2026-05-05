"""GPG key generation, export, and signing helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .runner import CommandResult, SubprocessRunner, default_runner


@dataclass(frozen=True)
class GpgKeyRequest:
    name_real: str = "RepoForge Custom Repo"
    name_email: str = "repoforge@local"
    expire_date: str = "2y"
    key_type: str = "RSA"
    key_length: int = 4096
    passphrase: str | None = None


def key_params_content(request: GpgKeyRequest) -> str:
    lines = [
        f"Key-Type: {request.key_type}",
        f"Key-Length: {request.key_length}",
        f"Name-Real: {request.name_real}",
        f"Name-Email: {request.name_email}",
        f"Expire-Date: {request.expire_date}",
    ]
    if request.passphrase:
        lines.append(f"Passphrase: {request.passphrase}")
    else:
        lines.append("%no-protection")
    lines.append("%commit")
    return "\n".join(lines) + "\n"


def write_key_params(request: GpgKeyRequest, output_path: Path | str) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(key_params_content(request), encoding="utf-8")
    return output


def gpg_base_command(gpg_home: Path | str | None = None) -> list[str]:
    command = ["gpg", "--batch"]
    if gpg_home:
        command.extend(["--homedir", str(gpg_home)])
    return command


def generate_key(
    params_file: Path | str,
    *,
    gpg_home: Path | str | None = None,
    runner: SubprocessRunner = default_runner,
    log: Callable[[str], None] | None = None,
    secrets: list[str] | None = None,
) -> CommandResult:
    command = gpg_base_command(gpg_home) + ["--generate-key", str(params_file)]
    return runner.run(command, log=log, secrets=secrets or [])


def export_public_key(
    fingerprint: str,
    output_path: Path | str,
    *,
    gpg_home: Path | str | None = None,
    runner: SubprocessRunner = default_runner,
    log: Callable[[str], None] | None = None,
) -> CommandResult:
    command = gpg_base_command(gpg_home) + ["--armor", "--output", str(output_path), "--export", fingerprint]
    return runner.run(command, log=log)


def sign_file_detached(
    file_path: Path | str,
    *,
    gpg_home: Path | str | None = None,
    local_user: str | None = None,
    runner: SubprocessRunner = default_runner,
    log: Callable[[str], None] | None = None,
) -> CommandResult:
    command = gpg_base_command(gpg_home)
    if local_user:
        command.extend(["--local-user", local_user])
    command.extend(["--detach-sign", "--armor", str(file_path)])
    return runner.run(command, log=log)


def list_secret_fingerprints(
    *,
    gpg_home: Path | str | None = None,
    runner: SubprocessRunner = default_runner,
    log: Callable[[str], None] | None = None,
) -> list[str]:
    command = gpg_base_command(gpg_home) + ["--with-colons", "--list-secret-keys"]
    result = runner.run(command, log=log, check=False)
    fingerprints: list[str] = []
    for line in result.stdout.splitlines():
        parts = line.split(":")
        if parts and parts[0] == "fpr" and len(parts) > 9 and parts[9]:
            fingerprints.append(parts[9])
    return fingerprints
