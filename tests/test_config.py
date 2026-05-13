from __future__ import annotations

import pytest

from app.config import normalize_log_level


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("INFO", "INFO"),
        ("WARN", "WARNING"),
        ("WARNING", "WARNING"),
        ("ERROR", "ERROR"),
        ("debug", "INFO"),
        ("", "INFO"),
        (None, "INFO"),
    ],
)
def test_normalize_log_level(value: str | None, expected: str) -> None:
    assert normalize_log_level(value) == expected
