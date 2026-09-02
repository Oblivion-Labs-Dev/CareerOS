import asyncio
import logging
import sys
import traceback
from pathlib import Path

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db.store import init_db
from app.middleware.metrics import MetricsMiddleware
from app.routers.api import router
from app.routers.application_assistant import router as application_assistant_router
from app.routers.intelligence import router as intelligence_router
from app.routers.job_search import router as job_search_router
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

app = FastAPI(
    title="CareerOS API",
    description="Backend for CareerOS / ApplyPilot",
    version="0.1.0",
)

origins = [origin.strip() for origin in settings.career_os_cors_origins.split(",") if origin.strip() and not origin.strip().endswith("*")]
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

app.include_router(router)
app.include_router(intelligence_router)
app.include_router(repair_demo_router)
app.include_router(repair_manual_router)
app.include_router(application_assistant_router)
app.include_router(resume_intelligence_router)
app.include_router(job_search_router)


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


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    seed_error_fix_history_if_empty()
    reconcile_error_history_on_startup()
    logger.info("CareerOS API started and local file logging initialized.")

