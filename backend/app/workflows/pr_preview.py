"""Fetch and select PR patches, then prepare review input when patches remain."""

from typing import Literal, NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.core.config import Settings
from app.integrations.github import GitHubClient, PullRequestMetadata
from app.integrations.github_files import PullRequestFile
from app.services.diff_selection import DiffSelection, select_diffs
from app.services.review_input import ReviewInput, build_review_input


class PreviewInput(TypedDict):
    pr_url: str


class PreviewState(PreviewInput):
    """Each invocation starts with a URL; nodes add their results to its state."""

    metadata: NotRequired[PullRequestMetadata]
    files: NotRequired[tuple[PullRequestFile, ...]]
    selection: NotRequired[DiffSelection]
    review_input: NotRequired[ReviewInput]


class PreviewOutput(TypedDict):
    """Expose the preview result, leaving files and AI input inside the graph."""

    metadata: PullRequestMetadata
    selection: DiffSelection


def route_after_selection(state: PreviewState) -> Literal["prepare", "finish"]:
    """Choose the next step from the selection already stored in state."""
    if state["selection"].selected:
        return "prepare"
    return "finish"


def build_pr_preview_graph(settings: Settings) -> CompiledStateGraph:
    """Compile once per app; settings and credentials stay outside graph state."""

    async def fetch_pr(state: PreviewState) -> dict[str, object]:
        async with GitHubClient(settings) as github:
            fetched = await github.get_pull_request_files(state["pr_url"])
        return {"metadata": fetched.metadata, "files": fetched.files}

    def select_diffs_node(state: PreviewState) -> dict[str, DiffSelection]:
        return {"selection": select_diffs(state["files"], settings=settings)}

    def prepare_review_input_node(state: PreviewState) -> dict[str, ReviewInput]:
        return {"review_input": build_review_input(state["metadata"], state["selection"])}

    builder = StateGraph(PreviewState, input_schema=PreviewInput, output_schema=PreviewOutput)
    builder.add_node("fetch_pr", fetch_pr)
    builder.add_node("select_diffs", select_diffs_node)
    builder.add_node("prepare_review_input", prepare_review_input_node)
    builder.add_edge(START, "fetch_pr")
    builder.add_edge("fetch_pr", "select_diffs")
    builder.add_conditional_edges(
        "select_diffs",
        route_after_selection,
        {"prepare": "prepare_review_input", "finish": END},
    )
    builder.add_edge("prepare_review_input", END)
    return builder.compile()
