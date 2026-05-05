"""Optional dependency resolution for uploaded RPMs."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .dnf_service import dnf_download_command, repoquery_whatprovides_command
from .runner import SubprocessRunner, default_runner


IGNORED_REQUIREMENT_PREFIXES = ("rpmlib(", "config(", "/bin/", "/usr/bin/", "/sbin/", "/usr/sbin/")


@dataclass(frozen=True)
class DependencyResolution:
    detected: list[str] = field(default_factory=list)
    resolved: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)


def filter_rpm_requirements(requirements: list[str]) -> list[str]:
    filtered: list[str] = []
    for requirement in requirements:
        value = requirement.strip()
        if not value:
            continue
        if any(value.startswith(prefix) for prefix in IGNORED_REQUIREMENT_PREFIXES):
            continue
        if value.startswith("(") or value.startswith("lib") and ".so" in value:
            continue
        filtered.append(value)
    return filtered


def resolve_requirements(
    requirements: list[str],
    dest_dir: Path | str,
    *,
    repo_id: str | None = None,
    runner: SubprocessRunner = default_runner,
    log: Callable[[str], None] | None = None,
    fail_on_unresolved: bool = False,
) -> DependencyResolution:
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    detected = filter_rpm_requirements(requirements)
    resolved: list[str] = []
    unresolved: list[str] = []

    for requirement in detected:
        query = runner.run(repoquery_whatprovides_command(requirement, repo_id), check=False, log=log)
        candidates = [line.strip() for line in query.stdout.splitlines() if line.strip()]
        if not query.ok or not candidates:
            unresolved.append(requirement)
            continue
        package_name = candidates[0]
        download = runner.run(dnf_download_command(package_name, dest, repo_id), check=False, log=log)
        if download.ok:
            resolved.append(package_name)
        else:
            unresolved.append(requirement)

    if fail_on_unresolved and unresolved:
        raise RuntimeError(f"unresolved dependencies: {', '.join(unresolved)}")
    return DependencyResolution(detected=detected, resolved=resolved, unresolved=unresolved)

