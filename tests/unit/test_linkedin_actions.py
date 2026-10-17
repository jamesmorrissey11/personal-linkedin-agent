from contextlib import asynccontextmanager

import pytest

import linkedin_actions
from linkedin_actions import message_precheck, perform_invitation_action, perform_message_action, same_profile
from linkedin_pages import ConversationMessage, LinkedInBusyError
from tests.async_helpers import run_async_test
from unattended import LoginRequiredError

NEW_MESSAGE_NOTE = "A new message arrived since this was queued; nothing was sent. Review it and choose again."
ALREADY_REPLIED_NOTE = "You already replied on LinkedIn; nothing was sent. Send this too by choosing again, or Ignore."


def message(author: str, content: str) -> ConversationMessage:
    return ConversationMessage(author=author, content=content, timestamp="now")


@pytest.mark.parametrize(
    ("messages", "logged_in_user", "expected_latest", "action", "reply", "expected"),
    [
        ([message("James", "Approved reply")], "James", "Older prompt", "reply", "Approved reply", ("already_sent", None)),
        ([message("Grace", "Queued prompt")], "James", "Queued prompt", "reply", "Approved reply", ("proceed", None)),
        ([message("James", "Handled elsewhere")], "James", "Queued prompt", "dismiss", "", ("proceed", None)),
        ([message("James", "Different reply")], "James", "Queued prompt", "reply", "Approved reply", ("stop", ALREADY_REPLIED_NOTE)),
        ([message("Grace", "New prompt")], "James", "Queued prompt", "reply", "Approved reply", ("stop", NEW_MESSAGE_NOTE)),
        ([message("Grace", "Queued prompt")], "Unknown User", "Queued prompt", "reply", "Approved reply", ("proceed", None)),
        ([message("Grace", "New prompt")], "Unknown User", "Queued prompt", "reply", "Approved reply", ("stop", NEW_MESSAGE_NOTE)),
        ([message("James", "Approved reply  \r\n")], "James", "Older prompt", "reply", "Approved reply", ("already_sent", None)),
    ],
)
def test_precheck_table(messages, logged_in_user, expected_latest, action, reply, expected):
    assert message_precheck(messages, logged_in_user, expected_latest, action, reply) == expected


def test_login_expired_returns_note(monkeypatch):
    @asynccontextmanager
    async def expired_session(*_args, **_kwargs):
        raise LoginRequiredError("expired")
        yield

    monkeypatch.setattr(linkedin_actions, "open_linkedin", expired_session)

    result = run_async_test(lambda: perform_invitation_action("https://www.linkedin.com/in/ada", "accept"))

    assert result.outcome is None
    assert result.error == "LinkedIn login expired. Log in with a visible browser, then try again."


def test_busy_lock_returns_note(monkeypatch):
    @asynccontextmanager
    async def busy_session(*_args, **_kwargs):
        raise LinkedInBusyError("busy")
        yield

    monkeypatch.setattr(linkedin_actions, "open_linkedin", busy_session)

    result = run_async_test(lambda: perform_invitation_action("https://www.linkedin.com/in/ada", "ignore"))

    assert result.outcome is None
    assert result.error == "Another LinkedIn task is running; try again in a few minutes."


def test_empty_reply_fails_without_opening_browser(monkeypatch):
    def unexpected_browser(*_args, **_kwargs):
        raise AssertionError("browser should not open")

    monkeypatch.setattr(linkedin_actions, "open_linkedin", unexpected_browser)

    result = run_async_test(lambda: perform_message_action("https://www.linkedin.com/messaging/thread/1/", "reply", " \n ", "hello"))

    assert result.outcome is None
    assert result.error == "The reply is empty; nothing was sent."


def test_same_profile_ignores_trailing_slash_and_query():
    assert same_profile("https://www.linkedin.com/in/ada/?mini=1", "https://www.linkedin.com/in/ada")
