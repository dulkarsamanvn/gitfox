"""Exercise real graph execution with an isolated, mocked GitHub boundary."""

import asyncio
import json
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.config import Settings
from app.integrations.github import GitHubClient, GitHubClientError, PullRequestFiles
from app.integrations.github_files import PullRequestFile
from app.workflows import pr_preview

pytestmark = pytest.mark.anyio
PR_URL = "https://github.com/example/project/pull/42"
PATCH = "@@ -1 +1 @@\n-old\n+new"


def _file(filename: str) -> PullRequestFile:
    return PullRequestFile(
        filename=filename, status="modified", additions=1, deletions=1, changes=2, patch=PATCH
    )


def _fetched(number: int = 42, files: tuple[PullRequestFile, ...] = ()) -> PullRequestFiles:
    return PullRequestFiles(
        metadata={
            "owner": "example",
            "repository": "project",
            "pr_number": number,
            "pr_url": f"https://github.com/example/project/pull/{number}",
            "title": f"PR {number}",
            "author": "contributor",
            "state": "open",
            "merged": False,
            "base_sha": "a" * 40,
            "head_sha": "b" * 40,
            "changed_files": len(files),
        },
        files=files,
    )


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    client = AsyncMock(spec=GitHubClient)
    client.__aenter__.return_value = client
    monkeypatch.setattr(pr_preview, "GitHubClient", Mock(return_value=client))
    return client


async def test_streams_ordered_node_updates_and_applies_selection_settings(
    github: AsyncMock,
) -> None:
    fetched = _fetched(files=(_file("src/first.py"), _file("src/second.py")))
    github.get_pull_request_files.return_value = fetched
    settings = Settings(_env_file=None, max_review_files=1)
    graph = pr_preview.build_pr_preview_graph(settings)

    updates = [update async for update in graph.astream({"pr_url": PR_URL}, stream_mode="updates")]

    assert [list(update) for update in updates] == [
        ["fetch_pr"],
        ["select_diffs"],
        ["prepare_review_input"],
    ]
    assert updates[0]["fetch_pr"] == {"metadata": fetched.metadata, "files": fetched.files}
    selection = updates[1]["select_diffs"]["selection"]
    assert [file.filename for file in selection.selected] == ["src/first.py"]
    assert [(file.filename, file.reason) for file in selection.skipped] == [
        ("src/second.py", "file_limit_exceeded")
    ]
    review_input = updates[2]["prepare_review_input"]["review_input"]
    content = json.loads(review_input.user_content)
    assert [file["file_path"] for file in content["files"]] == ["src/first.py"]
    assert content["coverage"] == {"files_seen": 2, "files_selected": 1, "files_skipped": 1}
    pr_preview.GitHubClient.assert_called_once_with(settings)
    github.get_pull_request_files.assert_awaited_once_with(PR_URL)
    github.__aexit__.assert_awaited_once()


async def test_final_output_keeps_metadata_and_selection_without_intermediate_state(
    github: AsyncMock,
) -> None:
    fetched = _fetched(files=(_file("src/main.py"),))
    github.get_pull_request_files.return_value = fetched
    graph = pr_preview.build_pr_preview_graph(Settings(_env_file=None))

    result = await graph.ainvoke({"pr_url": PR_URL})

    assert set(result) == {"metadata", "selection"}
    assert result["metadata"] == fetched.metadata
    assert result["selection"].selected[0].patch == PATCH
    assert result["selection"].files_seen == 1


@pytest.mark.parametrize("files", [(), (_file("logo.png"),)])
async def test_empty_or_all_skipped_inputs_complete_normally(
    github: AsyncMock, files: tuple[PullRequestFile, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    github.get_pull_request_files.return_value = _fetched(files=files)
    preparer = Mock(side_effect=AssertionError("Empty selections must not prepare AI input"))
    monkeypatch.setattr(pr_preview, "build_review_input", preparer)
    graph = pr_preview.build_pr_preview_graph(Settings(_env_file=None))

    updates = [update async for update in graph.astream({"pr_url": PR_URL}, stream_mode="updates")]

    assert [list(update) for update in updates] == [["fetch_pr"], ["select_diffs"]]
    selection = updates[-1]["select_diffs"]["selection"]
    assert selection.selected == ()
    assert selection.files_seen == selection.files_skipped == len(files)
    preparer.assert_not_called()


async def test_failed_fetch_closes_client_and_does_not_select(
    github: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = GitHubClientError("github_timeout", "Safe upstream failure")
    github.get_pull_request_files.side_effect = error
    selector = Mock()
    monkeypatch.setattr(pr_preview, "select_diffs", selector)
    graph = pr_preview.build_pr_preview_graph(Settings(_env_file=None))

    with pytest.raises(GitHubClientError) as caught:
        await graph.ainvoke({"pr_url": PR_URL})

    assert caught.value is error
    selector.assert_not_called()
    github.__aexit__.assert_awaited_once()


async def test_shared_graph_isolates_concurrent_and_later_invocations(github: AsyncMock) -> None:
    both_started = asyncio.Event()
    requests = []

    async def fetch(pr_url: str) -> PullRequestFiles:
        requests.append(pr_url)
        if len(requests) == 2:
            both_started.set()
        await both_started.wait()
        number = int(pr_url.rsplit("/", 1)[1])
        return _fetched(number, files=(_file(f"src/pr_{number}.py"),))

    github.get_pull_request_files.side_effect = fetch
    graph = pr_preview.build_pr_preview_graph(Settings(_env_file=None))
    urls = [PR_URL, PR_URL.replace("/42", "/43")]

    async def run(pr_url: str) -> dict:
        states = [state async for state in graph.astream({"pr_url": pr_url}, stream_mode="values")]
        return states[-1]

    results = await asyncio.wait_for(asyncio.gather(*(run(url) for url in urls)), timeout=5)
    for number, result in zip((42, 43), results, strict=True):
        assert result["metadata"].pr_number == number
        assert [file.filename for file in result["selection"].selected] == [f"src/pr_{number}.py"]
        content = json.loads(result["review_input"].user_content)
        assert content["pull_request"]["pr_number"] == number
        assert [file["file_path"] for file in content["files"]] == [f"src/pr_{number}.py"]

    github.get_pull_request_files.side_effect = None
    github.get_pull_request_files.return_value = _fetched()
    later = await run(PR_URL)
    assert later["metadata"].pr_number == 42
    assert later["selection"].files_seen == 0
    assert later["selection"].selected == ()
    assert "review_input" not in later
    assert github.get_pull_request_files.await_count == 3


async def test_cancelling_during_fetch_closes_the_github_client(github: AsyncMock) -> None:
    started = asyncio.Event()

    async def fetch(_pr_url: str) -> PullRequestFiles:
        started.set()
        await asyncio.Event().wait()
        raise AssertionError("Cancelled fetch must not finish")

    github.get_pull_request_files.side_effect = fetch
    graph = pr_preview.build_pr_preview_graph(Settings(_env_file=None))
    task = asyncio.create_task(graph.ainvoke({"pr_url": PR_URL}))
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    github.__aexit__.assert_awaited_once()
