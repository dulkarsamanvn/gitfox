from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.api.pull_requests import create_pull_requests_router
from app.core.config import Settings, get_settings
from app.db.database import Database


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else get_settings()
    database = Database(settings.database_url)

    @asynccontextmanager
    async def lifespan(_application: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            await run_in_threadpool(database.close)

    application = FastAPI(
        title=settings.app_name,
        description="AI-powered GitHub Pull Request Review Agent",
        version="1.0.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin).rstrip("/") for origin in settings.cors_origins],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    application.include_router(create_pull_requests_router(settings))

    @application.get("/")
    def home() -> dict[str, str]:
        return {
            "message": f"Welcome to {settings.app_name}",
            "status": "running",
        }

    @application.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        """Application liveness, independent of database availability."""
        return {"status": "ok"}

    @application.get(
        "/ready",
        tags=["health"],
        responses={503: {"description": "Database unavailable or not configured"}},
    )
    def ready() -> JSONResponse:
        """Database readiness, verified with an authenticated SELECT 1."""
        is_ready = database.is_ready()
        return JSONResponse(
            status_code=200 if is_ready else 503,
            content={
                "status": "ok" if is_ready else "not_ready",
                "database": "ok" if is_ready else "unavailable",
            },
        )

    return application


app = create_app()
