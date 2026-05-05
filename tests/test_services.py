from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.checksum_service import generate_checksums, sha256_file, write_sha256sums
from app.services.dependency_service import filter_rpm_requirements
from app.services.dnf_service import RepoSource, create_repo_file_content, dnf_download_command, reposync_command
from app.services.gpg_service import GpgKeyRequest, key_params_content
from app.services.iso_service import copy_into_iso_root, xorriso_command
from app.services.manifest_service import BundleManifest, write_manifest, write_package_list
from app.services.runner import SubprocessRunner, mask_args, require_relative_path


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
