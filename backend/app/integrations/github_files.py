"""Validated changed-file data; patches remain untrusted text in memory."""

import re
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
        if value is not None and (
            "\\" in value
            or re.match(r"^[A-Za-z]:", value) is not None
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or any(ord(character) < 32 or ord(character) == 127 for character in value)
        ):
            raise ValueError("Expected a relative repository file path")
        return value

    @model_validator(mode="after")
    def validate_change_metadata(self) -> Self:
        if self.changes != self.additions + self.deletions:
            raise ValueError("Change counts must match additions and deletions")
        if self.status == "renamed" and self.previous_filename is None:
            raise ValueError("Renamed files must include their previous filename")
        return self
