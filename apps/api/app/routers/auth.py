"""Login endpoints for the single-user access gate. See app/services/auth.py
for what this is (and, importantly, is not)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.services.auth import (
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    create_session_token,
    is_auth_configured,
    verify_credentials,
    verify_session_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginPayload(BaseModel):
    username: str
    password: str


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


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"success": True}
