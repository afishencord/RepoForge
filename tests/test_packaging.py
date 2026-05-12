from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def test_pyinstaller_spec_bundles_runtime_assets() -> None:
    spec = (ROOT / "packaging" / "repoforge.spec").read_text(encoding="utf-8")

    assert "app/templates" in spec
    assert "app/static" in spec
    assert "migrations" in spec
    assert "alembic.ini" in spec
    assert 'name="repoforge"' in spec


@pytest.mark.skipif(
    os.getenv("REPOFORGE_RUN_PYINSTALLER_SMOKE") != "1" or shutil.which("pyinstaller") is None,
    reason="set REPOFORGE_RUN_PYINSTALLER_SMOKE=1 with PyInstaller installed to build the binary",
)
def test_pyinstaller_binary_smoke_builds_and_prints_help() -> None:
    subprocess.run([sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm", "packaging/repoforge.spec"], cwd=ROOT, check=True)
    binary = ROOT / "dist" / ("repoforge.exe" if sys.platform == "win32" else "repoforge")

    result = subprocess.run([str(binary), "--help"], check=True, text=True, stdout=subprocess.PIPE)

    assert "Run and maintain RepoForge" in result.stdout
