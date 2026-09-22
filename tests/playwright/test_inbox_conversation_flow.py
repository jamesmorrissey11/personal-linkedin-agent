"""Tests for the conversation-opening/message-ordering flow used by
inbox_manager.py's get_inbox_messages(): clicking a `li.msg-conversation-listitem`
to open a thread, and taking the last three `li.msg-s-message-list__event` entries
in order.

get_inbox_messages() itself is not called directly here: it hardcodes
`page.goto("https://www.linkedin.com/messaging/")`, a real LinkedIn URL that can't be
swapped for a static fixture without changing production code. So, like the existing
test_inbox_scraping.py, this drives the same selectors/click/slicing logic the
production code uses directly against the static fixture instead.
"""

from playwright.sync_api import Page

from tests.playwright.helpers import fixture_url


def test_clicking_conversation_listitem_reveals_message_thread(page: Page):
    page.goto(fixture_url("inbox_conversation_flow.html"))

    thread = page.query_selector("#thread-sam")
    assert not thread.is_visible()

    conversation = page.query_selector("li.msg-conversation-listitem")
    conversation.click()

    assert thread.is_visible()
    assert conversation.get_attribute("data-clicked") == "true"


def test_last_three_messages_are_selected_in_chronological_order(page: Page):
    page.goto(fixture_url("inbox_conversation_flow.html"))

    page.query_selector("li.msg-conversation-listitem").click()

    message_elements = page.query_selector_all("li.msg-s-message-list__event")
    assert len(message_elements) == 5

    # Mirrors get_inbox_messages()'s `message_elements[-3:] if len(message_elements) >= 3
    # else message_elements` slice.
    recent_messages = message_elements[-3:] if len(message_elements) >= 3 else message_elements
    bodies = [m.query_selector("p.msg-s-event-listitem__body").inner_text() for m in recent_messages]

    assert bodies == ["Message 3", "Message 4", "Message 5 - newest"]
