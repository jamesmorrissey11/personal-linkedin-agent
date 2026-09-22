"""Tests for the fallback selector chains in inbox_manager.py's get_inbox_messages():
when the primary author selector (.msg-s-message-group__name) or primary timestamp
selector (time.msg-s-message-group__timestamp) is absent, the code falls back to
`a .msg-s-message-group__profile-link` / `time.msg-s-message-list__time-heading`.
"""

from playwright.sync_api import Page

from tests.playwright.helpers import fixture_url


def test_author_fallback_selector_is_used_when_primary_is_absent(page: Page):
    page.goto(fixture_url("inbox_thread_fallback_selectors.html"))

    message = page.query_selector("li.msg-s-message-list__event")
    primary_author = message.query_selector(".msg-s-message-group__name")
    fallback_author = message.query_selector("a .msg-s-message-group__profile-link")

    assert primary_author is None
    assert fallback_author is not None
    assert fallback_author.inner_text() == "Sam Colleague"


def test_timestamp_fallback_selector_is_used_when_primary_is_absent(page: Page):
    page.goto(fixture_url("inbox_thread_fallback_selectors.html"))

    message = page.query_selector("li.msg-s-message-list__event")
    primary_timestamp = message.query_selector("time.msg-s-message-group__timestamp")
    fallback_timestamp = message.query_selector("time.msg-s-message-list__time-heading")

    assert primary_timestamp is None
    assert fallback_timestamp is not None
    assert fallback_timestamp.inner_text() == "Yesterday 4:15 PM"
