import asyncio
from contextlib import asynccontextmanager
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
                        # Reload trigger for companyCounts feature
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
from app.routers.gemini import router as gemini_router
from app.routers.diagnostic import router as diagnostic_router
from app.routers.gmail_archive import router as gmail_archive_router
from app.routers.matcher_benchmark import router as matcher_benchmark_router
from app.routers.story_map import router as story_map_router
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
# Resume building narrates its own decisions under "career_os.resume_build",
# which inherits the handlers below. The summary of a build is INFO: what came
# in, how many slots were weak, what was replaced and why, how the skills lines
# were ordered, which requirements nothing evidences, and a tally of every
# reason a candidate was refused. The per-candidate detail is DEBUG, because a
# single build refuses a few hundred candidates — raise it with
# CAREEROS_RESUME_LOG_LEVEL=DEBUG when a specific bullet needs explaining.
logging.getLogger("career_os.resume_build").setLevel(
    getattr(logging, (os.environ.get("CAREEROS_RESUME_LOG_LEVEL") or "INFO").upper(), logging.INFO)
)

careeros_logger = logging.getLogger("careeros")
careeros_logger.setLevel(logging.INFO)
careeros_logger.addHandler(file_handler)
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("[%(levelname)s] [%(name)s]: %(message)s"))
careeros_logger.addHandler(console_handler)
logger.addHandler(console_handler)

async def _drain_in_flight_work(grace_seconds: float) -> None:
    """Let a submission in progress finish before the process goes away.

    A SIGTERM used to land in the middle of a live application: the browser was
    killed mid-form, the job stayed in APPLYING until its lease expired, and the
    only way back was the reset_stale_locks script. An application half-submitted
    to a real employer is the worst failure this system has, so shutdown stops
    admitting new work and then waits for the current job.

    The wait is bounded. If a job outlives the grace period its lease still
    expires on its own, which is the same recovery path as a hard crash - the
    point is to make that the rare case rather than every restart.
    """
    from app.services.application_assistant.autopilot_runner import AutopilotRunner

    deadline = asyncio.get_running_loop().time() + grace_seconds

    try:
        runner = AutopilotRunner.get_instance()
    except Exception:
        runner = None

    if runner is not None:
        try:
            await runner.stop()
            logger.info("Autopilot runner asked to stop; draining in-flight job.")
        except Exception:
            logger.exception("Autopilot runner did not stop cleanly.")

    # Wait for anything still marked APPLYING to leave that state.
    while asyncio.get_running_loop().time() < deadline:
        try:
            from app.db.store import session_scope
            from app.services.application_assistant.persistence import list_autopilot_jobs

            with session_scope() as db:
                in_flight = list_autopilot_jobs(db, "APPLYING")
            if not in_flight:
                break
            logger.info("Waiting on %d in-flight application(s) before shutdown.", len(in_flight))
        except Exception:
            break
        await asyncio.sleep(1.0)

    # Stop the scrape loop; a partial scrape is resumable, a wedged task is not.
    try:
        from app.services.job_discover import store as job_discover_store

        task = getattr(job_discover_store, "_scrape_task", None)
        if task is not None and not task.done():
            task.cancel()
    except Exception:
        logger.exception("Could not cancel the discovery scrape task.")

    # Close the dedicated Playwright loop and any browser it still owns.
    try:
        from app.services.application_assistant.browser_runner import shutdown_playwright_worker

        await asyncio.to_thread(shutdown_playwright_worker)
    except Exception:
        logger.exception("Playwright worker did not shut down cleanly.")


def _warn_if_multi_worker() -> None:
    """Say so loudly if this process was started alongside siblings.

    Live state lives in module-level dictionaries across a dozen modules -
    browser sessions, task handles, the scrape task, submission watchers, the
    prep semaphore, the read cache. None of it is shared, so two workers means
    two independent scrapers writing the same snapshot and task handles the
    other worker cannot see or cancel. The queue lease is now atomic, which
    stops the worst outcome (applying twice), but the rest is still
    single-process by design and should fail loudly rather than corrupt quietly.
    """
    workers = os.environ.get("WEB_CONCURRENCY") or os.environ.get("UVICORN_WORKERS")
    try:
        count = int(workers) if workers else 1
    except ValueError:
        count = 1
    if count > 1:
        logger.error(
            "CareerOS is running with %s workers. Autopilot state is process-local "
            "(browser sessions, task handles, scrape task, read cache), so multiple "
            "workers will duplicate scrapes and lose task handles. Run a single "
            "worker, or set CAREEROS_ALLOW_MULTI_WORKER=1 to proceed anyway.",
            count,
        )
        if os.environ.get("CAREEROS_ALLOW_MULTI_WORKER", "").strip().lower() not in ("1", "true", "yes"):
            raise RuntimeError(
                f"Refusing to start with {count} workers: Autopilot state is process-local. "
                "Set CAREEROS_ALLOW_MULTI_WORKER=1 to override."
            )


async def _retention_loop() -> None:
    """Apply the retention policy once a day.

    Dry run unless CAREEROS_RETENTION_ENABLED is set, so a fresh install reports
    what it would remove and deletes nothing until someone opts in.
    """
    interval = float(os.environ.get("CAREEROS_RETENTION_INTERVAL_SECONDS", str(24 * 3600)))
    while True:
        try:
            await asyncio.sleep(interval)
            from app.services.retention import sweep

            report = await asyncio.to_thread(sweep)
            if report.total:
                logger.info(
                    "Retention sweep %s %d row(s): %s",
                    "would remove" if report.dry_run else "removed",
                    report.total,
                    report.removed,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Retention sweep failed; will retry next cycle.")


def _restore_diagnostic_errors() -> None:
    """Rehydrate DiagnosticErrorStore from the database — see its docstring
    in services/observability.py. Without this, `/diagnostic/errors` genuinely
    could not answer for anything that happened before the current process
    started, which was the actual gap behind "you debug live runs by reading
    api.log": the structured store existed but never survived a restart.
    """
    try:
        from app.services.observability import error_store

        count = error_store.load_from_db()
        if count:
            logger.info("Restored %d diagnostic error(s) from the database.", count)
    except Exception:
        logger.exception("Could not restore diagnostic errors at startup.")


def _recover_stranded_applications() -> None:
    """Return anything stuck mid-application to the queue. Never starts a run.

    Kept non-fatal: a failure here must not stop the API coming up, since the
    dashboard is how the user would diagnose it.
    """
    try:
        from app.services.application_assistant.autopilot_runner import (
            recover_stranded_applying_jobs,
        )

        recover_stranded_applying_jobs()
    except Exception:
        logger.exception("Could not recover stranded APPLYING jobs at startup.")


def _warm_autopilot_caches() -> None:
    """Pre-populate the Autopilot jobs/stats read-cache so the dashboard's
    first request after a restart does not pay the full synchronous rebuild
    (~5,000+ rows deserialized and sorted) — the same cost `_invalidate_autopilot_jobs_cache`
    now avoids on every batch-loop write via `touch`. Runs on a worker thread
    so it never delays startup or the health check.
    """
    try:
        from app.db.store import session_scope
        from app.services.application_assistant.persistence import (
            AUTOPILOT_JOBS_CACHE_KEY,
            AUTOPILOT_STATS_CACHE_KEY,
            get_autopilot_status_company_stats,
            list_autopilot_jobs,
        )
        from app.services.read_cache import read_cache

        def _load_jobs() -> list:
            with session_scope() as db:
                return list_autopilot_jobs(db)

        def _load_stats() -> dict:
            with session_scope() as db:
                return get_autopilot_status_company_stats(db)

        read_cache.get(AUTOPILOT_JOBS_CACHE_KEY, 5.0, _load_jobs)
        read_cache.get(AUTOPILOT_STATS_CACHE_KEY, 30.0, _load_stats)
        logging.getLogger("career_os.main").info("Autopilot dashboard caches warmed at startup.")
    except Exception:
        logging.getLogger("career_os.main").exception("Could not warm autopilot caches at startup.")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _warn_if_multi_worker()
    init_db()
    seed_error_fix_history_if_empty()
    reconcile_error_history_on_startup()
    _ensure_ollama_started_background()
    # Nothing is left mid-application across a restart. Autopilot never starts
    # a batch on its own - every run comes from an explicit request - so a job
    # stranded in APPLYING by a killed process would otherwise sit there until
    # the user started a run purely to clear it. This requeues those; a job
    # whose submit was already issued becomes SUBMISSION_UNKNOWN instead of
    # being retried. It starts nothing.
    _recover_stranded_applications()
    _restore_diagnostic_errors()
    asyncio.create_task(asyncio.to_thread(_warm_autopilot_caches))
    retention_task = asyncio.create_task(_retention_loop())
    logger.info("CareerOS API started and local file logging initialized.")
    try:
        yield
    finally:
        retention_task.cancel()
        grace = float(os.environ.get("CAREEROS_SHUTDOWN_GRACE_SECONDS", "30"))
        logger.info("Shutting down; draining for up to %.0fs.", grace)
        try:
            await asyncio.wait_for(_drain_in_flight_work(grace), timeout=grace + 10)
        except TimeoutError:
            logger.warning("Shutdown drain exceeded its budget; exiting anyway.")
        except Exception:
            logger.exception("Shutdown drain failed.")
        logger.info("CareerOS API shutdown complete.")


app = FastAPI(
    title="CareerOS API",
    description="Backend for CareerOS / ApplyPilot",
    version="0.1.0",
    lifespan=lifespan,
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
app.include_router(story_map_router)
app.include_router(matcher_benchmark_router)
app.include_router(gmail_archive_router)
app.include_router(gemini_router)
app.include_router(diagnostic_router)


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
    from app.services.application_assistant.llm_client import LOCAL_LLM_ENABLED

    # With the local model switched off nothing may call it, so there is no
    # reason to have its server running and holding memory either.
    if not LOCAL_LLM_ENABLED:
        logger.info("CAREEROS_LOCAL_LLM=off: not starting Ollama.")
        return
    import shutil
    import subprocess
    import urllib.request

    base = settings.careeros_ollama_health_url.rstrip("/")
    try:
        req = urllib.request.Request(f"{base}/api/tags", headers={"User-Agent": "CareerOS"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                logger.info("Ollama is already running and reachable at %s", base)
                return
    except Exception:
        pass

    # Only the machine actually hosting Ollama should try to start it. When this
    # is pointed at another host - a container reaching the host through
    # host.docker.internal - there is no local binary to launch and no business
    # launching one, so report and stop.
    if "127.0.0.1" not in base and "localhost" not in base:
        logger.info("Ollama is configured at %s and is not reachable; not starting a local instance.", base)
        return

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


