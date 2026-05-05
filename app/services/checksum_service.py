"""Checksum generation for bundle artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from .runner import require_relative_path


@dataclass(frozen=True)
class FileChecksum:
    path: Path
    relative_path: str
    sha256: str
    size_bytes: int


def sha256_file(path: Path | str, chunk_size: int = 1024 * 1024) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_checksum_files(root: Path | str, include_suffixes: tuple[str, ...] | None = None) -> list[Path]:
    base = Path(root).resolve()
    files = [path for path in base.rglob("*") if path.is_file()]
    if include_suffixes:
        files = [path for path in files if path.suffix in include_suffixes]
    return sorted(files, key=lambda path: path.relative_to(base).as_posix())


def generate_checksums(root: Path | str, include_suffixes: tuple[str, ...] | None = None) -> list[FileChecksum]:
    base = Path(root).resolve()
    checksums: list[FileChecksum] = []
    for path in iter_checksum_files(base, include_suffixes):
        safe_path = require_relative_path(path, base)
        checksums.append(
            FileChecksum(
                path=safe_path,
                relative_path=safe_path.relative_to(base).as_posix(),
                sha256=sha256_file(safe_path),
                size_bytes=safe_path.stat().st_size,
            )
        )
    return checksums


def write_sha256sums(root: Path | str, output_path: Path | str, include_suffixes: tuple[str, ...] | None = None) -> Path:
    base = Path(root).resolve()
    output = require_relative_path(output_path, base)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"{item.sha256}  {item.relative_path}"
        for item in generate_checksums(base, include_suffixes)
        if item.path != output
    ]
    output.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return output

