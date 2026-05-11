from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import Base, SessionLocal
from app.main import app
from app.models import AuthProvider, RoleMapping, User
from app.services.auth_service import (
    DEFAULT_ADMIN_PASSWORD,
    DEFAULT_ADMIN_USERNAME,
    ExternalProfile,
    authenticate_oidc_callback,
    hash_password,
    has_role,
    provision_external_user,
    seed_default_admin,
    upsert_provider,
    verify_password,
)


def memory_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)()


def csrf_from(response) -> str:  # type: ignore[no-untyped-def]
    match = re.search('name="csrf_token" value="([^"]+)"', response.text)
    assert match
    return match.group(1)


def login(client: TestClient, username: str = DEFAULT_ADMIN_USERNAME, password: str = DEFAULT_ADMIN_PASSWORD) -> None:
    response = client.get("/login")
    token = csrf_from(response)
    result = client.post("/login", data={"csrf_token": token, "username": username, "password": password, "next": "/"})
    assert result.status_code == 303


def ensure_local_user(username: str, role: str) -> None:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username))
        if not user:
            user = User(username=username, display_name=username, role=role, password_hash=hash_password("password"), is_active=True)
            db.add(user)
        user.role = role
        user.is_active = True
        user.password_hash = hash_password("password")
        db.commit()


def test_password_hashing_round_trips() -> None:
    password_hash = hash_password("secret")

    assert verify_password("secret", password_hash)
    assert not verify_password("wrong", password_hash)
    assert "secret" not in password_hash


def test_default_admin_seed_is_idempotent() -> None:
    db = memory_session()

    first = seed_default_admin(db)
    first.password_hash = "custom"
    db.commit()
    second = seed_default_admin(db)

    assert first.id == second.id
    assert second.username == DEFAULT_ADMIN_USERNAME
    assert second.role == "admin"
    assert second.password_hash == "custom"


def test_role_hierarchy() -> None:
    assert has_role(User(username="a", role="admin"), "operator")
    assert has_role(User(username="o", role="operator"), "user")
    assert not has_role(User(username="u", role="user"), "operator")


def test_external_group_mapping_uses_highest_role() -> None:
    db = memory_session()
    provider = AuthProvider(provider_type="ldap", name="LDAP", enabled=True)
    db.add(provider)
    db.flush()
    db.add_all(
        [
            RoleMapping(provider_id=provider.id, external_group="repo-users", role="user"),
            RoleMapping(provider_id=provider.id, external_group="repo-ops", role="operator"),
            RoleMapping(provider_id=provider.id, external_group="repo-admins", role="admin"),
        ]
    )
    db.commit()
    db.refresh(provider)

    user = provision_external_user(
        db,
        ExternalProfile(
            provider=provider,
            subject="cn=Sam",
            username="sam",
            email="sam@example.test",
            groups=("repo-users", "repo-admins"),
        ),
    )

    assert user.role == "admin"
    assert user.auth_source == "ldap"


def test_routes_require_login_and_default_admin_can_login() -> None:
    with TestClient(app, follow_redirects=False) as client:
        anonymous = client.get("/")
        assert anonymous.status_code == 303
        assert anonymous.headers["location"].startswith("/login")

        login(client)
        dashboard = client.get("/")
        assert dashboard.status_code == 200
        assert "Dashboard" in dashboard.text


def test_user_cannot_access_operator_routes_and_post_requires_csrf() -> None:
    ensure_local_user("route-user", "user")
    with TestClient(app, follow_redirects=False) as client:
        login(client, "route-user", "password")

        forbidden = client.get("/repo-sources")
        assert forbidden.status_code == 403

        missing_csrf = client.post("/settings", data={"workspace_root": "storage/workspaces"})
        assert missing_csrf.status_code == 403


def test_mutating_build_and_sync_get_routes_are_removed() -> None:
    with TestClient(app, follow_redirects=False) as client:
        login(client)

        assert client.get("/bundles/1/build").status_code == 405
        assert client.get("/repo-sources/1/sync").status_code == 405


def test_oidc_callback_provisions_user_from_mocked_claims(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    db = memory_session()
    provider = upsert_provider(
        db,
        "adfs_oidc",
        "Microsoft ADFS",
        True,
        {
            "token_endpoint": "https://adfs.example.test/token",
            "userinfo_endpoint": "https://adfs.example.test/userinfo",
            "client_id": "client",
            "username_claim": "upn",
            "email_claim": "email",
            "display_name_claim": "name",
            "groups_claim": "groups",
        },
        {"client_secret": "secret"},
    )
    set_claims = {"sub": "abc", "upn": "ada@example.test", "email": "ada@example.test", "name": "Ada", "groups": ["adfs-ops"]}
    db.add(RoleMapping(provider_id=provider.id, external_group="adfs-ops", role="operator"))
    db.commit()

    monkeypatch.setattr(
        "app.services.auth_service.httpx.post",
        lambda *args, **kwargs: SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"access_token": "token"}),
    )
    monkeypatch.setattr(
        "app.services.auth_service.httpx.get",
        lambda *args, **kwargs: SimpleNamespace(raise_for_status=lambda: None, json=lambda: set_claims),
    )

    user = authenticate_oidc_callback(db, "code", "https://repoforge.test/auth/adfs/callback")

    assert user.username == "ada@example.test"
    assert user.role == "operator"
