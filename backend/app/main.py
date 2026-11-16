from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else get_settings()
    application = FastAPI(
        title=settings.app_name,
        description="AI-powered GitHub Pull Request Review Agent",
        version="1.0.0",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin).rstrip("/") for origin in settings.cors_origins],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

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

    return application


app = create_app()
