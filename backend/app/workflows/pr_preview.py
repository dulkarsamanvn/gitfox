"""Run the existing PR reader and patch selector as a two-node graph."""

from typing import NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.core.config import Settings
from app.integrations.github import GitHubClient, PullRequestMetadata
from app.integrations.github_files import PullRequestFile
from app.services.diff_selection import DiffSelection, select_diffs


class PreviewInput(TypedDict):
    pr_url: str


class PreviewState(PreviewInput):
    """Each invocation starts with a URL; nodes add their results to its state."""

    metadata: NotRequired[PullRequestMetadata]
    files: NotRequired[tuple[PullRequestFile, ...]]
    selection: NotRequired[DiffSelection]


class PreviewOutput(TypedDict):
    """Expose the preview result, leaving intermediate files inside the graph."""

    metadata: PullRequestMetadata
    selection: DiffSelection


def build_pr_preview_graph(settings: Settings) -> CompiledStateGraph:
    """Compile once per app; settings and credentials stay outside graph state."""

    async def fetch_pr(state: PreviewState) -> dict[str, object]:
        async with GitHubClient(settings) as github:
            fetched = await github.get_pull_request_files(state["pr_url"])
        return {"metadata": fetched.metadata, "files": fetched.files}

    def select_diffs_node(state: PreviewState) -> dict[str, DiffSelection]:
        return {"selection": select_diffs(state["files"], settings=settings)}

    builder = StateGraph(PreviewState, input_schema=PreviewInput, output_schema=PreviewOutput)
    builder.add_node("fetch_pr", fetch_pr)
    builder.add_node("select_diffs", select_diffs_node)
    builder.add_edge(START, "fetch_pr")
    builder.add_edge("fetch_pr", "select_diffs")
    builder.add_edge("select_diffs", END)
    return builder.compile()
