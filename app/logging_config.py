"""Logging setup for RepoForge processes."""

from __future__ import annotations

import logging
import sys

from app.config import normalize_log_level, settings


def configure_logging(level: str | None = None) -> str:
    level_name = normalize_log_level(level or settings.log_level)
    numeric_level = getattr(logging, level_name)
    formatter = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    root_logger = logging.getLogger()
    repoforge_logger = logging.getLogger("repoforge")

    if not root_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)

    root_logger.setLevel(numeric_level)
    if not repoforge_logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(formatter)
        repoforge_logger.addHandler(handler)
    repoforge_logger.propagate = False
    repoforge_logger.setLevel(numeric_level)
    for logger_name in ("repoforge", "uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(logger_name).setLevel(numeric_level)
    return level_name
