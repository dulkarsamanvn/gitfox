import asyncio
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.api import llm
from app.core.config import Settings
from app.integrations.llm_connection import (
    LlmConnectionResult,
)
from app.integrations.llm_connection import (
    test_llm_connection as check_connection,
)
from app.main import create_app
from app.services.llm_configuration import LlmConfigurationStore, LlmDraft, LlmError

pytestmark = pytest.mark.anyio
KEY = "fake-provider-secret"
BASE = "/api/v1/llm"


def settings() -> Settings:
    return Settings(_env_file=None, openai_api_key="fake-env-secret", openai_model="openai-test")


def test_saves_provider_profiles_and_preserves_keys_on_restart(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = LlmConfigurationStore(settings(), path)
    initial = store.catalog()
    assert initial.providers[0].key_configured is True
    assert "fake-env-secret" not in initial.model_dump_json()
    store.save(LlmDraft(provider="anthropic", model="claude-test", api_key=KEY))
    store.save(LlmDraft(provider="gemini", model="models/gemini-test", api_key="fake-google-key"))
    restarted = LlmConfigurationStore(settings(), path)
    assert restarted.catalog().active_provider == "gemini"
    assert (
        restarted.resolve(LlmDraft(provider="anthropic", model="claude-test"))[1].get_secret_value()
        == KEY
    )
    assert (
        restarted.resolve(LlmDraft(provider="openai", model="openai-test"))[1].get_secret_value()
        == "fake-env-secret"
    )
    restarted.save(LlmDraft(provider="anthropic", model="claude-new", api_key=""))
    assert (
        restarted.resolve(LlmDraft(provider="anthropic", model="claude-new"))[1].get_secret_value()
        == KEY
    )
    assert KEY not in restarted.catalog().model_dump_json()
    assert "fake-env-secret" not in path.read_text()  # Environment keys are not copied.
    assert list(tmp_path.glob(".llm-settings-*.tmp")) == []


def test_failed_save_does_not_replace_existing_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "settings.json"
    store = LlmConfigurationStore(settings(), path)
    store.save(LlmDraft(provider="openai", model="model-first"))
    original = path.read_bytes()
    monkeypatch.setattr(
        "app.services.llm_configuration.os.replace",
        Mock(side_effect=OSError("fake-sensitive-error")),
    )
    with pytest.raises(LlmError) as caught:
        store.save(LlmDraft(provider="anthropic", model="claude-test", api_key=KEY))
    assert caught.value.code == "llm_config_unavailable"
    assert "fake-sensitive-error" not in str(caught.value)
    assert path.read_bytes() == original
    assert list(tmp_path.glob(".llm-settings-*.tmp")) == []


@pytest.mark.parametrize("content", [b"fake-file-secret", b"x" * 16_385, b'{"version":3}'])
def test_corrupted_private_settings_fail_safely(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(content)
    with pytest.raises(LlmError) as caught:
        LlmConfigurationStore(settings(), path).catalog()
    assert caught.value.code == "llm_config_unavailable"
    assert "fake-file-secret" not in str(caught.value)


@pytest.mark.parametrize(
    "changes",
    [
        {"provider": "unknown"},
        {"model": "https://evil.example/model"},
        {"model": "../secret"},
        {"model": "model?key=secret"},
        {"model": "model\nheader"},
        {"api_key": "key\nheader"},
        {"base_url": "https://evil.example"},
        {"api_key": "x" * 2049},
    ],
)
def test_draft_rejects_unsafe_provider_arguments(changes: dict) -> None:
    payload = {"provider": "openai", "model": "model-test", **changes}
    with pytest.raises(ValidationError):
        LlmDraft.model_validate(payload)


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini"])
async def test_connection_uses_only_provider_metadata_with_correct_headers(provider: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert not request.url.query
        expected = {
            "openai": "https://api.openai.com/v1/models/model-test",
            "anthropic": "https://api.anthropic.com/v1/models/model-test",
            "gemini": "https://generativelanguage.googleapis.com/v1beta/models/model-test",
        }
        assert str(request.url) == expected[provider]
        if provider == "gemini":
            assert request.headers["x-goog-api-key"] == KEY
            assert "authorization" not in request.headers
            return httpx.Response(200, json={"name": "models/model-test"})
        assert request.headers["authorization"] == f"Bearer {KEY}"
        if provider == "anthropic":
            assert request.headers["anthropic-version"] == "2026-10-21"
        return httpx.Response(
            200, json={"id": "model-test", "object" if provider == "openai" else "type": "model"}
        )

    result = await check_connection(
        provider, "model-test", SecretStr(KEY), transport=httpx.MockTransport(handler)
    )
    assert result.resolved_model == "model-test"
    assert result.latency_ms >= 0
    assert KEY not in result.model_dump_json()


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (400, "llm_request_rejected"),
        (401, "llm_auth_failed"),
        (403, "llm_access_denied"),
        (404, "llm_model_not_found"),
        (429, "llm_rate_limited"),
        (302, "llm_unavailable"),
        (500, "llm_unavailable"),
    ],
)
async def test_provider_errors_are_safe_and_not_retried(status: int, code: str) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, headers={"location": "https://evil.example"}, text=KEY)

    with pytest.raises(LlmError) as caught:
        await check_connection(
            "openai", "test-model", SecretStr(KEY), transport=httpx.MockTransport(handler)
        )
    assert caught.value.code == code
    assert KEY not in str(caught.value)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "kind", ["timeout", "network", "bad-json", "bad-shape", "too-large", "key-echo"]
)
async def test_connection_failures_are_bounded_and_redacted(kind: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if kind in {"timeout", "network"}:
            exception = httpx.ReadTimeout if kind == "timeout" else httpx.ConnectError
            raise exception(KEY, request=request)
        if kind == "bad-json":
            return httpx.Response(200, text=KEY)
        if kind == "bad-shape":
            return httpx.Response(200, json={"id": "test-model"})
        if kind == "too-large":
            return httpx.Response(200, content=b"x" * 65_537)
        return httpx.Response(200, json={"id": KEY, "object": "model"})

    with pytest.raises(LlmError) as caught:
        await check_connection(
            "openai", "test-model", SecretStr(KEY), transport=httpx.MockTransport(handler)
        )
    expected = {"timeout": "llm_timeout", "network": "llm_unavailable"}.get(
        kind, "llm_invalid_response"
    )
    assert caught.value.code == expected
    assert KEY not in str(caught.value)


@pytest.fixture
def application(tmp_path: Path):
    return create_app(settings(), llm_settings_path=tmp_path / "settings.json")


@pytest.fixture
async def client(application):
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://127.0.0.1:8001"
        ) as http:
            yield http


async def test_api_saves_and_returns_only_public_settings(client: httpx.AsyncClient) -> None:
    response = await client.get(BASE + "/configuration")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["active_provider"] == "openai"
    assert response.json()["providers"][0]["key_configured"] is True
    response = await client.post(
        BASE + "/configuration",
        json={"provider": "gemini", "model": "models/gemini-test", "api_key": KEY},
    )
    assert response.status_code == 200
    assert response.json()["active_provider"] == "gemini"
    assert response.json()["providers"][2]["model"] == "gemini-test"
    assert KEY not in response.text
    assert "fake-env-secret" not in response.text
    assert (await client.get(BASE + "/configuration")).json() == response.json()


async def test_unsaved_test_uses_draft_key_without_persistence(
    client: httpx.AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def connection(provider, model, key):
        assert (provider, model, key.get_secret_value()) == ("anthropic", "claude-test", KEY)
        return LlmConnectionResult(
            provider=provider, model=model, resolved_model=model, latency_ms=5
        )

    monkeypatch.setattr(llm, "test_llm_connection", connection)
    response = await client.post(
        BASE + "/test-connection",
        json={"provider": "anthropic", "model": "claude-test", "api_key": KEY},
    )
    assert response.status_code == 200
    assert KEY not in response.text
    assert not (tmp_path / "settings.json").exists()
    assert (await client.get(BASE + "/configuration")).json()["active_provider"] == "openai"


async def test_missing_key_prevents_provider_call(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = Mock(side_effect=AssertionError("No network call without credentials"))
    monkeypatch.setattr(llm, "test_llm_connection", provider)
    response = await client.post(
        BASE + "/test-connection", json={"provider": "gemini", "model": "gemini-test"}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "llm_key_missing"
    provider.assert_not_called()


async def test_reuses_environment_key_for_connection(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def connection(provider, model, key):
        assert key.get_secret_value() == "fake-env-secret"
        return LlmConnectionResult(
            provider=provider, model=model, resolved_model=model, latency_ms=0
        )

    monkeypatch.setattr(llm, "test_llm_connection", connection)
    assert (
        await client.post(
            BASE + "/test-connection", json={"provider": "openai", "model": "test-model"}
        )
    ).status_code == 200


@pytest.mark.parametrize(
    "payload",
    [
        {"provider": "invalid", "model": "test", "api_key": KEY},
        {"provider": "openai", "model": "test", "api_key": {"secret": KEY}},
        {"provider": "openai", "model": "test", "api_key": KEY, "base_url": "https://evil.example"},
    ],
)
async def test_request_validation_does_not_echo_api_keys(
    client: httpx.AsyncClient, payload: dict
) -> None:
    response = await client.post(BASE + "/configuration", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_request"
    assert KEY not in response.text


async def test_blocks_remote_clients_and_untrusted_origins(
    application, client: httpx.AsyncClient
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application, client=("203.0.113.10", 123)),
        base_url="http://127.0.0.1:8001",
    ) as remote:
        assert (await remote.get(BASE + "/configuration")).status_code == 403
    response = await client.post(
        BASE + "/configuration",
        headers={"Origin": "https://evil.example"},
        json={"provider": "openai", "model": "test", "api_key": KEY},
    )
    assert response.status_code == 403
    response = await client.get(
        BASE + "/configuration",
        headers={"Origin": "http://localhost:5173", "sec-fetch-site": "cross-site"},
    )
    assert response.status_code == 200


async def test_only_one_connection_test_runs_at_a_time(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release = asyncio.Event(), asyncio.Event()

    async def connection(provider, model, key):
        entered.set()
        await release.wait()
        return LlmConnectionResult(
            provider=provider, model=model, resolved_model=model, latency_ms=0
        )

    monkeypatch.setattr(llm, "test_llm_connection", connection)
    body = {"provider": "openai", "model": "test-model"}
    first = asyncio.create_task(client.post(BASE + "/test-connection", json=body))
    await entered.wait()
    second = await client.post(BASE + "/test-connection", json=body)
    assert second.status_code == 429
    assert second.json()["detail"]["code"] == "llm_test_busy"
    release.set()
    assert (await first).status_code == 200


async def test_bounded_settings_requests_and_documented_schemas(client: httpx.AsyncClient) -> None:
    response = await client.post(
        BASE + "/configuration", content=b"x" * 4097, headers={"content-type": "application/json"}
    )
    assert response.status_code == 413
    schema = (await client.get("/openapi.json")).json()
    assert BASE + "/configuration" in schema["paths"]
    assert BASE + "/test-connection" in schema["paths"]


def test_all_provider_keys_are_hidden_in_settings_repr() -> None:
    config = Settings(_env_file=None, anthropic_api_key=KEY, gemini_api_key=KEY)
    assert KEY not in repr(config)
