import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.services.error_fix_tracker import error_fix_tracker
from app.services.runtime_metrics import metrics_store, should_skip_metrics
from app.services.observability import (
    tracer,
    set_correlation_context,
    get_correlation_context,
    generate_trace_id,
    generate_span_id,
    TRACEPARENT_RE,
)


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if should_skip_metrics(path):
            return await call_next(request)

        # Parse incoming W3C traceparent header if present
        traceparent = request.headers.get("traceparent") or request.headers.get("x-trace-id")
        trace_id = None
        parent_span_id = None
        if traceparent:
            match = TRACEPARENT_RE.match(traceparent)
            if match:
                trace_id = match.group(1)
                parent_span_id = match.group(2)
            elif len(traceparent) == 32:
                trace_id = traceparent

        trace_id = trace_id or generate_trace_id()
        span_id = generate_span_id()
        set_correlation_context(trace_id=trace_id, span_id=span_id)

        started = time.perf_counter()
        status_code = 500
        try:
            with tracer.start_as_current_span(
                f"HTTP {request.method} {path}",
                kind="SERVER",
                attributes={
                    "http.method": request.method,
                    "http.target": path,
                    "http.route": path,
                    "http.user_agent": request.headers.get("user-agent", ""),
                },
            ) as span:
                response = await call_next(request)
                status_code = response.status_code
                span.attributes["http.status_code"] = status_code
                response.headers["x-trace-id"] = trace_id
                response.headers["traceparent"] = f"00-{trace_id}-{span_id}-01"
                return response
        except Exception as exc:
            from app.services.observability import error_store
            error_store.record_error(
                error=f"Unhandled exception on {request.method} {path}: {exc}",
                service="careeros_api",
                severity="critical",
                status="open",
            )
            raise
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            metrics_store.record(
                method=request.method,
                path=path,
                status_code=status_code,
                duration_ms=duration_ms,
            )
            error_fix_tracker.record_api_response(request.method, path, status_code)
