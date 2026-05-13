from __future__ import annotations

import asyncio
from unittest.mock import patch

from starlette.requests import Request

from app.database import SessionLocal, init_db
from app.main import log_request_failures, readyz, request_logger
from tests.env_values import env_value


def test_readyz_checks_database() -> None:
    init_db()

    with SessionLocal() as db:
        response = readyz(db)

    assert response == {"status": "ok", "database": "ok"}


def test_readyz_reports_database_failure() -> None:
    class BrokenSession:
        def execute(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            raise RuntimeError("database unavailable")

    response = readyz(BrokenSession())  # type: ignore[arg-type]

    assert response.status_code == 503
    assert response.body == b'{"status":"error","database":"error"}'


def test_unhandled_request_exception_is_logged() -> None:
    async def failing_call_next(_request):  # type: ignore[no-untyped-def]
        raise RuntimeError("diagnostic failure")

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    client_host = env_value("REPOFORGE_TRUSTED_PROXY_IPS").split(",", 1)[0].strip().split("/", 1)[0]
    server_host = env_value("REPOFORGE_TLS_SUBJECT_ALT_NAMES").split(",", 1)[0].strip()
    request = Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": "/auth/__diagnostic_failure",
            "raw_path": b"/auth/__diagnostic_failure",
            "query_string": b"",
            "headers": [(b"x-request-id", b"diagnostic-request")],
            "client": (client_host, 0),
            "server": (server_host, int(env_value("REPOFORGE_HTTPS_PORT"))),
        },
        receive,
    )

    records: list[tuple[str, tuple[object, ...]]] = []

    def record_exception(message: str, *args: object, **_kwargs: object) -> None:
        records.append((message, args))

    with patch.object(request_logger, "exception", side_effect=record_exception):
        response = asyncio.run(log_request_failures(request, failing_call_next))

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "diagnostic-request"
    assert records
    assert "Unhandled request exception" in records[0][0]
    assert "diagnostic-request" in str(records[0][1])
