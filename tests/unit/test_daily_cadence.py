import pytest

from linkedin_agent import daily, inbox, invitations
from linkedin_agent.linkedin import pages
from linkedin_agent.linkedin.models import ConversationMessage, InboxMessage, Invitation, InvitationAction, InvitationDecision
from linkedin_agent.review.graphs import decision_from_response, message_result_from_response
from linkedin_agent.review.queue import classify_review, enqueue_review, fetch_pending_reviews, fetch_resolved_reviews, find_pending_review, supersede_review
from linkedin_agent.runtime import HealthCheckError, ReviewCounts
from tests.async_helpers import run_async_test


class FakeThreads:
    def __init__(self, threads=None):
        self.threads = threads or []
        self.search_calls = []
        self.updated = []

    async def search(self, limit=10, offset=0, **kwargs):
        self.search_calls.append((kwargs, offset))
        return self.threads[offset : offset + limit]

    async def get(self, thread_id):
        return {"thread_id": thread_id, "status": "interrupted", "metadata": {"kind": "graph"}}

    async def update(self, thread_id, **kwargs):
        self.updated.append((thread_id, kwargs))


class FakeRuns:
    def __init__(self):
        self.waited = []

    async def wait(self, thread_id, graph_id, **kwargs):
        self.waited.append((thread_id, graph_id, kwargs))


class FakeClient:
    def __init__(self, threads=None):
        self.threads = FakeThreads(threads)
        self.runs = FakeRuns()


def test_resolved_reviews_paginate_past_100_threads():
    threads = [{"thread_id": f"t{i}", "metadata": {"key": f"k{i}", "applied": i < 150}, "values": {"decision": "accept"}} for i in range(230)]
    client = FakeClient(threads)

    resolved = run_async_test(lambda: fetch_resolved_reviews(client, "graph"))

    assert len(resolved) == 80
    assert "k229" in resolved
    assert [offset for _, offset in client.threads.search_calls] == [0, 100, 200]


def test_pending_reviews_maps_key_to_thread():
    client = FakeClient([{"thread_id": "a", "metadata": {"key": "k1"}}, {"thread_id": "b", "metadata": {"key": "k2", "applied": True}}])

    assert run_async_test(lambda: fetch_pending_reviews(client, "graph")) == {"k1": "a"}


def test_find_pending_review_and_classification():
    assert run_async_test(lambda: find_pending_review(FakeClient([{"thread_id": "a", "metadata": {}}]), "graph", "k"))["thread_id"] == "a"
    assert run_async_test(lambda: find_pending_review(FakeClient([{"thread_id": "a", "metadata": {"applied": True, "outcome": "superseded"}}]), "graph", "k")) is None
    assert run_async_test(lambda: find_pending_review(FakeClient(), "graph", "k")) is None
    assert classify_review({"metadata": {"applied": True, "outcome": "superseded"}}) == "superseded"
    assert classify_review({"metadata": {"applied": True}}) == "applied"
    assert classify_review({"metadata": {}}) == "already_queued"


def test_supersede_resumes_interrupt_and_marks_thread_never_deletes():
    client = FakeClient()

    assert run_async_test(lambda: supersede_review(client, "t1", "handled elsewhere")) is True

    assert client.runs.waited == [("t1", "graph", {"command": {"resume": [{"type": "superseded", "args": "handled elsewhere"}]}})]
    assert client.threads.updated == [("t1", {"metadata": {"applied": True, "outcome": "superseded", "superseded_reason": "handled elsewhere"}})]


def test_graph_responses_accept_superseded():
    assert decision_from_response({"type": "superseded"}) == "superseded"
    assert message_result_from_response({"type": "superseded"}, "") == {"action": "superseded"}


def test_review_counts_add_and_describe():
    total = ReviewCounts(new=2, needs_judgment=1) + ReviewCounts(already_queued=3, applied=1, superseded=1, cap_hit=True)
    assert total.total == 7
    assert "2 new, 3 already queued, 1 applied, 1 superseded (7 total" in total.describe()
    assert "SAFETY CAP" in total.describe()


# --- invitations -----------------------------------------------------------


class FakeCard:
    def __init__(self, profile):
        self.profile = profile


class FakePage:
    def __init__(self, profiles, empty_text=False):
        self.profiles = profiles
        self.empty_text = empty_text
        self.scrolls = 0

    async def evaluate(self, script):
        self.scrolls += 1

    async def content(self):
        return "No pending invitations" if self.empty_text else "<html></html>"


@pytest.fixture
def invitation_page(monkeypatch):
    async def fake_cards(page):
        return [FakeCard(p) for p in page.profiles]

    async def fake_info(card):
        if card.profile is None:
            return None
        return Invitation(name=card.profile, profile=card.profile, job_title="x", mutual_connections=False)

    async def no_sleep(_):
        return None

    for module in (invitations, pages):
        monkeypatch.setattr(module, "get_invitation_cards", fake_cards)
        monkeypatch.setattr(module, "get_invitation_info", fake_info)
    monkeypatch.setattr(invitations.asyncio, "sleep", no_sleep)


def test_pending_invitations_skip_llm_and_closed_ones_are_requeued(monkeypatch, invitation_page):
    # find_pending_review only returns pending threads; closed ones (p2) come back as new items.
    existing = {"p1": {"metadata": {}}}
    llm_calls = []

    async def fake_find(client, graph_id, key):
        return existing.get(key)

    async def fake_decision(name, message, record):
        llm_calls.append(name)
        return InvitationDecision(action=InvitationAction.ACCEPT, reason="ok"), None

    async def fake_enqueue(client, graph_id, key, data):
        return True

    monkeypatch.setattr(invitations, "find_pending_review", fake_find)
    monkeypatch.setattr(invitations, "try_decision", fake_decision)
    monkeypatch.setattr(invitations, "enqueue_review", fake_enqueue)

    _, counts = run_async_test(lambda: invitations.propose_new_invitations(FakePage(["new1", "p1", "p2"]), object(), 100, False, True))

    assert llm_calls == ["new1", "p2"]
    assert (counts.new, counts.already_queued, counts.applied, counts.superseded) == (2, 1, 0, 0)


def test_second_run_with_no_changes_creates_nothing(monkeypatch, invitation_page):
    async def fake_find(client, graph_id, key):
        return {"metadata": {}}

    async def unexpected(*args, **kwargs):
        raise AssertionError("known items must not hit the LLM or the queue")

    monkeypatch.setattr(invitations, "find_pending_review", fake_find)
    monkeypatch.setattr(invitations, "try_decision", unexpected)
    monkeypatch.setattr(invitations, "enqueue_review", unexpected)

    _, counts = run_async_test(lambda: invitations.propose_new_invitations(FakePage([f"p{i}" for i in range(8)]), object(), 100, False, True))

    assert counts.new == 0
    assert counts.already_queued == 5  # stops once caught up


def test_failed_and_undecided_invitations_are_queued_for_judgment(monkeypatch, invitation_page):
    queued = {}

    async def no_existing(client, graph_id, key):
        return None

    async def fake_decision(name, message, record):
        if name == "fails":
            return None, "boom"
        return InvitationDecision(action=InvitationAction.UNDECIDED, reason="unsure"), None

    async def fake_profile(page, url):
        return "profile text"

    async def fake_enqueue(client, graph_id, key, data):
        queued[key] = data
        return True

    monkeypatch.setattr(invitations, "find_pending_review", no_existing)
    monkeypatch.setattr(invitations, "try_decision", fake_decision)
    monkeypatch.setattr(invitations, "get_profile_info", fake_profile)
    monkeypatch.setattr(invitations, "enqueue_review", fake_enqueue)

    _, counts = run_async_test(lambda: invitations.propose_new_invitations(FakePage(["fails", "unsure"]), object(), 100, False, True))

    assert counts.new == 2 and counts.needs_judgment == 2
    assert all(data["label"] == "Needs your judgment" for data in queued.values())
    assert "boom" in queued["fails"]["reason"]


def test_safety_cap_is_reported(monkeypatch, invitation_page):
    async def no_existing(client, graph_id, key):
        return None

    async def fake_decision(name, message, record):
        return InvitationDecision(action=InvitationAction.IGNORE, reason="r"), None

    async def fake_enqueue(client, graph_id, key, data):
        return True

    monkeypatch.setattr(invitations, "find_pending_review", no_existing)
    monkeypatch.setattr(invitations, "try_decision", fake_decision)
    monkeypatch.setattr(invitations, "enqueue_review", fake_enqueue)

    _, counts = run_async_test(lambda: invitations.propose_new_invitations(FakePage(["a", "b", "c"]), object(), 2, False, True))

    assert counts.new == 2 and counts.cap_hit


def test_zero_cards_is_a_health_alert_when_unattended(monkeypatch, invitation_page):
    with pytest.raises(HealthCheckError):
        run_async_test(lambda: invitations.propose_new_invitations(FakePage([]), object(), 100, False, True))
    _, counts = run_async_test(lambda: invitations.propose_new_invitations(FakePage([], empty_text=True), object(), 100, False, True))
    assert counts.total == 0


def stale_setup(monkeypatch, pending):
    closed = []

    async def fake_pending(client, graph_id):
        return pending

    async def fake_supersede(client, thread_id, reason):
        closed.append(thread_id)
        return True

    monkeypatch.setattr(invitations, "fetch_pending_reviews", fake_pending)
    monkeypatch.setattr(invitations, "supersede_review", fake_supersede)
    return closed


def test_stale_cleanup_closes_only_absent_profiles_after_full_scan(monkeypatch, invitation_page):
    closed = stale_setup(monkeypatch, {"here": "t1", "gone": "t2"})

    assert run_async_test(lambda: invitations.close_stale_invitations(object(), FakePage(["here"]))) == 1
    assert closed == ["t2"]


def test_stale_cleanup_does_not_count_skipped_busy_threads(monkeypatch, invitation_page):
    async def fake_pending(client, graph_id):
        return {"gone-busy": "busy-thread", "gone": "t2"}

    async def fake_supersede(client, thread_id, reason):
        return thread_id != "busy-thread"

    monkeypatch.setattr(invitations, "fetch_pending_reviews", fake_pending)
    monkeypatch.setattr(invitations, "supersede_review", fake_supersede)

    assert run_async_test(lambda: invitations.close_stale_invitations(object(), FakePage(["here"]))) == 1


def test_new_message_does_not_count_skipped_busy_supersede(monkeypatch):
    url = "https://www.linkedin.com/messaging/thread/1/"

    async def fake_enqueue(client, graph_id, key, data):
        return True

    async def fake_supersede(client, thread_id, reason):
        return False

    monkeypatch.setattr(inbox, "enqueue_review", fake_enqueue)
    monkeypatch.setattr(inbox, "supersede_review", fake_supersede)
    pending = {inbox.message_key(url, "old message"): "busy-thread"}

    counts = run_async_test(lambda: inbox.send_messages_to_inbox(object(), [msg(content="new message")], 4, pending))

    assert (counts.new, counts.superseded) == (1, 0)


def test_stale_cleanup_never_runs_on_empty_or_incomplete_scans(monkeypatch, invitation_page):
    closed = stale_setup(monkeypatch, {"gone": "t2"})

    with pytest.raises(HealthCheckError):
        run_async_test(lambda: invitations.close_stale_invitations(object(), FakePage([])))
    assert run_async_test(lambda: invitations.close_stale_invitations(object(), FakePage([], empty_text=True))) == 0
    # one unparseable card means the list is not fully understood
    assert run_async_test(lambda: invitations.close_stale_invitations(object(), FakePage(["other", None]))) == 0
    assert closed == []


# --- messages --------------------------------------------------------------


def msg(url="https://www.linkedin.com/messaging/thread/1/", author="Grace", content="Hi", from_user=False, known=None):
    return InboxMessage(sender_name="Grace", conversation_url=url, last_three_messages=[ConversationMessage(author=author, content=content, timestamp="Now")], from_user=from_user, known=known)


def test_latest_author_must_match_exactly_else_keep():
    me = "James Morrissey"
    assert inbox.latest_message_is_from_user([ConversationMessage(author="James Morrissey", content="x", timestamp="")], me)
    assert not inbox.latest_message_is_from_user([ConversationMessage(author="James M.", content="x", timestamp="")], me)
    assert not inbox.latest_message_is_from_user([ConversationMessage(author="Unknown", content="x", timestamp="")], me)
    assert not inbox.latest_message_is_from_user([ConversationMessage(author="Unknown User", content="x", timestamp="")], "Unknown User")
    assert not inbox.latest_message_is_from_user([], me)


def test_new_message_supersedes_older_pending_item_for_same_conversation(monkeypatch):
    url = "https://www.linkedin.com/messaging/thread/1/"
    superseded = []

    async def fake_enqueue(client, graph_id, key, data):
        return True

    async def fake_supersede(client, thread_id, reason):
        superseded.append(thread_id)
        return True

    monkeypatch.setattr(inbox, "enqueue_review", fake_enqueue)
    monkeypatch.setattr(inbox, "supersede_review", fake_supersede)
    old_key = inbox.message_key(url, "old message")
    other_key = inbox.message_key("https://www.linkedin.com/messaging/thread/2/", "x")

    counts = run_async_test(lambda: inbox.send_messages_to_inbox(object(), [msg(content="new message")], 4, {old_key: "old-thread", other_key: "other-thread"}))

    assert superseded == ["old-thread"]
    assert (counts.new, counts.superseded) == (1, 1)


def test_known_messages_are_counted_not_requeued(monkeypatch):
    async def unexpected(*args, **kwargs):
        raise AssertionError("known messages must not be queued again")

    monkeypatch.setattr(inbox, "enqueue_review", unexpected)

    counts = run_async_test(lambda: inbox.send_messages_to_inbox(object(), [msg(known="already_queued"), msg(known="applied"), msg(known="superseded"), msg(from_user=True)], 4))

    assert (counts.new, counts.already_queued, counts.applied, counts.superseded) == (0, 1, 1, 1)


class FakeMessagePage:
    def __init__(self, author):
        self.author = author
        self.visited = []

    async def goto(self, url):
        self.visited.append(url)

    async def wait_for_load_state(self, state):
        return None

    async def wait_for_timeout(self, ms):
        return None


@pytest.mark.parametrize("author,expected", [("Me Myself", ["t1"]), ("Grace", []), ("Unknown", [])])
def test_self_replied_conversation_is_closed_only_when_author_is_certain(monkeypatch, author, expected):
    closed = []
    key = inbox.message_key("https://www.linkedin.com/messaging/thread/1/", "hello")

    async def fake_pending(client, graph_id):
        return {key: "t1"}

    async def fake_extract(page, sender_name):
        return [ConversationMessage(author=author, content="x", timestamp="")]

    async def fake_supersede(client, thread_id, reason):
        closed.append(thread_id)
        return True

    monkeypatch.setattr(inbox, "fetch_pending_reviews", fake_pending)
    monkeypatch.setattr(inbox, "extract_conversation_messages", fake_extract)
    monkeypatch.setattr(inbox, "supersede_review", fake_supersede)

    monkeypatch.setattr(inbox, "conversation_is_archived", async_value(False))

    run_async_test(lambda: inbox.close_handled_messages(FakeMessagePage(author), object(), "Me Myself"))

    assert closed == expected


def test_archived_pending_conversation_is_superseded(monkeypatch):
    closed = []
    key = inbox.message_key("https://www.linkedin.com/messaging/thread/1/", "hello")

    async def fake_pending(client, graph_id):
        return {key: "t1"}

    async def fake_extract(page, sender_name):
        return [ConversationMessage(author="Grace", content="x", timestamp="")]

    async def fake_archived(page):
        return True

    async def fake_supersede(client, thread_id, reason):
        closed.append((thread_id, reason))
        return True

    monkeypatch.setattr(inbox, "fetch_pending_reviews", fake_pending)
    monkeypatch.setattr(inbox, "extract_conversation_messages", fake_extract)
    monkeypatch.setattr(inbox, "conversation_is_archived", fake_archived)
    monkeypatch.setattr(inbox, "supersede_review", fake_supersede)

    assert run_async_test(lambda: inbox.close_handled_messages(FakeMessagePage("Grace"), object(), "Me Myself")) == 1
    assert closed == [("t1", "You archived this conversation on LinkedIn.")]


def test_unknown_archive_state_keeps_item(monkeypatch):
    key = inbox.message_key("https://www.linkedin.com/messaging/thread/1/", "hello")

    async def fake_pending(client, graph_id):
        return {key: "t1"}

    async def fake_extract(page, sender_name):
        return [ConversationMessage(author="Grace", content="x", timestamp="")]

    async def unknown_archived(page):
        return None

    async def unexpected_supersede(*args):
        raise AssertionError("unknown archive state must keep the review")

    monkeypatch.setattr(inbox, "fetch_pending_reviews", fake_pending)
    monkeypatch.setattr(inbox, "extract_conversation_messages", fake_extract)
    monkeypatch.setattr(inbox, "conversation_is_archived", unknown_archived)
    monkeypatch.setattr(inbox, "supersede_review", unexpected_supersede)

    assert run_async_test(lambda: inbox.close_handled_messages(FakeMessagePage("Grace"), object(), "Me Myself")) == 0


def async_value(value):
    async def result(_page):
        return value

    return result


def test_previously_dismissed_conversation_is_requeued_when_still_unanswered():
    created = []

    class ClosedThreads:
        async def search(self, **kwargs):
            assert kwargs["status"] in {"busy", "interrupted"}
            return []

        async def create(self, metadata):
            created.append(metadata)
            return {"thread_id": "new-thread"}

    class Runs:
        async def create(self, thread_id, graph_id, input):
            created.append((thread_id, graph_id, input))

    client = type("Client", (), {"threads": ClosedThreads(), "runs": Runs()})()
    key = inbox.message_key("https://www.linkedin.com/messaging/thread/1/", "same reply")

    assert run_async_test(lambda: enqueue_review(client, "message_review", key, {"latest_message": "same reply"})) is True
    assert created[0] == {"kind": "message_review", "key": key}


# --- orchestrator ----------------------------------------------------------


def patch_steps(monkeypatch, *, invitations=None, messages=None):
    calls = []

    async def fake_recover_and_retire():
        calls.append(("recover + retire legacy", {}))
        return 2, 3

    async def fake_invitations(**kwargs):
        name = "invitations cleanup" if kwargs.get("cleanup_stale") else "invitations propose"
        calls.append((name, kwargs))
        if isinstance(invitations, Exception):
            raise invitations
        return ReviewCounts(new=2, needs_judgment=1)

    async def fake_messages(**kwargs):
        name = "messages cleanup" if kwargs.get("cleanup_only") else "messages propose"
        calls.append((name, kwargs))
        if isinstance(messages, Exception):
            raise messages
        return ReviewCounts(new=1)

    notes = []
    monkeypatch.setattr(daily, "recover_and_retire_reviews", fake_recover_and_retire)
    monkeypatch.setattr(daily.invitations, "process_linkedin_invitations", fake_invitations)
    monkeypatch.setattr(daily.inbox, "manage_linkedin_inbox", fake_messages)
    monkeypatch.setattr(daily, "notify", lambda title, message: notes.append((title, message)))
    return calls, notes


def test_full_run_orders_sync_steps(monkeypatch):
    calls, notes = patch_steps(monkeypatch)

    assert run_async_test(lambda: daily.run(True)) == daily.EXIT_OK

    assert [name for name, _ in calls] == ["recover + retire legacy", "invitations cleanup", "messages cleanup", "invitations propose", "messages propose"]
    assert notes == [
        (
            "LinkedIn agent",
            "3 new items in Agent Inbox (1 need judgment), 2 interrupted action(s) brought back for review, 3 old decision(s) from before live actions were retired; anything still open on LinkedIn was queued again",
        )
    ]


def test_legacy_and_recovered_counts_appear_in_summary():
    summary = daily.build_summary(ReviewCounts(new=1), [], recovered=2, retired=3)
    assert "2 interrupted action(s) brought back for review" in summary
    assert "3 old decision(s) from before live actions were retired; anything still open on LinkedIn was queued again" in summary


def test_expired_login_notifies_and_exits_nonzero_without_further_steps(monkeypatch):
    from linkedin_agent.runtime import LoginRequiredError

    calls, notes = patch_steps(monkeypatch, invitations=LoginRequiredError("expired"))

    assert run_async_test(lambda: daily.run(True)) == daily.EXIT_LOGIN
    assert len(calls) == 2
    assert notes[0][0] == "LinkedIn login needed"


def test_health_failure_continues_but_exits_nonzero(monkeypatch):
    calls, notes = patch_steps(monkeypatch, messages=HealthCheckError("zero conversations"))

    assert run_async_test(lambda: daily.run(True)) == daily.EXIT_HEALTH
    assert "warning" in notes[-1][1]
