"""Vendor repository sync helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .dnf_service import RepoSource, download_package_with_dependencies, sync_full_repo
from .runner import CommandResult, SubprocessRunner, default_runner


@dataclass(frozen=True)
class RepoSyncPlan:
    repo_source: RepoSource
    mode: str
    dest_dir: Path
    packages: list[str] = field(default_factory=list)


def sync_vendor_repo(
    plan: RepoSyncPlan,
    *,
    runner: SubprocessRunner = default_runner,
    log: Callable[[str], None] | None = None,
) -> list[CommandResult]:
    plan.dest_dir.mkdir(parents=True, exist_ok=True)
    if plan.mode == "full_mirror":
        return [sync_full_repo(plan.repo_source, plan.dest_dir, runner=runner, log=log)]
    if plan.mode == "curated_packages":
        return [
            download_package_with_dependencies(package, plan.repo_source, plan.dest_dir, runner=runner, log=log)
            for package in plan.packages
        ]
    if plan.mode == "metadata_only":
        return [sync_full_repo(plan.repo_source, plan.dest_dir, runner=runner, log=log)]
    raise ValueError(f"unsupported sync mode: {plan.mode}")
