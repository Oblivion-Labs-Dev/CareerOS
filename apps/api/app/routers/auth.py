"""Login and authentication endpoints for CareerOS.
Supports:
- Single-user / admin login gate
- Multi-tenant candidate signup and login with secure PBKDF2 hashing
- JWT bearer session tokens for web and API
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.db.store import (
    EntityStore,
    get_kv,
    json_field,
    now_iso,
    session_scope,
    set_kv,
    upsert_entity,
)
from app.services.auth import (
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    create_session_token,
    extract_user_from_request,
    is_auth_configured,
    verify_credentials,
    verify_session_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginPayload(BaseModel):
    username: str
    password: str


class CandidateAuthPayload(BaseModel):
    email: str
    password: str
    fullName: str | None = None


def _hash_password(password: str) -> tuple[str, str]:
    salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000).hex()
    return hashed, salt


def _verify_password(password: str, hashed: str, salt: str) -> bool:
    candidate_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000).hex()
    return hmac.compare_digest(candidate_hash, hashed)


def _create_jwt_token(user_id: str, email: str) -> str:
    import jwt
    from app.config import settings
    from app.services.auth import _get_or_create_secret

    secret = settings.supabase_jwt_secret or _get_or_create_secret()
    payload = {
        "sub": user_id,
        "email": email,
        "role": "candidate",
        "exp": int(time.time()) + SESSION_TTL_SECONDS,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


@router.get("/status")
def auth_status(request: Request) -> dict[str, object]:
    """Whether a login is required at all, and whether the current request is authenticated."""
    if not is_auth_configured():
        return {"authRequired": False, "authenticated": True}
    session = verify_session_token(request.cookies.get(SESSION_COOKIE_NAME))
    return {"authRequired": True, "authenticated": session is not None}


@router.post("/login")
def login(payload: LoginPayload, response: Response) -> dict[str, bool]:
    if not is_auth_configured():
        return {"success": True}

    if not verify_credentials(payload.username, payload.password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")

    token = create_session_token(payload.username)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return {"success": True}


@router.post("/candidate/signup")
def candidate_signup(payload: CandidateAuthPayload, response: Response) -> dict[str, Any]:
    email = payload.email.strip().lower()
    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="A valid email address is required")
    if len(payload.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    user_id = f"cand_{uuid.uuid4().hex[:12]}"
    with session_scope() as db:
        existing = (
            db.query(EntityStore)
            .filter(
                EntityStore.entity_type == "candidate_user",
                json_field("$.email") == email,
            )
            .one_or_none()
        )
        if existing:
            raise HTTPException(status_code=409, detail="An account with this email already exists")

        pwd_hash, salt = _hash_password(payload.password)
        user_record = {
            "id": user_id,
            "email": email,
            "fullName": payload.fullName or "",
            "passwordHash": pwd_hash,
            "salt": salt,
            "createdAt": now_iso(),
            "role": "candidate",
        }
        upsert_entity(db, "candidate_user", user_record, user_id=user_id)

        # Initialize default candidate profile
        candidate_profile = {
            "id": f"prof_{user_id}",
            "email": email,
            "fullName": payload.fullName or "",
            "createdAt": now_iso(),
            "workExperience": [],
            "education": [],
            "screeningAnswers": [],
        }
        set_kv(db, "profile", candidate_profile, user_id=user_id)

    token = _create_jwt_token(user_id, email)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return {
        "success": True,
        "token": token,
        "userId": user_id,
        "email": email,
        "needsOnboarding": True,
    }


@router.post("/candidate/login")
def candidate_login(payload: CandidateAuthPayload, response: Response) -> dict[str, Any]:
    email = payload.email.strip().lower()
    with session_scope() as db:
        existing = (
            db.query(EntityStore)
            .filter(
                EntityStore.entity_type == "candidate_user",
                json_field("$.email") == email,
            )
            .one_or_none()
        )
        if not existing:
            raise HTTPException(status_code=401, detail="Invalid email or password")

        user_data = existing.payload
        if not _verify_password(payload.password, user_data.get("passwordHash", ""), user_data.get("salt", "")):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        user_id = existing.id
        profile = get_kv(db, "profile", user_id=user_id) or {}
        from app.services.application_assistant.profile_readiness import evaluate_profile_readiness

        readiness = evaluate_profile_readiness(profile)
        needs_onboarding = not readiness.ready

    token = _create_jwt_token(user_id, email)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return {
        "success": True,
        "token": token,
        "userId": user_id,
        "email": email,
        "needsOnboarding": needs_onboarding,
    }


@router.get("/me")
def get_current_user(request: Request) -> dict[str, Any]:
    user_id = extract_user_from_request(request)
    with session_scope() as db:
        profile = get_kv(db, "profile", user_id=user_id) or {}
        from app.services.application_assistant.profile_readiness import evaluate_profile_readiness

        readiness = evaluate_profile_readiness(profile)
        return {
            "userId": user_id,
            "email": profile.get("email", ""),
            "fullName": profile.get("fullName", ""),
            "readyForAutopilot": readiness.ready,
            "blockingCount": len(readiness.blocking),
            "missingRequired": [gap.raw_label for gap in readiness.blocking],
            "softCount": len(readiness.soft),
        }


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"success": True}

