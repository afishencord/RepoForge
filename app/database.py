"""SQLAlchemy setup for RepoForge."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import PROJECT_ROOT, settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)


def init_db() -> None:
    settings.ensure_directories()
    if settings.auto_migrate:
        run_migrations()
    else:
        seed_database()


def alembic_config():
    from alembic.config import Config

    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


def run_migrations() -> None:
    from alembic import command

    settings.ensure_directories()
    config = alembic_config()
    if _schema_exists_without_alembic_version():
        from . import models  # noqa: F401

        Base.metadata.create_all(bind=engine)
        _ensure_sqlite_schema()
        command.stamp(config, "head")
    else:
        command.upgrade(config, "head")
    seed_database()


def seed_database() -> None:
    from . import models  # noqa: F401
    from .services.auth_service import seed_default_admin

    with SessionLocal() as db:
        seed_default_admin(db)


def _schema_exists_without_alembic_version() -> bool:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    return bool(tables - {"alembic_version"}) and "alembic_version" not in tables


def _ensure_sqlite_schema() -> None:
    """Apply additive SQLite upgrades for MVP databases created before migrations."""

    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    existing = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in inspector.get_table_names()
    }
    statements: list[str] = []
    if "bundles" in existing and "builder_mode" not in existing["bundles"]:
        statements.append("ALTER TABLE bundles ADD COLUMN builder_mode VARCHAR(40) NOT NULL DEFAULT 'container'")
    if "build_jobs" in existing and "builder_mode" not in existing["build_jobs"]:
        statements.append("ALTER TABLE build_jobs ADD COLUMN builder_mode VARCHAR(40) NOT NULL DEFAULT 'container'")
    if "build_jobs" in existing and "worker" not in existing["build_jobs"]:
        statements.append("ALTER TABLE build_jobs ADD COLUMN worker VARCHAR(160) NOT NULL DEFAULT ''")

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
