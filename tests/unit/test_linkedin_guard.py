import pytest

import linkedin_guard
from linkedin_guard import ApprovedAction, approval_permits, blocked_write_summary, blocked_writes, describe_destructive_match, is_messaging_write, reset_blocked_writes, safe_click


@pytest.fixture(autouse=True)
def clean_blocked_log():
    reset_blocked_writes()
    yield
    reset_blocked_writes()


def descriptor(**overrides):
    base = {"tag": "button", "interactive": True, "ariaLabel": "", "title": "", "name": "", "id": "", "type": "", "controlName": "", "className": "", "text": ""}
    return {**base, **overrides}


class FakeElement:
    def __init__(self, **overrides):
        self.descriptor = descriptor(**overrides)
        self.clicks = 0

    async def evaluate(self, script):
        return self.descriptor

    async def click(self):
        self.clicks += 1


@pytest.mark.parametrize(
    "method,url,expected",
    [
        ("POST", "https://www.linkedin.com/voyager/api/voyagerMessagingDashMessengerMessages?action=createMessage", True),
        ("DELETE", "https://www.linkedin.com/voyager/api/messaging/conversations/2-abc", True),
        ("POST", "https://www.linkedin.com/voyager/api/voyagerMessagingGraphQL/graphql?action=archive", True),
        ("PUT", "https://www.linkedin.com/messaging/thread/2-abc/", True),
        ("GET", "https://www.linkedin.com/voyager/api/messaging/conversations", False),
        ("OPTIONS", "https://www.linkedin.com/voyager/api/messaging/conversations", False),
        ("POST", "https://www.linkedin.com/voyager/api/identity/dash/profiles", False),
        ("POST", "https://example.com/messaging/send", False),
        ("POST", "https://notlinkedin.com/messaging/send", False),
    ],
)
def test_is_messaging_write(method, url, expected):
    assert is_messaging_write(method, url) is expected


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"ariaLabel": "Send"}, "send"),
        ({"text": "Send"}, "send"),
        ({"type": "submit"}, "send"),
        ({"className": "msg-form__send-button"}, "send"),
        ({"ariaLabel": "Delete conversation"}, "delete"),
        ({"text": "Archive"}, "archive"),
        ({"ariaLabel": "Report this conversation"}, "report"),
        ({"ariaLabel": "Block Sam"}, "block"),
        ({"ariaLabel": "Leave conversation"}, "leave"),
        ({"text": "Mark as spam"}, "spam"),
        ({"ariaLabel": "Recall message"}, "recall"),
        ({"ariaLabel": "Accept"}, None),
        ({"ariaLabel": "Ignore"}, None),
        ({"ariaLabel": "Open profile menu"}, None),
        ({"tag": "li", "interactive": False, "text": "please delete and send this"}, None),
        ({"ariaLabel": "Blocked"}, None),
    ],
)
def test_destructive_pattern_matching(overrides, expected):
    assert describe_destructive_match(descriptor(**overrides)) == expected


def test_safe_click_clicks_harmless_elements():
    element = FakeElement(ariaLabel="Accept")

    assert run(safe_click(element)) is True
    assert element.clicks == 1
    assert blocked_writes() == []


def test_safe_click_refuses_destructive_elements_without_approval():
    element = FakeElement(ariaLabel="Delete conversation")

    assert run(safe_click(element)) is False
    assert element.clicks == 0
    assert len(blocked_writes()) == 1
    assert "blocked" in blocked_write_summary()


def test_message_send_approval_unlocks_only_send():
    approval = ApprovedAction("message", "send")
    send = FakeElement(ariaLabel="Send")
    delete = FakeElement(ariaLabel="Delete conversation")

    assert run(safe_click(send, approval=approval)) is True
    assert run(safe_click(delete, approval=approval)) is False
    assert send.clicks == 1
    assert delete.clicks == 0


def test_message_archive_approval_unlocks_only_archive():
    approval = ApprovedAction("message", "archive")
    archive = FakeElement(text="Archive")
    send = FakeElement(ariaLabel="Send")
    delete = FakeElement(ariaLabel="Delete conversation")

    assert run(safe_click(archive, approval=approval)) is True
    assert run(safe_click(send, approval=approval)) is False
    assert run(safe_click(delete, approval=approval)) is False
    assert (archive.clicks, send.clicks, delete.clicks) == (1, 0, 0)


@pytest.mark.parametrize("matched", ["delete", "report", "block", "leave", "spam", "recall", "reply", "unsend"])
@pytest.mark.parametrize("label", ["send", "archive"])
def test_message_approval_never_permits_other_destructive_controls(label, matched):
    assert approval_permits(ApprovedAction("message", label), matched) is False


def test_approval_permits_rules():
    assert approval_permits(None, "send") is False
    assert approval_permits(ApprovedAction("invitation", "accept"), "send") is True
    assert approval_permits(ApprovedAction("message", "send"), "send") is True
    assert approval_permits(ApprovedAction("message", "archive"), "archive") is True


@pytest.mark.parametrize("scope,label", [("message", "delete"), ("message", "accept"), ("profile", "send")])
def test_invalid_approvals_are_rejected(scope, label):
    with pytest.raises(ValueError):
        ApprovedAction(scope, label)


def test_summary_is_none_when_nothing_blocked():
    assert blocked_write_summary() is None


class FakeRequest:
    def __init__(self, method, url):
        self.method = method
        self.url = url


class FakeRoute:
    def __init__(self, method, url):
        self.request = FakeRequest(method, url)
        self.outcome = None

    async def abort(self, reason):
        self.outcome = "aborted"

    async def fallback(self):
        self.outcome = "allowed"


class FakeContext:
    def __init__(self):
        self.handler = None
        self.init_scripts = []

    async def route(self, matcher, handler):
        self.handler = handler

    async def add_init_script(self, script):
        self.init_scripts.append(script)

    def post(self, url):
        route = FakeRoute("POST", url)
        run(self.handler(route))
        return route.outcome


SEND_URL = "https://www.linkedin.com/voyager/api/voyagerMessagingDashMessengerMessages?action=createMessage"


def test_primary_write_allowance_is_per_context():
    first, second = FakeContext(), FakeContext()
    run(linkedin_guard.install_linkedin_write_guard(first, ApprovedAction("message", "send")))
    run(linkedin_guard.install_linkedin_write_guard(second, ApprovedAction("message", "send")))

    assert [first.post(SEND_URL), first.post(SEND_URL)] == ["allowed", "aborted"]
    assert second.post(SEND_URL) == "allowed"
    assert first.init_scripts == [] and second.init_scripts == []


MESSAGING_API = "https://www.linkedin.com/voyager/api"
ARCHIVE_WRITE_URL = f"{MESSAGING_API}/voyagerMessagingGraphQL/graphql?action=archive"
DESTRUCTIVE_WRITE_URLS = [
    f"{MESSAGING_API}/voyagerMessagingDashMessengerConversations?action=deleteConversation",
    f"{MESSAGING_API}/voyagerMessagingDashMessengerMessages?action=recall",
    f"{MESSAGING_API}/voyagerMessagingDashMessengerConversations?action=addCategory",
    f"{MESSAGING_API}/voyagerMessagingDashMessengerConversations?action=unarchive",
    f"{MESSAGING_API}/voyagerMessagingDashMessengerConversations?action=reportSpam",
]
INCIDENTAL_WRITE_URLS = [
    f"{MESSAGING_API}/messaging/dash/presenceStatuses",
    f"{MESSAGING_API}/voyagerMessagingDashMessengerConversations?action=markAllMessagesAsSeen",
    f"{MESSAGING_API}/voyagerMessagingDashMessengerMessages?action=sendDeliveryAcknowledgement",
    f"{MESSAGING_API}/voyagerMessagingDashMessengerConversations?action=typing",
    f"{MESSAGING_API}/voyagerMessagingDashMessengerConversations?action=markRead",
]


@pytest.mark.parametrize("label", ["send", "archive"])
@pytest.mark.parametrize("url", DESTRUCTIVE_WRITE_URLS)
def test_message_approval_blocks_unlisted_messaging_writes(label, url):
    context = FakeContext()
    run(linkedin_guard.install_linkedin_write_guard(context, ApprovedAction("message", label)))
    reset_blocked_writes()

    assert context.post(url) == "aborted"
    assert len(blocked_writes()) == 1
    reset_blocked_writes()


@pytest.mark.parametrize("label", ["send", "archive"])
@pytest.mark.parametrize("url", INCIDENTAL_WRITE_URLS)
def test_message_approval_allows_incidental_writes(label, url):
    context = FakeContext()
    run(linkedin_guard.install_linkedin_write_guard(context, ApprovedAction("message", label)))

    assert [context.post(url), context.post(url)] == ["allowed", "allowed"]


def test_send_approval_blocks_archive_and_keeps_its_one_send():
    context = FakeContext()
    run(linkedin_guard.install_linkedin_write_guard(context, ApprovedAction("message", "send")))

    assert [context.post(ARCHIVE_WRITE_URL), context.post(SEND_URL), context.post(SEND_URL)] == ["aborted", "allowed", "aborted"]
    reset_blocked_writes()


def test_archive_approval_blocks_send_and_keeps_its_one_archive():
    context = FakeContext()
    run(linkedin_guard.install_linkedin_write_guard(context, ApprovedAction("message", "archive")))

    assert [context.post(SEND_URL), context.post(ARCHIVE_WRITE_URL), context.post(ARCHIVE_WRITE_URL)] == ["aborted", "allowed", "aborted"]
    reset_blocked_writes()


@pytest.mark.parametrize("approval", [None, ApprovedAction("invitation", "accept")])
def test_unapproved_contexts_block_every_messaging_write(approval):
    context = FakeContext()
    run(linkedin_guard.install_linkedin_write_guard(context, approval))

    assert context.post(SEND_URL) == "aborted"
    assert context.init_scripts == [linkedin_guard.COMPOSER_GUARD_SCRIPT]


def run(coroutine):
    from tests.async_helpers import run_async_test

    return run_async_test(lambda: coroutine)


def test_module_exposes_guard_entry_points():
    assert callable(linkedin_guard.install_linkedin_write_guard)
