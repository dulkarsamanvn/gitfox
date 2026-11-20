"""Exercise the HTTP preview with the real reader/selector and mocked GitHub."""

from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from app.api import pull_requests
from app.core.config import Settings
from app.integrations.github import GitHubClient, GitHubClientError
from app.main import create_app

pytestmark = pytest.mark.anyio
ENDPOINT = "/api/v1/pull-requests/preview"
PR_URL = "https://github.com/example/project/pull/42"
PATCH = "@@ -1 +1 @@\n-old\n+new"
FAKE_TOKEN = "fake-backend-token"


@pytest.fixture
def upstream(monkeypatch: pytest.MonkeyPatch) -> dict:
    def file(filename: str, patch: str | None = PATCH) -> dict:
        return {
            "filename": filename,
            "status": "modified",
            "additions": 1,
            "deletions": 1,
            "changes": 2,
            "patch": patch,
        }

    state = {
        "metadata": {
            "number": 42,
            "title": "Fix a guard",
            "user": {"login": "contributor"},
            "state": "open",
            "merged": False,
            "changed_files": 4,
            "base": {"sha": "a" * 40, "repo": {"full_name": "example/project", "private": False}},
            "head": {"sha": "b" * 40},
        },
        "files": [
            file("src/review.py"),
            file("logo.png", None),
            file("dist/bundle.js"),
            file("src/other.py"),
        ],
        "requests": [],
        "settings": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        assert request.method == "GET"
        assert request.url.host == "api.github.com"
        assert request.headers["authorization"] == f"Bearer {FAKE_TOKEN}"
        if request.url.path.endswith("/files"):
            assert request.url.path == "/repos/example/project/pulls/42/files"
            assert dict(request.url.params) == {"per_page": "100", "page": "1"}
            return httpx.Response(200, json=state["files"])
        assert str(request.url) == "https://api.github.com/repos/example/project/pulls/42"
        return httpx.Response(200, json=state["metadata"])

    def factory(settings: Settings) -> GitHubClient:
        state["settings"].append(settings)
        return GitHubClient(settings, transport=httpx.MockTransport(handler))

    monkeypatch.setattr(pull_requests, "GitHubClient", factory)
    return state


@pytest.fixture
async def client(upstream: dict) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(
        _env_file=None,
        github_token=FAKE_TOKEN,
        openai_api_key="fake-openai-key",
        max_review_files=1,
        cors_origins=["http://localhost:5173"],
    )
    application = create_app(settings)
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://testserver"
        ) as test_client:
            yield test_client


async def test_previews_metadata_selection_and_counts_without_a_database(
    client: httpx.AsyncClient, upstream: dict
) -> None:
    response = await client.post(ENDPOINT, json={"pr_url": PR_URL})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert result["metadata"]["title"] == "Fix a guard"
    assert result["metadata"]["pr_url"] == PR_URL
    assert result["metadata"]["head_sha"] == "b" * 40
    selection = result["selection"]
    assert selection["selected"][0]["filename"] == "src/review.py"
    assert selection["selected"][0]["patch"] == PATCH
    assert [(file["filename"], file["reason"]) for file in selection["skipped"]] == [
        ("logo.png", "binary_file"),
        ("dist/bundle.js", "generated_file"),
        ("src/other.py", "file_limit_exceeded"),
    ]
    assert (selection["files_seen"], selection["files_selected"], selection["files_skipped"]) == (
        4,
        1,
        3,
    )
    assert selection["patch_chars"] == len(PATCH)
    assert all("patch" not in file for file in selection["skipped"])
    assert "files_reviewed" not in selection
    assert "id" not in result
    assert len(upstream["requests"]) == 3
    assert upstream["settings"][0].max_review_files == 1
    assert upstream["settings"][0].database_url is None
    assert FAKE_TOKEN not in response.text
    assert "fake-openai-key" not in response.text


async def test_normalizes_url_before_fetching(client: httpx.AsyncClient, upstream: dict) -> None:
    response = await client.post(
        ENDPOINT, json={"pr_url": "HTTPS://GITHUB.COM/example/project/pull/42/"}
    )
    assert response.status_code == 200
    assert response.json()["metadata"]["pr_url"] == PR_URL
    assert len(upstream["requests"]) == 3


@pytest.mark.parametrize("count", [0, 4])
async def test_empty_or_all_skipped_results_are_valid_previews(
    client: httpx.AsyncClient, upstream: dict, count: int
) -> None:
    upstream["metadata"]["changed_files"] = count
    if count == 0:
        upstream["files"] = []
    else:
        for file in upstream["files"]:
            file["patch"] = None
    response = await client.post(ENDPOINT, json={"pr_url": PR_URL})
    assert response.status_code == 200
    result = response.json()["selection"]
    assert result["selected"] == []
    assert result["files_seen"] == result["files_skipped"] == count
    assert result["patch_chars"] == 0


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"pr_url": None},
        {"pr_url": 42},
        {"pr_url": True},
        {"pr_url": ""},
        {"pr_url": "x" * 2049},
        {"pr_url": "https://evil.example/project/pull/42"},
        {"pr_url": "http://127.0.0.1/private"},
        {"pr_url": "https://user:fake-input-secret@github.com/example/project/pull/42"},
        {"pr_url": PR_URL + "?token=fake-input-secret"},
    ],
)
async def test_invalid_urls_are_safe_and_never_fetch_github(
    client: httpx.AsyncClient, upstream: dict, payload: dict
) -> None:
    response = await client.post(ENDPOINT, json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_pr_url"
    assert "fake-input-secret" not in response.text
    assert response.headers["cache-control"] == "no-store"
    assert upstream["requests"] == upstream["settings"] == []


@pytest.mark.parametrize(
    "payload", [[], "fake-input-secret", {"pr_url": PR_URL, "github_token": "fake-input-secret"}]
)
async def test_rejects_wrong_body_shape_and_extra_fields(
    client: httpx.AsyncClient, upstream: dict, payload: object
) -> None:
    response = await client.post(ENDPOINT, json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_request"
    assert "fake-input-secret" not in response.text
    assert upstream["requests"] == []


@pytest.mark.parametrize(
    "body", [b'{"pr_url": "fake-input-secret"', b"\xff", b"[" * 1500 + b"]" * 1500]
)
async def test_malformed_json_errors_do_not_echo_input(
    client: httpx.AsyncClient, upstream: dict, body: bytes
) -> None:
    response = await client.post(
        ENDPOINT, content=body, headers={"content-type": "application/json"}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_request"
    assert "fake-input-secret" not in response.text
    assert upstream["requests"] == []


@pytest.mark.parametrize("size", [4096, 4097])
async def test_request_body_limit_boundary(
    client: httpx.AsyncClient, upstream: dict, size: int
) -> None:
    body = ('{"pr_url":"' + PR_URL + '"}').encode()
    body += b" " * (size - len(body))
    response = await client.post(
        ENDPOINT, content=body, headers={"content-type": "application/json"}
    )
    assert response.status_code == (200 if size == 4096 else 413)
    if size > 4096:
        assert response.json()["detail"]["code"] == "request_too_large"
        assert upstream["requests"] == []


async def test_streaming_request_limit_stops_reading_early(
    client: httpx.AsyncClient, upstream: dict
) -> None:
    async def body() -> AsyncIterator[bytes]:
        yield b"x" * 4096
        yield b"x"
        raise AssertionError("The endpoint should stop reading after the size limit")

    response = await client.post(
        ENDPOINT, content=body(), headers={"content-type": "application/json"}
    )
    assert response.status_code == 413
    assert upstream["requests"] == []


async def test_spoofed_content_length_cannot_bypass_limit(client: httpx.AsyncClient) -> None:
    response = await client.post(
        ENDPOINT,
        content=b"x" * 4097,
        headers={"content-type": "application/json", "content-length": "1"},
    )
    assert response.status_code == 413


@pytest.mark.parametrize("content_type", ["text/plain", "application/x-www-form-urlencoded"])
async def test_requires_json_content_type(
    client: httpx.AsyncClient, upstream: dict, content_type: str
) -> None:
    response = await client.post(
        ENDPOINT, content=b"fake-input-secret", headers={"content-type": content_type}
    )
    assert response.status_code == 415
    assert response.json()["detail"]["code"] == "unsupported_media_type"
    assert "fake-input-secret" not in response.text
    assert upstream["requests"] == []


async def test_accepts_json_charset_parameter(client: httpx.AsyncClient) -> None:
    response = await client.post(
        ENDPOINT,
        json={"pr_url": PR_URL},
        headers={"content-type": "application/json; charset=utf-8"},
    )
    assert response.status_code == 200


@pytest.mark.parametrize(
    ("code", "status"),
    [
        ("github_not_found", 404),
        ("github_private_repository", 422),
        ("github_forbidden", 403),
        ("github_rate_limited", 503),
        ("github_auth_failed", 503),
        ("github_timeout", 504),
        ("github_unavailable", 503),
        ("github_invalid_response", 502),
        ("github_request_failed", 502),
        ("github_redirect", 422),
        ("github_too_many_files", 422),
        ("github_response_too_large", 422),
        ("github_pr_changed", 409),
        ("github_incomplete_files", 502),
        ("unknown-error", 502),
    ],
)
async def test_maps_github_errors_to_safe_http_responses(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, code: str, status: int
) -> None:
    github = AsyncMock(spec=GitHubClient)
    github.__aenter__.return_value = github
    github.get_pull_request_files.side_effect = GitHubClientError(code, "fake-upstream-secret")
    monkeypatch.setattr(pull_requests, "GitHubClient", Mock(return_value=github))

    response = await client.post(ENDPOINT, json={"pr_url": PR_URL})

    assert response.status_code == status
    assert response.json()["detail"]["code"] == (
        "github_request_failed" if code == "unknown-error" else code
    )
    assert "fake-upstream-secret" not in response.text
    assert FAKE_TOKEN not in response.text
    assert response.headers["cache-control"] == "no-store"
    github.__aexit__.assert_awaited_once()


async def test_rejects_actual_private_metadata_before_file_requests(
    client: httpx.AsyncClient, upstream: dict
) -> None:
    upstream["metadata"]["base"]["repo"]["private"] = True
    response = await client.post(ENDPOINT, json={"pr_url": PR_URL})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "github_private_repository"
    assert len(upstream["requests"]) == 1


async def test_openapi_documents_request_and_response_models(client: httpx.AsyncClient) -> None:
    schema = (await client.get("/openapi.json")).json()
    operation = schema["paths"][ENDPOINT]["post"]
    assert operation["requestBody"]["required"] is True
    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/PullRequestPreviewRequest"
    }
    assert (
        schema["components"]["schemas"]["PullRequestPreviewRequest"]["additionalProperties"]
        is False
    )
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/PullRequestPreviewResponse"
    }
    assert operation["responses"]["422"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/PreviewErrorResponse"
    }
    assert (
        "selection" in schema["components"]["schemas"]["PullRequestPreviewResponse"]["properties"]
    )


async def test_allows_configured_frontend_origin(client: httpx.AsyncClient) -> None:
    response = await client.post(
        ENDPOINT, json={"pr_url": PR_URL}, headers={"origin": "http://localhost:5173"}
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
