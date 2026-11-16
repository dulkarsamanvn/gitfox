from collections.abc import AsyncIterator
from unittest.mock import Mock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.db.database import Database
from app.main import create_app

pytestmark = pytest.mark.anyio


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    settings = Settings(
        _env_file=None,
        openai_api_key="fake-key-not-for-exposure",
        cors_origins=["http://localhost:5173"],
    )
    application = create_app(settings)
    transport = ASGITransport(app=application)
    async with application.router.lifespan_context(application):
        async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
            yield test_client


async def test_health_is_available_without_database(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_cors_allows_configured_frontend(client: AsyncClient) -> None:
    response = await client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-credentials" not in response.headers


async def test_cors_rejects_unconfigured_frontend(client: AsyncClient) -> None:
    response = await client.options(
        "/health",
        headers={
            "Origin": "https://unconfigured.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


async def test_readiness_without_database_configuration(client: AsyncClient) -> None:
    response = await client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "database": "unavailable"}
    assert (await client.get("/health")).status_code == 200


@pytest.mark.parametrize("available", [True, False])
async def test_readiness_reports_database_status(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, available: bool
) -> None:
    monkeypatch.setattr(Database, "is_ready", lambda self: available)

    response = await client.get("/ready")

    assert response.status_code == (200 if available else 503)
    assert response.json() == {
        "status": "ok" if available else "not_ready",
        "database": "ok" if available else "unavailable",
    }


async def test_application_shutdown_closes_database(monkeypatch: pytest.MonkeyPatch) -> None:
    close = Mock()
    monkeypatch.setattr(Database, "close", close)
    application = create_app(Settings(_env_file=None))

    async with application.router.lifespan_context(application):
        pass

    close.assert_called_once()
