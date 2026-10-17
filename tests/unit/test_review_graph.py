import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from review_graph import build_interrupt, build_message_interrupt, builder, decision_from_response, message_builder, message_result_from_response

STATE = {"name": "Ada", "profile": "https://www.linkedin.com/in/ada/", "job_title": "Engineer", "reason": "Unclear role"}


def test_build_interrupt_allows_only_accept_and_ignore():
    interrupt_payload = build_interrupt(STATE)
    assert interrupt_payload["config"] == {"allow_ignore": True, "allow_respond": False, "allow_edit": False, "allow_accept": True}
    assert interrupt_payload["action_request"]["args"]["profile"] == STATE["profile"]
    assert "Unclear role" in interrupt_payload["description"]


def test_decision_from_response_maps_types():
    assert decision_from_response({"type": "accept", "args": None}) == "accept"
    assert decision_from_response({"type": "ignore", "args": None}) == "ignore"
    with pytest.raises(ValueError):
        decision_from_response({"type": "response", "args": "hi"})


@pytest.mark.parametrize("response_type", ["accept", "ignore"])
def test_graph_interrupts_then_resumes_with_decision(response_type):
    graph = builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "t1"}}

    paused = graph.invoke(STATE, config)
    assert paused["__interrupt__"][0].value[0]["action_request"]["args"]["name"] == "Ada"

    result = graph.invoke(Command(resume=[{"type": response_type, "args": None}]), config)
    assert result["decision"] == response_type


MESSAGE_STATE = {
    "sender_name": "Grace",
    "conversation_url": "https://www.linkedin.com/messaging/thread/1/",
    "urgency_score": 8,
    "latest_message": "Can we talk Friday?",
    "reason": "Direct question",
    "suggested_reply": "Friday works!",
}


def test_message_interrupt_allows_accept_edit_ignore():
    payload = build_message_interrupt(MESSAGE_STATE)
    assert payload["config"] == {"allow_ignore": True, "allow_respond": False, "allow_edit": True, "allow_accept": True}
    assert payload["action_request"]["args"] == {"suggested_reply": "Friday works!"}
    assert "Can we talk Friday?" in payload["description"]


def test_message_result_from_response():
    assert message_result_from_response({"type": "accept", "args": None}, "Hi") == {"action": "reply", "reply": "Hi"}
    edited = {"type": "edit", "args": {"action": "x", "args": {"suggested_reply": "Edited"}}}
    assert message_result_from_response(edited, "Hi") == {"action": "reply", "reply": "Edited"}
    assert message_result_from_response({"type": "ignore", "args": None}, "Hi") == {"action": "dismiss"}
    with pytest.raises(ValueError):
        message_result_from_response({"type": "response", "args": "x"}, "Hi")


def test_message_graph_resumes_with_edited_reply():
    graph = message_builder.compile(checkpointer=MemorySaver())
    config = {"configurable": {"thread_id": "m1"}}
    graph.invoke(MESSAGE_STATE, config)
    edited = {"type": "edit", "args": {"action": "Reply to Grace?", "args": {"suggested_reply": "Friday at 3?"}}}
    result = graph.invoke(Command(resume=[edited]), config)
    assert result["action"] == "reply"
    assert result["reply"] == "Friday at 3?"
