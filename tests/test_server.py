from __future__ import annotations

import asyncio
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


async def ok_asgi_app(scope, receive, send):  # type: ignore[no-untyped-def]
    assert scope["type"] == "http"
    body = scope["scheme"].encode("ascii")
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-length", str(len(body)).encode("ascii"))]})
    await send({"type": "http.response.body", "body": body})


def request_messages(path: str, headers: list[tuple[bytes, bytes]], query_string: bytes = b"") -> list[dict]:
    messages: list[dict] = []
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": query_string,
        "headers": headers,
        "client": ("127.0.0.1", 54321),
    }

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        messages.append(message)

    asyncio.run(server.http_entrypoint_app(scope, receive, send))
    return messages


def test_http_entrypoint_redirects_plain_http() -> None:
    settings = SimpleNamespace(https_port=443)

    with patch.object(server, "settings", settings), patch.object(server, "_repo_app", return_value=ok_asgi_app):
        messages = request_messages("/healthz", [(b"host", b"repoforge.mesh1labs.com")], b"probe=1")

    assert messages[0]["status"] == 307
    assert (b"location", b"https://repoforge.mesh1labs.com/healthz?probe=1") in messages[0]["headers"]


def test_http_entrypoint_serves_forwarded_https() -> None:
    settings = SimpleNamespace(https_port=443, trusted_proxy_ips="127.0.0.1")

    with patch.object(server, "settings", settings), patch.object(server, "_repo_app", return_value=ok_asgi_app):
        messages = request_messages(
            "/healthz",
            [(b"x-forwarded-proto", b"https"), (b"x-forwarded-host", b"repoforge.mesh1labs.com")],
        )

    assert messages[0]["status"] == 200
    assert messages[1]["body"] == b"https"


def test_http_entrypoint_rejects_untrusted_forwarded_https() -> None:
    settings = SimpleNamespace(https_port=443, trusted_proxy_ips="10.0.0.5")

    with patch.object(server, "settings", settings), patch.object(server, "_repo_app", return_value=ok_asgi_app):
        messages = request_messages(
            "/healthz",
            [(b"x-forwarded-proto", b"https"), (b"x-forwarded-host", b"repoforge.mesh1labs.com")],
        )

    assert messages[0]["status"] == 307
