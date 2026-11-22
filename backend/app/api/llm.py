"""Local-only management of provider selection and read-only connection checks."""

import asyncio
import ipaddress
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.api.json_routes import SafeJSONRoute, api_error
from app.api.pull_requests import PreviewErrorResponse
from app.core.config import Settings
from app.integrations.llm_connection import LlmConnectionResult, test_llm_connection
from app.services.llm_configuration import (
    LLM_SETTINGS_PATH,
    LlmConfiguration,
    LlmConfigurationStore,
    LlmDraft,
    LlmError,
)


def create_llm_router(settings: Settings, path: Path = LLM_SETTINGS_PATH) -> APIRouter:
    store = LlmConfigurationStore(settings, path)
    test_gate = asyncio.Semaphore(1)

    def local_only(request: Request) -> None:
        try:
            if request.client is None or not ipaddress.ip_address(request.client.host).is_loopback:
                raise ValueError
        except ValueError:
            raise HTTPException(
                403,
                detail={
                    "code": "llm_local_only",
                    "message": "LLM settings are available only from this computer.",
                },
            ) from None
        origin = request.headers.get("origin")
        allowed = {str(value).rstrip("/") for value in settings.cors_origins}
        if request.url.hostname in {"127.0.0.1", "localhost", "::1"}:
            allowed.add(f"{request.url.scheme}://{request.url.netloc}")
        if origin and origin not in allowed:
            raise HTTPException(
                403,
                detail={
                    "code": "llm_local_only",
                    "message": "This origin cannot manage LLM settings.",
                },
            )
        if request.headers.get("sec-fetch-site") == "cross-site" and not origin:
            raise HTTPException(
                403,
                detail={
                    "code": "llm_local_only",
                    "message": "Cross-site configuration requests are not allowed.",
                },
            )

    router = APIRouter(
        prefix="/api/v1/llm",
        tags=["LLM configuration"],
        route_class=SafeJSONRoute,
        dependencies=[Depends(local_only)],
    )
    errors = {
        status: {"model": PreviewErrorResponse}
        for status in (401, 403, 413, 415, 422, 429, 502, 503, 504)
    }

    @router.get("/configuration", response_model=LlmConfiguration, responses=errors)
    async def get_configuration() -> LlmConfiguration | JSONResponse:
        try:
            return await run_in_threadpool(store.catalog)
        except LlmError as exc:
            return api_error(exc.status, exc.code, str(exc))

    @router.post("/configuration", response_model=LlmConfiguration, responses=errors)
    async def save_configuration(payload: LlmDraft) -> LlmConfiguration | JSONResponse:
        try:
            return await run_in_threadpool(store.save, payload)
        except LlmError as exc:
            return api_error(exc.status, exc.code, str(exc))

    @router.post("/test-connection", response_model=LlmConnectionResult, responses=errors)
    async def test_connection(payload: LlmDraft) -> LlmConnectionResult | JSONResponse:
        if test_gate.locked():
            return api_error(
                429, "llm_test_busy", "A connection test is already running. Try again shortly."
            )
        async with test_gate:
            try:
                model, key = await run_in_threadpool(store.resolve, payload)
                return await test_llm_connection(payload.provider, model, key)
            except LlmError as exc:
                return api_error(exc.status, exc.code, str(exc))

    return router
