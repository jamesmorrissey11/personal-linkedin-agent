import pytest

from linkedin_agent import inbox, invitations
from linkedin_agent.linkedin.models import ConversationMessage, InboxMessage, Invitation, InvitationAction, InvitationDecision, MessageRanking
from tests.async_helpers import run_async_test


class FakeButton:
    def __init__(self):
        self.clicks = 0

    async def evaluate(self, script):
        return {"tag": "button", "interactive": True, "ariaLabel": "Accept", "title": "", "name": "", "id": "", "type": "", "controlName": "", "className": "", "text": "Accept"}

    async def click(self):
        self.clicks += 1


class FakeInvitationCard:
    def __init__(self):
        self.accept = FakeButton()
        self.ignore = FakeButton()

    async def query_selector(self, selector):
        if "Accept" in selector:
            return self.accept
        if "Ignore" in selector:
            return self.ignore
        return None


def invitation(action=InvitationAction.ACCEPT):
    return Invitation(
        name="Ada",
        profile="https://www.linkedin.com/in/ada/",
        job_title="Engineer",
        mutual_connections=False,
        decision=InvitationDecision(action=action, reason="Agent proposal"),
    )


def message(*, urgency=8, reply="Thanks, I will take a look."):
    return InboxMessage(
        sender_name="Grace",
        conversation_url="https://www.linkedin.com/messaging/thread/1/",
        last_three_messages=[ConversationMessage(author="Grace", content="Can you review this?", timestamp="Now")],
        ranking=MessageRanking(reason="Direct request", urgency_score=urgency, suggested_reply=reply),
    )


def test_agent_invitation_proposal_only_queues_and_does_not_click(monkeypatch):
    queued = []

    async def fake_enqueue(client, graph_id, key, input_data):
        queued.append((client, graph_id, key, input_data))
        return True

    monkeypatch.setattr(invitations, "enqueue_review", fake_enqueue)
    card = FakeInvitationCard()
    candidate = invitation()

    created = run_async_test(lambda: invitations.queue_invitation_proposal(object(), candidate, candidate.decision))

    assert created is True
    assert queued[0][2] == candidate.profile
    assert "Agent proposes **accept**" in queued[0][3]["reason"]
    assert card.accept.clicks == 0
    assert card.ignore.clicks == 0


def test_undecided_invitation_is_queued_for_judgment_without_clicking(monkeypatch):
    queued = []

    async def fake_enqueue(client, graph_id, key, input_data):
        queued.append(input_data)
        return True

    monkeypatch.setattr(invitations, "enqueue_review", fake_enqueue)
    card = FakeInvitationCard()
    candidate = invitation(InvitationAction.UNDECIDED)

    created = run_async_test(lambda: invitations.queue_invitation_proposal(object(), candidate, candidate.decision))

    assert created is True
    assert queued[0]["label"] == "Needs your judgment"
    assert "Agent proposes" not in queued[0]["reason"]
    assert card.accept.clicks == 0
    assert card.ignore.clicks == 0


def test_failed_llm_invitation_is_queued_with_error(monkeypatch):
    queued = []

    async def fake_enqueue(client, graph_id, key, input_data):
        queued.append(input_data)
        return True

    monkeypatch.setattr(invitations, "enqueue_review", fake_enqueue)

    run_async_test(lambda: invitations.queue_invitation_proposal(object(), invitation(), None, "TimeoutError()"))

    assert queued[0]["label"] == "Needs your judgment"
    assert "TimeoutError()" in queued[0]["reason"]


def test_invitation_queue_failure_is_surfaced_without_clicking(monkeypatch):
    async def failed_enqueue(*args, **kwargs):
        raise RuntimeError("review server unavailable")

    monkeypatch.setattr(invitations, "enqueue_review", failed_enqueue)
    card = FakeInvitationCard()
    candidate = invitation()

    with pytest.raises(RuntimeError, match="review server unavailable"):
        run_async_test(lambda: invitations.queue_invitation_proposal(object(), candidate, candidate.decision))

    assert card.accept.clicks == 0
    assert card.ignore.clicks == 0


def test_every_message_where_other_person_spoke_last_is_queued_with_labels(monkeypatch):
    queued = []

    async def fake_enqueue(client, graph_id, key, input_data):
        queued.append(input_data)
        return True

    monkeypatch.setattr(inbox, "enqueue_review", fake_enqueue)
    unscored = message()
    unscored.ranking = None
    from_user = message()
    from_user.from_user = True

    counts = run_async_test(lambda: inbox.send_messages_to_inbox(object(), [message(), message(urgency=2), message(reply=""), unscored, from_user], min_urgency=4))

    assert counts.new == 4
    assert counts.needs_judgment == 1
    assert queued[0] == {
        "sender_name": "Grace",
        "conversation_url": "https://www.linkedin.com/messaging/thread/1/",
        "latest_message": "Can you review this?",
        "urgency_score": 8,
        "reason": "Direct request",
        "suggested_reply": "Thanks, I will take a look.",
    }
    assert queued[1]["label"] == "Low urgency (2/10)"
    assert queued[2]["suggested_reply"] == ""
    assert queued[3]["label"] == "Couldn't score"
    assert queued[3]["suggested_reply"] == ""
    assert "urgency_score" not in queued[3]


def test_message_queue_failure_is_surfaced(monkeypatch):
    async def failed_enqueue(*args, **kwargs):
        raise RuntimeError("review server unavailable")

    monkeypatch.setattr(inbox, "enqueue_review", failed_enqueue)

    with pytest.raises(RuntimeError, match="review server unavailable"):
        run_async_test(lambda: inbox.send_messages_to_inbox(object(), [message()], min_urgency=4))
