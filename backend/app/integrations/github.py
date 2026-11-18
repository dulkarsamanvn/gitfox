"""Read public PR metadata from GitHub without fetching arbitrary URLs."""

import asyncio
import json
from types import TracebackType
from typing import Annotated, Literal, Self

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import Settings, get_settings
from app.integrations.github_url import PullRequestRef, parse_pull_request_url

_MAX_RESPONSE_BYTES = 1_048_576
_MAX_ATTEMPTS = 2
_REQUEST_DEADLINE_SECONDS = 15
_SHA = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]


class GitHubClientError(Exception):
    """Stable errors for a future API route; never include raw upstream errors."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class PullRequestMetadata(BaseModel):
    """The small, validated subset of GitHub's response needed by a review."""

    model_config = ConfigDict(strict=True, frozen=True, hide_input_in_errors=True)

    owner: str
    repository: str
    pr_number: int = Field(gt=0, le=2_147_483_647)
    pr_url: str
    title: str = Field(min_length=1)
    author: str | None
    state: Literal["open", "closed"]
    merged: bool
    base_sha: _SHA
    head_sha: _SHA
    changed_files: int = Field(ge=0)


class GitHubClient:
    """Use as an async context manager so the HTTP connection pool is closed."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        settings = settings if settings is not None else get_settings()
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10",
            "User-Agent": "GitFox",
        }
        if settings.github_token is not None:
            headers["Authorization"] = f"Bearer {settings.github_token.get_secret_value()}"
        self._http = httpx.AsyncClient(
            base_url="https://api.github.com",
            headers=headers,
            timeout=httpx.Timeout(10, connect=5),
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=5),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )

    async def __aenter__(self) -> Self:
        await self._http.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._http.__aexit__(exc_type, exc_value, traceback)

    async def get_pull_request(self, pr_url: str) -> PullRequestMetadata:
        reference = parse_pull_request_url(pr_url)
        path = f"/repos/{reference.owner}/{reference.repository}/pulls/{reference.pr_number}"
        data = await self._get_json(path)
        return _parse_metadata(data, reference)

    async def _get_json(self, path: str) -> object:
        for attempt in range(_MAX_ATTEMPTS):
            try:
                # HTTPX timeouts bound inactivity; this also bounds slow streams.
                async with asyncio.timeout(_REQUEST_DEADLINE_SECONDS):
                    async with self._http.stream("GET", path) as response:
                        if response.status_code >= 500:
                            raise GitHubClientError(
                                "github_unavailable", "GitHub is unavailable. Try again later."
                            )
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
                                raise GitHubClientError(
                                    "github_response_too_large",
                                    "GitHub's PR metadata exceeded the response size limit.",
                                )
                            body.extend(chunk)
                        if response.status_code != 200:
                            raise _response_error(response, body)
                        try:
                            return json.loads(body)
                        except (ValueError, RecursionError):
                            raise _invalid_response() from None
            except (TimeoutError, httpx.TimeoutException):
                error = GitHubClientError("github_timeout", "GitHub timed out. Try again later.")
            except httpx.RequestError:
                error = GitHubClientError(
                    "github_unavailable", "Could not reach GitHub. Try again later."
                )
            except GitHubClientError as exc:
                if exc.code != "github_unavailable":
                    raise
                error = exc
            if attempt + 1 < _MAX_ATTEMPTS:
                await asyncio.sleep(0.5)
        raise error from None


def _invalid_response() -> GitHubClientError:
    return GitHubClientError("github_invalid_response", "GitHub returned invalid PR metadata.")


def _response_error(response: httpx.Response, body: bytearray) -> GitHubClientError:
    status = response.status_code
    if status in {403, 429}:
        # Secondary limits may arrive as 403 even with primary quota remaining.
        message = ""
        try:
            data = json.loads(body)
            if isinstance(data, dict) and isinstance(data.get("message"), str):
                message = data["message"].lower()
        except (ValueError, RecursionError):
            pass
        if (
            status == 429
            or response.headers.get("x-ratelimit-remaining") == "0"
            or "retry-after" in response.headers
            or "rate limit" in message
        ):
            return GitHubClientError(
                "github_rate_limited", "GitHub's rate limit was reached. Try again later."
            )
        return GitHubClientError("github_forbidden", "GitHub denied access to this pull request.")
    if status == 404:
        return GitHubClientError(
            "github_not_found", "Pull request not found. Check the URL and use a public repository."
        )
    if status == 401:
        return GitHubClientError(
            "github_auth_failed", "GitHub authentication failed. Check the backend GITHUB_TOKEN."
        )
    if status in {301, 302, 303, 307, 308}:
        return GitHubClientError(
            "github_redirect",
            "GitHub redirected this request. Submit the current repository PR URL.",
        )
    return GitHubClientError("github_request_failed", "GitHub could not return this pull request.")


def _parse_metadata(data: object, reference: PullRequestRef) -> PullRequestMetadata:
    try:
        if not isinstance(data, dict):
            raise ValueError
        base_repo = data["base"]["repo"]
        if type(base_repo["private"]) is not bool:
            raise ValueError
        if base_repo["private"]:
            raise GitHubClientError(
                "github_private_repository", "Only public GitHub repositories are supported."
            )
        returned_ref = parse_pull_request_url(
            f"https://github.com/{base_repo['full_name']}/pull/{data['number']}"
        )
        if (
            returned_ref.owner.lower() != reference.owner.lower()
            or returned_ref.repository.lower() != reference.repository.lower()
            or returned_ref.pr_number != reference.pr_number
        ):
            raise ValueError
        return PullRequestMetadata(
            owner=returned_ref.owner,
            repository=returned_ref.repository,
            pr_number=data["number"],
            pr_url=returned_ref.pr_url,
            title=data["title"],
            author=None if data["user"] is None else data["user"]["login"],
            state=data["state"],
            merged=data["merged"],
            base_sha=data["base"]["sha"],
            head_sha=data["head"]["sha"],
            changed_files=data["changed_files"],
        )
    except (KeyError, TypeError, ValueError):
        raise _invalid_response() from None
