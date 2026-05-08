"""Framework-light build orchestration for RepoForge bundles."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
import shutil
from typing import Any, Callable

from .checksum_service import write_sha256sums
from .custom_repo_service import add_rpm_to_custom_repo, create_repo_metadata
from .dependency_service import resolve_requirements
from .gpg_service import export_public_key, sign_file_detached
from .iso_service import build_iso, validate_iso
from .manifest_service import BundleManifest, write_manifest, write_package_list
from .repo_sync_service import RepoSyncPlan, sync_vendor_repo
from .runner import SubprocessRunner, default_runner
from .system_tools import check_system_tools, missing_required_tools


@dataclass
class BuildRequest:
    bundle_id: str
    bundle_name: str
    target_os: str
    architecture: str
    workspace_dir: Path
    artifact_dir: Path
    job_id: str | None = None
    builder_mode: str = "container"
    worker: str = ""
    repo_sync_plans: list[RepoSyncPlan] = field(default_factory=list)
    repo_sources: list[dict[str, Any]] = field(default_factory=list)
    packages: list[dict[str, Any] | str] = field(default_factory=list)
    uploaded_rpms: list[dict[str, Any]] = field(default_factory=list)
    gpg_fingerprint: str | None = None
    fail_on_missing_tools: bool = True
    fail_on_unresolved_dependencies: bool = False
    iso_label: str = "REPOFORGE"
    include_install_scripts: bool = True
    include_validation_scripts: bool = True


@dataclass
class BuildResult:
    status: str
    iso_path: Path | None
    manifest_path: Path
    checksum_path: Path
    warnings: list[str] = field(default_factory=list)


class BuildOrchestrator:
    def __init__(self, runner: SubprocessRunner = default_runner, log: Callable[[str], None] | None = None):
        self.runner = runner
        self.log = log

    def build(self, request: BuildRequest) -> BuildResult:
        workspace = Path(request.workspace_dir)
        artifact_dir = Path(request.artifact_dir)
        manifests_dir = workspace / "manifests"
        checksums_dir = workspace / "checksums"
        custom_repo_dir = workspace / "repos" / "custom"
        iso_root = workspace / "iso-root"
        warnings: list[str] = []
        resolved_dependencies: list[dict[str, Any]] = []

        for path in (manifests_dir, checksums_dir, custom_repo_dir, artifact_dir):
            path.mkdir(parents=True, exist_ok=True)
        _clean_dir(iso_root)

        tool_checks = check_system_tools()
        missing = missing_required_tools(tool_checks)
        if missing:
            message = f"missing required system tools: {', '.join(missing)}"
            if request.fail_on_missing_tools:
                raise RuntimeError(message)
            warnings.append(message)

        for plan in request.repo_sync_plans:
            sync_vendor_repo(plan, runner=self.runner, log=self.log)

        first_repo_id = next((plan.repo_source.repo_id for plan in request.repo_sync_plans if plan.repo_source.repo_id), None)
        dependency_dir = workspace / "repos" / "custom-dependencies"
        for rpm in request.uploaded_rpms:
            storage_path = rpm.get("storage_path")
            if storage_path:
                add_rpm_to_custom_repo(storage_path, custom_repo_dir)
            if rpm.get("resolve_dependencies") and rpm.get("requires"):
                resolution = resolve_requirements(
                    list(rpm.get("requires") or []),
                    dependency_dir,
                    repo_id=first_repo_id,
                    runner=self.runner,
                    log=self.log,
                    fail_on_unresolved=request.fail_on_unresolved_dependencies,
                )
                for dep_rpm in sorted(dependency_dir.glob("*.rpm")):
                    add_rpm_to_custom_repo(dep_rpm, custom_repo_dir)
                resolved_dependencies.append(
                    {
                        "rpm": rpm.get("original_filename") or rpm.get("filename"),
                        "detected": resolution.detected,
                        "resolved": resolution.resolved,
                        "unresolved": resolution.unresolved,
                    }
                )
                if resolution.unresolved:
                    warnings.append(
                        f"{rpm.get('original_filename') or rpm.get('filename')} has unresolved dependencies: "
                        + ", ".join(resolution.unresolved)
                    )

        create_repo_metadata(custom_repo_dir, runner=self.runner, log=self.log)

        public_key_path = None
        if request.gpg_fingerprint:
            public_key_path = workspace / "keys" / "public" / "RPM-GPG-KEY-repoforge-custom"
            public_key_path.parent.mkdir(parents=True, exist_ok=True)
            export_public_key(request.gpg_fingerprint, public_key_path, runner=self.runner, log=self.log)
            repomd = custom_repo_dir / "repodata" / "repomd.xml"
            if repomd.exists():
                sign_file_detached(repomd, local_user=request.gpg_fingerprint, runner=self.runner, log=self.log)

        manifest = BundleManifest(
            bundle_name=request.bundle_name,
            target_os=request.target_os,
            architecture=request.architecture,
            builder_mode=request.builder_mode,
            worker=request.worker,
            repo_sources=request.repo_sources,
            packages=request.packages,
            uploaded_rpms=request.uploaded_rpms,
            resolved_dependencies=resolved_dependencies,
            gpg_keys=[{"fingerprint": request.gpg_fingerprint, "public_key_path": public_key_path}] if public_key_path else [],
        )
        manifest_path = write_manifest(manifest, manifests_dir / "bundle-manifest.json")
        write_package_list(request.packages, manifests_dir / "package-list.txt")

        _assemble_iso_root(
            request=request,
            workspace=workspace,
            iso_root=iso_root,
            public_key_path=public_key_path,
            include_scripts=request.include_install_scripts or request.include_validation_scripts,
        )
        iso_checksum_path = write_sha256sums(iso_root, iso_root / "checksums" / "SHA256SUMS")
        checksums_dir.mkdir(parents=True, exist_ok=True)
        checksum_path = checksums_dir / "SHA256SUMS"
        shutil.copy2(iso_checksum_path, checksum_path)

        iso_path = artifact_dir / f"repoforge-{_slug(request.bundle_name)}.iso"
        prefer_xorriso = any(check.name == "xorriso" and check.present for check in tool_checks)
        if not prefer_xorriso and not any(check.name == "genisoimage" and check.present for check in tool_checks):
            raise RuntimeError("missing ISO builder: install xorriso or genisoimage")
        build_iso(iso_root, iso_path, runner=self.runner, log=self.log, volume_id=request.iso_label or "REPOFORGE", prefer_xorriso=prefer_xorriso)
        if any(check.name == "isoinfo" and check.present for check in tool_checks):
            validate_iso(iso_path, runner=self.runner, log=self.log)
        else:
            warnings.append("isoinfo is not installed; ISO structural validation was skipped")

        return BuildResult(status="completed", iso_path=iso_path, manifest_path=manifest_path, checksum_path=checksum_path, warnings=warnings)


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-").lower()
    return slug or "bundle"


def _clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _assemble_iso_root(
    *,
    request: BuildRequest,
    workspace: Path,
    iso_root: Path,
    public_key_path: Path | None,
    include_scripts: bool,
) -> None:
    repos_dir = workspace / "repos"
    if repos_dir.exists():
        shutil.copytree(repos_dir, iso_root / "repos", dirs_exist_ok=True)
    shutil.copytree(workspace / "manifests", iso_root / "manifests", dirs_exist_ok=True)
    (iso_root / "keys").mkdir(parents=True, exist_ok=True)
    if public_key_path and public_key_path.exists():
        shutil.copy2(public_key_path, iso_root / "keys" / public_key_path.name)
    _write_repo_files(iso_root, request.repo_sync_plans, public_key_path)
    if include_scripts:
        _write_scripts(
            iso_root / "scripts",
            include_install=request.include_install_scripts,
            include_validation=request.include_validation_scripts,
        )
    _write_readme(iso_root / "README.md", request)


def _write_repo_files(iso_root: Path, plans: list[RepoSyncPlan], public_key_path: Path | None) -> None:
    output_dir = iso_root / "yum.repos.d"
    output_dir.mkdir(parents=True, exist_ok=True)
    custom_gpgcheck = "1" if public_key_path else "0"
    custom_key = "gpgkey=file:///mnt/repoforge/keys/RPM-GPG-KEY-repoforge-custom" if public_key_path else ""
    (output_dir / "repoforge-custom.repo").write_text(
        "\n".join(
            [
                "[repoforge-custom]",
                "name=RepoForge Custom Repository",
                "baseurl=file:///mnt/repoforge/repos/custom",
                "enabled=1",
                f"gpgcheck={custom_gpgcheck}",
                f"repo_gpgcheck={custom_gpgcheck}",
                custom_key,
                "",
            ]
        ),
        encoding="utf-8",
    )
    vendor_sections: list[str] = []
    for plan in plans:
        repo_id = plan.repo_source.repo_id or _slug(plan.repo_source.name)
        vendor_sections.extend(
            [
                f"[repoforge-{_slug(repo_id)}]",
                f"name=RepoForge mirror of {plan.repo_source.name}",
                f"baseurl=file:///mnt/repoforge/repos/vendor/{_slug(repo_id)}",
                "enabled=1",
                f"gpgcheck={1 if plan.repo_source.gpgcheck else 0}",
            ]
        )
        if plan.repo_source.gpgkey_url:
            vendor_sections.append(f"# upstream-gpgkey={plan.repo_source.gpgkey_url}")
        vendor_sections.append("")
    if vendor_sections:
        (output_dir / "repoforge-vendor.repo").write_text("\n".join(vendor_sections), encoding="utf-8")


def _write_scripts(scripts_dir: Path, *, include_install: bool, include_validation: bool) -> None:
    scripts_dir.mkdir(parents=True, exist_ok=True)
    scripts: dict[str, str] = {}
    if include_install:
        scripts["import-gpg-keys.sh"] = """#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

for key in "${ROOT_DIR}"/keys/RPM-GPG-KEY-*; do
  [ -e "$key" ] || continue
  echo "Importing $key"
  rpm --import "$key"
done
"""
        scripts["install-repo-files.sh"] = """#!/usr/bin/env bash
set -euo pipefail

MOUNT_PATH="${1:-/mnt/repoforge}"

cp "${MOUNT_PATH}"/yum.repos.d/*.repo /etc/yum.repos.d/
dnf clean all
dnf repolist
"""
        scripts["mount-example.sh"] = """#!/usr/bin/env bash
set -euo pipefail

ISO_PATH="${1}"
MOUNT_PATH="${2:-/mnt/repoforge}"

mkdir -p "$MOUNT_PATH"
mount -o loop "$ISO_PATH" "$MOUNT_PATH"
echo "Mounted $ISO_PATH at $MOUNT_PATH"
"""
    if include_validation:
        scripts["validate-repos.sh"] = """#!/usr/bin/env bash
set -euo pipefail

dnf clean all
dnf repolist
dnf makecache
echo "Repo validation completed."
"""
        scripts["list-packages.sh"] = """#!/usr/bin/env bash
set -euo pipefail

MOUNT_PATH="${1:-/mnt/repoforge}"
find "${MOUNT_PATH}/repos" -name "*.rpm" -print | sort
"""
    for name, content in scripts.items():
        path = scripts_dir / name
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)


def _write_readme(path: Path, request: BuildRequest) -> None:
    path.write_text(
        "\n".join(
            [
                f"# RepoForge Bundle: {request.bundle_name}",
                "",
                f"Target: {request.target_os} / {request.architecture}",
                "",
                "Mount the ISO and install the included repository files:",
                "",
                "```bash",
                "mount -o loop repoforge.iso /mnt/repoforge",
                "/mnt/repoforge/scripts/import-gpg-keys.sh",
                "/mnt/repoforge/scripts/install-repo-files.sh /mnt/repoforge",
                "/mnt/repoforge/scripts/validate-repos.sh",
                "```",
                "",
                "Private GPG key material is not included in this ISO.",
                "",
            ]
        ),
        encoding="utf-8",
    )
