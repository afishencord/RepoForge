"""RPM inspection helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .checksum_service import sha256_file
from .runner import CommandResult, SubprocessRunner, default_runner


RPM_QUERYFORMAT = r"%{NAME}\n%{VERSION}\n%{RELEASE}\n%{ARCH}\n%{SUMMARY}\n"


@dataclass(frozen=True)
class RpmMetadata:
    path: Path
    name: str
    version: str
    release: str
    architecture: str
    summary: str
    sha256: str
    requires: list[str] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)
    signature: str | None = None


def rpm_metadata_command(rpm_path: Path | str) -> list[str]:
    return ["rpm", "-qp", "--queryformat", RPM_QUERYFORMAT, str(rpm_path)]


def rpm_requires_command(rpm_path: Path | str) -> list[str]:
    return ["rpm", "-qpR", str(rpm_path)]


def rpm_provides_command(rpm_path: Path | str) -> list[str]:
    return ["rpm", "-qp", "--provides", str(rpm_path)]


def rpm_signature_command(rpm_path: Path | str) -> list[str]:
    return ["rpm", "-K", str(rpm_path)]


def parse_rpm_metadata(stdout: str, rpm_path: Path | str, *, requires: list[str] | None = None, provides: list[str] | None = None, signature: str | None = None) -> RpmMetadata:
    lines = stdout.splitlines()
    if len(lines) < 5:
        raise ValueError("rpm metadata output did not include expected fields")
    return RpmMetadata(
        path=Path(rpm_path),
        name=lines[0],
        version=lines[1],
        release=lines[2],
        architecture=lines[3],
        summary=lines[4],
        sha256=sha256_file(rpm_path),
        requires=requires or [],
        provides=provides or [],
        signature=signature,
    )


def inspect_rpm(
    rpm_path: Path | str,
    *,
    runner: SubprocessRunner = default_runner,
    log: Callable[[str], None] | None = None,
) -> RpmMetadata:
    metadata = runner.run(rpm_metadata_command(rpm_path), log=log)
    requires = runner.run(rpm_requires_command(rpm_path), log=log).stdout.splitlines()
    provides = runner.run(rpm_provides_command(rpm_path), log=log).stdout.splitlines()
    signature_result: CommandResult = runner.run(rpm_signature_command(rpm_path), log=log, check=False)
    return parse_rpm_metadata(
        metadata.stdout,
        rpm_path,
        requires=requires,
        provides=provides,
        signature=signature_result.stdout.strip() or signature_result.stderr.strip() or None,
    )

