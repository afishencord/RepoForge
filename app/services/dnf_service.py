"""DNF command construction and execution helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Callable

from .runner import CommandResult, SubprocessRunner, default_runner


@dataclass(frozen=True)
class RepoSource:
    name: str
    repo_id: str
    baseurl: str | None = None
    mirrorlist: str | None = None
    gpgkey_url: str | None = None
    enabled: bool = True
    gpgcheck: bool = True
    repo_gpgcheck: bool = False
    username: str | None = None
    password: str | None = None


def dnf_download_command(package_name: str, dest_dir: Path | str, repo_id: str | None = None) -> list[str]:
    command = ["dnf", "download", "--resolve", f"--destdir={Path(dest_dir)}"]
    if repo_id:
        command.append(f"--repoid={repo_id}")
    command.append(package_name)
    return command


def reposync_command(repo_id: str, dest_dir: Path | str) -> list[str]:
    return ["reposync", f"--repoid={repo_id}", "--download-metadata", f"--download-path={Path(dest_dir)}"]


def repoquery_whatprovides_command(requirement: str, repo_id: str | None = None) -> list[str]:
    command = ["dnf", "repoquery", "--whatprovides", requirement]
    if repo_id:
        command.append(f"--repoid={repo_id}")
    return command


def create_repo_file_content(repo_source: RepoSource) -> str:
    if not repo_source.baseurl and not repo_source.mirrorlist:
        raise ValueError("repo source requires baseurl or mirrorlist")
    lines = [
        f"[{repo_source.repo_id}]",
        f"name={repo_source.name}",
        f"enabled={1 if repo_source.enabled else 0}",
        f"gpgcheck={1 if repo_source.gpgcheck else 0}",
        f"repo_gpgcheck={1 if repo_source.repo_gpgcheck else 0}",
    ]
    if repo_source.baseurl:
        lines.append(f"baseurl={repo_source.baseurl}")
    if repo_source.mirrorlist:
        lines.append(f"mirrorlist={repo_source.mirrorlist}")
    if repo_source.gpgkey_url:
        lines.append(f"gpgkey={repo_source.gpgkey_url}")
    if repo_source.username:
        lines.append(f"username={repo_source.username}")
    if repo_source.password:
        lines.append(f"password={repo_source.password}")
    return "\n".join(lines) + "\n"


def create_temp_repo_file(repo_source: RepoSource) -> Path:
    temp = NamedTemporaryFile("w", encoding="utf-8", suffix=".repo", delete=False)
    with temp:
        temp.write(create_repo_file_content(repo_source))
    return Path(temp.name)


def validate_repo_source(
    repo_source: RepoSource,
    *,
    runner: SubprocessRunner = default_runner,
    log: Callable[[str], None] | None = None,
) -> CommandResult:
    command = ["dnf", "repolist", "--enabled", repo_source.repo_id]
    return runner.run(command, secrets=[repo_source.password or ""], log=log)


def download_package_with_dependencies(
    package_name: str,
    repo_config: RepoSource | None,
    dest_dir: Path | str,
    *,
    runner: SubprocessRunner = default_runner,
    log: Callable[[str], None] | None = None,
) -> CommandResult:
    repo_id = repo_config.repo_id if repo_config else None
    return runner.run(dnf_download_command(package_name, dest_dir, repo_id), secrets=[repo_config.password if repo_config else ""], log=log)


def sync_full_repo(
    repo_id: str,
    dest_dir: Path | str,
    *,
    runner: SubprocessRunner = default_runner,
    log: Callable[[str], None] | None = None,
) -> CommandResult:
    return runner.run(reposync_command(repo_id, dest_dir), log=log)

