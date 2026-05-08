from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.checksum_service import generate_checksums, sha256_file, write_sha256sums
from app.services.builder_deployment import (
    BuilderValidationError,
    RemoteWorkerConfig,
    normalize_builder_mode,
    validate_builder_mode_for_sources,
)
from app.services.build_orchestrator import BuildRequest
from app.services.build_request_io import build_request_from_dict, build_request_to_dict, with_remote_paths
from app.services.dependency_service import filter_rpm_requirements
from app.services.dnf_service import RepoSource, create_repo_file_content, dnf_download_command, reposync_command, temporary_repo_dir, with_reposdir
from app.services.gpg_service import GpgKeyRequest, key_params_content
from app.services.iso_service import copy_into_iso_root, xorriso_command
from app.services.manifest_service import BundleManifest, write_manifest, write_package_list
from app.services.runner import SubprocessRunner, mask_args, require_relative_path


class RecordingRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, args, **kwargs):  # type: ignore[no-untyped-def]
        self.commands.append(list(args))
        stdout = "rhel-9-baseos-rpms Red Hat Enterprise Linux 9 BaseOS\n" if args[:2] == ["dnf", "repolist"] else ""
        from app.services.runner import CommandResult

        return CommandResult(args=tuple(args), returncode=0, stdout=stdout)


def test_require_relative_path_blocks_escape(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()

    assert require_relative_path("nested/file.txt", root) == root / "nested" / "file.txt"

    with pytest.raises(ValueError):
        require_relative_path("../outside.txt", root)


def test_mask_args_hides_secrets_and_sensitive_tokens() -> None:
    masked = mask_args(["dnf", "--setopt=password=hunter2", "token=abc123", "plain"], secrets=["hunter2"])

    assert masked == ("dnf", "--setopt=***", "token=***", "plain")


def test_runner_rejects_shell_string() -> None:
    runner = SubprocessRunner()

    with pytest.raises(ValueError):
        runner.run("echo unsafe")  # type: ignore[arg-type]


def test_builder_mode_normalization_defaults_unknown_values() -> None:
    assert normalize_builder_mode("remote-rhel-worker") == "remote-rhel-worker"
    assert normalize_builder_mode("bogus") == "container"


def test_redhat_container_mode_requires_local_entitlement_tools() -> None:
    source = {"name": "RHEL BaseOS", "source_type": "redhat9", "repo_id": "rhel-9-baseos-rpms", "enabled": True}

    with pytest.raises(BuilderValidationError, match="subscription-manager"):
        validate_builder_mode_for_sources("container", [source], command_exists=lambda name: None)


def test_local_rhel_validation_checks_subscription_and_repo_ids() -> None:
    source = {"name": "RHEL BaseOS", "source_type": "redhat9", "repo_id": "rhel-9-baseos-rpms", "enabled": True}
    runner = RecordingRunner()

    validate_builder_mode_for_sources("local-rhel", [source], runner=runner, command_exists=lambda name: f"/usr/bin/{name}")

    assert runner.commands == [
        ["subscription-manager", "identity"],
        ["subscription-manager", "repos", "--list-enabled"],
        ["dnf", "repolist", "--enabled"],
    ]


def test_external_mirror_requires_redhat_sources_to_have_urls() -> None:
    source = {"name": "RHEL BaseOS", "source_type": "redhat9", "repo_id": "rhel-9-baseos-rpms", "enabled": True}

    with pytest.raises(BuilderValidationError, match="base URL or mirrorlist"):
        validate_builder_mode_for_sources("external-mirror", [source])

    validate_builder_mode_for_sources("external-mirror", [{**source, "base_url": "https://mirror.example/rhel9"}])


def test_remote_worker_mode_requires_worker_settings() -> None:
    source = {"name": "RHEL BaseOS", "source_type": "redhat9", "repo_id": "rhel-9-baseos-rpms", "enabled": True}

    with pytest.raises(BuilderValidationError, match="configured worker"):
        validate_builder_mode_for_sources("remote-rhel-worker", [source], worker_config=RemoteWorkerConfig())

    generic_source = {"name": "Docker CE", "source_type": "generic_yum", "repo_id": "docker-ce", "enabled": True}
    with pytest.raises(BuilderValidationError, match="configured worker"):
        validate_builder_mode_for_sources("remote-rhel-worker", [generic_source], worker_config=RemoteWorkerConfig())


def test_build_request_serialization_round_trips_remote_paths(tmp_path: Path) -> None:
    rpm = tmp_path / "custom.rpm"
    rpm.write_text("rpm payload", encoding="utf-8")
    request = BuildRequest(
        bundle_id="1",
        bundle_name="rhel baseline",
        target_os="rhel9",
        architecture="x86_64",
        workspace_dir=tmp_path / "workspace",
        artifact_dir=tmp_path / "artifacts",
        job_id="42",
        builder_mode="remote-rhel-worker",
        worker="rhel-worker",
        repo_sync_plans=[],
        uploaded_rpms=[{"storage_path": str(rpm), "original_filename": "custom.rpm"}],
    )

    remote = with_remote_paths(
        request,
        remote_workspace="/var/lib/repoforge-worker/42/workspace",
        remote_artifact_dir="/var/lib/repoforge-worker/42/artifacts",
        remote_upload_dir="/var/lib/repoforge-worker/42/input/uploads",
    )
    data = build_request_to_dict(remote)
    restored = build_request_from_dict(data)

    assert restored.builder_mode == "remote-rhel-worker"
    assert restored.worker == "rhel-worker"
    assert restored.uploaded_rpms[0]["storage_path"] == "/var/lib/repoforge-worker/42/input/uploads/custom.rpm"


def test_checksum_generation_and_sha256sums_are_stable(tmp_path: Path) -> None:
    (tmp_path / "b.txt").write_text("bravo", encoding="utf-8")
    (tmp_path / "a.txt").write_text("alpha", encoding="utf-8")

    checksums = generate_checksums(tmp_path)
    assert [item.relative_path for item in checksums] == ["a.txt", "b.txt"]
    assert checksums[0].sha256 == sha256_file(tmp_path / "a.txt")

    output = write_sha256sums(tmp_path, tmp_path / "checksums" / "SHA256SUMS")
    lines = output.read_text(encoding="utf-8").splitlines()
    assert lines[0].endswith("  a.txt")
    assert lines[1].endswith("  b.txt")


def test_manifest_and_package_list_generation(tmp_path: Path) -> None:
    manifest = BundleManifest(
        bundle_name="elastic-rhel9",
        target_os="rhel9",
        architecture="x86_64",
        packages=[{"name": "kibana"}, "elasticsearch"],
    )

    manifest_path = write_manifest(manifest, tmp_path / "bundle-manifest.json")
    package_list_path = write_package_list(manifest.packages, tmp_path / "package-list.txt")

    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert data["bundle_name"] == "elastic-rhel9"
    assert data["build_status"] == "completed"
    assert package_list_path.read_text(encoding="utf-8").splitlines() == ["elasticsearch", "kibana"]


def test_dnf_and_reposync_command_construction(tmp_path: Path) -> None:
    assert dnf_download_command("docker-ce", tmp_path, "docker-ce-stable") == [
        "dnf",
        "download",
        "--resolve",
        f"--destdir={tmp_path}",
        "--repoid=docker-ce-stable",
        "docker-ce",
    ]
    assert reposync_command("rhel-9-baseos", tmp_path) == [
        "reposync",
        "--repoid=rhel-9-baseos",
        "--download-metadata",
        f"--download-path={tmp_path}",
    ]


def test_repo_file_content_supports_baseurl_and_masks_nothing_in_data() -> None:
    repo = RepoSource(
        name="Docker CE Stable",
        repo_id="docker-ce-stable",
        baseurl="https://download.docker.com/linux/rhel/$releasever/$basearch/stable",
        gpgkey_url="https://download.docker.com/linux/rhel/gpg",
    )

    content = create_repo_file_content(repo)
    assert "[docker-ce-stable]" in content
    assert "enabled=1" in content
    assert "baseurl=https://download.docker.com/linux/rhel/$releasever/$basearch/stable" in content
    assert "gpgkey=https://download.docker.com/linux/rhel/gpg" in content


def test_ui_defined_repo_sources_get_a_transient_reposdir() -> None:
    repo = RepoSource(
        name="Docker CE Stable",
        repo_id="docker-ce",
        baseurl="https://download.docker.com/linux/rhel/9/x86_64/stable",
        gpgkey_url="https://download.docker.com/linux/rhel/gpg",
    )

    with temporary_repo_dir(repo) as repo_dir:
        assert repo_dir is not None
        assert (repo_dir / "docker-ce.repo").exists()
        command = with_reposdir(reposync_command(repo.repo_id, "/tmp/out"), repo_dir)

    assert command[:2] == ["reposync", f"--setopt=reposdir={repo_dir}"]
    assert "--repoid=docker-ce" in command


def test_dependency_requirement_filtering() -> None:
    requirements = [
        "rpmlib(CompressedFileNames) <= 3.0.4-1",
        "/bin/bash",
        "python3 >= 3.9",
        "libcrypto.so.3()(64bit)",
        "systemd",
        "",
    ]

    assert filter_rpm_requirements(requirements) == ["python3 >= 3.9", "systemd"]


def test_gpg_key_params_content_no_protection_for_mvp() -> None:
    content = key_params_content(GpgKeyRequest(name_real="RepoForge", name_email="repo@example.test", expire_date="1y"))

    assert "Key-Type: RSA" in content
    assert "Name-Real: RepoForge" in content
    assert "%no-protection" in content
    assert content.endswith("%commit\n")


def test_xorriso_command_and_iso_copy_path_safety(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_text("payload", encoding="utf-8")
    iso_root = tmp_path / "iso-root"

    target = copy_into_iso_root(source, "repoforge/source.txt", iso_root)
    assert target.read_text(encoding="utf-8") == "payload"

    with pytest.raises(ValueError):
        copy_into_iso_root(source, "../escaped.txt", iso_root)

    assert xorriso_command(iso_root, tmp_path / "out.iso")[:8] == [
        "xorriso",
        "-as",
        "mkisofs",
        "-iso-level",
        "3",
        "-full-iso9660-filenames",
        "-volid",
        "REPOFORGE",
    ]
