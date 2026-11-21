"""Validated changed-file data; patches remain untrusted text in memory."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.repository_paths import validate_repository_path


class PullRequestFile(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, hide_input_in_errors=True)

    filename: str = Field(min_length=1)
    previous_filename: str | None = None
    status: Literal["added", "removed", "modified", "renamed", "copied", "changed", "unchanged"]
    additions: int = Field(ge=0)
    deletions: int = Field(ge=0)
    changes: int = Field(ge=0)
    patch: str | None = Field(default=None, repr=False)

    @field_validator("filename", "previous_filename")
    @classmethod
    def validate_relative_path(cls, value: str | None) -> str | None:
        return validate_repository_path(value) if value is not None else None

    @model_validator(mode="after")
    def validate_change_metadata(self) -> Self:
        if self.changes != self.additions + self.deletions:
            raise ValueError("Change counts must match additions and deletions")
        if self.status == "renamed" and self.previous_filename is None:
            raise ValueError("Renamed files must include their previous filename")
        return self
