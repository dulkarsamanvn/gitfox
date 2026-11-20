"""Selection is deterministic local processing; no database or model API is needed."""

import httpx
import pytest

from app.core.config import Settings
from app.integrations.github import GitHubClient
from app.integrations.github_files import PullRequestFile
from app.services.diff_selection import select_diffs

REPLACEMENT = "@@ -1 +1 @@\n-old\n+new"


def changed_file(
    filename: str = "src/review.py",
    *,
    patch: str | None = REPLACEMENT,
    additions: int = 1,
    deletions: int = 1,
    **overrides,
) -> PullRequestFile:
    return PullRequestFile(
        filename=filename,
        status="modified",
        additions=additions,
        deletions=deletions,
        changes=additions + deletions,
        patch=patch,
        **overrides,
    )


def limits(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def test_accounts_for_every_file_without_retaining_skipped_patches() -> None:
    files = [
        changed_file(),
        changed_file("logo.png", patch=None),
        changed_file("dist/bundle.js"),
        changed_file("package-lock.json"),
        changed_file("src/other.py", patch=None),
    ]
    original = [file.model_dump() for file in files]

    result = select_diffs(files, settings=limits())

    assert [file.filename for file in result.selected] == ["src/review.py"]
    assert [(file.filename, file.reason) for file in result.skipped] == [
        ("logo.png", "binary_file"),
        ("dist/bundle.js", "generated_file"),
        ("package-lock.json", "lock_file"),
        ("src/other.py", "missing_patch"),
    ]
    assert (result.files_seen, result.files_selected, result.files_skipped) == (5, 1, 4)
    assert result.patch_chars == len(REPLACEMENT)
    assert result.files_seen == result.files_selected + result.files_skipped
    assert result.selected[0].patch == REPLACEMENT
    assert all("patch" not in file.model_dump() for file in result.skipped)
    assert REPLACEMENT not in repr(result)
    assert result.model_dump()["files_selected"] == 1
    assert "files_reviewed" not in result.model_dump()
    assert [file.model_dump() for file in files] == original
    assert select_diffs(files, settings=limits()) == result


def test_empty_input_has_zero_coverage() -> None:
    result = select_diffs((), settings=limits())
    assert result.selected == result.skipped == ()
    assert (result.files_seen, result.files_selected, result.files_skipped, result.patch_chars) == (
        0,
        0,
        0,
        0,
    )


@pytest.mark.parametrize(
    "filename",
    [
        "frontend/App.tsx",
        "schema.json",
        "docs/README.md",
        ".github/workflows/ci.yml",
        "Dockerfile.prod",
        "Makefile",
        "src/日本語/my file.PY",
        "src/vendor.py",
        "icon.svg",
    ],
)
def test_accepts_supported_text_paths(filename: str) -> None:
    result = select_diffs([changed_file(filename)], settings=limits())
    assert result.selected[0].filename == filename
    assert result.skipped == ()


@pytest.mark.parametrize("patch", [None, "", " \n\t\r\n"])
def test_missing_or_empty_patches_have_a_reason(patch: str | None) -> None:
    result = select_diffs([changed_file(patch=patch)], settings=limits())
    assert result.selected == ()
    assert result.skipped[0].reason == "missing_patch"


@pytest.mark.parametrize(
    ("filename", "reason"),
    [
        ("src/__generated__/api.ts", "generated_file"),
        ("frontend/node_modules/a/index.js", "generated_file"),
        ("vendor/library.php", "generated_file"),
        ("app/client.generated.ts", "generated_file"),
        ("app.min.js", "generated_file"),
        ("bundle.js.map", "generated_file"),
        ("message_pb2.py", "generated_file"),
        ("message.pb.go", "generated_file"),
        ("poetry.lock", "lock_file"),
        ("Cargo.lock", "lock_file"),
        ("pnpm-lock.yaml", "lock_file"),
        ("go.sum", "lock_file"),
        ("npm-shrinkwrap.json", "lock_file"),
        ("Package.resolved", "lock_file"),
        ("assets/PHOTO.JPG", "binary_file"),
        ("archive.zip", "binary_file"),
        ("src/file.unknown", "unsupported_file_type"),
        ("script", "unsupported_file_type"),
    ],
)
def test_path_filters_have_stable_reasons(filename: str, reason: str) -> None:
    result = select_diffs([changed_file(filename)], settings=limits())
    assert result.selected == ()
    assert result.skipped[0].reason == reason


def test_selects_first_eligible_files_and_keeps_accounting_after_limit() -> None:
    files = [
        changed_file("logo.png"),
        changed_file("z.py"),
        changed_file("a.py"),
        changed_file("package-lock.json"),
    ]
    result = select_diffs(files, settings=limits(max_review_files=1))
    assert [file.filename for file in result.selected] == ["z.py"]
    assert [(file.filename, file.reason) for file in result.skipped] == [
        ("logo.png", "binary_file"),
        ("a.py", "file_limit_exceeded"),
        ("package-lock.json", "lock_file"),
    ]
    assert result.files_seen == 4


@pytest.mark.parametrize(
    ("limit", "selected"), [(len(REPLACEMENT), True), (len(REPLACEMENT) - 1, False)]
)
def test_per_file_patch_limit_boundary(limit: int, selected: bool) -> None:
    result = select_diffs([changed_file()], settings=limits(max_file_patch_chars=limit))
    assert bool(result.selected) is selected
    if not selected:
        assert result.skipped[0].reason == "patch_too_large"


def test_total_patch_budget_has_an_inclusive_boundary() -> None:
    files = [changed_file(f"src/{index}.py") for index in range(3)]
    result = select_diffs(files, settings=limits(max_patch_chars=2 * len(REPLACEMENT)))
    assert result.files_selected == 2
    assert result.patch_chars == 2 * len(REPLACEMENT)
    assert result.skipped[0].reason == "patch_budget_exceeded"


def test_total_budget_can_be_smaller_than_one_file_budget() -> None:
    result = select_diffs([changed_file()], settings=limits(max_patch_chars=len(REPLACEMENT) - 1))
    assert result.selected == ()
    assert result.skipped[0].reason == "patch_budget_exceeded"
    assert result.patch_chars == 0


@pytest.mark.parametrize(
    ("limit_overrides", "reason"),
    [
        ({"max_file_patch_chars": 50}, "patch_too_large"),
        ({"max_patch_chars": 50}, "patch_budget_exceeded"),
    ],
)
def test_skips_large_file_and_still_selects_later_small_file(
    limit_overrides: dict, reason: str
) -> None:
    long_patch = "@@ -1 +1 @@\n-old\n+" + "x" * 100
    result = select_diffs(
        [changed_file("big.py", patch=long_patch), changed_file("small.py")],
        settings=limits(**limit_overrides),
    )
    assert [file.filename for file in result.selected] == ["small.py"]
    assert result.skipped[0].reason == reason
    assert result.patch_chars == len(REPLACEMENT)


def test_fills_remaining_budget_with_a_later_smaller_patch() -> None:
    tiny_patch = "@@ -0,0 +1 @@\n+x"
    total = len(REPLACEMENT) + len(tiny_patch)
    result = select_diffs(
        [
            changed_file("first.py"),
            changed_file("second.py"),
            changed_file("tiny.py", patch=tiny_patch, additions=1, deletions=0),
        ],
        settings=limits(max_patch_chars=total),
    )
    assert [file.filename for file in result.selected] == ["first.py", "tiny.py"]
    assert result.skipped[0].filename == "second.py"
    assert result.skipped[0].reason == "patch_budget_exceeded"
    assert result.patch_chars == total


@pytest.mark.parametrize(
    ("patch", "additions", "deletions"),
    [
        ("@@ -0,0 +1,2 @@\n+first\n+second", 2, 0),
        ("@@ -1,2 +0,0 @@\n-first\n-second", 0, 2),
        ("@@ -1,2 +1,2 @@ function\n context\n-old\n+new\n@@ -10 +10 @@\n-x\n+y\n", 2, 2),
        (
            "@@ -1 +1 @@\n-old\n\\ No newline at end of file\n+new\n\\ No newline at end of file",
            1,
            1,
        ),
        ("@@ -1 +1 @@\r\n-old\r\n+new\r\n", 1, 1),
        ("@@ -1 +1 @@\n-old\n+text\u2028inside one source line", 1, 1),
        ("@@ -1,2 +1,2 @@\n \n-old\n+new", 1, 1),
    ],
)
def test_selects_complete_patches_without_modifying_text(
    patch: str, additions: int, deletions: int
) -> None:
    file = changed_file(patch=patch, additions=additions, deletions=deletions)
    result = select_diffs([file], settings=limits())
    assert result.skipped == ()
    assert result.selected[0].patch == patch
    assert result.patch_chars == len(patch)


def test_renames_preserve_previous_path() -> None:
    file = PullRequestFile(
        filename="src/new.py",
        previous_filename="src/old.py",
        status="renamed",
        additions=1,
        deletions=1,
        changes=2,
        patch=REPLACEMENT,
    )
    result = select_diffs([file], settings=limits())
    assert result.selected[0].previous_filename == "src/old.py"


@pytest.mark.parametrize(
    ("patch", "additions", "deletions", "reason"),
    [
        ("@@ -1,2 +1,2 @@\n-old\n+new", 1, 1, "incomplete_patch"),
        (REPLACEMENT, 2, 2, "incomplete_patch"),
        ("@@ -1,2 +1,2 @@\n-old\n+new\n@@ -10 +10 @@\n-x\n+y", 2, 2, "incomplete_patch"),
        ("fake-sensitive-source", 1, 1, "invalid_patch"),
        ("@@ -x +1 @@\n-old\n+new", 1, 1, "invalid_patch"),
        ("@@ -0 +1 @@\n-old\n+new", 1, 1, "invalid_patch"),
        ("@@ -1 +1 @@\n-old\n+new\n+extra", 2, 1, "invalid_patch"),
        ("@@ -1 +1 @@\n?old\n+new", 1, 1, "invalid_patch"),
        ("@@ -1 +1 @@\n\\ No newline at end of file\n-old\n+new", 1, 1, "invalid_patch"),
        (
            "@@ -1 +1 @@\n-old\n+new\n\\ No newline at end of file\n\\ No newline at end of file",
            1,
            1,
            "invalid_patch",
        ),
        ("@@ -1 +1 @@\n-old\n+new\x00", 1, 1, "invalid_patch"),
        ("@@ -1 +1 @@\n context", 0, 0, "no_text_changes"),
    ],
)
def test_skips_invalid_or_incomplete_diffs_with_metadata_only(
    patch: str, additions: int, deletions: int, reason: str
) -> None:
    result = select_diffs(
        [changed_file(patch=patch, additions=additions, deletions=deletions)], settings=limits()
    )
    assert result.selected == ()
    assert result.skipped[0].reason == reason
    assert "patch" not in result.skipped[0].model_dump()
    assert patch not in repr(result)


@pytest.mark.anyio
async def test_selects_from_actual_github_reader_result() -> None:
    metadata = {
        "number": 42,
        "title": "Fix a guard",
        "user": {"login": "contributor"},
        "state": "open",
        "merged": False,
        "changed_files": 2,
        "base": {"sha": "a" * 40, "repo": {"full_name": "example/project", "private": False}},
        "head": {"sha": "b" * 40},
    }
    files = [changed_file().model_dump(), changed_file("logo.png", patch=None).model_dump()]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=files if request.url.path.endswith("/files") else metadata)

    settings = limits()
    async with GitHubClient(settings, transport=httpx.MockTransport(handler)) as github:
        fetched = await github.get_pull_request_files("https://github.com/example/project/pull/42")
    result = select_diffs(fetched.files, settings=settings)
    assert result.files_seen == fetched.metadata.changed_files == 2
    assert result.files_selected == 1
    assert result.skipped[0].reason == "binary_file"
