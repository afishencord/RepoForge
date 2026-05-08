"""Safe subprocess execution primitives used by builder services."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
import subprocess
from typing import Callable, Iterable, Mapping, Sequence


DEFAULT_TIMEOUT_SECONDS = 3600
DEFAULT_SECRET_TOKENS = ("password", "passwd", "token", "secret", "apikey", "api_key")
MAX_ERROR_DIAGNOSTIC_CHARS = 1000


class CommandError(RuntimeError):
    """Raised when a command exits unsuccessfully or times out."""

    def __init__(self, result: "CommandResult"):
        self.result = result
        super().__init__(result.summary)


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    masked_args: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    @property
    def summary(self) -> str:
        command = " ".join(self.masked_args or self.args)
        if self.timed_out:
            return f"Command timed out: {command}"
        summary = f"Command failed with exit code {self.returncode}: {command}"
        diagnostic = (self.stderr or self.stdout).strip()
        if diagnostic:
            diagnostic_tail = diagnostic[-MAX_ERROR_DIAGNOSTIC_CHARS:]
            return f"{summary}\n{diagnostic_tail}"
        return summary


def mask_value(value: object, secrets: Iterable[str] = ()) -> str:
    """Mask sensitive text for logs while preserving non-secret diagnostics."""

    text = str(value)
    masked = text
    for secret in secrets:
        if secret:
            masked = masked.replace(secret, "***")

    lower = masked.lower()
    for token in DEFAULT_SECRET_TOKENS:
        if token in lower:
            if "=" in masked:
                key, _, _ = masked.partition("=")
                return f"{key}=***"
            return "***"
    return masked


def mask_args(args: Sequence[object], secrets: Iterable[str] = ()) -> tuple[str, ...]:
    return tuple(mask_value(arg, secrets) for arg in args)


def require_relative_path(path: Path | str, base_dir: Path | str) -> Path:
    """Resolve a path and ensure it remains inside base_dir."""

    base = Path(base_dir).expanduser().resolve()
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"path escapes base directory: {path}") from exc
    return resolved


class SubprocessRunner:
    """Small wrapper around subprocess.run with safe defaults."""

    def __init__(self, default_timeout: int = DEFAULT_TIMEOUT_SECONDS):
        self.default_timeout = default_timeout

    def run(
        self,
        args: Sequence[object],
        *,
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        timeout: int | None = None,
        secrets: Iterable[str] = (),
        check: bool = True,
        log: Callable[[str], None] | None = None,
    ) -> CommandResult:
        if isinstance(args, (str, bytes)) or not args:
            raise ValueError("args must be a non-empty sequence; shell strings are not allowed")

        normalized_args = tuple(str(arg) for arg in args)
        masked = mask_args(normalized_args, secrets)
        if log:
            log("$ " + " ".join(masked))

        merged_env = os.environ.copy()
        if env:
            merged_env.update(env)

        try:
            completed = subprocess.run(
                normalized_args,
                cwd=str(cwd) if cwd is not None else None,
                env=merged_env,
                text=True,
                capture_output=True,
                timeout=timeout if timeout is not None else self.default_timeout,
                check=False,
            )
            result = CommandResult(
                args=normalized_args,
                masked_args=masked,
                returncode=completed.returncode,
                stdout=mask_value(completed.stdout, secrets),
                stderr=mask_value(completed.stderr, secrets),
            )
        except subprocess.TimeoutExpired as exc:
            result = CommandResult(
                args=normalized_args,
                masked_args=masked,
                returncode=124,
                stdout=mask_value(exc.stdout or "", secrets),
                stderr=mask_value(exc.stderr or "", secrets),
                timed_out=True,
            )

        if log:
            if result.stdout:
                log(result.stdout.rstrip())
            if result.stderr:
                log(result.stderr.rstrip())

        if check and not result.ok:
            raise CommandError(result)
        return result


default_runner = SubprocessRunner()
