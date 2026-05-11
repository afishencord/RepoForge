"""Authentication, session, and provider helpers for RepoForge."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AuthProvider, ExternalIdentity, RoleMapping, User, json_dump, utc_now


VALID_ROLES = ("user", "operator", "admin")
ROLE_RANK = {"user": 1, "operator": 2, "admin": 3}
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123!"
PASSWORD_ITERATIONS = 260_000


@dataclass(frozen=True)
class ExternalProfile:
    provider: AuthProvider
    subject: str
    username: str
    email: str = ""
    display_name: str = ""
    groups: tuple[str, ...] = ()
    claims: dict[str, Any] | None = None


def normalize_role(role: str | None) -> str:
    value = (role or "user").strip().lower()
    return value if value in VALID_ROLES else "user"


def has_role(user: User | None, required_role: str) -> bool:
    if not user or user.is_active is False:
        return False
    return ROLE_RANK.get(normalize_role(user.role), 0) >= ROLE_RANK[normalize_role(required_role)]


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations, salt_value, digest_value = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_value.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_value.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
    except Exception:
        return False
    return hmac.compare_digest(actual, expected)


def seed_default_admin(db: Session) -> User:
    user = db.scalar(select(User).where(User.username == DEFAULT_ADMIN_USERNAME))
    if user:
        return user
    user = User(
        username=DEFAULT_ADMIN_USERNAME,
        email="admin@local",
        display_name="RepoForge Admin",
        password_hash=hash_password(DEFAULT_ADMIN_PASSWORD),
        role="admin",
        auth_source="local",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_local(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username.strip()))
    if not user or not user.is_active or not user.password_hash:
        return None
    if not verify_password(password, user.password_hash):
        return None
    user.last_login_at = utc_now()
    db.commit()
    db.refresh(user)
    return user


def get_provider(db: Session, provider_type: str) -> AuthProvider | None:
    return db.scalar(select(AuthProvider).where(AuthProvider.provider_type == provider_type).order_by(AuthProvider.id.asc()))


def enabled_provider(db: Session, provider_type: str) -> AuthProvider | None:
    provider = get_provider(db, provider_type)
    return provider if provider and provider.enabled else None


def provider_config(provider: AuthProvider) -> dict[str, Any]:
    config = _json_dict(provider.config_json)
    secrets_config = decrypt_secret_json(provider.secret_config_json)
    config.update({key: value for key, value in secrets_config.items() if value})
    return config


def upsert_provider(
    db: Session,
    provider_type: str,
    name: str,
    enabled: bool,
    config: dict[str, Any],
    secret_config: dict[str, Any] | None = None,
) -> AuthProvider:
    provider = get_provider(db, provider_type) or AuthProvider(provider_type=provider_type, name=name)
    provider.name = name
    provider.enabled = enabled
    provider.config_json = json_dump(config)
    if secret_config:
        existing = decrypt_secret_json(provider.secret_config_json)
        merged = {**existing, **{key: value for key, value in secret_config.items() if value}}
        provider.secret_config_json = encrypt_secret_json(merged)
    db.add(provider)
    db.commit()
    db.refresh(provider)
    return provider


def set_role_mappings(db: Session, provider: AuthProvider, mappings: list[tuple[str, str]]) -> None:
    for mapping in list(provider.role_mappings):
        db.delete(mapping)
    for external_group, role in mappings:
        group = external_group.strip()
        if group:
            db.add(RoleMapping(provider_id=provider.id, external_group=group, role=normalize_role(role)))
    db.commit()


def resolve_role(provider: AuthProvider, groups: list[str] | tuple[str, ...]) -> str:
    group_values = {group.lower() for group in groups if group}
    best = "user"
    for mapping in provider.role_mappings:
        if mapping.external_group.lower() in group_values and ROLE_RANK[normalize_role(mapping.role)] > ROLE_RANK[best]:
            best = normalize_role(mapping.role)
    return best


def provision_external_user(db: Session, profile: ExternalProfile) -> User:
    identity = db.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.provider_id == profile.provider.id,
            ExternalIdentity.subject == profile.subject,
        )
    )
    db.expire(profile.provider, ["role_mappings"])
    role = resolve_role(profile.provider, profile.groups)
    if identity:
        user = identity.user
    else:
        user = _find_user_for_profile(db, profile)
        if not user:
            user = User(
                username=_available_username(db, profile.username or profile.email or profile.subject),
                email=profile.email or "",
                display_name=profile.display_name or profile.username,
                role=role,
                auth_source=profile.provider.provider_type,
                is_active=True,
            )
            db.add(user)
            db.flush()
        identity = ExternalIdentity(provider_id=profile.provider.id, user_id=user.id, subject=profile.subject)
        db.add(identity)
    user.email = profile.email or user.email
    user.display_name = profile.display_name or user.display_name
    user.role = role
    user.auth_source = profile.provider.provider_type
    user.last_login_at = utc_now()
    identity.username = profile.username
    identity.email = profile.email
    identity.claims_json = json_dump(profile.claims or {})
    db.commit()
    db.refresh(user)
    return user


def authenticate_ldap(db: Session, username: str, password: str) -> User | None:
    provider = enabled_provider(db, "ldap")
    if not provider or not username.strip() or not password:
        return None
    try:
        from ldap3 import ALL, Connection, Server, Tls
    except ImportError as exc:
        raise RuntimeError("LDAP authentication requires the ldap3 package to be installed") from exc

    config = provider_config(provider)
    server_uri = str(config.get("server_uri") or "")
    if not server_uri:
        return None
    verify_tls = bool(config.get("verify_tls", True))
    tls = Tls(validate=ssl_cert_required(verify_tls))
    server = Server(server_uri, get_info=ALL, use_ssl=server_uri.lower().startswith("ldaps://"), tls=tls)
    user_dn = ""
    attributes: dict[str, Any] = {}
    groups: list[str] = []
    bind_dn = str(config.get("bind_dn") or "")
    bind_password = str(config.get("bind_password") or "")
    user_filter = str(config.get("user_filter") or "(uid={username})").replace("{username}", username.strip())
    user_base_dn = str(config.get("user_base_dn") or "")
    username_attr = str(config.get("username_attribute") or "uid")
    email_attr = str(config.get("email_attribute") or "mail")
    display_attr = str(config.get("display_name_attribute") or "cn")
    group_attr = str(config.get("group_attribute") or "memberOf")
    user_dn_template = str(config.get("user_dn_template") or "")

    if bind_dn and user_base_dn:
        with Connection(server, user=bind_dn, password=bind_password, auto_bind=True) as connection:
            connection.search(user_base_dn, user_filter, attributes=[username_attr, email_attr, display_attr, group_attr])
            if not connection.entries:
                return None
            entry = connection.entries[0]
            user_dn = entry.entry_dn
            attributes = entry.entry_attributes_as_dict
    elif user_dn_template:
        user_dn = user_dn_template.replace("{username}", username.strip())
    else:
        user_dn = username.strip()

    if not Connection(server, user=user_dn, password=password, auto_bind=True).bound:
        return None

    groups = _value_list(attributes.get(group_attr))
    profile = ExternalProfile(
        provider=provider,
        subject=user_dn,
        username=_first_value(attributes.get(username_attr)) or username.strip(),
        email=_first_value(attributes.get(email_attr)),
        display_name=_first_value(attributes.get(display_attr)) or username.strip(),
        groups=tuple(groups),
        claims=attributes,
    )
    return provision_external_user(db, profile)


def oidc_authorization_url(db: Session, redirect_uri: str, state: str) -> str:
    provider = enabled_provider(db, "adfs_oidc")
    if not provider:
        raise RuntimeError("ADFS OIDC is not enabled")
    config = provider_config(provider)
    auth_endpoint = str(config.get("authorization_endpoint") or "")
    if not auth_endpoint:
        raise RuntimeError("ADFS OIDC authorization endpoint is required")
    query = urlencode(
        {
            "client_id": config.get("client_id") or "",
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": config.get("scopes") or "openid email profile",
            "state": state,
        }
    )
    return f"{auth_endpoint}?{query}"


def authenticate_oidc_callback(db: Session, code: str, redirect_uri: str) -> User:
    provider = enabled_provider(db, "adfs_oidc")
    if not provider:
        raise RuntimeError("ADFS OIDC is not enabled")
    config = provider_config(provider)
    token_endpoint = str(config.get("token_endpoint") or "")
    if not token_endpoint:
        raise RuntimeError("ADFS OIDC token endpoint is required")
    token_response = httpx.post(
        token_endpoint,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": config.get("client_id") or "",
            "client_secret": config.get("client_secret") or "",
        },
        timeout=15,
    )
    token_response.raise_for_status()
    token_data = token_response.json()
    claims = _claims_from_token_response(token_data, config)
    userinfo_endpoint = str(config.get("userinfo_endpoint") or "")
    if userinfo_endpoint and token_data.get("access_token"):
        userinfo_response = httpx.get(userinfo_endpoint, headers={"Authorization": f"Bearer {token_data['access_token']}"}, timeout=15)
        userinfo_response.raise_for_status()
        claims.update(userinfo_response.json())

    username_claim = str(config.get("username_claim") or "upn")
    email_claim = str(config.get("email_claim") or "email")
    display_claim = str(config.get("display_name_claim") or "name")
    groups_claim = str(config.get("groups_claim") or "groups")
    subject = str(claims.get("sub") or claims.get(username_claim) or claims.get(email_claim) or "")
    if not subject:
        raise RuntimeError("ADFS OIDC response did not include a usable subject")
    profile = ExternalProfile(
        provider=provider,
        subject=subject,
        username=str(claims.get(username_claim) or claims.get(email_claim) or subject),
        email=str(claims.get(email_claim) or ""),
        display_name=str(claims.get(display_claim) or ""),
        groups=tuple(_value_list(claims.get(groups_claim))),
        claims=claims,
    )
    return provision_external_user(db, profile)


def encrypt_secret_json(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True).encode("utf-8")
    key = hashlib.sha256(settings.auth_secret_key.encode("utf-8")).digest()
    stream = _keystream(key, len(payload))
    encrypted = bytes(byte ^ stream[index] for index, byte in enumerate(payload))
    signature = hmac.new(key, encrypted, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(signature + encrypted).decode("ascii")


def decrypt_secret_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        raw = base64.urlsafe_b64decode(value.encode("ascii"))
        signature, encrypted = raw[:32], raw[32:]
        key = hashlib.sha256(settings.auth_secret_key.encode("utf-8")).digest()
        if not hmac.compare_digest(signature, hmac.new(key, encrypted, hashlib.sha256).digest()):
            return {}
        stream = _keystream(key, len(encrypted))
        payload = bytes(byte ^ stream[index] for index, byte in enumerate(encrypted))
        parsed = json.loads(payload.decode("utf-8"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def ssl_cert_required(verify_tls: bool) -> int:
    import ssl

    return ssl.CERT_REQUIRED if verify_tls else ssl.CERT_NONE


def _claims_from_token_response(token_data: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    claims: dict[str, Any] = {}
    id_token = token_data.get("id_token")
    jwks_uri = str(config.get("jwks_uri") or "")
    if isinstance(id_token, str) and jwks_uri:
        from authlib.jose import JsonWebKey, JsonWebToken

        jwks_response = httpx.get(jwks_uri, timeout=15)
        jwks_response.raise_for_status()
        key_set = JsonWebKey.import_key_set(jwks_response.json())
        jwt = JsonWebToken(["RS256", "RS384", "RS512"])
        claims_options: dict[str, Any] = {}
        if config.get("issuer"):
            claims_options["iss"] = {"values": [config["issuer"]]}
        if config.get("client_id"):
            claims_options["aud"] = {"values": [config["client_id"]]}
        decoded = jwt.decode(id_token, key_set, claims_options=claims_options)
        decoded.validate()
        claims.update(dict(decoded))
    return claims


def _keystream(key: bytes, length: int) -> bytes:
    chunks: list[bytes] = []
    counter = 0
    while sum(len(chunk) for chunk in chunks) < length:
        chunks.append(hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha256).digest())
        counter += 1
    return b"".join(chunks)[:length]


def _find_user_for_profile(db: Session, profile: ExternalProfile) -> User | None:
    if profile.email:
        user = db.scalar(select(User).where(User.email == profile.email))
        if user:
            return user
    return db.scalar(select(User).where(User.username == profile.username))


def _available_username(db: Session, desired: str) -> str:
    base = "".join(char for char in desired.strip().lower() if char.isalnum() or char in "._-@").strip(".-_@") or "user"
    candidate = base
    counter = 2
    while db.scalar(select(User).where(User.username == candidate)):
        candidate = f"{base}{counter}"
        counter += 1
    return candidate


def _json_dict(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _first_value(value: Any) -> str:
    values = _value_list(value)
    return values[0] if values else ""


def _value_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item]
    return [str(value)]


__all__ = [
    "DEFAULT_ADMIN_PASSWORD",
    "DEFAULT_ADMIN_USERNAME",
    "VALID_ROLES",
    "authenticate_ldap",
    "authenticate_local",
    "authenticate_oidc_callback",
    "decrypt_secret_json",
    "enabled_provider",
    "get_provider",
    "has_role",
    "hash_password",
    "normalize_role",
    "oidc_authorization_url",
    "provider_config",
    "resolve_role",
    "seed_default_admin",
    "set_role_mappings",
    "upsert_provider",
    "verify_password",
]
