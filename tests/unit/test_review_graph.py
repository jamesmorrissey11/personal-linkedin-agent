import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from review_graph import build_interrupt, builder, decision_from_response

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
