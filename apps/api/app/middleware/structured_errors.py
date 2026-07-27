from __future__ import annotations

from fastapi import HTTPException
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.config import settings
from app.services.structured_errors import build_structured_error, forward_to_repair_orchestrator


class StructuredErrorMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except (HTTPException, StarletteHTTPException):
            raise
        except Exception as exc:
            if settings.career_os_repair_enabled:
                payload = build_structured_error(
                    exc,
                    endpoint=f"{request.method} {request.url.path}",
                    correlation_id=request.headers.get("x-correlation-id"),
                )
                forward_to_repair_orchestrator(payload)
            raise
