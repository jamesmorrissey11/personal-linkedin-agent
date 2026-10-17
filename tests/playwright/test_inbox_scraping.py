"""Tests for the conversation-thread scraping selectors used by inbox_manager.py.

Loads a static fixture (tests/playwright/fixtures/inbox_thread_list.html) instead of a live
LinkedIn session, and exercises the same selector strings the production code uses.
"""

from playwright.async_api import async_playwright
from playwright.sync_api import Page

import inbox_manager
from tests.async_helpers import run_async_test
from tests.playwright.helpers import FIXTURES_DIR, fixture_url


def test_conversation_listitems_are_found(page: Page):
    page.goto(fixture_url("inbox_thread_list.html"))

    conversations = page.query_selector_all("li.msg-conversation-listitem")

    assert len(conversations) == 2


def test_participant_name_is_scoped_to_conversation(page: Page):
    page.goto(fixture_url("inbox_thread_list.html"))

    conversations = page.query_selector_all("li.msg-conversation-listitem")
    names = [c.query_selector("h3.msg-conversation-card__participant-names").inner_text() for c in conversations]

    assert names == ["Alex Recruiter", "Sam Colleague"]


def test_message_events_expose_author_content_and_timestamp(page: Page):
    page.goto(fixture_url("inbox_thread_list.html"))

    message_elements = page.query_selector_all("li.msg-s-message-list__event")

    assert len(message_elements) == 2

    first = message_elements[0]
    author = first.query_selector(".msg-s-message-group__name").inner_text()
    content = first.query_selector("p.msg-s-event-listitem__body").inner_text()
    timestamp = first.query_selector("time.msg-s-message-group__timestamp").inner_text()

    assert author == "Sam Colleague"
    assert content == "Hey, can you take a look at the PR when you get a chance?"
    assert timestamp == "10:02 AM"


def test_approved_message_review_never_clicks_send(monkeypatch):
    marked = []

    async def fake_fetch(client, graph_id):
        return {
            "approved": {
                "thread_id": "thread-1",
                "values": {
                    "action": "reply",
                    "reply": "Approved reply",
                    "sender_name": "Sam Colleague",
                    "conversation_url": "https://www.linkedin.com/messaging/thread/test/",
                },
            }
        }

    async def fake_mark(client, thread_id):
        marked.append(thread_id)

    monkeypatch.setattr(inbox_manager, "fetch_resolved_reviews", fake_fetch)
    monkeypatch.setattr(inbox_manager, "mark_applied", fake_mark)

    async def scenario():
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            context = await browser.new_context()
            await context.route(
                "https://www.linkedin.com/**",
                lambda route: route.fulfill(path=FIXTURES_DIR / "inbox_thread_list.html"),
            )

            assert await inbox_manager.apply_message_reviews(context, object()) == 1

            opened_page = context.pages[-1]
            assert await opened_page.evaluate("window.__sendCount") == 0
            assert marked == ["thread-1"]
            await browser.close()

    run_async_test(scenario)
