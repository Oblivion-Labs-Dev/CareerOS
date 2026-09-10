import asyncio
import logging
import os
import sys
import traceback
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    # Patch asyncio.proactor_events.BaseProactorEventLoop._start_serving to prevent
    # WinError 64 / 121 (client disconnected before accept completed) from closing the listener socket.
    try:
        from asyncio import trsock, exceptions
        import asyncio.proactor_events as pe
        def _safe_start_serving(self, protocol_factory, sock,
                                sslcontext=None, server=None, backlog=100,
                                ssl_handshake_timeout=None,
                                ssl_shutdown_timeout=None):
            def loop(f=None):
                try:
                    if f is not None:
                        try:
                            conn, addr = f.result()
                        except OSError as exc:
                            if getattr(exc, "winerror", None) in (64, 121, 1225, 10054):
                                if not self.is_closed() and sock.fileno() != -1:
                                    loop()
                                return
                            raise
                        if self._debug:
                            pe.logger.debug("%r got a new connection from %r: %r",
                                         server, addr, conn)
                        protocol = protocol_factory()
                        if sslcontext is not None:
                            self._make_ssl_transport(
                                conn, protocol, sslcontext, server_side=True,
                                extra={'peername': addr}, server=server,
                                ssl_handshake_timeout=ssl_handshake_timeout,
                                ssl_shutdown_timeout=ssl_shutdown_timeout)
                        else:
                            self._make_socket_transport(
                                conn, protocol,
                                extra={'peername': addr}, server=server)
                    if self.is_closed():
                        return
                    f = self._proactor.accept(sock)
                except OSError as exc:
                    if getattr(exc, "winerror", None) in (64, 121, 1225, 10054):
                        if not self.is_closed() and sock.fileno() != -1:
                            self.call_soon(loop)
                        return
                    if sock.fileno() != -1:
                        self.call_exception_handler({
                            'message': 'Accept failed on a socket',
                            'exception': exc,
                            'socket': trsock.TransportSocket(sock),
                        })
                        sock.close()
                    elif self._debug:
                        pe.logger.debug("Accept failed on socket %r",
                                     sock, exc_info=True)
                except exceptions.CancelledError:
                    sock.close()
                else:
                    self._accept_futures[sock.fileno()] = f
                    f.add_done_callback(loop)
            self.call_soon(loop)
        pe.BaseProactorEventLoop._start_serving = _safe_start_serving
    except Exception as _patch_err:
        pass

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db.store import init_db
from app.middleware.auth import AuthGateMiddleware
from app.middleware.metrics import MetricsMiddleware
from app.routers.api import router
from app.routers.application_assistant import router as application_assistant_router
from app.routers.auth import router as auth_router
from app.routers.intelligence import router as intelligence_router
from app.routers.job_search import router as job_search_router
from app.routers.networking import router as networking_router
from app.routers.repair_demo import router as repair_demo_router
from app.routers.repair_manual import router as repair_manual_router
from app.routers.resume_intelligence import router as resume_intelligence_router
from app.services.error_fix_tracker import error_fix_tracker, reconcile_error_history_on_startup, seed_error_fix_history_if_empty

log_dir = Path(__file__).resolve().parent.parent / "data" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
api_log_file = log_dir / "api.log"

logger = logging.getLogger("career_os")
logger.setLevel(logging.INFO)

file_handler = logging.FileHandler(api_log_file, encoding="utf-8")
file_handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s"))
logger.addHandler(file_handler)
logging.getLogger("uvicorn.error").addHandler(file_handler)
logging.getLogger("uvicorn.access").addHandler(file_handler)

# The LLM client logs under "careeros.*" (no underscore), a different tree from
# "career_os" above, so without this its per-call telemetry — model, token
# counts, latency, context usage, retries and fallback events — was written to a
# logger with no handler and silently discarded. Everything CareerOS logs should
# land in the same file regardless of which spelling the module picked.
careeros_logger = logging.getLogger("careeros")
careeros_logger.setLevel(logging.INFO)
careeros_logger.addHandler(file_handler)
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("[%(levelname)s] [%(name)s]: %(message)s"))
careeros_logger.addHandler(console_handler)
logger.addHandler(console_handler)

app = FastAPI(
    title="CareerOS API",
    description="Backend for CareerOS / ApplyPilot",
    version="0.1.0",
)

origins = [origin.strip() for origin in settings.career_os_cors_origins.split(",") if origin.strip() and not origin.strip().endswith("*")]

# AuthGateMiddleware is registered before CORSMiddleware so that CORS ends up as the
# OUTER layer (Starlette wraps in reverse registration order — last added = outermost).
# That matters here specifically: when the auth gate short-circuits with a 401, that
# response must still pass back out through CORSMiddleware's header-adding logic, or
# the browser's fetch() blocks it as a CORS failure and the frontend never sees the 401
# to redirect to /login — it would just look like every request silently broke.
app.add_middleware(AuthGateMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins else ["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_origin_regex=r"^(https?://(localhost|127\.0\.0\.1)(:\d+)?|chrome-extension://.*)$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(MetricsMiddleware)

static_dir = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

app.include_router(auth_router)
app.include_router(router)
app.include_router(intelligence_router)
app.include_router(repair_demo_router)
app.include_router(repair_manual_router)
app.include_router(application_assistant_router)
app.include_router(resume_intelligence_router)
app.include_router(job_search_router)
app.include_router(networking_router)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    error_msg = f"Unhandled exception on {request.method} {request.url.path}: {exc}\n{traceback.format_exc()}"
    logger.error(error_msg)
    error_fix_tracker.record_api_response(request.method, request.url.path, 500)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "error": str(exc)},
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    icon_path = static_dir / "api-dashboard" / "favicon.svg"
    if icon_path.is_file():
        return FileResponse(icon_path, media_type="image/svg+xml")
    return Response(status_code=204)


def _ensure_ollama_started_background() -> None:
    """Check if Ollama is running and start it in background if not already alive."""
    import shutil
    import subprocess
    import urllib.request

    try:
        req = urllib.request.Request("http://127.0.0.1:11434/api/tags", headers={"User-Agent": "CareerOS"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                logger.info("Ollama is already running and reachable at http://127.0.0.1:11434")
                return
    except Exception:
        pass

    ollama_path = shutil.which("ollama")
    if not ollama_path:
        candidate = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"
        if candidate.is_file():
            ollama_path = str(candidate)

    if ollama_path:
        try:
            flags = 0
            if sys.platform == "win32":
                flags = subprocess.CREATE_NO_WINDOW | getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            subprocess.Popen(
                [ollama_path, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=flags,
                close_fds=True,
            )
            logger.info("Automatically launched Ollama serve (%s) in background.", ollama_path)
        except Exception as ex:
            logger.warning("Attempted to start Ollama in background but encountered: %s", ex)
    else:
        logger.info("Ollama executable not detected on PATH or default location.")


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    seed_error_fix_history_if_empty()
    reconcile_error_history_on_startup()
    _ensure_ollama_started_background()
    logger.info("CareerOS API started and local file logging initialized.")

