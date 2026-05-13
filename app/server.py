"""RepoForge HTTP and HTTPS serving helpers."""

from __future__ import annotations

import os
import logging
from ipaddress import ip_address, ip_network
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Awaitable, Callable, Iterable

from app.config import settings
from app.logging_config import configure_logging

AsgiApp = Callable[[dict, Callable[[], Awaitable[dict]], Callable[[dict], Awaitable[None]]], Awaitable[None]]


_main_app: AsgiApp | None = None
logger = logging.getLogger("repoforge.server")


def _host_without_port(host: str) -> str:
    if host.startswith("[") and "]" in host:
        return host[: host.index("]") + 1]
    if host.count(":") == 1:
        return host.rsplit(":", 1)[0]
    return host


def _repo_app() -> AsgiApp:
    global _main_app
    if _main_app is None:
        from app.main import app

        _main_app = app
    return _main_app


def _headers(scope: dict) -> dict[str, str]:
    return {key.decode("latin1").lower(): value.decode("latin1") for key, value in scope.get("headers", [])}


def _first_header_value(headers: dict[str, str], name: str) -> str:
    return headers.get(name, "").split(",", 1)[0].strip()


def _forwarded_proto(headers: dict[str, str]) -> str:
    proto = _first_header_value(headers, "x-forwarded-proto").lower()
    if proto:
        return proto
    forwarded = _first_header_value(headers, "forwarded")
    for part in forwarded.split(";"):
        key, _, value = part.partition("=")
        if key.strip().lower() == "proto":
            return value.strip().strip('"').lower()
    return ""


def _forwarded_host(headers: dict[str, str]) -> str:
    return _first_header_value(headers, "x-forwarded-host") or headers.get("host", "")


def _trusted_forwarded_client(scope: dict) -> bool:
    allowed = {value.strip() for value in settings.trusted_proxy_ips.split(",") if value.strip()}
    if "*" in allowed:
        return True
    client = scope.get("client")
    if not client:
        return False
    client_host = str(client[0])
    if client_host in allowed:
        return True
    try:
        client_ip = ip_address(client_host)
    except ValueError:
        return False
    for value in allowed:
        try:
            if client_ip in ip_network(value, strict=False):
                return True
        except ValueError:
            continue
    return False


def _scope_for_forwarded_https(scope: dict, headers: dict[str, str]) -> dict:
    forwarded_host = _forwarded_host(headers)
    updated_headers: list[tuple[bytes, bytes]] = []
    replaced_host = False
    for key, value in scope.get("headers", []):
        if key.decode("latin1").lower() == "host":
            updated_headers.append((key, forwarded_host.encode("latin1")))
            replaced_host = True
        else:
            updated_headers.append((key, value))
    if not replaced_host:
        updated_headers.append((b"host", forwarded_host.encode("latin1")))

    updated = dict(scope)
    updated["scheme"] = "https"
    updated["headers"] = updated_headers
    return updated


async def _redirect_to_https(scope, send):  # type: ignore[no-untyped-def]
    headers = _headers(scope)
    host = _host_without_port(_forwarded_host(headers))
    port = "" if settings.https_port == 443 else f":{settings.https_port}"
    raw_path = scope.get("raw_path", scope.get("path", "/"))
    path = raw_path.decode("latin1") if isinstance(raw_path, bytes) else str(raw_path)
    query = scope.get("query_string", b"")
    query_string = query.decode("latin1") if isinstance(query, bytes) else str(query)
    location = f"https://{host}{port}{path}"
    if query_string:
        location = f"{location}?{query_string}"

    await send(
        {
            "type": "http.response.start",
            "status": 307,
            "headers": [(b"location", location.encode("latin1")), (b"content-length", b"0")],
        }
    )
    await send({"type": "http.response.body", "body": b""})


async def https_redirect_app(scope, receive, send):  # type: ignore[no-untyped-def]
    if scope["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return

    if scope["type"] != "http":
        await send({"type": "websocket.close"})
        return

    await _redirect_to_https(scope, send)


async def http_entrypoint_app(scope, receive, send):  # type: ignore[no-untyped-def]
    if scope["type"] == "lifespan":
        await _repo_app()(scope, receive, send)
        return

    if scope["type"] == "http":
        headers = _headers(scope)
        if _forwarded_proto(headers) == "https" and _trusted_forwarded_client(scope):
            await _repo_app()(_scope_for_forwarded_https(scope, headers), receive, send)
            return
        await _redirect_to_https(scope, send)
        return

    await send({"type": "websocket.close"})


def _uvicorn_command(asgi_app: str, port: int, *, cert_file: Path | None = None, key_file: Path | None = None) -> list[str]:
    if getattr(sys, "frozen", False):
        command = [sys.executable, "_serve-asgi", asgi_app, "--port", str(port)]
    else:
        command = [sys.executable, "-m", "uvicorn", asgi_app, "--port", str(port)]
    command.extend(["--log-level", settings.log_level.lower()])
    if settings.server_host:
        command.extend(["--host", settings.server_host])
    if cert_file and key_file:
        command.extend(["--ssl-certfile", str(cert_file), "--ssl-keyfile", str(key_file)])
    return command


def _san_config() -> str:
    entries: list[str] = []
    for value in settings.tls_subject_alt_names.split(","):
        name = value.strip()
        if not name:
            continue
        prefix = "IP" if all(part.isdigit() for part in name.split(".") if part) and name.count(".") == 3 else "DNS"
        entries.append(f"{prefix}:{name}")
    return ",".join(entries)


def _validate_cert_chain(cert_file: Path, key_file: Path) -> bool:
    import ssl

    try:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=str(cert_file), keyfile=str(key_file))
    except Exception as error:
        print(f"RepoForge TLS certificate/key could not be loaded: {error}", file=sys.stderr, flush=True)
        return False
    return True


def _tls_paths() -> tuple[Path, Path]:
    cert_file = settings.tls_cert_file or settings.storage_root / "tls" / "repoforge.crt"
    key_file = settings.tls_key_file or settings.storage_root / "tls" / "repoforge.key"
    return cert_file, key_file


def _generate_self_signed_cert(cert_file: Path, key_file: Path) -> bool:
    cert_file.parent.mkdir(parents=True, exist_ok=True)
    key_file.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-sha256",
        "-days",
        "3650",
        "-subj",
        "/CN=RepoForge",
        "-keyout",
        str(key_file),
        "-out",
        str(cert_file),
    ]
    san_config = _san_config()
    if san_config:
        command[command.index("-keyout"):command.index("-keyout")] = ["-addext", f"subjectAltName={san_config}"]
    try:
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError:
        print("OpenSSL is not installed; cannot auto-generate a RepoForge TLS certificate.", file=sys.stderr, flush=True)
        return False
    except subprocess.CalledProcessError as error:
        print(f"OpenSSL failed to generate the RepoForge TLS certificate: {error.stderr}", file=sys.stderr, flush=True)
        return False
    try:
        key_file.chmod(0o600)
    except OSError:
        pass
    print(f"Generated self-signed RepoForge TLS certificate at {cert_file}.", flush=True)
    return True


def _resolve_tls_files() -> tuple[Path, Path] | None:
    cert_file, key_file = _tls_paths()
    if cert_file.is_file() and key_file.is_file():
        return (cert_file, key_file) if _validate_cert_chain(cert_file, key_file) else None

    if not settings.tls_auto_generate:
        if settings.tls_cert_file or settings.tls_key_file:
            print(
                "RepoForge TLS cert/key were configured but one or both files are missing; starting HTTP only.",
                file=sys.stderr,
                flush=True,
            )
        return None

    missing = ", ".join(str(path) for path in (cert_file, key_file) if not path.is_file())
    print(f"RepoForge TLS cert/key missing ({missing}); generating a self-signed certificate.", flush=True)
    if not _generate_self_signed_cert(cert_file, key_file):
        return None
    return (cert_file, key_file) if _validate_cert_chain(cert_file, key_file) else None


def _start_processes(commands: Iterable[list[str]]) -> int:
    processes = [subprocess.Popen(command) for command in commands]

    def stop_processes(*_: object) -> None:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        deadline = time.time() + 10
        for process in processes:
            remaining = max(0.1, deadline - time.time())
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                process.kill()

    signal.signal(signal.SIGTERM, stop_processes)
    signal.signal(signal.SIGINT, stop_processes)

    while processes:
        for process in processes:
            return_code = process.poll()
            if return_code is not None:
                stop_processes()
                return return_code
        time.sleep(0.5)
    return 0


def _database_dialect() -> str:
    return settings.database_url.split(":", 1)[0] or "unknown"


def main() -> int:
    configure_logging()
    commands: list[list[str]] = []
    tls_files = _resolve_tls_files()
    if tls_files:
        cert_file, key_file = tls_files
        if settings.enable_http:
            commands.append(_uvicorn_command("app.server:http_entrypoint_app", settings.http_port))
        commands.append(_uvicorn_command("app.main:app", settings.https_port, cert_file=cert_file, key_file=key_file))
    else:
        commands.append(_uvicorn_command("app.main:app", settings.http_port))

    logger.info(
        "Starting RepoForge pid=%s processes=%s http_enabled=%s http_port=%s https_port=%s tls_enabled=%s "
        "trusted_proxy_configured=%s database_dialect=%s log_level=%s",
        os.getpid(),
        len(commands),
        settings.enable_http,
        settings.http_port,
        settings.https_port,
        bool(tls_files),
        bool(settings.trusted_proxy_ips.strip()),
        _database_dialect(),
        settings.log_level,
    )
    return _start_processes(commands)


if __name__ == "__main__":
    raise SystemExit(main())
