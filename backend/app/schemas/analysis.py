"""Provider-independent AI review output, before grounding and persistence."""

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.repository_paths import validate_repository_path
from app.models.finding import FindingCategory, FindingConfidence, FindingSeverity

REVIEW_ANALYSIS_SCHEMA_VERSION = "review-analysis-v1"
_MAX_OUTPUT_BYTES = 1_048_576


class ReviewFinding(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)

    # Enum fields accept JSON-style strings and resolve to the existing DB enums.
    severity: FindingSeverity = Field(strict=False, description="Potential impact of the issue.")
    category: FindingCategory = Field(strict=False, description="Kind of issue identified.")
    file_path: str = Field(
        min_length=1,
        max_length=4096,
        description="Exact repository-relative path from the selected changes.",
    )
    line: int | None = Field(
        ge=1,
        le=2_147_483_647,
        description="New-side changed line number, or null when no precise location is supported.",
    )
    title: str = Field(min_length=1, max_length=200, repr=False)
    explanation: str = Field(min_length=1, max_length=4000, repr=False)
    evidence: str = Field(
        min_length=1,
        max_length=4000,
        repr=False,
        description="Short excerpt from the supplied diff or context supporting this finding.",
    )
    suggestion: str = Field(min_length=1, max_length=4000, repr=False)
    confidence: FindingConfidence = Field(strict=False, description="Confidence in this finding.")

    @field_validator("severity", "category", "confidence", mode="before")
    @classmethod
    def require_enum_string(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("Expected an allowed string value")
        return value

    @field_validator("file_path")
    @classmethod
    def validate_file_path(cls, value: str) -> str:
        return validate_repository_path(value)

    @field_validator("title", "explanation", "evidence", "suggestion")
    @classmethod
    def reject_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Text must contain a non-whitespace character")
        return value  # Keep evidence and suggested code indentation intact.


class ReviewAnalysis(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", hide_input_in_errors=True)

    summary: str = Field(min_length=1, max_length=4000, repr=False)
    findings: list[ReviewFinding] = Field(max_length=50, repr=False)

    @field_validator("summary")
    @classmethod
    def reject_blank_summary(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Summary must contain a non-whitespace character")
        return value


class InvalidReviewOutput(ValueError):
    """Safe application error; never attach raw model output to this message."""

    code = "invalid_review_output"

    def __init__(self) -> None:
        super().__init__("AI review output did not match the expected format.")


def parse_review_analysis(output: str | bytes) -> ReviewAnalysis:
    """Validate bounded, complete JSON; reject coercion and unexpected metadata."""
    try:
        if not isinstance(output, (str, bytes)) or len(output) > _MAX_OUTPUT_BYTES:
            raise InvalidReviewOutput()
        if isinstance(output, str) and len(output.encode("utf-8")) > _MAX_OUTPUT_BYTES:
            raise InvalidReviewOutput()
        return ReviewAnalysis.model_validate_json(output)
    except (ValidationError, ValueError, RecursionError):
        raise InvalidReviewOutput() from None
