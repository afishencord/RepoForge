from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import server


def test_resolve_tls_files_returns_valid_existing_pair(tmp_path: Path) -> None:
    cert_file = tmp_path / "repoforge.crt"
    key_file = tmp_path / "repoforge.key"
    cert_file.write_text("cert", encoding="utf-8")
    key_file.write_text("key", encoding="utf-8")
    settings = SimpleNamespace(tls_cert_file=cert_file, tls_key_file=key_file, storage_root=tmp_path, tls_auto_generate=False)

    with patch.object(server, "settings", settings), patch.object(server, "_validate_cert_chain", return_value=True):
        assert server._resolve_tls_files() == (cert_file, key_file)


def test_resolve_tls_files_generates_when_enabled(tmp_path: Path) -> None:
    cert_file = tmp_path / "tls" / "repoforge.crt"
    key_file = tmp_path / "tls" / "repoforge.key"
    settings = SimpleNamespace(tls_cert_file=cert_file, tls_key_file=key_file, storage_root=tmp_path, tls_auto_generate=True)

    def generate_cert(cert: Path, key: Path) -> bool:
        cert.parent.mkdir(parents=True, exist_ok=True)
        key.parent.mkdir(parents=True, exist_ok=True)
        cert.write_text("cert", encoding="utf-8")
        key.write_text("key", encoding="utf-8")
        return True

    with (
        patch.object(server, "settings", settings),
        patch.object(server, "_generate_self_signed_cert", side_effect=generate_cert),
        patch.object(server, "_validate_cert_chain", return_value=True),
    ):
        assert server._resolve_tls_files() == (cert_file, key_file)


def test_resolve_tls_files_returns_none_without_files_or_auto_generation(tmp_path: Path) -> None:
    cert_file = tmp_path / "repoforge.crt"
    key_file = tmp_path / "repoforge.key"
    settings = SimpleNamespace(tls_cert_file=cert_file, tls_key_file=key_file, storage_root=tmp_path, tls_auto_generate=False)

    with patch.object(server, "settings", settings):
        assert server._resolve_tls_files() is None
