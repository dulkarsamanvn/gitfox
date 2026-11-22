"""Bounded JSON requests with safe validation errors and uncached responses."""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException
from starlette.types import Message


def api_error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"detail": {"code": code, "message": message}},
        headers={"Cache-Control": "no-store"},
    )


class SafeJSONRoute(APIRoute):
    def invalid_request(self, error: RequestValidationError | None = None) -> JSONResponse:
        return api_error(
            422, "invalid_request", "Send a valid JSON request with the required fields."
        )

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def bounded_handler(request: Request) -> Response:
            if request.method not in {"POST", "PUT", "PATCH"}:
                response = await handler(request)
                response.headers["Cache-Control"] = "no-store"
                return response
            media_type = request.headers.get("content-type", "").partition(";")[0].strip().lower()
            if media_type != "application/json":
                return api_error(
                    415, "unsupported_media_type", "Use Content-Type: application/json."
                )
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > 4096:
                    return api_error(
                        413, "request_too_large", "Request body must not exceed 4096 bytes."
                    )
                body.extend(chunk)
            received = False

            async def receive() -> Message:
                nonlocal received
                if received:
                    return await request.receive()
                received = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}

            try:
                response = await handler(Request(request.scope, receive=receive))
            except RequestValidationError as exc:
                return self.invalid_request(exc)
            except HTTPException as exc:
                if exc.status_code == 400:
                    return self.invalid_request()
                raise
            response.headers["Cache-Control"] = "no-store"
            return response

        return bounded_handler
