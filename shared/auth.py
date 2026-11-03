"""Lightweight single-user login gate for CareerOS.

This is deliberately NOT a multi-tenant auth system: CareerOS today has exactly
one user (the person running it locally), so there is no users table, no
per-user data scoping, and no signup flow. This just keeps the dashboard and
API from being usable by anyone who can reach the machine/network, via one
admin credential and a signed session cookie.

The session token is a stateless HMAC-signed value (username + expiry, signed
with a secret persisted in the KV store) rather than a server-side session
table, so logins survive the frequent dev-server restarts this project sees
without needing a dedicated sessions table for a single user.

If/when CareerOS grows real multi-user accounts (signup, per-user data, cloud
deployment), this module should be replaced outright, not extended.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Any

from app.config import settings

SESSION_COOKIE_NAME = "co_session"
SESSION_TTL_SECONDS = 60 * 60 * 24 * 14  # 14 days

_SECRET_KV_KEY = "auth_session_secret"


def _get_or_create_secret() -> str:
    """Persist the HMAC secret in the KV store so sessions survive server restarts."""
    if settings.career_os_session_secret:
        return settings.career_os_session_secret

    from app.db.store import get_kv, session_scope, set_kv

    with session_scope() as db:
        existing = get_kv(db, _SECRET_KV_KEY)
        if isinstance(existing, str) and existing:
            return existing
        new_secret = secrets.token_hex(32)
        set_kv(db, _SECRET_KV_KEY, new_secret)
        return new_secret


def is_auth_configured() -> bool:
    """Auth is only enforced once an admin password has actually been set.

    Without this, a fresh checkout with no .env would lock the owner out of
    their own local instance with no way back in.
    """
    return bool(settings.career_os_admin_password)


def verify_credentials(username: str, password: str) -> bool:
    if not is_auth_configured():
        return False
    user_ok = hmac.compare_digest(username, settings.career_os_admin_username)
    pass_ok = hmac.compare_digest(password, settings.career_os_admin_password)
    return user_ok and pass_ok


def create_session_token(username: str) -> str:
    secret = _get_or_create_secret()
    expires_at = int(time.time()) + SESSION_TTL_SECONDS
    payload = f"{username}.{expires_at}"
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{signature}"


def verify_session_token(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    # rsplit, not split: an email-address username (the common case) contains
    # its own "."s, so a plain split() would over-fragment the token instead
    # of cleanly separating username / expiry / signature.
    parts = token.rsplit(".", 2)
    if len(parts) != 3:
        return None
    username, expires_at_raw, signature = parts

    secret = _get_or_create_secret()
    payload = f"{username}.{expires_at_raw}"
    expected_signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        return None

    try:
        expires_at = int(expires_at_raw)
    except ValueError:
        return None
    if expires_at < int(time.time()):
        return None

    return {"username": username, "expiresAt": expires_at}
