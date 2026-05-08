"""Bundle manifest and package-list generation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return value.as_posix()
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


@dataclass
class BundleManifest:
    bundle_name: str
    target_os: str
    architecture: str
    builder_mode: str = "container"
    worker: str = ""
    build_status: str = "completed"
    created_at: str = field(default_factory=utc_now_iso)
    repo_sources: list[dict[str, Any]] = field(default_factory=list)
    packages: list[dict[str, Any] | str] = field(default_factory=list)
    uploaded_rpms: list[dict[str, Any]] = field(default_factory=list)
    resolved_dependencies: list[dict[str, Any]] = field(default_factory=list)
    gpg_keys: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def write_manifest(manifest: BundleManifest, output_path: Path | str) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(manifest.to_dict(), indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
    )
    return output


def write_package_list(packages: list[dict[str, Any] | str], output_path: Path | str) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    for package in packages:
        if isinstance(package, str):
            names.append(package)
        else:
            names.append(str(package.get("name") or package.get("nevra") or package))
    output.write_text("\n".join(sorted(names)) + ("\n" if names else ""), encoding="utf-8")
    return output
