import pytest

import linkedin_guard
from linkedin_guard import ApprovedAction, blocked_write_summary, blocked_writes, describe_destructive_match, is_messaging_write, reset_blocked_writes, safe_click


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


def test_message_scope_approval_never_unlocks_destructive_clicks():
    element = FakeElement(ariaLabel="Send")

    assert run(safe_click(element, approval=ApprovedAction("message", "send"))) is False
    assert element.clicks == 0


def test_summary_is_none_when_nothing_blocked():
    assert blocked_write_summary() is None


def run(coroutine):
    from tests.async_helpers import run_async_test

    return run_async_test(lambda: coroutine)


def test_module_exposes_guard_entry_points():
    assert callable(linkedin_guard.install_linkedin_write_guard)
