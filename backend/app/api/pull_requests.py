"""Read-only PR previews using the GitHub reader and local patch selector."""

from fastapi import APIRouter
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.json_routes import SafeJSONRoute
from app.api.json_routes import api_error as _error
from app.core.config import Settings
from app.integrations.github import GitHubClientError, PullRequestMetadata
from app.integrations.github_url import InvalidPullRequestURL, parse_pull_request_url
from app.services.diff_selection import DiffSelection
from app.workflows.pr_preview import build_pr_preview_graph

_GITHUB_ERRORS = {
    "github_not_found": (404, "Pull request not found. Check the URL and use a public repository."),
    "github_private_repository": (422, "Only public GitHub repositories are supported."),
    "github_forbidden": (403, "GitHub denied access to this pull request."),
    "github_rate_limited": (503, "GitHub's rate limit was reached. Try again later."),
    "github_auth_failed": (503, "The server could not authenticate with GitHub."),
    "github_timeout": (504, "Fetching GitHub's pull request timed out. Try again later."),
    "github_unavailable": (503, "GitHub is unavailable. Try again later."),
    "github_invalid_response": (502, "GitHub returned invalid pull request data."),
    "github_request_failed": (502, "GitHub could not return this pull request."),
    "github_redirect": (422, "Submit the pull request URL for the current repository location."),
    "github_too_many_files": (422, "This pull request exceeds the 300-file fetch limit."),
    "github_response_too_large": (422, "GitHub's response exceeded the supported size limit."),
    "github_pr_changed": (409, "The pull request changed while fetching files. Try again."),
    "github_incomplete_files": (502, "GitHub returned an incomplete file list. Try again later."),
}


class PullRequestPreviewRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)

    pr_url: str = Field(
        min_length=1,
        max_length=2048,
        examples=["https://github.com/fastapi/fastapi/pull/16780"],
    )

    @field_validator("pr_url")
    @classmethod
    def validate_pr_url(cls, value: str) -> str:
        return parse_pull_request_url(value).pr_url


class PullRequestPreviewResponse(BaseModel):
    metadata: PullRequestMetadata
    selection: DiffSelection


class PreviewErrorDetail(BaseModel):
    code: str
    message: str


class PreviewErrorResponse(BaseModel):
    detail: PreviewErrorDetail


def _invalid_request() -> JSONResponse:
    return _error(422, "invalid_request", "Send a JSON object containing only a pr_url string.")


class _PreviewRoute(SafeJSONRoute):
    """Bound input before JSON parsing and omit raw input from validation errors."""

    def invalid_request(self, error: RequestValidationError | None = None) -> JSONResponse:
        if error and any(item.get("loc") == ("body", "pr_url") for item in error.errors()):
            return _error(422, "invalid_pr_url", str(InvalidPullRequestURL()))
        return _invalid_request()


def create_pull_requests_router(settings: Settings) -> APIRouter:
    preview_graph = build_pr_preview_graph(settings)
    router = APIRouter(
        prefix="/api/v1/pull-requests", tags=["pull requests"], route_class=_PreviewRoute
    )

    @router.post(
        "/preview",
        response_model=PullRequestPreviewResponse,
        summary="Preview public pull request changes",
        responses={
            status: {"model": PreviewErrorResponse, "description": description}
            for status, description in {
                403: "GitHub denied access",
                404: "Pull request not found or inaccessible",
                409: "Pull request changed during retrieval",
                413: "Request body exceeds 4096 bytes",
                415: "Content-Type must be application/json",
                422: "Invalid request or unsupported pull request",
                502: "Invalid or incomplete GitHub response",
                503: "GitHub access, rate limit, or availability problem",
                504: "GitHub request timed out",
            }.items()
        },
    )
    async def preview(
        payload: PullRequestPreviewRequest,
    ) -> PullRequestPreviewResponse | JSONResponse:
        """Fetch metadata and select patches. No AI analysis or database writes."""
        try:
            result = await preview_graph.ainvoke({"pr_url": payload.pr_url})
        except GitHubClientError as exc:
            # Keep the public API message independent of any upstream error text.
            code = exc.code if exc.code in _GITHUB_ERRORS else "github_request_failed"
            status, message = _GITHUB_ERRORS[code]
            return _error(status, code, message)
        return PullRequestPreviewResponse(**result)

    return router
