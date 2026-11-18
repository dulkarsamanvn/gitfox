"""Exercise the GitHub reader without a token, database, or live network."""

import asyncio
import json
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import Settings
from app.integrations import github
from app.integrations.github import GitHubClient, GitHubClientError
from app.integrations.github_url import InvalidPullRequestURL

pytestmark = pytest.mark.anyio
PR_URL = "https://github.com/example/project/pull/42"


@pytest.fixture
def metadata() -> dict:
    return {
        "number": 42,
        "title": "Handle an empty result",
        "user": {"login": "contributor"},
        "state": "open",
        "merged": False,
        "base": {
            "sha": "a" * 40,
            "repo": {"full_name": "Example/Project", "private": False},
        },
        "head": {"sha": "b" * 40, "repo": None},
        "changed_files": 3,
        "body": "Untrusted instructions must not affect the reader.",
    }


@pytest.fixture(autouse=True)
def retry_sleep(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    sleep = AsyncMock()
    monkeypatch.setattr(github.asyncio, "sleep", sleep)
    return sleep


def make_client(handler, *, token: str | None = None) -> GitHubClient:
    settings = Settings(_env_file=None, github_token=SecretStr(token) if token else None)
    return GitHubClient(settings, transport=httpx.MockTransport(handler))


async def test_normalizes_public_pr_metadata(metadata: dict) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == "https://api.github.com/repos/example/project/pulls/42"
        assert "authorization" not in request.headers
        assert request.headers["accept"] == "application/vnd.github+json"
        assert request.headers["x-github-api-version"] == "2026-03-10"
        assert request.headers["user-agent"] == "GitFox"
        assert request.extensions["timeout"] == {"connect": 5, "read": 10, "write": 10, "pool": 10}
        return httpx.Response(200, json=metadata)

    async with make_client(handler) as client:
        result = await client.get_pull_request(PR_URL)

    assert result.model_dump() == {
        "owner": "Example",
        "repository": "Project",
        "pr_number": 42,
        "pr_url": "https://github.com/Example/Project/pull/42",
        "title": "Handle an empty result",
        "author": "contributor",
        "state": "open",
        "merged": False,
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "changed_files": 3,
    }


async def test_sends_only_configured_token(metadata: dict) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer fake-test-token"
        return httpx.Response(200, json=metadata)

    async with make_client(handler, token="fake-test-token") as client:
        await client.get_pull_request(PR_URL)


@pytest.mark.parametrize(("state", "merged"), [("closed", False), ("closed", True)])
async def test_closed_and_merged_prs(metadata: dict, state: str, merged: bool) -> None:
    metadata.update(state=state, merged=merged, user=None, changed_files=0)
    async with make_client(lambda _: httpx.Response(200, json=metadata)) as client:
        result = await client.get_pull_request(PR_URL)
    assert result.state == state
    assert result.merged is merged
    assert result.author is None
    assert result.changed_files == 0


async def test_rejects_invalid_url_before_network() -> None:
    handler = AsyncMock()
    async with make_client(handler) as client:
        with pytest.raises(InvalidPullRequestURL):
            await client.get_pull_request("https://127.0.0.1/private-token")
    handler.assert_not_called()


async def test_rejects_private_repo_even_when_token_can_access_it(metadata: dict) -> None:
    metadata["base"]["repo"]["private"] = True
    async with make_client(lambda _: httpx.Response(200, json=metadata)) as client:
        with pytest.raises(GitHubClientError) as caught:
            await client.get_pull_request(PR_URL)
    assert caught.value.code == "github_private_repository"


@pytest.mark.parametrize(
    ("status", "headers", "message", "code"),
    [
        (401, {}, "Bad credentials", "github_auth_failed"),
        (404, {}, "Not Found", "github_not_found"),
        (403, {}, "Resource not accessible", "github_forbidden"),
        (403, {"x-ratelimit-remaining": "0"}, "Forbidden", "github_rate_limited"),
        (403, {"retry-after": "60"}, "Forbidden", "github_rate_limited"),
        (403, {}, "You have exceeded a secondary rate limit.", "github_rate_limited"),
        (429, {}, "Too many requests", "github_rate_limited"),
        (422, {}, "Validation failed", "github_request_failed"),
        (304, {}, "Not modified", "github_request_failed"),
    ],
)
async def test_sanitizes_failures_without_retrying(
    status: int, headers: dict, message: str, code: str, retry_sleep: AsyncMock
) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, headers=headers, json={"message": message + " fake-secret"})

    async with make_client(handler, token="fake-test-token") as client:
        with pytest.raises(GitHubClientError) as caught:
            await client.get_pull_request(PR_URL)
    assert caught.value.code == code
    assert "fake-secret" not in str(caught.value)
    assert "fake-test-token" not in repr(caught.value)
    assert "api.github.com" not in str(caught.value)
    assert len(requests) == 1
    retry_sleep.assert_not_awaited()


async def test_never_follows_redirect_or_forwards_token() -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(301, headers={"location": "https://evil.example/token-collector"})

    async with make_client(handler, token="fake-test-token") as client:
        with pytest.raises(GitHubClientError) as caught:
            await client.get_pull_request(PR_URL)
    assert caught.value.code == "github_redirect"
    assert len(requests) == 1
    assert requests[0].url.host == "api.github.com"


@pytest.mark.parametrize("failure", ["server", "connect", "timeout"])
async def test_retries_transient_failure_once(
    metadata: dict, failure: str, retry_sleep: AsyncMock
) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            if failure == "server":
                return httpx.Response(503)
            exception = httpx.ReadTimeout if failure == "timeout" else httpx.ConnectError
            raise exception("fake-sensitive-network-details", request=request)
        return httpx.Response(200, json=metadata)

    async with make_client(handler) as client:
        result = await client.get_pull_request(PR_URL)
    assert result.pr_number == 42
    assert len(requests) == 2
    retry_sleep.assert_awaited_once_with(0.5)


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        ("server", "github_unavailable"),
        ("connect", "github_unavailable"),
        ("timeout", "github_timeout"),
    ],
)
async def test_retry_budget_is_bounded(failure: str, code: str, retry_sleep: AsyncMock) -> None:
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if failure == "server":
            return httpx.Response(502, text="fake-sensitive-network-details")
        exception = httpx.ReadTimeout if failure == "timeout" else httpx.ConnectError
        raise exception("fake-sensitive-network-details", request=request)

    async with make_client(handler) as client:
        with pytest.raises(GitHubClientError) as caught:
            await client.get_pull_request(PR_URL)
    assert caught.value.code == code
    assert "fake-sensitive-network-details" not in str(caught.value)
    assert len(requests) == 2
    retry_sleep.assert_awaited_once_with(0.5)


async def test_deadline_bounds_slow_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github, "_REQUEST_DEADLINE_SECONDS", 0.01)
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        await asyncio.Event().wait()
        raise AssertionError("The deadline should cancel the pending request")

    async with make_client(handler) as client:
        with pytest.raises(GitHubClientError) as caught:
            await client.get_pull_request(PR_URL)
    assert caught.value.code == "github_timeout"
    assert len(requests) == 2


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("number",), 43),
        (("number",), "42"),
        (("number",), True),
        (("title",), None),
        (("title",), ""),
        (("user",), {}),
        (("user",), "contributor"),
        (("state",), "merged"),
        (("merged",), "false"),
        (("base", "sha"), "invalid-sha"),
        (("head", "sha"), "b" * 39),
        (("base", "repo", "full_name"), "other/project"),
        (("base", "repo", "full_name"), "example/other"),
        (("base", "repo", "private"), "false"),
        (("base", "repo", "private"), None),
        (("changed_files",), -1),
        (("changed_files",), True),
        (("changed_files",), "3"),
    ],
)
async def test_rejects_inconsistent_or_malformed_metadata(
    metadata: dict, path: tuple, value: object
) -> None:
    target = metadata
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    async with make_client(lambda _: httpx.Response(200, json=metadata)) as client:
        with pytest.raises(GitHubClientError) as caught:
            await client.get_pull_request(PR_URL)
    assert caught.value.code == "github_invalid_response"


@pytest.mark.parametrize("data", [None, [], "fake-secret", {}, {"base": None}])
async def test_rejects_missing_or_wrong_response_shape(data: object) -> None:
    # Response(json=None) produces an empty body, so encode null explicitly.
    async with make_client(lambda _: httpx.Response(200, content=json.dumps(data))) as client:
        with pytest.raises(GitHubClientError) as caught:
            await client.get_pull_request(PR_URL)
    assert caught.value.code == "github_invalid_response"
    assert "fake-secret" not in str(caught.value)


@pytest.mark.parametrize("body", [b"not JSON fake-secret", b"\xff", b"[" * 2000 + b"]" * 2000])
async def test_rejects_invalid_json(body: bytes) -> None:
    async with make_client(lambda _: httpx.Response(200, content=body)) as client:
        with pytest.raises(GitHubClientError) as caught:
            await client.get_pull_request(PR_URL)
    assert caught.value.code == "github_invalid_response"
    assert "fake-secret" not in str(caught.value)


@pytest.mark.parametrize("body", [b"<html>fake-secret</html>", b"[" * 2000 + b"]" * 2000])
async def test_non_json_or_nested_access_errors_are_sanitized(body: bytes) -> None:
    async with make_client(lambda _: httpx.Response(403, content=body)) as client:
        with pytest.raises(GitHubClientError) as caught:
            await client.get_pull_request(PR_URL)
    assert caught.value.code == "github_forbidden"
    assert "fake-secret" not in str(caught.value)


class OversizedStream(httpx.AsyncByteStream):
    def __init__(self) -> None:
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"x" * 600_000
        yield b"x" * 600_000
        raise AssertionError("Stop reading once the response size limit is reached")

    async def aclose(self) -> None:
        self.closed = True


async def test_caps_streamed_responses_and_closes_them(retry_sleep: AsyncMock) -> None:
    stream = OversizedStream()
    async with make_client(lambda _: httpx.Response(200, stream=stream)) as client:
        with pytest.raises(GitHubClientError) as caught:
            await client.get_pull_request(PR_URL)
    assert caught.value.code == "github_response_too_large"
    assert stream.closed
    retry_sleep.assert_not_awaited()
