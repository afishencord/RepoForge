"""Command line entrypoint for the RepoForge executable."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

import uvicorn

from app import server
from app.config import settings
from app.database import run_migrations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="repoforge", description="Run and maintain RepoForge.")
    parser.add_argument("--version", action="version", version="RepoForge 0.1.0")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("serve", help="start the RepoForge web service")
    subparsers.add_parser("migrate", help="run database migrations and seed the default admin")

    asgi = subparsers.add_parser("_serve-asgi", help=argparse.SUPPRESS)
    asgi.add_argument("asgi_app")
    asgi.add_argument("--host", default=settings.server_host)
    asgi.add_argument("--port", type=int, required=True)
    asgi.add_argument("--ssl-certfile", type=Path)
    asgi.add_argument("--ssl-keyfile", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "serve"

    if command == "serve":
        return server.main()
    if command == "migrate":
        run_migrations()
        print("RepoForge database is migrated and seeded.", flush=True)
        return 0
    if command == "_serve-asgi":
        uvicorn_kwargs = {
            "port": args.port,
            "ssl_certfile": str(args.ssl_certfile) if args.ssl_certfile else None,
            "ssl_keyfile": str(args.ssl_keyfile) if args.ssl_keyfile else None,
        }
        if args.host:
            uvicorn_kwargs["host"] = args.host
        uvicorn.run(
            args.asgi_app,
            **uvicorn_kwargs,
        )
        return 0

    parser.error(f"unknown command: {command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
