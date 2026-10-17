"""LangGraph graph that asks a human (via Agent Inbox) to resolve an undecided LinkedIn invitation.

Served by `uv run langgraph dev` (see langgraph.json) and rendered by the self-hosted UI in agent-inbox/.
"""

from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

GRAPH_ID = "invitation_review"


# Agent Inbox interrupt schema (https://github.com/langchain-ai/agent-inbox)
class HumanInterruptConfig(TypedDict):
    allow_ignore: bool
    allow_respond: bool
    allow_edit: bool
    allow_accept: bool


class ActionRequest(TypedDict):
    action: str
    args: dict[str, Any]


class HumanInterrupt(TypedDict):
    action_request: ActionRequest
    config: HumanInterruptConfig
    description: str | None


class ReviewState(TypedDict, total=False):
    name: str
    profile: str
    job_title: str
    reason: str
    decision: Literal["accept", "ignore"]


def build_interrupt(state: ReviewState) -> HumanInterrupt:
    return HumanInterrupt(
        action_request=ActionRequest(
            action=f"Accept invitation from {state['name']}?",
            args={"name": state["name"], "job_title": state.get("job_title", ""), "profile": state["profile"]},
        ),
        # "Accept" accepts the invitation; "Ignore" ignores it.
        config=HumanInterruptConfig(allow_ignore=True, allow_respond=False, allow_edit=False, allow_accept=True),
        description=f"The agent was undecided about this invitation.\n\n**Reason:** {state.get('reason', 'n/a')}\n\n[View profile]({state['profile']})",
    )


def decision_from_response(response: dict[str, Any]) -> Literal["accept", "ignore"]:
    response_type = response.get("type")
    if response_type == "accept":
        return "accept"
    if response_type == "ignore":
        return "ignore"
    raise ValueError(f"Unsupported Agent Inbox response type: {response_type!r}")


def review(state: ReviewState) -> ReviewState:
    # Agent Inbox always replies with a single-item list of HumanResponse
    responses = interrupt([build_interrupt(state)])
    return {"decision": decision_from_response(responses[0])}


builder = StateGraph(ReviewState)
builder.add_node("review", review)
builder.add_edge(START, "review")
builder.add_edge("review", END)

graph = builder.compile()
