from __future__ import annotations

import asyncio
from ipaddress import ip_address
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import server
from tests.env_values import env_value


def configured_host() -> str:
    return env_value("REPOFORGE_TLS_SUBJECT_ALT_NAMES").split(",", 1)[0].strip()


def trusted_proxy_client() -> str:
    return env_value("REPOFORGE_TRUSTED_PROXY_IPS").split(",", 1)[0].strip().split("/", 1)[0]


def trusted_proxy_cidr() -> str:
    client = ip_address(trusted_proxy_client())
    return f"{client}/{client.max_prefixlen}"


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


def test_uvicorn_command_includes_configured_log_level() -> None:
    settings = SimpleNamespace(server_host="", log_level=env_value("REPOFORGE_LOG_LEVEL"))

    with patch.object(server, "settings", settings):
        command = server._uvicorn_command("app.main:app", int(env_value("REPOFORGE_HTTP_PORT")))

    assert "--log-level" in command
    assert env_value("REPOFORGE_LOG_LEVEL").lower() in command


async def ok_asgi_app(scope, receive, send):  # type: ignore[no-untyped-def]
    assert scope["type"] == "http"
    body = scope["scheme"].encode("ascii")
    await send({"type": "http.response.start", "status": 200, "headers": [(b"content-length", str(len(body)).encode("ascii"))]})
    await send({"type": "http.response.body", "body": body})


def request_messages(
    path: str,
    headers: list[tuple[bytes, bytes]],
    query_string: bytes = b"",
    client_host: str | None = None,
) -> list[dict]:
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
        "client": (client_host or trusted_proxy_client(), 54321),
    }

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        messages.append(message)

    asyncio.run(server.http_entrypoint_app(scope, receive, send))
    return messages


def test_http_entrypoint_redirects_plain_http() -> None:
    settings = SimpleNamespace(https_port=int(env_value("REPOFORGE_HTTPS_PORT")))
    host = configured_host()

    with patch.object(server, "settings", settings), patch.object(server, "_repo_app", return_value=ok_asgi_app):
        messages = request_messages("/healthz", [(b"host", host.encode("ascii"))], b"probe=1")

    assert messages[0]["status"] == 307
    assert (b"location", f"https://{host}/healthz?probe=1".encode("ascii")) in messages[0]["headers"]


def test_http_entrypoint_serves_forwarded_https() -> None:
    settings = SimpleNamespace(https_port=int(env_value("REPOFORGE_HTTPS_PORT")), trusted_proxy_ips=env_value("REPOFORGE_TRUSTED_PROXY_IPS"))
    host = configured_host()

    with patch.object(server, "settings", settings), patch.object(server, "_repo_app", return_value=ok_asgi_app):
        messages = request_messages(
            "/healthz",
            [(b"x-forwarded-proto", b"https"), (b"x-forwarded-host", host.encode("ascii"))],
        )

    assert messages[0]["status"] == 200
    assert messages[1]["body"] == b"https"


def test_http_entrypoint_accepts_trusted_proxy_cidr() -> None:
    settings = SimpleNamespace(https_port=int(env_value("REPOFORGE_HTTPS_PORT")), trusted_proxy_ips=trusted_proxy_cidr())
    host = configured_host()

    with patch.object(server, "settings", settings), patch.object(server, "_repo_app", return_value=ok_asgi_app):
        messages = request_messages(
            "/healthz",
            [(b"x-forwarded-proto", b"https"), (b"x-forwarded-host", host.encode("ascii"))],
            client_host=trusted_proxy_client(),
        )

    assert messages[0]["status"] == 200
    assert messages[1]["body"] == b"https"


def test_http_entrypoint_rejects_untrusted_forwarded_https() -> None:
    settings = SimpleNamespace(https_port=int(env_value("REPOFORGE_HTTPS_PORT")), trusted_proxy_ips="")
    host = configured_host()

    with patch.object(server, "settings", settings), patch.object(server, "_repo_app", return_value=ok_asgi_app):
        messages = request_messages(
            "/healthz",
            [(b"x-forwarded-proto", b"https"), (b"x-forwarded-host", host.encode("ascii"))],
        )

    assert messages[0]["status"] == 307
