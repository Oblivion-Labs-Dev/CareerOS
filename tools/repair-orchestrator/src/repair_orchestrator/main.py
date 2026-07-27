from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from repair_orchestrator.api.routes import router
from repair_orchestrator.config import settings
from repair_orchestrator.db import init_db

app = FastAPI(
    title="CareerOS Repair Orchestrator",
    description="Local automated error detection and repair pipeline",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


def main() -> None:
    import uvicorn

    uvicorn.run(
        "repair_orchestrator.main:app",
        host=settings.repair_host,
        port=settings.repair_port,
        reload=True,
    )


if __name__ == "__main__":
    main()
