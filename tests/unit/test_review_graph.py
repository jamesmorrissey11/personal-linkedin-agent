import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

import review_graph
from linkedin_actions import ActionResult
from review_graph import MessageReviewState, ReviewState, build_interrupt, build_message_interrupt, builder, decision_from_response, message_builder, message_result_from_response
from tests.async_helpers import run_async_test

STATE: ReviewState = {"name": "Ada", "profile": "https://www.linkedin.com/in/ada/", "job_title": "Engineer", "reason": "Unclear role"}


def test_build_interrupt_allows_only_accept_and_ignore():
    interrupt_payload = build_interrupt(STATE)
    assert interrupt_payload["config"] == {"allow_ignore": True, "allow_respond": False, "allow_edit": False, "allow_accept": True}
    assert interrupt_payload["action_request"]["args"]["profile"] == STATE["profile"]
    description = interrupt_payload["description"]
    assert description is not None
    assert "Unclear role" in description


def test_decision_from_response_maps_types():
    assert decision_from_response({"type": "accept", "args": None}) == "accept"
    assert decision_from_response({"type": "ignore", "args": None}) == "ignore"
    with pytest.raises(ValueError):
        decision_from_response({"type": "response", "args": "hi"})


@pytest.mark.parametrize("response_type", ["accept", "ignore"])
def test_graph_interrupts_then_resumes_with_action(response_type, monkeypatch):
    async def fake_action(_profile, decision):
        return ActionResult("accepted" if decision == "accept" else "ignored")

    patch_graph_dependencies(monkeypatch)
    monkeypatch.setattr(review_graph, "perform_invitation_action", fake_action)

    async def scenario():
        graph = builder.compile(checkpointer=MemorySaver())
        config: RunnableConfig = {"configurable": {"thread_id": f"t-{response_type}"}}
        paused = await graph.ainvoke(STATE, config)
        assert paused["__interrupt__"][0].value[0]["action_request"]["args"]["name"] == "Ada"
        return await graph.ainvoke(Command(resume=[{"type": response_type, "args": None}]), config)

    result = run_async_test(scenario)
    assert result["decision"] == response_type
    assert result["outcome"] == ("accepted" if response_type == "accept" else "ignored")


MESSAGE_STATE: MessageReviewState = {
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
    description = payload["description"]
    assert description is not None
    assert "Can we talk Friday?" in description


def test_accept_hidden_without_suggestion():
    payload = build_message_interrupt({**MESSAGE_STATE, "suggested_reply": "  "})
    assert payload["config"]["allow_accept"] is False


def test_message_result_from_response():
    assert message_result_from_response({"type": "accept", "args": None}, "Hi") == {"action": "reply", "reply": "Hi"}
    edited = {"type": "edit", "args": {"action": "x", "args": {"suggested_reply": "Edited"}}}
    assert message_result_from_response(edited, "Hi") == {"action": "reply", "reply": "Edited"}
    assert message_result_from_response({"type": "ignore", "args": None}, "Hi") == {"action": "dismiss"}
    with pytest.raises(ValueError):
        message_result_from_response({"type": "response", "args": "x"}, "Hi")


def test_message_reply_passes_exact_edited_text(monkeypatch):
    calls = []

    async def fake_action(conversation_url, action, reply, expected_latest):
        calls.append((conversation_url, action, reply, expected_latest))
        return ActionResult("sent")

    patch_graph_dependencies(monkeypatch)
    monkeypatch.setattr(review_graph, "perform_message_action", fake_action)

    async def scenario():
        graph = message_builder.compile(checkpointer=MemorySaver())
        config: RunnableConfig = {"configurable": {"thread_id": "m1"}}
        await graph.ainvoke(MESSAGE_STATE, config)
        edited = {"type": "edit", "args": {"action": "Reply to Grace?", "args": {"suggested_reply": "Friday at 3?"}}}
        return await graph.ainvoke(Command(resume=[edited]), config)

    result = run_async_test(scenario)
    assert result["outcome"] == "sent"
    assert calls == [(MESSAGE_STATE["conversation_url"], "reply", "Friday at 3?", MESSAGE_STATE["latest_message"])]


def test_failure_loops_back_to_interrupt_with_note(monkeypatch):
    results = [
        ActionResult(None, "LinkedIn login expired. Log in with a visible browser, then try again."),
        ActionResult("ignored"),
    ]
    notifications = patch_graph_dependencies(monkeypatch)

    async def fake_action(_profile, _decision):
        return results.pop(0)

    monkeypatch.setattr(review_graph, "perform_invitation_action", fake_action)

    async def scenario():
        graph = builder.compile(checkpointer=MemorySaver())
        config: RunnableConfig = {"configurable": {"thread_id": "failure-loop"}}
        await graph.ainvoke(STATE, config)
        failed = await graph.ainvoke(Command(resume=[{"type": "accept", "args": None}]), config)
        description = failed["__interrupt__"][0].value[0]["description"]
        assert description.startswith("⚠️ **Last attempt failed:** LinkedIn login expired.")
        return await graph.ainvoke(Command(resume=[{"type": "ignore", "args": None}]), config)

    result = run_async_test(scenario)
    assert result["outcome"] == "ignored"
    assert notifications == [("LinkedIn action failed", "Ada: LinkedIn login expired. Log in with a visible browser, then try again.")]


def test_superseded_never_calls_action(monkeypatch):
    patch_graph_dependencies(monkeypatch)

    async def unexpected_action(*_args):
        raise AssertionError("superseded must not act")

    monkeypatch.setattr(review_graph, "perform_invitation_action", unexpected_action)

    async def scenario():
        graph = builder.compile(checkpointer=MemorySaver())
        config: RunnableConfig = {"configurable": {"thread_id": "superseded"}}
        await graph.ainvoke(STATE, config)
        return await graph.ainvoke(Command(resume=[{"type": "superseded", "args": None}]), config)

    result = run_async_test(scenario)
    assert result["decision"] == "superseded"


def patch_graph_dependencies(monkeypatch):
    notifications = []

    async def fake_recover(*_args, **_kwargs):
        return 0

    async def fake_notify_async(title, message):
        notifications.append((title, message))

    monkeypatch.setattr(review_graph, "get_review_client", lambda: object())
    monkeypatch.setattr(review_graph, "recover_stuck_reviews", fake_recover)
    monkeypatch.setattr(review_graph, "notify_async", fake_notify_async)
    return notifications
