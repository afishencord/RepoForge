"""Custom RPM repository management."""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Callable

from .runner import CommandResult, SubprocessRunner, default_runner, require_relative_path


def custom_packages_dir(custom_repo_dir: Path | str) -> Path:
    return Path(custom_repo_dir) / "Packages"


def add_rpm_to_custom_repo(rpm_path: Path | str, custom_repo_dir: Path | str) -> Path:
    source = Path(rpm_path).resolve()
    packages_dir = custom_packages_dir(custom_repo_dir)
    packages_dir.mkdir(parents=True, exist_ok=True)
    target = packages_dir / source.name
    shutil.copy2(source, target)
    return target


def createrepo_command(custom_repo_dir: Path | str, *, update: bool = True) -> list[str]:
    command = ["createrepo_c"]
    if update:
        command.append("--update")
    command.append(str(Path(custom_repo_dir)))
    return command


def create_repo_metadata(
    custom_repo_dir: Path | str,
    *,
    runner: SubprocessRunner = default_runner,
    log: Callable[[str], None] | None = None,
) -> CommandResult:
    Path(custom_repo_dir).mkdir(parents=True, exist_ok=True)
    return runner.run(createrepo_command(custom_repo_dir), log=log)


def write_mounted_repo_file(repo_id: str, name: str, baseurl_path: str, gpgkey_path: str, output_path: Path | str, root: Path | str) -> Path:
    output = require_relative_path(output_path, root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(
            [
                f"[{repo_id}]",
                f"name={name}",
                f"baseurl=file://{baseurl_path}",
                "enabled=1",
                "gpgcheck=1",
                "repo_gpgcheck=1",
                f"gpgkey=file://{gpgkey_path}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return output

