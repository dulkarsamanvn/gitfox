"""Read-only model metadata checks against fixed provider endpoints."""

import asyncio
import json
import time
from urllib.parse import quote

import httpx
from pydantic import BaseModel, SecretStr

from app.services.llm_configuration import LlmError, Provider


class LlmConnectionResult(BaseModel):
    status: str = "ok"
    provider: Provider
    model: str
    resolved_model: str
    latency_ms: int


async def test_llm_connection(
    provider: Provider,
    model: str,
    key: SecretStr,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> LlmConnectionResult:
    headers = {"Accept": "application/json", "User-Agent": "GitFox"}
    encoded = quote(model, safe="")
    if provider == "openai":
        url = f"https://api.openai.com/v1/models/{encoded}"
        headers["Authorization"] = f"Bearer {key.get_secret_value()}"
    elif provider == "anthropic":
        url = f"https://api.anthropic.com/v1/models/{encoded}"
        headers.update(
            {"Authorization": f"Bearer {key.get_secret_value()}", "anthropic-version": "2026-10-21"}
        )
    elif provider == "gemini":
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{encoded}"
        headers["x-goog-api-key"] = key.get_secret_value()
    else:
        raise LlmError("llm_invalid_provider", "Choose a supported provider.")
    started = time.monotonic()
    try:
        async with asyncio.timeout(15):
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(10, connect=5),
                follow_redirects=False,
                trust_env=False,
                transport=transport,
            ) as client:
                async with client.stream("GET", url, headers=headers) as response:
                    if response.status_code != 200:
                        codes = {
                            400: (
                                "llm_request_rejected",
                                "The provider rejected the settings. Check the model and API key.",
                                422,
                            ),
                            401: ("llm_auth_failed", "The provider rejected the API key.", 401),
                            403: (
                                "llm_access_denied",
                                "This key does not have access to the selected model.",
                                403,
                            ),
                            404: (
                                "llm_model_not_found",
                                "The model was not found or is not available to this key.",
                                422,
                            ),
                            429: (
                                "llm_rate_limited",
                                "The provider rate limit was reached. Try again later.",
                                429,
                            ),
                        }
                        code, message, status = codes.get(
                            response.status_code,
                            (
                                "llm_unavailable",
                                "The provider could not complete the connection test.",
                                503,
                            ),
                        )
                        raise LlmError(code, message, status)
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body) + len(chunk) > 65_536:
                            raise ValueError
                        body.extend(chunk)
                    data = json.loads(body)
                    if not isinstance(data, dict):
                        raise ValueError
                    resolved = data.get("name" if provider == "gemini" else "id")
                    if not isinstance(resolved, str) or not resolved or len(resolved) > 256:
                        raise ValueError
                    if provider == "gemini":
                        if not resolved.startswith("models/"):
                            raise ValueError
                        resolved = resolved.removeprefix("models/")
                    elif data.get("object" if provider == "openai" else "type") != "model":
                        raise ValueError
                    # Treat response identifiers as data, never as a subsequent fetch URL.
                    if (
                        any(ord(char) < 33 or ord(char) > 126 for char in resolved)
                        or "/" in resolved
                        or key.get_secret_value() in resolved
                    ):
                        raise ValueError
    except (TimeoutError, httpx.TimeoutException):
        raise LlmError("llm_timeout", "The provider connection test timed out.", 504) from None
    except httpx.RequestError:
        raise LlmError(
            "llm_unavailable", "Could not reach the provider. Try again later.", 503
        ) from None
    except (ValueError, RecursionError):
        raise LlmError(
            "llm_invalid_response", "The provider returned an unexpected model response.", 502
        ) from None
    return LlmConnectionResult(
        provider=provider,
        model=model,
        resolved_model=resolved,
        latency_ms=max(0, round((time.monotonic() - started) * 1000)),
    )
