"""LangGraph graph that asks a human (via Agent Inbox) to resolve an undecided LinkedIn invitation.

Served by `uv run linkedin-agent server` (see deploy/langgraph.json) and rendered by the self-hosted UI in deploy/agent-inbox/.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from linkedin_agent.linkedin.actions import perform_invitation_action, perform_message_action
from linkedin_agent.review.queue import get_review_client, recover_stuck_reviews
from linkedin_agent.runtime import notify_async

GRAPH_ID = "invitation_review"
logger = logging.getLogger("review_graph")


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
    decision: Literal["accept", "ignore", "superseded"] | None
    last_error: str
    outcome: str


def build_interrupt(state: ReviewState) -> HumanInterrupt:
    error_prefix = f"⚠️ **Last attempt failed:** {state['last_error']}\n\n" if state.get("last_error") else ""
    return HumanInterrupt(
        action_request=ActionRequest(
            action=f"Accept invitation from {state['name']}?",
            args={"name": state["name"], "job_title": state.get("job_title", ""), "profile": state["profile"]},
        ),
        # "Accept" accepts the invitation; "Ignore" ignores it.
        config=HumanInterruptConfig(allow_ignore=True, allow_respond=False, allow_edit=False, allow_accept=True),
        description=f"{error_prefix}**{state.get('label') or 'Agent proposal'}**\n\n**Reason:** {state.get('reason', 'n/a')}\n\n[View profile]({state['profile']})",
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


async def _recover_reviews(graph_id: str) -> None:
    try:
        await recover_stuck_reviews(get_review_client(), graph_id, datetime.now(timezone.utc))
    except Exception:
        logger.exception("Could not recover stuck %s reviews before acting.", graph_id)


async def act_on_invitation(state: ReviewState) -> ReviewState:
    await _recover_reviews(GRAPH_ID)
    decision = state.get("decision")
    if decision not in {"accept", "ignore"}:
        return {}
    result = await perform_invitation_action(state["profile"], decision)
    if result.outcome:
        return {"outcome": result.outcome, "last_error": ""}
    error = result.error or "The LinkedIn action failed; try again."
    await notify_async("LinkedIn action failed", f"{state['name']}: {error}")
    return {"last_error": error, "decision": None}


def route_after_review(state: dict[str, Any]) -> Literal["act", "__end__"]:
    return "__end__" if state.get("decision") == "superseded" or state.get("action") == "superseded" else "act"


def route_after_act(state: dict[str, Any]) -> Literal["review", "__end__"]:
    return "__end__" if state.get("outcome") else "review"


builder = StateGraph(ReviewState)
builder.add_node("review", review)
builder.add_node("act", act_on_invitation)
builder.add_edge(START, "review")
builder.add_conditional_edges("review", route_after_review, {"act": "act", "__end__": END})
builder.add_conditional_edges("act", route_after_act, {"review": "review", "__end__": END})

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
    action: Literal["reply", "dismiss", "superseded"] | None
    reply: str
    last_error: str
    outcome: str


def build_message_interrupt(state: MessageReviewState) -> HumanInterrupt:
    error_prefix = f"⚠️ **Last attempt failed:** {state['last_error']}\n\n" if state.get("last_error") else ""
    label_line = f"**{state['label']}**\n\n" if state.get("label") else ""
    return HumanInterrupt(
        action_request=ActionRequest(
            action=f"Reply to {state['sender_name']}?",
            args={"suggested_reply": state.get("suggested_reply", "")},
        ),
        # Accept uses the suggested reply, Edit lets you change it, Ignore dismisses the conversation.
        config=HumanInterruptConfig(allow_ignore=True, allow_respond=False, allow_edit=True, allow_accept=bool(state.get("suggested_reply", "").strip())),
        description=(f"{error_prefix}{label_line}**Urgency:** {state.get('urgency_score', '?')}/10\n\n**Latest message:** {state.get('latest_message', '')}\n\n**Why:** {state.get('reason', 'n/a')}\n\n[Open conversation]({state['conversation_url']})"),
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


async def act_on_message(state: MessageReviewState) -> MessageReviewState:
    await _recover_reviews(MESSAGE_GRAPH_ID)
    action = state.get("action")
    if action not in {"reply", "dismiss"}:
        return {}
    result = await perform_message_action(
        state["conversation_url"],
        action,
        state.get("reply", ""),
        state.get("latest_message", ""),
    )
    if result.outcome:
        return {"outcome": result.outcome, "last_error": ""}
    error = result.error or "The LinkedIn action failed; try again."
    await notify_async("LinkedIn action failed", f"{state['sender_name']}: {error}")
    update: MessageReviewState = {"last_error": error, "action": None}
    if result.latest_message is not None:
        update["latest_message"] = result.latest_message
    return update


message_builder = StateGraph(MessageReviewState)
message_builder.add_node("review_message", review_message)
message_builder.add_node("act_message", act_on_message)
message_builder.add_edge(START, "review_message")
message_builder.add_conditional_edges("review_message", route_after_review, {"act": "act_message", "__end__": END})
message_builder.add_conditional_edges("act_message", route_after_act, {"review": "review_message", "__end__": END})

message_graph = message_builder.compile()
