"""ISO root assembly and data ISO creation helpers."""

from __future__ import annotations

from pathlib import Path
import shutil
from typing import Callable

from .runner import CommandResult, SubprocessRunner, default_runner, require_relative_path


def xorriso_command(iso_root: Path | str, output_iso: Path | str, volume_id: str = "REPOFORGE") -> list[str]:
    return [
        "xorriso",
        "-as",
        "mkisofs",
        "-iso-level",
        "3",
        "-full-iso9660-filenames",
        "-volid",
        volume_id,
        "-output",
        str(output_iso),
        str(iso_root),
    ]


def genisoimage_command(iso_root: Path | str, output_iso: Path | str, volume_id: str = "REPOFORGE") -> list[str]:
    return [
        "genisoimage",
        "-iso-level",
        "3",
        "-l",
        "-V",
        volume_id,
        "-o",
        str(output_iso),
        str(iso_root),
    ]


def copy_into_iso_root(source: Path | str, relative_target: Path | str, iso_root: Path | str) -> Path:
    root = Path(iso_root).resolve()
    target = require_relative_path(relative_target, root)
    source_path = Path(source).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    if source_path.is_dir():
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source_path, target)
    else:
        shutil.copy2(source_path, target)
    return target


def build_iso(
    iso_root: Path | str,
    output_iso: Path | str,
    *,
    runner: SubprocessRunner = default_runner,
    log: Callable[[str], None] | None = None,
    volume_id: str = "REPOFORGE",
    prefer_xorriso: bool = True,
) -> CommandResult:
    output = Path(output_iso)
    output.parent.mkdir(parents=True, exist_ok=True)
    command = xorriso_command(iso_root, output, volume_id) if prefer_xorriso else genisoimage_command(iso_root, output, volume_id)
    return runner.run(command, log=log)


def validate_iso(
    output_iso: Path | str,
    *,
    runner: SubprocessRunner = default_runner,
    log: Callable[[str], None] | None = None,
) -> CommandResult:
    return runner.run(["isoinfo", "-d", "-i", str(output_iso)], log=log)

