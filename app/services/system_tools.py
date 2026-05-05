"""System tool discovery and validation."""

from __future__ import annotations

from dataclasses import dataclass
import shutil
import subprocess


@dataclass(frozen=True)
class ToolCheck:
    name: str
    present: bool
    path: str | None = None
    required: bool = True
    version: str | None = None


REQUIRED_TOOLS = ("dnf", "reposync", "createrepo_c", "rpm", "gpg")
OPTIONAL_TOOLS = ("xorriso", "genisoimage", "isoinfo", "sha256sum", "pip")


def check_tool(name: str, *, required: bool = True) -> ToolCheck:
    path = shutil.which(name)
    version = tool_version(name) if path else None
    return ToolCheck(name=name, present=path is not None, path=path, required=required, version=version)


def tool_version(name: str) -> str | None:
    version_args = {
        "dnf": ["dnf", "--version"],
        "reposync": ["reposync", "--help"],
        "createrepo_c": ["createrepo_c", "--version"],
        "rpm": ["rpm", "--version"],
        "gpg": ["gpg", "--version"],
        "xorriso": ["xorriso", "-version"],
        "genisoimage": ["genisoimage", "--version"],
        "isoinfo": ["isoinfo", "-version"],
        "sha256sum": ["sha256sum", "--version"],
        "pip": ["pip", "--version"],
    }
    args = version_args.get(name, [name, "--version"])
    try:
        completed = subprocess.run(args, check=False, capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (completed.stdout or completed.stderr).splitlines()
    return text[0][:120] if text else None


def check_system_tools(
    required_tools: tuple[str, ...] = REQUIRED_TOOLS,
    optional_tools: tuple[str, ...] = OPTIONAL_TOOLS,
) -> list[ToolCheck]:
    checks = [check_tool(tool, required=True) for tool in required_tools]
    checks.extend(check_tool(tool, required=False) for tool in optional_tools)
    return checks


def missing_required_tools(checks: list[ToolCheck]) -> list[str]:
    return [check.name for check in checks if check.required and not check.present]
