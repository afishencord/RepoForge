from __future__ import annotations

import os
from pathlib import Path
import re
import sys
import tempfile
import uuid

import pytest


ROOT = Path(__file__).resolve().parents[1]
TEST_STORAGE = ROOT / "storage" / "test-runtime"
TEST_TMP = TEST_STORAGE / "tmp"

sys.path.insert(0, str(ROOT))

TEST_TMP.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("REPOFORGE_DATABASE_URL", f"sqlite:///{(TEST_STORAGE / 'repoforge-test.db').as_posix()}")
os.environ.setdefault("REPOFORGE_STORAGE_ROOT", str(TEST_STORAGE))
os.environ.setdefault("REPOFORGE_UPLOAD_ROOT", str(TEST_STORAGE / "uploads"))
os.environ.setdefault("REPOFORGE_WORKSPACE_ROOT", str(TEST_STORAGE / "workspaces"))
os.environ.setdefault("REPOFORGE_ARTIFACT_ROOT", str(TEST_STORAGE / "artifacts"))
os.environ.setdefault("REPOFORGE_KEY_ROOT", str(TEST_STORAGE / "keys"))
os.environ.setdefault("REPOFORGE_TLS_CERT_FILE", str(TEST_STORAGE / "tls" / "repoforge.crt"))
os.environ.setdefault("REPOFORGE_TLS_KEY_FILE", str(TEST_STORAGE / "tls" / "repoforge.key"))
os.environ.setdefault("TMP", str(TEST_TMP))
os.environ.setdefault("TEMP", str(TEST_TMP))
os.environ.setdefault("TMPDIR", str(TEST_TMP))
tempfile.tempdir = str(TEST_TMP)


@pytest.fixture
def tmp_path(request) -> Path:  # type: ignore[no-untyped-def]
    name = re.sub(r"[^A-Za-z0-9_.-]+", "-", request.node.name).strip("-")
    path = TEST_TMP / f"{name}-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path
