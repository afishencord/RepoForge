from __future__ import annotations

from app import cli
from app.config import DEFAULT_STORAGE_ROOT
from tests.env_values import env_value


def test_cli_defaults_to_serve(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(cli.server, "main", lambda: 23)

    assert cli.main([]) == 23


def test_cli_serve_dispatches_to_server(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(cli.server, "main", lambda: 42)

    assert cli.main(["serve"]) == 42


def test_cli_migrate_runs_database_migration(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    called = []
    monkeypatch.setattr(cli, "run_migrations", lambda: called.append("migrated"))

    assert cli.main(["migrate"]) == 0
    assert called == ["migrated"]


def test_hidden_asgi_command_invokes_uvicorn(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    host = env_value("REPOFORGE_HOST")

    assert cli.main(["_serve-asgi", "app.main:app", "--host", host, "--port", "8443"]) == 0

    assert calls == [(("app.main:app",), {"host": host, "port": 8443, "ssl_certfile": None, "ssl_keyfile": None})]


def test_rhel_storage_default_is_var_lib_repoforge() -> None:
    assert DEFAULT_STORAGE_ROOT == "/var/lib/repoforge"
