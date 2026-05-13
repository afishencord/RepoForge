from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENV_FILES = (ROOT / "packaging" / "repoforge.env", ROOT / "tests" / "fixtures" / "repoforge.env")


def env_value(name: str) -> str:
    for env_file in ENV_FILES:
        if not env_file.is_file():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip()
    files = ", ".join(str(path) for path in ENV_FILES)
    raise AssertionError(f"{name} is not configured in {files}")
