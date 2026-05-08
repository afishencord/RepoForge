"""JSON serialization helpers for build requests sent to remote workers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .build_orchestrator import BuildRequest
from .dnf_service import RepoSource
from .repo_sync_service import RepoSyncPlan


def build_request_to_dict(request: BuildRequest) -> dict[str, Any]:
    return {
        "job_id": request.job_id,
        "builder_mode": request.builder_mode,
        "worker": request.worker,
        "bundle_id": request.bundle_id,
        "bundle_name": request.bundle_name,
        "target_os": request.target_os,
        "architecture": request.architecture,
        "workspace_dir": str(request.workspace_dir),
        "artifact_dir": str(request.artifact_dir),
        "repo_sync_plans": [_repo_sync_plan_to_dict(plan) for plan in request.repo_sync_plans],
        "repo_sources": request.repo_sources,
        "packages": request.packages,
        "uploaded_rpms": request.uploaded_rpms,
        "gpg_fingerprint": request.gpg_fingerprint,
        "gpg_private_key_path": str(request.gpg_private_key_path) if request.gpg_private_key_path else None,
        "fail_on_missing_tools": request.fail_on_missing_tools,
        "fail_on_unresolved_dependencies": request.fail_on_unresolved_dependencies,
        "iso_label": request.iso_label,
        "include_install_scripts": request.include_install_scripts,
        "include_validation_scripts": request.include_validation_scripts,
    }


def build_request_from_dict(data: dict[str, Any]) -> BuildRequest:
    return BuildRequest(
        job_id=_optional_str(data.get("job_id")),
        builder_mode=str(data.get("builder_mode") or "container"),
        worker=str(data.get("worker") or ""),
        bundle_id=str(data["bundle_id"]),
        bundle_name=str(data["bundle_name"]),
        target_os=str(data["target_os"]),
        architecture=str(data["architecture"]),
        workspace_dir=Path(str(data["workspace_dir"])),
        artifact_dir=Path(str(data["artifact_dir"])),
        repo_sync_plans=[_repo_sync_plan_from_dict(item) for item in data.get("repo_sync_plans", [])],
        repo_sources=list(data.get("repo_sources") or []),
        packages=list(data.get("packages") or []),
        uploaded_rpms=list(data.get("uploaded_rpms") or []),
        gpg_fingerprint=_optional_str(data.get("gpg_fingerprint")),
        gpg_private_key_path=_optional_path(data.get("gpg_private_key_path")),
        fail_on_missing_tools=bool(data.get("fail_on_missing_tools", True)),
        fail_on_unresolved_dependencies=bool(data.get("fail_on_unresolved_dependencies", False)),
        iso_label=str(data.get("iso_label") or "REPOFORGE"),
        include_install_scripts=bool(data.get("include_install_scripts", True)),
        include_validation_scripts=bool(data.get("include_validation_scripts", True)),
    )


def with_remote_paths(request: BuildRequest, *, remote_workspace: str, remote_artifact_dir: str, remote_upload_dir: str) -> BuildRequest:
    upload_lookup = {
        Path(str(rpm.get("storage_path"))).name: f"{remote_upload_dir}/{Path(str(rpm.get('storage_path'))).name}"
        for rpm in request.uploaded_rpms
        if rpm.get("storage_path")
    }
    uploaded_rpms: list[dict[str, Any]] = []
    for rpm in request.uploaded_rpms:
        item = dict(rpm)
        local_path = str(item.get("storage_path") or "")
        if local_path:
            item["storage_path"] = upload_lookup.get(Path(local_path).name, local_path)
        uploaded_rpms.append(item)

    repo_sync_plans = [
        RepoSyncPlan(
            repo_source=plan.repo_source,
            mode=plan.mode,
            dest_dir=Path(str(plan.dest_dir).replace(str(request.workspace_dir), remote_workspace, 1)),
            packages=list(plan.packages),
        )
        for plan in request.repo_sync_plans
    ]

    return BuildRequest(
        job_id=request.job_id,
        builder_mode=request.builder_mode,
        worker=request.worker,
        bundle_id=request.bundle_id,
        bundle_name=request.bundle_name,
        target_os=request.target_os,
        architecture=request.architecture,
        workspace_dir=Path(remote_workspace),
        artifact_dir=Path(remote_artifact_dir),
        repo_sync_plans=repo_sync_plans,
        repo_sources=request.repo_sources,
        packages=request.packages,
        uploaded_rpms=uploaded_rpms,
        gpg_fingerprint=request.gpg_fingerprint,
        gpg_private_key_path=request.gpg_private_key_path,
        fail_on_missing_tools=request.fail_on_missing_tools,
        fail_on_unresolved_dependencies=request.fail_on_unresolved_dependencies,
        iso_label=request.iso_label,
        include_install_scripts=request.include_install_scripts,
        include_validation_scripts=request.include_validation_scripts,
    )


def _repo_sync_plan_to_dict(plan: RepoSyncPlan) -> dict[str, Any]:
    repo = plan.repo_source
    return {
        "repo_source": {
            "name": repo.name,
            "repo_id": repo.repo_id,
            "baseurl": repo.baseurl,
            "mirrorlist": repo.mirrorlist,
            "gpgkey_url": repo.gpgkey_url,
            "enabled": repo.enabled,
            "gpgcheck": repo.gpgcheck,
            "repo_gpgcheck": repo.repo_gpgcheck,
            "username": repo.username,
            "password": repo.password,
        },
        "mode": plan.mode,
        "dest_dir": str(plan.dest_dir),
        "packages": list(plan.packages),
    }


def _repo_sync_plan_from_dict(data: dict[str, Any]) -> RepoSyncPlan:
    repo_data = data["repo_source"]
    return RepoSyncPlan(
        repo_source=RepoSource(
            name=str(repo_data["name"]),
            repo_id=str(repo_data["repo_id"]),
            baseurl=_optional_str(repo_data.get("baseurl")),
            mirrorlist=_optional_str(repo_data.get("mirrorlist")),
            gpgkey_url=_optional_str(repo_data.get("gpgkey_url")),
            enabled=bool(repo_data.get("enabled", True)),
            gpgcheck=bool(repo_data.get("gpgcheck", True)),
            repo_gpgcheck=bool(repo_data.get("repo_gpgcheck", False)),
            username=_optional_str(repo_data.get("username")),
            password=_optional_str(repo_data.get("password")),
        ),
        mode=str(data["mode"]),
        dest_dir=Path(str(data["dest_dir"])),
        packages=list(data.get("packages") or []),
    )


def _optional_str(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _optional_path(value: Any) -> Path | None:
    return Path(str(value)) if value not in (None, "") else None
