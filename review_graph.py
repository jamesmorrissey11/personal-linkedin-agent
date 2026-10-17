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
    label: str
    decision: Literal["accept", "ignore", "superseded"]


def build_interrupt(state: ReviewState) -> HumanInterrupt:
    return HumanInterrupt(
        action_request=ActionRequest(
            action=f"Accept invitation from {state['name']}?",
            args={"name": state["name"], "job_title": state.get("job_title", ""), "profile": state["profile"]},
        ),
        # "Accept" accepts the invitation; "Ignore" ignores it.
        config=HumanInterruptConfig(allow_ignore=True, allow_respond=False, allow_edit=False, allow_accept=True),
        description=f"**{state.get('label') or 'Agent proposal'}**\n\n**Reason:** {state.get('reason', 'n/a')}\n\n[View profile]({state['profile']})",
    )


def decision_from_response(response: dict[str, Any]) -> Literal["accept", "ignore", "superseded"]:
    response_type = response.get("type")
    if response_type == "accept":
        return "accept"
    if response_type == "ignore":
        return "ignore"
    if response_type == "superseded":
        # Sent by the scheduled job when LinkedIn shows the item was already handled; a terminal no-op.
        return "superseded"
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


MESSAGE_GRAPH_ID = "message_review"


class MessageReviewState(TypedDict, total=False):
    sender_name: str
    conversation_url: str
    urgency_score: int
    label: str
    latest_message: str
    reason: str
    suggested_reply: str
    action: Literal["reply", "dismiss", "superseded"]
    reply: str


def build_message_interrupt(state: MessageReviewState) -> HumanInterrupt:
    label_line = f"**{state['label']}**\n\n" if state.get("label") else ""
    return HumanInterrupt(
        action_request=ActionRequest(
            action=f"Reply to {state['sender_name']}?",
            args={"suggested_reply": state.get("suggested_reply", "")},
        ),
        # Accept uses the suggested reply, Edit lets you change it, Ignore dismisses the conversation.
        config=HumanInterruptConfig(allow_ignore=True, allow_respond=False, allow_edit=True, allow_accept=True),
        description=(f"{label_line}**Urgency:** {state.get('urgency_score', '?')}/10\n\n**Latest message:** {state.get('latest_message', '')}\n\n**Why:** {state.get('reason', 'n/a')}\n\n[Open conversation]({state['conversation_url']})"),
    )


def message_result_from_response(response: dict[str, Any], suggested_reply: str) -> MessageReviewState:
    response_type = response.get("type")
    if response_type == "accept":
        return {"action": "reply", "reply": suggested_reply}
    if response_type == "edit":
        args = response.get("args") or {}
        return {"action": "reply", "reply": str((args.get("args") or {}).get("suggested_reply", suggested_reply))}
    if response_type == "ignore":
        return {"action": "dismiss"}
    if response_type == "superseded":
        return {"action": "superseded"}
    raise ValueError(f"Unsupported Agent Inbox response type: {response_type!r}")


def review_message(state: MessageReviewState) -> MessageReviewState:
    responses = interrupt([build_message_interrupt(state)])
    return message_result_from_response(responses[0], state.get("suggested_reply", ""))


message_builder = StateGraph(MessageReviewState)
message_builder.add_node("review_message", review_message)
message_builder.add_edge(START, "review_message")
message_builder.add_edge("review_message", END)

message_graph = message_builder.compile()
