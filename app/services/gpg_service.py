"""GPG key generation, export, and signing helpers."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import tempfile
from typing import Callable
import uuid

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


def _is_gpg_runtime_entry(path: Path) -> bool:
    name = path.name
    return name.startswith("S.") or name.endswith(".lock")


def _ignore_gpg_runtime_entries(directory: str, names: list[str]) -> set[str]:
    return {name for name in names if _is_gpg_runtime_entry(Path(directory) / name)}


def _copy_gpg_home(source: Path, destination: Path) -> None:
    if not source.exists():
        return
    for item in source.iterdir():
        if _is_gpg_runtime_entry(item):
            continue
        target = destination / item.name
        if item.is_dir():
            shutil.copytree(item, target, ignore=_ignore_gpg_runtime_entries, dirs_exist_ok=True)
        elif item.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def _chmod_private(path: Path) -> None:
    if os.name == "nt":
        return
    path.chmod(0o700)


@contextmanager
def _runtime_gpg_home(persistent_home: Path):
    persistent_home.mkdir(parents=True, exist_ok=True)
    _chmod_private(persistent_home)
    temp_root = Path(tempfile.gettempdir()) / f"repoforge-gnupg-{uuid.uuid4().hex}"
    temp_root.mkdir(parents=True, exist_ok=False)
    try:
        runtime_home = temp_root / "gnupg"
        runtime_home.mkdir()
        _chmod_private(runtime_home)
        _copy_gpg_home(persistent_home, runtime_home)
        try:
            yield runtime_home
        finally:
            _chmod_private(runtime_home)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def _run_gpg(
    command_args: list[str],
    *,
    gpg_home: Path | str | None = None,
    persist_home: bool = False,
    runner: SubprocessRunner = default_runner,
    log: Callable[[str], None] | None = None,
    secrets: list[str] | None = None,
    check: bool = True,
) -> CommandResult:
    if not gpg_home:
        return runner.run(gpg_base_command() + command_args, log=log, secrets=secrets or [], check=check)

    persistent_home = Path(gpg_home)
    with _runtime_gpg_home(persistent_home) as runtime_home:
        result: CommandResult | None = None
        try:
            result = runner.run(gpg_base_command(runtime_home) + command_args, log=log, secrets=secrets or [], check=check)
            return result
        finally:
            try:
                runner.run(["gpgconf", "--homedir", str(runtime_home), "--kill", "gpg-agent"], check=False)
            except Exception:
                pass
            if persist_home and result is not None and result.ok:
                _copy_gpg_home(runtime_home, persistent_home)


def generate_key(
    params_file: Path | str,
    *,
    gpg_home: Path | str | None = None,
    runner: SubprocessRunner = default_runner,
    log: Callable[[str], None] | None = None,
    secrets: list[str] | None = None,
) -> CommandResult:
    return _run_gpg(
        ["--generate-key", str(params_file)],
        gpg_home=gpg_home,
        persist_home=True,
        runner=runner,
        log=log,
        secrets=secrets,
    )


def export_public_key(
    fingerprint: str,
    output_path: Path | str,
    *,
    gpg_home: Path | str | None = None,
    runner: SubprocessRunner = default_runner,
    log: Callable[[str], None] | None = None,
) -> CommandResult:
    return _run_gpg(
        ["--armor", "--output", str(output_path), "--export", fingerprint],
        gpg_home=gpg_home,
        runner=runner,
        log=log,
    )


def sign_file_detached(
    file_path: Path | str,
    *,
    gpg_home: Path | str | None = None,
    local_user: str | None = None,
    runner: SubprocessRunner = default_runner,
    log: Callable[[str], None] | None = None,
) -> CommandResult:
    command = []
    if local_user:
        command.extend(["--local-user", local_user])
    command.extend(["--detach-sign", "--armor", str(file_path)])
    return _run_gpg(command, gpg_home=gpg_home, runner=runner, log=log)


def list_secret_fingerprints(
    *,
    gpg_home: Path | str | None = None,
    runner: SubprocessRunner = default_runner,
    log: Callable[[str], None] | None = None,
) -> list[str]:
    result = _run_gpg(
        ["--with-colons", "--list-secret-keys"],
        gpg_home=gpg_home,
        runner=runner,
        log=log,
        check=False,
    )
    fingerprints: list[str] = []
    for line in result.stdout.splitlines():
        parts = line.split(":")
        if parts and parts[0] == "fpr" and len(parts) > 9 and parts[9]:
            fingerprints.append(parts[9])
    return fingerprints
