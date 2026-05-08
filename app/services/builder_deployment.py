"""Builder mode selection and entitlement validation."""

from __future__ import annotations

from dataclasses import dataclass
import shutil
from typing import Any, Callable, Iterable

from .runner import CommandError, CommandResult, SubprocessRunner, default_runner


BUILDER_MODES = ("container", "local-rhel", "remote-rhel-worker", "external-mirror")
DEFAULT_BUILDER_MODE = "container"
RHEL_CDN_NOTICE = (
    "Red Hat CDN repositories require an entitled RHEL builder host or an internal mirror. "
    "Container-only builds can assemble public and generic repositories, but cannot sync "
    "RHEL CDN content unless valid entitlement is available inside the builder environment."
)


class BuilderValidationError(RuntimeError):
    """Raised when a bundle cannot run with the selected builder mode."""


@dataclass(frozen=True)
class RemoteWorkerConfig:
    name: str = "rhel-worker"
    host: str = ""
    username: str = ""
    port: int = 22
    key_path: str = ""
    remote_root: str = "/var/lib/repoforge-worker"
    app_path: str = "/opt/repoforge"

    @property
    def display_name(self) -> str:
        if self.name:
            return self.name
        if self.host:
            return self.host
        return "remote-rhel-worker"

    @property
    def is_configured(self) -> bool:
        return bool(self.host and self.username and self.remote_root and self.app_path)


def normalize_builder_mode(value: str | None) -> str:
    mode = (value or DEFAULT_BUILDER_MODE).strip()
    return mode if mode in BUILDER_MODES else DEFAULT_BUILDER_MODE


def worker_config_from_settings(values: dict[str, Any]) -> RemoteWorkerConfig:
    return RemoteWorkerConfig(
        name=str(values.get("remote_worker_name") or "rhel-worker"),
        host=str(values.get("remote_worker_host") or ""),
        username=str(values.get("remote_worker_username") or ""),
        port=_int_value(values.get("remote_worker_port"), 22),
        key_path=str(values.get("remote_worker_key_path") or ""),
        remote_root=str(values.get("remote_worker_root") or "/var/lib/repoforge-worker"),
        app_path=str(values.get("remote_worker_app_path") or "/opt/repoforge"),
    )


def builder_mode_options() -> list[dict[str, str]]:
    return [
        {"value": "container", "label": "Container"},
        {"value": "local-rhel", "label": "Local entitled RHEL host"},
        {"value": "remote-rhel-worker", "label": "Remote entitled RHEL worker"},
        {"value": "external-mirror", "label": "External mirror"},
    ]


def validate_builder_mode_for_sources(
    builder_mode: str,
    sources: Iterable[Any],
    *,
    worker_config: RemoteWorkerConfig | None = None,
    runner: SubprocessRunner = default_runner,
    remote_entitlement_check: Callable[[RemoteWorkerConfig, list[str]], None] | None = None,
    command_exists: Callable[[str], str | None] = shutil.which,
) -> None:
    mode = normalize_builder_mode(builder_mode)
    enabled_sources = [source for source in sources if _truthy_attr(source, "enabled", True) and _attr(source, "source_type") != "python"]
    if mode == "remote-rhel-worker" and (not worker_config or not worker_config.is_configured):
        raise BuilderValidationError(
            "Remote RHEL worker mode requires a configured worker host, username, app path, and remote work root in Settings."
        )

    redhat_sources = [source for source in enabled_sources if is_redhat_cdn_source(source)]
    if not redhat_sources:
        return

    repo_ids = [repo_id for repo_id in (source_repo_id(source) for source in redhat_sources) if repo_id]

    if mode == "external-mirror":
        missing_urls = [source for source in redhat_sources if not source_has_external_url(source)]
        if missing_urls:
            names = ", ".join(source_name(source) for source in missing_urls)
            raise BuilderValidationError(
                "External mirror mode requires each Red Hat source to use a base URL or mirrorlist. "
                f"Missing mirror endpoint: {names}."
            )
        return

    if mode == "remote-rhel-worker":
        if remote_entitlement_check:
            remote_entitlement_check(worker_config, repo_ids)
        return

    check_local_rhel_entitlement(repo_ids, mode=mode, runner=runner, command_exists=command_exists)


def check_local_rhel_entitlement(
    repo_ids: list[str],
    *,
    mode: str = "local-rhel",
    runner: SubprocessRunner = default_runner,
    command_exists: Callable[[str], str | None] = shutil.which,
) -> None:
    if command_exists("subscription-manager") is None:
        raise BuilderValidationError(
            f"{mode} mode needs subscription-manager available in the builder environment for Red Hat CDN sources."
        )
    if command_exists("dnf") is None:
        raise BuilderValidationError(f"{mode} mode needs dnf available in the builder environment.")

    try:
        runner.run(["subscription-manager", "identity"], timeout=45)
        runner.run(["subscription-manager", "repos", "--list-enabled"], timeout=45)
        repolist = runner.run(["dnf", "repolist", "--enabled"], timeout=45)
    except CommandError as exc:
        raise BuilderValidationError(f"Red Hat entitlement validation failed: {exc}") from exc
    except OSError as exc:
        raise BuilderValidationError(f"Red Hat entitlement validation could not run: {exc}") from exc

    enabled_text = f"{repolist.stdout}\n{repolist.stderr}"
    missing = [repo_id for repo_id in repo_ids if repo_id and repo_id not in enabled_text]
    if missing:
        raise BuilderValidationError(
            "Red Hat entitlement is present, but these requested repo IDs are not enabled: " + ", ".join(missing)
        )


def is_redhat_cdn_source(source: Any) -> bool:
    source_type = str(_attr(source, "source_type") or "").lower()
    return bool(_truthy_attr(source, "subscription_required", False) or source_type.startswith("redhat"))


def source_has_external_url(source: Any) -> bool:
    return bool(str(_attr(source, "base_url") or "").strip() or str(_attr(source, "mirrorlist") or "").strip())


def source_repo_id(source: Any) -> str:
    return str(_attr(source, "repo_id") or "").strip()


def source_name(source: Any) -> str:
    return str(_attr(source, "name") or source_repo_id(source) or "unnamed source")


def _attr(source: Any, key: str) -> Any:
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)


def _truthy_attr(source: Any, key: str, default: bool) -> bool:
    value = _attr(source, key)
    return default if value is None else bool(value)


def _int_value(value: Any, default: int) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default
