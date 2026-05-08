"""Remote worker CLI for executing a serialized RepoForge build request."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tarfile
import traceback

from app.services.build_orchestrator import BuildOrchestrator
from app.services.build_request_io import build_request_from_dict


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a RepoForge build request on a remote worker.")
    parser.add_argument("--archive", required=True, help="Path to the uploaded job archive.")
    parser.add_argument("--work-root", required=True, help="Remote job working directory.")
    args = parser.parse_args()

    work_root = Path(args.work_root)
    input_dir = work_root / "input"
    log_path = work_root / "build.log"
    result_path = work_root / "result.json"
    input_dir.mkdir(parents=True, exist_ok=True)

    def log(message: str) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(str(message).rstrip() + "\n")
        print(message, flush=True)

    try:
        with tarfile.open(args.archive, "r:gz") as archive:
            _safe_extract(archive, input_dir)
        request_data = json.loads((input_dir / "build-request.json").read_text(encoding="utf-8"))
        request = build_request_from_dict(request_data)
        result = BuildOrchestrator(log=log).build(request)
        result_path.write_text(
            json.dumps(
                {
                    "status": result.status,
                    "iso_path": str(result.iso_path) if result.iso_path else None,
                    "manifest_path": str(result.manifest_path),
                    "checksum_path": str(result.checksum_path),
                    "warnings": result.warnings,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        return 0
    except Exception as exc:
        log(f"Remote build failed: {exc}")
        log(traceback.format_exc())
        result_path.write_text(
            json.dumps({"status": "failed", "iso_path": None, "manifest_path": None, "checksum_path": None, "warnings": []})
            + "\n",
            encoding="utf-8",
        )
        return 1


def _safe_extract(archive: tarfile.TarFile, destination: Path) -> None:
    destination_root = destination.resolve()
    for member in archive.getmembers():
        target = (destination / member.name).resolve()
        try:
            target.relative_to(destination_root)
        except ValueError as exc:
            raise ValueError(f"archive member escapes destination: {member.name}") from exc
    archive.extractall(destination)


if __name__ == "__main__":
    raise SystemExit(main())
