"""Parse GitHub PR URLs as identifiers, without fetching user-provided URLs."""

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

_OWNER = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]{1,100}")
_PR_NUMBER = re.compile(r"[1-9][0-9]{0,9}")
_MAX_PR_NUMBER = 2_147_483_647  # Fits reviews.pr_number's PostgreSQL INTEGER column.


class InvalidPullRequestURL(ValueError):
    """A stable error that does not expose the submitted URL."""

    code = "invalid_pr_url"

    def __init__(self) -> None:
        super().__init__(
            "Enter an HTTPS GitHub pull request URL in the form "
            "https://github.com/OWNER/REPO/pull/NUMBER."
        )


@dataclass(frozen=True, slots=True)
class PullRequestRef:
    """Identifiers extracted by parse_pull_request_url for the GitHub reader."""

    owner: str
    repository: str
    pr_number: int

    @property
    def pr_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repository}/pull/{self.pr_number}"


def parse_pull_request_url(url: str) -> PullRequestRef:
    """Validate a canonical PR link and return its immutable identifiers.

    Accept one optional trailing slash and case-insensitive scheme/hostname.
    Preserve owner/repository spelling. Repository existence and visibility are
    checked by the GitHub client, not by this syntax-only parser.
    """
    if not isinstance(url, str) or not url or len(url) > 2048:
        raise InvalidPullRequestURL()

    # urlsplit silently strips some whitespace/control characters. Reject them
    # first, along with Unicode confusables, instead of changing the input.
    if any(ord(character) < 33 or ord(character) > 126 for character in url):
        raise InvalidPullRequestURL()
    if "?" in url or "#" in url:
        raise InvalidPullRequestURL()

    try:
        parsed = urlsplit(url)
    except ValueError:
        raise InvalidPullRequestURL() from None

    # An exact authority also rules out credentials, ports, and alternate hosts.
    if parsed.scheme != "https" or parsed.netloc.lower() != "github.com":
        raise InvalidPullRequestURL()

    parts = parsed.path.removesuffix("/").split("/")
    if len(parts) != 5 or parts[0] != "" or parts[3] != "pull":
        raise InvalidPullRequestURL()
    owner, repository, number = parts[1], parts[2], parts[4]

    if (
        len(owner) > 39
        or _OWNER.fullmatch(owner) is None
        or _REPOSITORY.fullmatch(repository) is None
        or repository in {".", ".."}
        or _PR_NUMBER.fullmatch(number) is None
    ):
        raise InvalidPullRequestURL()

    pr_number = int(number)
    if pr_number > _MAX_PR_NUMBER:
        raise InvalidPullRequestURL()

    return PullRequestRef(owner=owner, repository=repository, pr_number=pr_number)
