"""Choose bounded, complete text patches and account for every skipped file."""

import re
from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.core.config import Settings, get_settings
from app.integrations.github_files import PullRequestFile

SkipReason = Literal[
    "generated_file",
    "lock_file",
    "binary_file",
    "unsupported_file_type",
    "missing_patch",
    "patch_too_large",
    "invalid_patch",
    "incomplete_patch",
    "no_text_changes",
    "file_limit_exceeded",
    "patch_budget_exceeded",
]

_GENERATED_DIRECTORIES = frozenset(
    {
        "generated",
        "__generated__",
        "node_modules",
        "vendor",
        "dist",
        "build",
        "coverage",
        "__pycache__",
        ".next",
        ".nuxt",
        ".venv",
        "venv",
        "env",
    }
)
_GENERATED_SUFFIXES = (
    ".min.js",
    ".min.css",
    ".map",
    "_pb2.py",
    "_pb2.pyi",
    "_pb2_grpc.py",
    ".pb.go",
)
_LOCK_FILENAMES = frozenset(
    {
        "package-lock.json",
        "npm-shrinkwrap.json",
        "pnpm-lock.yaml",
        "bun.lockb",
        "go.sum",
        "packages.lock.json",
        "package.resolved",
    }
)
_BINARY_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".avif",
        ".ico",
        ".bmp",
        ".pdf",
        ".woff",
        ".woff2",
        ".ttf",
        ".otf",
        ".zip",
        ".gz",
        ".7z",
        ".tar",
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".wasm",
        ".pyc",
        ".class",
        ".jar",
        ".bin",
        ".mp3",
        ".mp4",
    }
)
_TEXT_EXTENSIONS = frozenset(
    {
        ".py",
        ".pyi",
        ".js",
        ".jsx",
        ".mjs",
        ".cjs",
        ".ts",
        ".tsx",
        ".mts",
        ".cts",
        ".php",
        ".rb",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".kts",
        ".cs",
        ".c",
        ".h",
        ".cpp",
        ".hpp",
        ".cc",
        ".swift",
        ".scala",
        ".sh",
        ".bash",
        ".zsh",
        ".ps1",
        ".sql",
        ".html",
        ".css",
        ".scss",
        ".sass",
        ".vue",
        ".svelte",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".md",
        ".mdx",
        ".txt",
        ".xml",
        ".svg",
        ".graphql",
        ".gql",
        ".proto",
    }
)
_TEXT_FILENAMES = frozenset(
    {
        "dockerfile",
        "containerfile",
        "makefile",
        "gemfile",
        "rakefile",
        "jenkinsfile",
        ".gitignore",
        ".dockerignore",
        ".editorconfig",
        ".gitattributes",
        ".env.example",
    }
)
_HUNK_HEADER = re.compile(
    r"^@@ -([0-9]{1,10})(?:,([0-9]{1,10}))? \+([0-9]{1,10})(?:,([0-9]{1,10}))? @@(?: .*)?$"
)


class SelectedDiff(PullRequestFile):
    """A selected file always carries a nonempty, unchanged patch."""

    patch: str = Field(min_length=1, repr=False)


class SkippedFile(BaseModel):
    """Coverage metadata without keeping the skipped source patch."""

    model_config = ConfigDict(strict=True, frozen=True, hide_input_in_errors=True)

    filename: str
    previous_filename: str | None
    status: str
    additions: int = Field(ge=0)
    deletions: int = Field(ge=0)
    changes: int = Field(ge=0)
    reason: SkipReason


class DiffSelection(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, hide_input_in_errors=True)

    selected: tuple[SelectedDiff, ...]
    skipped: tuple[SkippedFile, ...]

    @computed_field
    @property
    def files_seen(self) -> int:
        return len(self.selected) + len(self.skipped)

    @computed_field
    @property
    def files_selected(self) -> int:
        return len(self.selected)

    @computed_field
    @property
    def files_skipped(self) -> int:
        return len(self.skipped)

    @computed_field
    @property
    def patch_chars(self) -> int:
        return sum(len(file.patch) for file in self.selected)


def select_diffs(
    files: Sequence[PullRequestFile], *, settings: Settings | None = None
) -> DiffSelection:
    """Keep eligible whole patches in input order; selected does not mean reviewed."""
    settings = settings if settings is not None else get_settings()
    selected: list[SelectedDiff] = []
    skipped: list[SkippedFile] = []
    patch_chars = 0
    for file in files:
        file_patch_chars = len(file.patch or "")
        reason = _eligibility_reason(file, settings.max_file_patch_chars)
        if reason is None and len(selected) >= settings.max_review_files:
            reason = "file_limit_exceeded"
        if reason is None and patch_chars + file_patch_chars > settings.max_patch_chars:
            reason = "patch_budget_exceeded"
        if reason is not None:
            skipped.append(SkippedFile(**file.model_dump(exclude={"patch"}), reason=reason))
            continue
        selected.append(SelectedDiff.model_validate(file.model_dump()))
        patch_chars += file_patch_chars
    return DiffSelection(selected=tuple(selected), skipped=tuple(skipped))


def _eligibility_reason(file: PullRequestFile, max_file_chars: int) -> SkipReason | None:
    path = PurePosixPath(file.filename)
    name = path.name.lower()
    suffix = path.suffix.lower()
    if (
        any(part.lower() in _GENERATED_DIRECTORIES for part in path.parts[:-1])
        or name.endswith(_GENERATED_SUFFIXES)
        or ".generated." in name
    ):
        return "generated_file"
    if name in _LOCK_FILENAMES or name.endswith(".lock"):
        return "lock_file"
    if suffix in _BINARY_EXTENSIONS:
        return "binary_file"
    if (
        suffix not in _TEXT_EXTENSIONS
        and name not in _TEXT_FILENAMES
        and not name.startswith(("dockerfile.", "containerfile."))
    ):
        return "unsupported_file_type"
    if file.patch is None or not file.patch.strip():
        return "missing_patch"
    if len(file.patch) > max_file_chars:
        return "patch_too_large"
    return _patch_reason(file.patch, file.additions, file.deletions)


def _patch_reason(patch: str, additions: int, deletions: int) -> SkipReason | None:
    """Check hunk lengths and change totals to detect malformed/truncated patches.

    Finding-to-line mapping belongs to the later diff mapper. Keep source text
    untouched here, including CRLF and Git's no-final-newline markers.
    """
    if "\x00" in patch:
        return "invalid_patch"
    lines = patch.split("\n")
    if lines[-1] == "":
        lines.pop()
    old_remaining = new_remaining = added = deleted = 0
    has_hunk = previous_content = False
    for raw_line in lines:
        line = raw_line.removesuffix("\r")
        if line.startswith("@@"):
            if old_remaining or new_remaining:
                return "incomplete_patch"
            header = _HUNK_HEADER.fullmatch(line)
            if header is None:
                return "invalid_patch"
            old_start, old_count, new_start, new_count = header.groups()
            old_remaining = int(old_count) if old_count is not None else 1
            new_remaining = int(new_count) if new_count is not None else 1
            if (old_remaining and int(old_start) == 0) or (new_remaining and int(new_start) == 0):
                return "invalid_patch"
            has_hunk, previous_content = True, False
            continue
        if not has_hunk:
            return "invalid_patch"
        if line == "\\ No newline at end of file":
            if not previous_content:
                return "invalid_patch"
            previous_content = False
            continue
        if line.startswith("+"):
            added += 1
            new_remaining -= 1
        elif line.startswith("-"):
            deleted += 1
            old_remaining -= 1
        elif line.startswith(" "):
            old_remaining -= 1
            new_remaining -= 1
        else:
            return "invalid_patch"
        if old_remaining < 0 or new_remaining < 0:
            return "invalid_patch"
        previous_content = True
    if old_remaining or new_remaining or (added, deleted) != (additions, deletions):
        return "incomplete_patch"
    if not has_hunk:
        return "invalid_patch"
    if added + deleted == 0:
        return "no_text_changes"
    return None
