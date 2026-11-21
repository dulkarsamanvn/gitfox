"""Shared syntax checks for repository-relative file paths."""

import re


def validate_repository_path(value: str) -> str:
    """Preserve safe path spelling; existence and diff membership are checked later."""
    if (
        "\\" in value
        or re.match(r"^[A-Za-z]:", value) is not None
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("Expected a relative repository file path")
    return value
