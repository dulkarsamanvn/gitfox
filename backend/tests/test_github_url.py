from dataclasses import FrozenInstanceError

import pytest

from app.integrations.github_url import (
    InvalidPullRequestURL,
    PullRequestRef,
    parse_pull_request_url,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://github.com/octocat/Hello-World/pull/123",
            PullRequestRef("octocat", "Hello-World", 123),
        ),
        (
            "https://github.com/dulkarsamanvn/gitfox/pull/1",
            PullRequestRef("dulkarsamanvn", "gitfox", 1),
        ),
        (
            "https://github.com/an-org/repo_name.v2/pull/42/",
            PullRequestRef("an-org", "repo_name.v2", 42),
        ),
        (
            "HTTPS://GITHUB.COM/An-Org/Repo/pull/7",
            PullRequestRef("An-Org", "Repo", 7),
        ),
        (
            "https://github.com/a/.github/pull/1",
            PullRequestRef("a", ".github", 1),
        ),
        (
            f"https://github.com/{'a' * 39}/{'b' * 100}/pull/2147483647",
            PullRequestRef("a" * 39, "b" * 100, 2_147_483_647),
        ),
    ],
)
def test_extracts_pr_identifiers(url: str, expected: PullRequestRef) -> None:
    result = parse_pull_request_url(url)

    assert result == expected
    assert result.pr_url == (
        f"https://github.com/{expected.owner}/{expected.repository}/pull/{expected.pr_number}"
    )


@pytest.mark.parametrize(
    "url",
    [
        "",
        "github.com/owner/repo/pull/1",
        "//github.com/owner/repo/pull/1",
        "http://github.com/owner/repo/pull/1",
        "ftp://github.com/owner/repo/pull/1",
        "file:///owner/repo/pull/1",
        "https://example.com/owner/repo/pull/1",
        "https://api.github.com/owner/repo/pull/1",
        "https://www.github.com/owner/repo/pull/1",
        "https://github.com.example.com/owner/repo/pull/1",
        "https://github.com./owner/repo/pull/1",
        "https://127.0.0.1/owner/repo/pull/1",
        "https://[::1]/owner/repo/pull/1",
        "https://[github.com/owner/repo/pull/1",
        "https://user:fake-password@github.com/owner/repo/pull/1",
        "https://user@github.com/owner/repo/pull/1",
        "https://github.com@evil.example/owner/repo/pull/1",
        "https://github.com:443/owner/repo/pull/1",
        "https://github.com:not-a-port/owner/repo/pull/1",
        "https://github.com/owner/repo",
        "https://github.com/owner/repo/issues/1",
        "https://github.com/owner/repo/pulls/1",
        "https://github.com/owner/repo/Pull/1",
        "https://github.com/owner/repo/pull/1/files",
        "https://github.com/owner/repo/pull/1//",
        "https://github.com//repo/pull/1",
        "https://github.com/owner//pull/1",
        "https://github.com/owner/repo/../pull/1",
        "https://github.com/owner/./pull/1",
        "https://github.com/owner/../pull/1",
        "https://github.com/owner/%2e%2e/pull/1",
        "https://github.com/owner/repo%2fother/pull/1",
        "https://github.com/owner/repo%252fother/pull/1",
        "https://github.com/owner/repo\\other/pull/1",
        "https://github.com\\@evil.example/owner/repo/pull/1",
        "https://github.com/-owner/repo/pull/1",
        "https://github.com/owner-/repo/pull/1",
        "https://github.com/an--org/repo/pull/1",
        "https://github.com/owner_name/repo/pull/1",
        f"https://github.com/{'a' * 40}/repo/pull/1",
        f"https://github.com/owner/{'b' * 101}/pull/1",
        "https://github.com/owner/repo/pull/0",
        "https://github.com/owner/repo/pull/-1",
        "https://github.com/owner/repo/pull/+1",
        "https://github.com/owner/repo/pull/01",
        "https://github.com/owner/repo/pull/1.0",
        "https://github.com/owner/repo/pull/one",
        "https://github.com/owner/repo/pull/2147483648",
        f"https://github.com/owner/repo/pull/{'9' * 3000}",
        "https://github.com/owner/repo/pull/1?tab=files",
        "https://github.com/owner/repo/pull/1?",
        "https://github.com/owner/repo/pull/1#discussion",
        "https://github.com/owner/repo/pull/1#",
        " https://github.com/owner/repo/pull/1",
        "https://github.com/owner/repo/pull/1 ",
        "https://git\nhub.com/owner/repo/pull/1",
        "\x00https://github.com/owner/repo/pull/1",
        "https://github.com/owner/repo/pull/1\r\n",
        "https://github.com/owner/repo/pull/1\x7f",
        "https://gіthub.com/owner/repo/pull/1",
        "https://github.com/owner/répo/pull/1",
        "https://github.com/owner/repo/pull/١",
    ],
)
def test_rejects_invalid_pr_urls(url: str) -> None:
    with pytest.raises(InvalidPullRequestURL) as error:
        parse_pull_request_url(url)

    assert error.value.code == "invalid_pr_url"


@pytest.mark.parametrize("value", [None, 123, True, b"https://github.com/a/b/pull/1", [], {}])
def test_rejects_non_string_input(value) -> None:
    with pytest.raises(InvalidPullRequestURL):
        parse_pull_request_url(value)


def test_error_does_not_repeat_submitted_credentials() -> None:
    with pytest.raises(InvalidPullRequestURL) as error:
        parse_pull_request_url("https://user:fake-secret@github.com/owner/repo/pull/1")

    assert "fake-secret" not in str(error.value)
    assert "user:" not in str(error.value)


def test_parsed_identifiers_cannot_be_changed() -> None:
    result = parse_pull_request_url("https://github.com/owner/repo/pull/1")

    with pytest.raises(FrozenInstanceError):
        result.owner = "another-owner"
