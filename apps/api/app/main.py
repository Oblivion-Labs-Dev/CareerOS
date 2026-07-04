from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.store import init_db
from app.routers.api import router

app = FastAPI(
    title="CareerOS API",
    description="Backend for CareerOS / ApplyPilot",
    version="0.1.0",
)

origins = [origin.strip() for origin in settings.career_os_cors_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins if origins != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
