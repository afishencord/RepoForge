"""FastAPI entrypoint for RepoForge."""

from __future__ import annotations

from datetime import datetime, timezone
from ipaddress import ip_address, ip_network
import json
import logging
from pathlib import Path
import re
import secrets
import shutil
import traceback
from typing import Any, Optional

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from starlette.datastructures import MutableHeaders
from starlette.middleware.sessions import SessionMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import PROJECT_ROOT, settings
from app.database import SessionLocal, get_db, init_db
from app.logging_config import configure_logging
from app.models import (
    Artifact,
    AuthProvider,
    BuildJob,
    Bundle,
    GPGKey,
    RepoSource,
    Setting,
    UploadedRPM,
    User,
    format_datetime,
    json_dump,
    parse_lines,
    utc_now,
)
from app.services.auth_service import (
    VALID_ROLES,
    authenticate_ldap,
    authenticate_local,
    authenticate_oidc_callback,
    enabled_provider,
    get_provider,
    has_role,
    hash_password,
    normalize_role,
    oidc_authorization_url,
    provider_config,
    set_role_mappings,
    upsert_provider,
)
from app.services.builder_deployment import (
    RHEL_CDN_NOTICE,
    BuilderValidationError,
    builder_mode_options,
    normalize_builder_mode,
    validate_builder_mode_for_sources,
    worker_config_from_settings,
)
from app.services.build_orchestrator import BuildOrchestrator, BuildRequest
from app.services.checksum_service import sha256_file
from app.services.dnf_service import RepoSource as DnfRepoSource
from app.services.dnf_service import validate_repo_source
from app.services.gpg_service import GpgKeyRequest, export_public_key, generate_key, list_secret_fingerprints, write_key_params
from app.services.repo_sync_service import RepoSyncPlan
from app.services.remote_worker_service import RemoteWorkerClient
from app.services.rpm_service import inspect_rpm
from app.services.runner import CommandError, SubprocessRunner
from app.services.system_tools import REQUIRED_TOOLS, check_system_tools


configure_logging()
logger = logging.getLogger("repoforge.app")
request_logger = logging.getLogger("repoforge.requests")
templates = Jinja2Templates(directory=str(PROJECT_ROOT / "app" / "templates"))
app = FastAPI(title="RepoForge", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "app" / "static")), name="static")


@app.on_event("startup")
def startup() -> None:
    init_db()
    logger.info(
        "RepoForge application startup complete database_dialect=%s session_https_only=%s log_level=%s",
        settings.database_url.split(":", 1)[0] or "unknown",
        settings.session_https_only,
        settings.log_level,
    )


PUBLIC_PATHS = {"/healthz", "/readyz", "/login", "/logout"}
PUBLIC_PREFIXES = ("/static/", "/auth/")


@app.middleware("http")
async def require_authenticated_session(request: Request, call_next):  # type: ignore[no-untyped-def]
    request.state.current_user = None
    path = request.url.path
    public = path in PUBLIC_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PREFIXES)
    user_id = request.session.get("user_id")
    if user_id:
        db = SessionLocal()
        try:
            user = db.get(User, int(user_id))
            if user and user.is_active:
                request.state.current_user = user
        finally:
            db.close()
    if not public and request.state.current_user is None:
        return redirect(f"/login?next={url_quote(str(request.url.path))}")
    return await call_next(request)


def trusted_proxy_source(client_host: str) -> bool:
    allowed = {value.strip() for value in settings.trusted_proxy_ips.split(",") if value.strip()}
    if "*" in allowed:
        return True
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


def request_log_context(request: Request, request_id: str) -> dict[str, object]:
    client_host = request.client.host if request.client else ""
    return {
        "method": request.method,
        "path": request.url.path,
        "request_id": request_id,
        "client": client_host,
        "trusted_proxy": trusted_proxy_source(client_host) if client_host else False,
        "forwarded_proto": request.headers.get("x-forwarded-proto", ""),
        "forwarded_for": request.headers.get("x-forwarded-for", ""),
    }


class RequestDiagnosticsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        request_id = request.headers.get("x-request-id") or secrets.token_urlsafe(16)
        status_code: int | None = None
        response_started = False

        async def send_with_diagnostics(message: dict[str, Any]) -> None:
            nonlocal response_started, status_code
            if message["type"] == "http.response.start":
                response_started = True
                status_code = int(message["status"])
                MutableHeaders(scope=message).setdefault("X-Request-ID", request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_diagnostics)
        except Exception:
            request_logger.exception("Unhandled request exception: %s", request_log_context(request, request_id))
            if response_started:
                raise
            response = PlainTextResponse("Internal Server Error", status_code=500, headers={"X-Request-ID": request_id})
            await response(scope, receive, send)
            return

        if status_code and status_code >= 500:
            context = request_log_context(request, request_id)
            context["status_code"] = status_code
            request_logger.error("Request returned server error: %s", context)


app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax", https_only=settings.session_https_only)
app.add_middleware(RequestDiagnosticsMiddleware)


def render(request: Request, template_name: str, context: Optional[dict[str, Any]] = None, *, status_code: int = 200):
    data = dict(context or {})
    data.setdefault("request", request)
    data.setdefault("system_status", quick_system_status())
    data.setdefault("flash_messages", flash_messages(request))
    data.setdefault("current_user", getattr(request.state, "current_user", None))
    data.setdefault("csrf_token", csrf_token(request))
    data.setdefault("can", lambda role: has_role(getattr(request.state, "current_user", None), role))
    return templates.TemplateResponse(request, template_name, data, status_code=status_code)


def auth_provider_enabled(db: Session, provider_type: str) -> bool:
    try:
        return enabled_provider(db, provider_type) is not None
    except Exception:
        logger.exception("Unable to load auth provider configuration for provider_type=%s", provider_type)
        return False


def validate_login_page_dependencies(request: Request, db: Session) -> None:
    db.execute(text("SELECT 1")).scalar_one()
    db.scalars(select(User).limit(1)).first()
    providers = list(
        db.scalars(
            select(AuthProvider)
            .where(AuthProvider.provider_type.in_(("ldap", "adfs_oidc")))
            .order_by(AuthProvider.id.asc())
            .limit(2)
        ).all()
    )
    request.state.current_user = None
    response = templates.TemplateResponse(
        request,
        "auth/login.html",
        {
            "request": request,
            "system_status": quick_system_status(),
            "flash_messages": [],
            "current_user": None,
            "csrf_token": "readyz",
            "can": lambda role: False,
            "next_url": "/",
            "ldap_enabled": any(provider.provider_type == "ldap" and provider.enabled for provider in providers),
            "adfs_enabled": any(provider.provider_type == "adfs_oidc" and provider.enabled for provider in providers),
        },
    )
    response.body


def redirect(url: str, *, notice: Optional[str] = None, level: str = "info") -> RedirectResponse:
    if notice:
        joiner = "&" if "?" in url else "?"
        url = f"{url}{joiner}notice={url_quote(notice)}&level={url_quote(level)}"
    return RedirectResponse(url, status_code=303)


def flash_messages(request: Request) -> list[dict[str, str]]:
    notice = request.query_params.get("notice")
    if not notice:
        return []
    return [{"text": notice, "level": request.query_params.get("level", "info")}]


def quick_system_status() -> str:
    missing = [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]
    return "healthy" if not missing else "degraded"


def url_quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return str(token)


def establish_session(request: Request, user: User) -> None:
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["csrf_token"] = secrets.token_urlsafe(32)


def safe_next(value: str) -> str:
    if not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


async def require_csrf(request: Request) -> None:
    form = await request.form()
    submitted = str(form.get("csrf_token") or "")
    expected = str(request.session.get("csrf_token") or "")
    if not expected or not secrets.compare_digest(submitted, expected):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


def require_role(role: str):
    def dependency(request: Request) -> User:
        user = getattr(request.state, "current_user", None)
        if not has_role(user, role):
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return user

    return dependency


require_admin = require_role("admin")
require_operator = require_role("operator")
require_user = require_role("user")


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-").lower()
    return slug or "item"


def safe_filename(value: str) -> str:
    name = Path(value).name.strip()
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name)
    return name or "upload.rpm"


def query_all(db: Session, model: type[Any], order_by: Any) -> list[Any]:
    return list(db.scalars(select(model).order_by(order_by)).all())


def filter_records(records: list[Any], q: Optional[str], fields: tuple[str, ...]) -> list[Any]:
    if not q:
        return records
    needle = q.lower()
    filtered: list[Any] = []
    for record in records:
        haystack = " ".join(str(getattr(record, field, "") or "") for field in fields).lower()
        if needle in haystack:
            filtered.append(record)
    return filtered


@app.get("/login")
def login_page(request: Request, next: Optional[str] = None, db: Session = Depends(get_db)):
    if getattr(request.state, "current_user", None):
        return redirect(next or "/")
    return render(
        request,
        "auth/login.html",
        {
            "next_url": next or "/",
            "ldap_enabled": auth_provider_enabled(db, "ldap"),
            "adfs_enabled": auth_provider_enabled(db, "adfs_oidc"),
        },
    )


@app.post("/login", dependencies=[Depends(require_csrf)])
async def login_local(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    next_url = safe_next(str(form.get("next") or "/"))
    username = str(form.get("username") or "")
    password = str(form.get("password") or "")
    user = authenticate_local(db, username, password)
    if not user:
        return redirect(f"/login?next={url_quote(next_url)}", notice="Invalid username or password", level="error")
    establish_session(request, user)
    return redirect(next_url, notice="Signed in", level="success")


@app.post("/login/ldap", dependencies=[Depends(require_csrf)])
async def login_ldap(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    next_url = safe_next(str(form.get("next") or "/"))
    try:
        user = authenticate_ldap(db, str(form.get("username") or ""), str(form.get("password") or ""))
    except Exception as exc:
        return redirect(f"/login?next={url_quote(next_url)}", notice=f"LDAP login failed: {exc}", level="error")
    if not user:
        return redirect(f"/login?next={url_quote(next_url)}", notice="Invalid LDAP username or password", level="error")
    establish_session(request, user)
    return redirect(next_url, notice="Signed in with LDAP", level="success")


@app.get("/auth/adfs/login")
def adfs_login(request: Request, next: Optional[str] = None, db: Session = Depends(get_db)):
    state = secrets.token_urlsafe(24)
    request.session["oidc_state"] = state
    request.session["oidc_next"] = safe_next(next or "/")
    redirect_uri = str(request.url_for("adfs_callback"))
    try:
        auth_url = oidc_authorization_url(db, redirect_uri, state)
    except Exception as exc:
        return redirect("/login", notice=f"ADFS is not ready: {exc}", level="error")
    return RedirectResponse(auth_url, status_code=303)


@app.get("/auth/adfs/callback")
def adfs_callback(request: Request, code: Optional[str] = None, state: Optional[str] = None, db: Session = Depends(get_db)):
    expected_state = request.session.pop("oidc_state", "")
    next_url = safe_next(str(request.session.pop("oidc_next", "/")))
    if not code or not state or not expected_state or not secrets.compare_digest(state, expected_state):
        return redirect("/login", notice="Invalid ADFS sign-in response", level="error")
    try:
        user = authenticate_oidc_callback(db, code, str(request.url_for("adfs_callback")))
    except Exception as exc:
        return redirect("/login", notice=f"ADFS sign-in failed: {exc}", level="error")
    establish_session(request, user)
    return redirect(next_url, notice="Signed in with ADFS", level="success")


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return redirect("/login", notice="Signed out", level="success")


@app.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    bundle_count = db.scalar(select(func.count(Bundle.id))) or 0
    completed_count = db.scalar(select(func.count(BuildJob.id)).where(BuildJob.status == "completed")) or 0
    failed_count = db.scalar(select(func.count(BuildJob.id)).where(BuildJob.status == "failed")) or 0
    source_count = db.scalar(select(func.count(RepoSource.id))) or 0
    artifact_count = db.scalar(select(func.count(Artifact.id))) or 0
    recent_jobs = list(db.scalars(select(BuildJob).order_by(BuildJob.id.desc()).limit(8)).all())
    recent_artifacts = list(db.scalars(select(Artifact).order_by(Artifact.created_at.desc()).limit(6)).all())
    return render(
        request,
        "dashboard.html",
        {
            "metrics": [
                {"label": "Bundles", "value": bundle_count, "detail": "configured"},
                {"label": "Completed Builds", "value": completed_count, "detail": "ISO outputs"},
                {"label": "Failed Builds", "value": failed_count, "detail": "needs attention"},
                {"label": "Repo Sources", "value": source_count, "detail": f"{artifact_count} artifacts"},
            ],
            "recent_jobs": recent_jobs,
            "recent_artifacts": recent_artifacts,
            "tool_checks": tool_view_models(limit=8),
        },
    )


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz(request: Request, db: Session = Depends(get_db)):
    try:
        validate_login_page_dependencies(request, db)
    except Exception:
        logger.exception("RepoForge readiness check failed")
        return JSONResponse({"status": "error", "database": "error", "login_page": "error"}, status_code=503)
    return {"status": "ok", "database": "ok", "login_page": "ok"}


@app.get("/bundles")
def bundles(request: Request, q: Optional[str] = None, db: Session = Depends(get_db)):
    records = query_all(db, Bundle, Bundle.created_at.desc())
    return render(request, "bundles/list.html", {"bundles": filter_records(records, q, ("name", "target_os", "architecture", "status")), "q": q or ""})


@app.get("/bundles/new")
def new_bundle(request: Request, db: Session = Depends(get_db), _current: User = Depends(require_operator)):
    return render(request, "bundles/form.html", bundle_form_context(db))


@app.post("/bundles", dependencies=[Depends(require_csrf)])
async def create_bundle(request: Request, db: Session = Depends(get_db), _current: User = Depends(require_operator)):
    form = await request.form()
    bundle = Bundle()
    apply_bundle_form(bundle, form, db)
    db.add(bundle)
    db.commit()
    db.refresh(bundle)
    return redirect(f"/bundles/{bundle.id}", notice="Bundle created", level="success")


@app.get("/bundles/{bundle_id}")
def bundle_detail(request: Request, bundle_id: int, tab: Optional[str] = None, db: Session = Depends(get_db)):
    bundle = get_or_404(db, Bundle, bundle_id)
    latest_build = db.scalars(select(BuildJob).where(BuildJob.bundle_id == bundle.id).order_by(BuildJob.id.desc()).limit(1)).first()
    manifest_text = ""
    if bundle.manifest_path and Path(bundle.manifest_path).exists():
        manifest_text = Path(bundle.manifest_path).read_text(encoding="utf-8")
    return render(
        request,
        "bundles/detail.html",
        {
            "bundle": bundle,
            "latest_build": latest_build,
            "repo_sources": bundle.repo_sources,
            "rpm_packages": bundle.uploaded_rpms,
            "build_jobs": list(reversed(bundle.build_jobs[-8:])),
            "artifacts": list(reversed(bundle.artifacts[-8:])),
            "package_names": bundle.package_names,
            "manifest_text": manifest_text or "No manifest generated yet.",
            "active_tab": normalize_tab(tab),
            "rhel_cdn_notice": RHEL_CDN_NOTICE,
        },
    )


@app.get("/bundles/{bundle_id}/edit")
def edit_bundle(request: Request, bundle_id: int, db: Session = Depends(get_db), _current: User = Depends(require_operator)):
    bundle = get_or_404(db, Bundle, bundle_id)
    return render(request, "bundles/form.html", bundle_form_context(db, bundle))


@app.post("/bundles/{bundle_id}", dependencies=[Depends(require_csrf)])
async def update_bundle(request: Request, bundle_id: int, db: Session = Depends(get_db), _current: User = Depends(require_operator)):
    form = await request.form()
    bundle = get_or_404(db, Bundle, bundle_id)
    apply_bundle_form(bundle, form, db)
    db.commit()
    return redirect(f"/bundles/{bundle.id}", notice="Bundle updated", level="success")


@app.get("/bundles/{bundle_id}/sources")
def bundle_sources(request: Request, bundle_id: int, db: Session = Depends(get_db), _current: User = Depends(require_operator)):
    bundle = get_or_404(db, Bundle, bundle_id)
    return render(request, "bundles/sources.html", bundle_form_context(db, bundle))


@app.post("/bundles/{bundle_id}/sources", dependencies=[Depends(require_csrf)])
async def update_bundle_sources(request: Request, bundle_id: int, db: Session = Depends(get_db), _current: User = Depends(require_operator)):
    form = await request.form()
    bundle = get_or_404(db, Bundle, bundle_id)
    ids = [int(value) for value in form.getlist("repo_source_ids") if str(value).isdigit()]
    bundle.repo_sources = list(db.scalars(select(RepoSource).where(RepoSource.id.in_(ids))).all()) if ids else []
    db.commit()
    return redirect(f"/bundles/{bundle.id}?tab=sources", notice="Repository source selection updated", level="success")


@app.post("/bundles/{bundle_id}/build", dependencies=[Depends(require_csrf)])
def start_bundle_build(bundle_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_user: User = Depends(require_operator)):
    bundle = get_or_404(db, Bundle, bundle_id)
    builder_mode = normalize_builder_mode(bundle.builder_mode)
    worker_config = worker_config_from_settings(settings_map(db))
    try:
        validate_builder_mode_for_sources(
            builder_mode,
            bundle.repo_sources,
            worker_config=worker_config,
            runner=SubprocessRunner(default_timeout=60),
            remote_entitlement_check=remote_entitlement_check,
        )
    except BuilderValidationError as exc:
        return redirect(f"/bundles/{bundle.id}", notice=str(exc), level="error")

    job = BuildJob(
        bundle_id=bundle.id,
        name=f"{safe_slug(bundle.name)}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
        builder_mode=builder_mode,
        worker=worker_config.display_name if builder_mode == "remote-rhel-worker" else builder_mode,
        created_by=current_user.username,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    log_path = settings.workspace_root / str(bundle.id) / "logs" / f"build-{job.id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    job.log_path = str(log_path)
    db.commit()
    append_log(log_path, f"Queued build job {job.id} for bundle {bundle.name}")
    background_tasks.add_task(execute_build_job, job.id)
    return redirect(f"/build-jobs/{job.id}/logs", notice=f"Build job {job.id} queued", level="success")


@app.get("/repo-sources")
def repo_sources(request: Request, q: Optional[str] = None, db: Session = Depends(get_db), _current: User = Depends(require_operator)):
    records = query_all(db, RepoSource, RepoSource.created_at.desc())
    return render(
        request,
        "repo_sources/list.html",
        {"repo_sources": filter_records(records, q, ("name", "source_type", "base_url", "repo_id", "status")), "q": q or ""},
    )


@app.get("/repo-sources/new")
def new_repo_source(request: Request, _current: User = Depends(require_operator)):
    return render(request, "repo_sources/form.html", repo_source_form_context())


@app.post("/repo-sources", dependencies=[Depends(require_csrf)])
async def create_repo_source(request: Request, db: Session = Depends(get_db), _current: User = Depends(require_operator)):
    form = await request.form()
    source = RepoSource()
    apply_repo_source_form(source, form)
    db.add(source)
    db.commit()
    db.refresh(source)
    return redirect("/repo-sources", notice="Repository source created", level="success")


@app.get("/repo-sources/{source_id}/edit")
def edit_repo_source(request: Request, source_id: int, db: Session = Depends(get_db), _current: User = Depends(require_operator)):
    source = get_or_404(db, RepoSource, source_id)
    return render(request, "repo_sources/form.html", repo_source_form_context(source))


@app.post("/repo-sources/{source_id}", dependencies=[Depends(require_csrf)])
async def update_repo_source(request: Request, source_id: int, db: Session = Depends(get_db), _current: User = Depends(require_operator)):
    form = await request.form()
    source = get_or_404(db, RepoSource, source_id)
    apply_repo_source_form(source, form)
    db.commit()
    return redirect("/repo-sources", notice="Repository source updated", level="success")


@app.post("/repo-sources/{source_id}/sync", dependencies=[Depends(require_csrf)])
def sync_repo_source(source_id: int, db: Session = Depends(get_db), _current: User = Depends(require_operator)):
    source = get_or_404(db, RepoSource, source_id)
    runner = SubprocessRunner(default_timeout=60)
    try:
        validate_repo_source(to_dnf_repo_source(source), runner=runner)
    except Exception as exc:
        source.status = "error"
        db.commit()
        return redirect("/repo-sources", notice=f"Repo validation failed: {exc}", level="error")
    source.status = "active"
    source.last_sync_at = utc_now()
    db.commit()
    return redirect("/repo-sources", notice="Repository source validated", level="success")


@app.get("/custom-rpms")
def custom_rpms(request: Request, db: Session = Depends(get_db), _current: User = Depends(require_operator)):
    rpm_packages = list(db.scalars(select(UploadedRPM).order_by(UploadedRPM.uploaded_at.desc())).all())
    return render(request, "custom_rpms.html", {"rpm_packages": rpm_packages})


@app.get("/custom-rpms/upload")
def upload_rpms_form(request: Request, db: Session = Depends(get_db), _current: User = Depends(require_operator)):
    bundles = query_all(db, Bundle, Bundle.name.asc())
    return render(request, "custom_rpms_upload.html", {"bundles": bundles})


@app.post("/custom-rpms/upload", dependencies=[Depends(require_csrf)])
async def upload_rpm(
    request: Request,
    bundle_id: int = Form(...),
    resolve_dependencies: bool = Form(False),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _current: User = Depends(require_operator),
):
    bundle = get_or_404(db, Bundle, bundle_id)
    original_name = safe_filename(file.filename or "")
    if not original_name.endswith(".rpm"):
        raise HTTPException(status_code=400, detail="Only .rpm uploads are accepted")
    stored_name = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{original_name}"
    output_dir = settings.upload_root / str(bundle.id)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / stored_name
    size = 0
    with output_path.open("wb") as handle:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > settings.max_upload_bytes:
                output_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Upload exceeds configured size limit")
            handle.write(chunk)
    rpm = UploadedRPM(
        bundle_id=bundle.id,
        filename=stored_name,
        original_filename=original_name,
        storage_path=str(output_path),
        name=original_name.removesuffix(".rpm"),
        version="-",
        release="-",
        architecture="-",
        sha256=sha256_file(output_path),
        size_bytes=size,
        resolve_dependencies=resolve_dependencies,
    )
    if shutil.which("rpm"):
        try:
            metadata = inspect_rpm(output_path)
        except Exception as exc:
            output_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=f"RPM metadata validation failed: {exc}") from exc
        rpm.name = metadata.name
        rpm.version = metadata.version
        rpm.release = metadata.release
        rpm.architecture = metadata.architecture
        rpm.summary = metadata.summary
        rpm.sha256 = metadata.sha256
        rpm.requires_json = json_dump(metadata.requires)
        rpm.provides_json = json_dump(metadata.provides)
        rpm.dependency_status = "pending" if resolve_dependencies else "not_checked"
    else:
        rpm.summary = "RPM metadata inspection pending; rpm tool is not installed on this builder."
        rpm.dependency_status = "not_checked"
    db.add(rpm)
    db.commit()
    return redirect("/custom-rpms", notice="RPM uploaded", level="success")


@app.post("/custom-rpms/{rpm_id}/toggle-dependencies", dependencies=[Depends(require_csrf)])
def toggle_rpm_dependencies(rpm_id: int, db: Session = Depends(get_db), _current: User = Depends(require_operator)):
    rpm = get_or_404(db, UploadedRPM, rpm_id)
    rpm.resolve_dependencies = not rpm.resolve_dependencies
    rpm.dependency_status = "pending" if rpm.resolve_dependencies else "not_checked"
    db.commit()
    return redirect("/custom-rpms", notice="Dependency resolution setting updated", level="success")


@app.get("/keys")
def keys(request: Request, db: Session = Depends(get_db)):
    gpg_keys = list(db.scalars(select(GPGKey).order_by(GPGKey.created_at.desc())).all())
    return render(request, "keys.html", {"gpg_keys": gpg_keys})


@app.get("/keys/new")
def new_key(request: Request, _current: User = Depends(require_operator)):
    return render(request, "keys_form.html")


@app.post("/keys", dependencies=[Depends(require_csrf)])
async def create_key(request: Request, db: Session = Depends(get_db), _current: User = Depends(require_operator)):
    form = await request.form()
    if not shutil.which("gpg"):
        return redirect("/keys", notice="gpg is not installed on this builder", level="error")
    name = str(form.get("name") or "RepoForge Custom Repo")
    email = str(form.get("email") or "repoforge@local")
    expire_date = str(form.get("expire_date") or "2y")
    key_dir = settings.key_root / f"{safe_slug(name)}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    gpg_home = key_dir / "gnupg"
    gpg_home.mkdir(parents=True, exist_ok=True)
    gpg_home.chmod(0o700)
    params_path = write_key_params(GpgKeyRequest(name_real=name, name_email=email, expire_date=expire_date), key_dir / "keyparams")
    runner = SubprocessRunner(default_timeout=120)
    try:
        before = set(list_secret_fingerprints(gpg_home=gpg_home, runner=runner))
        generate_key(params_path, gpg_home=gpg_home, runner=runner)
        after = set(list_secret_fingerprints(gpg_home=gpg_home, runner=runner))
        fingerprint = next(iter(after - before), next(iter(after), ""))
        if not fingerprint:
            raise RuntimeError("gpg did not report a generated fingerprint")
        public_key_path = key_dir / "RPM-GPG-KEY-repoforge-custom"
        export_public_key(fingerprint, public_key_path, gpg_home=gpg_home, runner=runner)
    except Exception as exc:
        return redirect("/keys", notice=f"GPG key generation failed: {exc}", level="error")
    key = GPGKey(
        name=name,
        email=email,
        fingerprint=fingerprint,
        public_key_path=str(public_key_path),
        private_key_path=str(gpg_home),
        associated_repo="repoforge-custom",
        status="active",
    )
    db.add(key)
    db.commit()
    return redirect("/keys", notice="GPG key generated", level="success")


@app.get("/keys/{key_id}/public")
def download_public_key(key_id: int, db: Session = Depends(get_db)):
    key = get_or_404(db, GPGKey, key_id)
    path = Path(key.public_key_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Public key file is missing")
    return FileResponse(path, media_type="application/pgp-keys", filename=path.name)


@app.get("/build-jobs")
def build_jobs(request: Request, q: Optional[str] = None, db: Session = Depends(get_db)):
    records = list(db.scalars(select(BuildJob).order_by(BuildJob.id.desc())).all())
    return render(request, "build_jobs/list.html", {"build_jobs": filter_records(records, q, ("name", "status", "stage")), "q": q or ""})


@app.get("/build-jobs/{job_id}")
def build_job_detail(request: Request, job_id: int, db: Session = Depends(get_db)):
    job = get_or_404(db, BuildJob, job_id)
    return render(request, "build_jobs/detail.html", {"job": job, "stages": build_stage_view(job)})


@app.get("/build-jobs/{job_id}/logs")
def build_job_logs(request: Request, job_id: int, db: Session = Depends(get_db)):
    job = get_or_404(db, BuildJob, job_id)
    return render(
        request,
        "build_jobs/logs.html",
        {"job": job, "log_lines": read_log_lines(job.log_path), "refresh_url": f"/build-jobs/{job.id}/logs/raw"},
    )


@app.get("/build-jobs/{job_id}/logs/raw")
def build_job_logs_raw(job_id: int, db: Session = Depends(get_db)):
    job = get_or_404(db, BuildJob, job_id)
    path = Path(job.log_path)
    text = path.read_text(encoding="utf-8") if path.exists() else "No log output available.\n"
    return PlainTextResponse(text)


@app.get("/artifacts")
def artifacts(request: Request, db: Session = Depends(get_db)):
    records = list(db.scalars(select(Artifact).order_by(Artifact.created_at.desc())).all())
    return render(request, "artifacts.html", {"artifacts": records})


@app.get("/artifacts/{artifact_id}")
def artifact_detail(request: Request, artifact_id: int, db: Session = Depends(get_db)):
    artifact = get_or_404(db, Artifact, artifact_id)
    manifest_text = ""
    if artifact.bundle and artifact.bundle.manifest_path and Path(artifact.bundle.manifest_path).exists():
        manifest_text = Path(artifact.bundle.manifest_path).read_text(encoding="utf-8")
    return render(request, "artifact_detail.html", {"artifact": artifact, "manifest_text": manifest_text})


@app.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: int, db: Session = Depends(get_db)):
    artifact = get_or_404(db, Artifact, artifact_id)
    path = Path(artifact.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact file is missing")
    return FileResponse(path, media_type="application/octet-stream", filename=path.name)


@app.get("/artifacts/{artifact_id}/manifest")
def download_manifest(artifact_id: int, db: Session = Depends(get_db)):
    artifact = get_or_404(db, Artifact, artifact_id)
    path_value = artifact.bundle.manifest_path if artifact.bundle else None
    path = Path(path_value) if path_value else None
    if not path or not path.exists():
        raise HTTPException(status_code=404, detail="Manifest file is missing")
    return FileResponse(path, media_type="application/json", filename=path.name)


@app.get("/system")
def system(request: Request, _current: User = Depends(require_operator)):
    return render(request, "system.html", {"tool_checks": tool_view_models(), "storage_stats": storage_stats()})


@app.get("/settings")
def settings_page(request: Request, db: Session = Depends(get_db), _current: User = Depends(require_operator)):
    return render(request, "settings.html", {"settings": settings_map(db), "iso_tool_options": ["xorriso", "genisoimage"]})


@app.post("/settings", dependencies=[Depends(require_csrf)])
async def update_settings(request: Request, db: Session = Depends(get_db), _current: User = Depends(require_admin)):
    form = await request.form()
    for key in (
        "workspace_root",
        "artifact_root",
        "iso_tool",
        "max_concurrent_builds",
        "retain_failed_workspaces",
        "require_signed_metadata",
        "remote_worker_name",
        "remote_worker_host",
        "remote_worker_username",
        "remote_worker_port",
        "remote_worker_key_path",
        "remote_worker_root",
        "remote_worker_app_path",
    ):
        value = "true" if key in form and key.startswith(("retain_", "require_")) else str(form.get(key) or "")
        setting = db.get(Setting, key) or Setting(key=key)
        setting.value = value
        db.merge(setting)
    db.commit()
    return redirect("/settings", notice="Settings saved", level="success")


@app.get("/admin/users")
def admin_users(request: Request, db: Session = Depends(get_db), _current: User = Depends(require_admin)):
    users = list(db.scalars(select(User).order_by(User.username.asc())).all())
    return render(request, "admin/users.html", {"users": users, "role_options": VALID_ROLES})


@app.post("/admin/users", dependencies=[Depends(require_csrf)])
async def create_user(request: Request, db: Session = Depends(get_db), _current: User = Depends(require_admin)):
    form = await request.form()
    username = str(form.get("username") or "").strip()
    password = str(form.get("password") or "")
    if not username or not password:
        return redirect("/admin/users", notice="Username and password are required", level="error")
    if db.scalar(select(User).where(User.username == username)):
        return redirect("/admin/users", notice="Username already exists", level="error")
    user = User(
        username=username,
        email=str(form.get("email") or ""),
        display_name=str(form.get("display_name") or username),
        password_hash=hash_password(password),
        role=normalize_role(str(form.get("role") or "user")),
        auth_source="local",
        is_active="is_active" in form,
    )
    db.add(user)
    db.commit()
    return redirect("/admin/users", notice="User created", level="success")


@app.post("/admin/users/{user_id}", dependencies=[Depends(require_csrf)])
async def update_user(user_id: int, request: Request, db: Session = Depends(get_db), _current: User = Depends(require_admin)):
    form = await request.form()
    user = get_or_404(db, User, user_id)
    user.email = str(form.get("email") or "")
    user.display_name = str(form.get("display_name") or user.username)
    user.role = normalize_role(str(form.get("role") or user.role))
    user.is_active = "is_active" in form
    password = str(form.get("password") or "")
    if password:
        user.password_hash = hash_password(password)
        user.auth_source = "local"
    db.commit()
    return redirect("/admin/users", notice="User updated", level="success")


@app.get("/admin/auth")
def admin_auth(request: Request, db: Session = Depends(get_db), _current: User = Depends(require_admin)):
    ldap_provider = get_provider(db, "ldap")
    adfs_provider = get_provider(db, "adfs_oidc")
    return render(
        request,
        "admin/auth.html",
        {
            "ldap_provider": ldap_provider,
            "ldap_config": provider_config(ldap_provider) if ldap_provider else {},
            "adfs_provider": adfs_provider,
            "adfs_config": provider_config(adfs_provider) if adfs_provider else {},
            "role_options": VALID_ROLES,
        },
    )


@app.post("/admin/auth/ldap", dependencies=[Depends(require_csrf)])
async def update_ldap_provider(request: Request, db: Session = Depends(get_db), _current: User = Depends(require_admin)):
    form = await request.form()
    config = {
        "server_uri": str(form.get("server_uri") or ""),
        "verify_tls": "verify_tls" in form,
        "bind_dn": str(form.get("bind_dn") or ""),
        "user_base_dn": str(form.get("user_base_dn") or ""),
        "user_filter": str(form.get("user_filter") or "(uid={username})"),
        "user_dn_template": str(form.get("user_dn_template") or ""),
        "username_attribute": str(form.get("username_attribute") or "uid"),
        "email_attribute": str(form.get("email_attribute") or "mail"),
        "display_name_attribute": str(form.get("display_name_attribute") or "cn"),
        "group_attribute": str(form.get("group_attribute") or "memberOf"),
    }
    provider = upsert_provider(
        db,
        "ldap",
        "LDAP",
        "enabled" in form,
        config,
        {"bind_password": str(form.get("bind_password") or "")},
    )
    set_role_mappings(db, provider, role_mapping_rows(form))
    return redirect("/admin/auth", notice="LDAP settings saved", level="success")


@app.post("/admin/auth/adfs", dependencies=[Depends(require_csrf)])
async def update_adfs_provider(request: Request, db: Session = Depends(get_db), _current: User = Depends(require_admin)):
    form = await request.form()
    config = {
        "authorization_endpoint": str(form.get("authorization_endpoint") or ""),
        "token_endpoint": str(form.get("token_endpoint") or ""),
        "userinfo_endpoint": str(form.get("userinfo_endpoint") or ""),
        "jwks_uri": str(form.get("jwks_uri") or ""),
        "issuer": str(form.get("issuer") or ""),
        "client_id": str(form.get("client_id") or ""),
        "scopes": str(form.get("scopes") or "openid email profile"),
        "username_claim": str(form.get("username_claim") or "upn"),
        "email_claim": str(form.get("email_claim") or "email"),
        "display_name_claim": str(form.get("display_name_claim") or "name"),
        "groups_claim": str(form.get("groups_claim") or "groups"),
    }
    provider = upsert_provider(
        db,
        "adfs_oidc",
        "Microsoft ADFS",
        "enabled" in form,
        config,
        {"client_secret": str(form.get("client_secret") or "")},
    )
    set_role_mappings(db, provider, role_mapping_rows(form))
    return redirect("/admin/auth", notice="ADFS settings saved", level="success")


def bundle_form_context(db: Session, bundle: Optional[Bundle] = None) -> dict[str, Any]:
    sources = query_all(db, RepoSource, RepoSource.name.asc())
    context: dict[str, Any] = {
        "available_repo_sources": sources,
        "selected_repo_source_ids": [source.id for source in bundle.repo_sources] if bundle else [],
        "status_options": ["draft", "ready", "building", "failed", "completed", "archived"],
        "os_options": ["rhel", "fedora", "rocky", "almalinux", "centos-stream"],
        "arch_options": ["x86_64", "aarch64", "ppc64le", "s390x"],
        "signing_options": ["metadata", "packages_and_metadata", "disabled"],
        "builder_mode_options": builder_mode_options(),
        "rhel_cdn_notice": RHEL_CDN_NOTICE,
    }
    if bundle:
        context["bundle"] = bundle
        context["form_action"] = f"/bundles/{bundle.id}"
    return context


def repo_source_form_context(source: Optional[RepoSource] = None) -> dict[str, Any]:
    context: dict[str, Any] = {
        "source_type_options": ["redhat9", "fedora44", "docker_ce", "docker_ee", "python", "generic_yum", "custom"],
        "sync_policy_options": ["manual", "scheduled", "disabled"],
    }
    if source:
        context["repo_source"] = source
        context["form_action"] = f"/repo-sources/{source.id}"
    return context


def apply_bundle_form(bundle: Bundle, form: Any, db: Session) -> None:
    bundle.name = required_text(form, "name")
    bundle.status = str(form.get("status") or "draft")
    bundle.target_os = str(form.get("target_os") or "rhel")
    bundle.target_os_version = str(form.get("target_os_version") or "")
    bundle.architecture = str(form.get("architecture") or "x86_64")
    bundle.signing_mode = str(form.get("signing_mode") or "metadata")
    bundle.description = str(form.get("description") or "")
    bundle.package_include = str(form.get("package_include") or "")
    bundle.package_exclude = str(form.get("package_exclude") or "")
    bundle.resolve_dependencies = "resolve_dependencies" in form
    bundle.resolve_custom_rpm_dependencies = "resolve_custom_rpm_dependencies" in form
    bundle.iso_label = str(form.get("iso_label") or "REPOFORGE")[:32]
    bundle.artifact_prefix = str(form.get("artifact_prefix") or "")
    bundle.include_validation_scripts = "include_validation_scripts" in form
    bundle.include_install_scripts = "include_install_scripts" in form
    bundle.builder_mode = normalize_builder_mode(str(form.get("builder_mode") or "container"))
    ids = [int(value) for value in form.getlist("repo_source_ids") if str(value).isdigit()]
    bundle.repo_sources = list(db.scalars(select(RepoSource).where(RepoSource.id.in_(ids))).all()) if ids else []


def apply_repo_source_form(source: RepoSource, form: Any) -> None:
    source.name = required_text(form, "name")
    source.source_type = str(form.get("source_type") or "generic_yum")
    source.base_url = str(form.get("base_url") or "")
    source.repo_id = str(form.get("repo_id") or safe_slug(source.name))
    source.gpg_key_url = str(form.get("gpg_key_url") or "")
    source.sync_policy = str(form.get("sync_policy") or "manual")
    source.enabled = "enabled" in form
    source.verify_ssl = "verify_ssl" in form
    source.gpgcheck = "gpgcheck" in form
    source.repo_gpgcheck = "repo_gpgcheck" in form
    source.requires_auth = "requires_auth" in form
    source.notes = str(form.get("notes") or "")
    source.subscription_required = source.source_type.startswith("redhat")


def role_mapping_rows(form: Any) -> list[tuple[str, str]]:
    groups = [str(value or "") for value in form.getlist("mapping_group")]
    roles = [str(value or "user") for value in form.getlist("mapping_role")]
    return list(zip(groups, roles))


def required_text(form: Any, key: str) -> str:
    value = str(form.get(key) or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail=f"{key} is required")
    return value


def normalize_tab(tab: Optional[str]) -> str:
    mapping = {"custom-rpms": "custom_rpms"}
    return mapping.get(tab or "overview", tab or "overview")


def get_or_404(db: Session, model: type[Any], item_id: int) -> Any:
    item = db.get(model, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail=f"{model.__name__} not found")
    return item


def remote_entitlement_check(worker_config: Any, repo_ids: list[str]) -> None:
    try:
        RemoteWorkerClient(worker_config).validate_entitlement(repo_ids)
    except BuilderValidationError:
        raise
    except Exception as exc:
        raise BuilderValidationError(f"Remote RHEL worker validation failed: {exc}") from exc


def tool_view_models(limit: Optional[int] = None) -> list[dict[str, str]]:
    checks = check_system_tools()
    rows = [
        {
            "name": check.name,
            "status": "healthy" if check.present else "missing",
            "version": check.version or "-",
            "path": check.path or "-",
            "required": "yes" if check.required else "no",
        }
        for check in checks
    ]
    return rows[:limit] if limit else rows


def storage_stats() -> list[dict[str, str]]:
    return [
        {"label": "Uploads", "value": directory_summary(settings.upload_root)},
        {"label": "Workspaces", "value": directory_summary(settings.workspace_root)},
        {"label": "Artifacts", "value": directory_summary(settings.artifact_root)},
        {"label": "Keys", "value": directory_summary(settings.key_root)},
    ]


def directory_summary(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    files = [item for item in path.rglob("*") if item.is_file()]
    size = sum(item.stat().st_size for item in files)
    return f"{len(files)} files / {human_bytes(size)}"


def human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


def settings_map(db: Session) -> dict[str, Any]:
    saved = {setting.key: setting.value for setting in db.scalars(select(Setting)).all()}
    return {
        "workspace_root": saved.get("workspace_root", str(settings.workspace_root)),
        "artifact_root": saved.get("artifact_root", str(settings.artifact_root)),
        "iso_tool": saved.get("iso_tool", "xorriso"),
        "max_concurrent_builds": saved.get("max_concurrent_builds", "1"),
        "retain_failed_workspaces": saved.get("retain_failed_workspaces", "true") == "true",
        "require_signed_metadata": saved.get("require_signed_metadata", "true") == "true",
        "remote_worker_name": saved.get("remote_worker_name", "rhel-worker"),
        "remote_worker_host": saved.get("remote_worker_host", ""),
        "remote_worker_username": saved.get("remote_worker_username", ""),
        "remote_worker_port": saved.get("remote_worker_port", "22"),
        "remote_worker_key_path": saved.get("remote_worker_key_path", ""),
        "remote_worker_root": saved.get("remote_worker_root", "/var/lib/repoforge-worker"),
        "remote_worker_app_path": saved.get("remote_worker_app_path", "/opt/repoforge"),
    }


def to_dnf_repo_source(source: RepoSource) -> DnfRepoSource:
    return DnfRepoSource(
        name=source.name,
        repo_id=source.repo_id or safe_slug(source.name),
        baseurl=source.base_url or None,
        mirrorlist=source.mirrorlist or None,
        gpgkey_url=source.gpg_key_url or None,
        enabled=source.enabled,
        gpgcheck=source.gpgcheck,
        repo_gpgcheck=source.repo_gpgcheck,
        username=source.username or None,
        password=None,
    )


def execute_build_job(job_id: int) -> None:
    db = SessionLocal()
    try:
        job = db.get(BuildJob, job_id)
        if not job:
            return
        bundle = job.bundle
        log_path = Path(job.log_path)

        def log(message: str) -> None:
            append_log(log_path, message)

        job.status = "running"
        job.stage = "preparing workspace"
        job.started_at = utc_now()
        db.commit()
        log(f"Starting build job {job.id}")

        workspace = settings.workspace_root / str(bundle.id)
        artifact_dir = settings.artifact_root / str(bundle.id) / str(job.id)
        packages = [{"name": package, "include_dependencies": bundle.resolve_dependencies} for package in bundle.package_names]
        package_names = [item["name"] for item in packages]
        repo_sources = [source for source in bundle.repo_sources if source.enabled and source.source_type != "python"]
        plans = [
            RepoSyncPlan(
                repo_source=to_dnf_repo_source(source),
                mode="curated_packages" if package_names else "metadata_only",
                dest_dir=workspace / "repos" / "vendor" / safe_slug(source.repo_id or source.name),
                packages=package_names,
            )
            for source in repo_sources
        ]
        latest_key = db.scalars(select(GPGKey).where(GPGKey.status == "active").order_by(GPGKey.created_at.desc()).limit(1)).first()
        signing_key = latest_key if latest_key and bundle.signing_mode != "disabled" else None
        uploaded_rpms = [uploaded_rpm_manifest(rpm, bundle) for rpm in bundle.uploaded_rpms]
        job.stage = "building"
        db.commit()

        worker_config = worker_config_from_settings(settings_map(db))
        build_request = BuildRequest(
            bundle_id=str(bundle.id),
            bundle_name=bundle.name,
            target_os=f"{bundle.target_os}{bundle.target_os_version}",
            architecture=bundle.architecture,
            workspace_dir=workspace,
            artifact_dir=artifact_dir,
            job_id=str(job.id),
            builder_mode=normalize_builder_mode(job.builder_mode or bundle.builder_mode),
            worker=job.worker or "",
            repo_sync_plans=plans,
            repo_sources=[repo_source_manifest(source) for source in repo_sources],
            packages=packages,
            uploaded_rpms=uploaded_rpms,
            gpg_fingerprint=signing_key.fingerprint if signing_key else None,
            gpg_private_key_path=Path(signing_key.private_key_path) if signing_key else None,
            fail_on_missing_tools=settings.require_system_tools_for_build,
            fail_on_unresolved_dependencies=bundle.fail_on_unresolved_dependencies,
            iso_label=bundle.iso_label or "REPOFORGE",
            include_install_scripts=bundle.include_install_scripts,
            include_validation_scripts=bundle.include_validation_scripts,
        )
        if build_request.builder_mode == "remote-rhel-worker":
            result = RemoteWorkerClient(worker_config).run_build(build_request, log=log)
        else:
            result = BuildOrchestrator(log=log).build(build_request)
        if not result.iso_path:
            raise RuntimeError("build completed without an ISO path")
        artifact = Artifact(
            bundle_id=bundle.id,
            build_job_id=job.id,
            artifact_type="iso",
            name=result.iso_path.name,
            path=str(result.iso_path),
            checksum=sha256_file(result.iso_path),
            size_bytes=result.iso_path.stat().st_size,
        )
        db.add(artifact)
        bundle.status = "completed"
        bundle.last_built_at = utc_now()
        bundle.iso_artifact_path = str(result.iso_path)
        bundle.manifest_path = str(result.manifest_path)
        bundle.checksum_path = str(result.checksum_path)
        job.status = "completed"
        job.stage = "completed"
        job.finished_at = utc_now()
        job.warnings_json = json_dump(result.warnings)
        db.commit()
        log(f"Build completed: {result.iso_path}")
    except Exception as exc:
        if "job" in locals() and job:
            job.status = "failed"
            job.stage = "failed"
            job.error_message = str(exc)
            job.finished_at = utc_now()
            if job.bundle:
                job.bundle.status = "failed"
            db.commit()
            append_log(Path(job.log_path), f"Build failed: {exc}")
            append_log(Path(job.log_path), traceback.format_exc())
    finally:
        db.close()


def uploaded_rpm_manifest(rpm: UploadedRPM, bundle: Bundle) -> dict[str, Any]:
    return {
        "id": rpm.id,
        "filename": rpm.filename,
        "original_filename": rpm.original_filename,
        "storage_path": rpm.storage_path,
        "name": rpm.name,
        "version": rpm.version,
        "release": rpm.release,
        "architecture": rpm.architecture,
        "summary": rpm.summary,
        "sha256": rpm.sha256,
        "requires": rpm.requires,
        "provides": rpm.provides,
        "resolve_dependencies": rpm.resolve_dependencies or bundle.resolve_custom_rpm_dependencies,
    }


def repo_source_manifest(source: RepoSource) -> dict[str, Any]:
    return {
        "name": source.name,
        "type": source.source_type,
        "repo_id": source.repo_id,
        "base_url": source.base_url,
        "enabled": source.enabled,
        "gpgcheck": source.gpgcheck,
    }


def append_log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with path.open("a", encoding="utf-8") as handle:
        for line in str(message).splitlines() or [""]:
            handle.write(f"[{timestamp}] {line}\n")


def read_log_lines(path_value: str) -> list[str]:
    path = Path(path_value)
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def build_stage_view(job: BuildJob) -> list[dict[str, str]]:
    stages = ["queued", "preparing workspace", "building", "completed"]
    current = job.stage
    rows: list[dict[str, str]] = []
    for stage in stages:
        if job.status == "failed":
            status = "failed" if stage == current or stage == "building" else "completed"
        elif job.status == "completed":
            status = "completed"
        elif stage == current:
            status = "running"
        elif stages.index(stage) < stages.index(current) if current in stages else False:
            status = "completed"
        else:
            status = "pending"
        rows.append({"name": stage.title(), "status": status, "detail": ""})
    return rows
