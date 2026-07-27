import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.services.runtime_metrics import metrics_store, should_skip_metrics
from app.services.error_fix_tracker import error_fix_tracker


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if should_skip_metrics(path):
            return await call_next(request)

        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            metrics_store.record(
                method=request.method,
                path=path,
                status_code=status_code,
                duration_ms=duration_ms,
            )
            error_fix_tracker.record_api_response(request.method, path, status_code)
